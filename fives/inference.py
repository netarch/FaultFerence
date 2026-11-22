"""Stateful Cross-Perturbation Inference Engines: Set-Intersection & Multi-Round Bayesian PGM."""

import math
from typing import Dict, List, Optional, Sequence, Set, Tuple
import numpy as np
from scipy.special import logsumexp

from .perturbations import ActiveProbe, ComponentReset, FlowLinkDrain, FullLinkDrain, PacketMirror, SubtleWeightShift
from .systems import NetworkSystem, TelemetryRecord, TelemetryWindow


def _binom_logpmf(k: int, n: int, p: float) -> float:
    """Exact log P(Binomial(n, p) == k) without scipy overhead."""
    p_clamped = min(1.0 - 1.0e-12, max(1.0e-12, p))
    log_comb = math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)
    return log_comb + k * math.log(p_clamped) + (n - k) * math.log(1.0 - p_clamped)


class InferenceEngine:
    def reset(self, candidate_nodes: Sequence[int]) -> None:
        raise NotImplementedError

    def update(self, window: TelemetryWindow) -> None:
        raise NotImplementedError

    def posteriors(self) -> Dict[int, float]:
        raise NotImplementedError

    def equivalence_set(self, cred_mass: float = 0.95) -> Set[int]:
        raise NotImplementedError


class SetIntersectionInference(InferenceEngine):
    """Deterministic split-intersection inference with statistical rate-shift checks (human/basic mode)."""

    def __init__(self, system: NetworkSystem, bg_noise_prob: float = 1.0e-4):
        self.system = system
        self.bg_noise_prob = bg_noise_prob
        self.suspects: Set[int] = set()
        self.baseline_bad_rate: Dict[Tuple[int, int], float] = {}

    def reset(self, candidate_nodes: Sequence[int]) -> None:
        self.suspects = set(candidate_nodes)
        self.baseline_bad_rate = {}

    def update(self, window: TelemetryWindow) -> None:
        if window.perturbation is None:
            # Initial passive snapshot: narrow to union of switches on affected pairs' paths
            path_nodes: Set[int] = set()
            for rec in window.records:
                rate = float(rec.packets_bad) / float(max(1, rec.packets_sent))
                self.baseline_bad_rate[rec.pair] = rate
                if rate > 5.0 * self.bg_noise_prob and rec.packets_bad > 0:
                    for path, _ in rec.path_weights:
                        path_nodes.update(path)
            if len(path_nodes) > 0:
                self.suspects &= path_nodes
            return

        pert = window.perturbation

        if isinstance(pert, ComponentReset):
            still_bad = any(
                (float(r.packets_bad) / float(max(1, r.packets_sent))) > max(5.0 * self.bg_noise_prob, 0.35 * self.baseline_bad_rate[r.pair])
                for r in window.records if not r.is_probe and not r.is_mirror
            )
            next_set = (self.suspects - {pert.node}) if still_bad else ({pert.node} & self.suspects)
            if len(next_set) > 0:
                self.suspects = next_set
            return

        if isinstance(pert, ActiveProbe):
            probe_recs = [r for r in window.records if r.is_probe]
            assert len(probe_recs) == 1
            pr = probe_recs[0]
            sub_nodes: Set[int] = set()
            for path, _ in pr.path_weights:
                sub_nodes.update(path)
            # Probe hit failure if bad rate significantly exceeds background noise
            probe_rate = float(pr.packets_bad) / float(max(1, pr.packets_sent))
            probe_failed = (pr.packets_bad >= 1) and (probe_rate > 10.0 * self.bg_noise_prob)
            next_set = (self.suspects & sub_nodes) if probe_failed else (self.suspects - sub_nodes)
            if len(next_set) > 0:
                self.suspects = next_set
            return

        if isinstance(pert, PacketMirror):
            mir_recs = [r for r in window.records if r.is_mirror]
            if len(mir_recs) == 1:
                mr = mir_recs[0]
                up_nodes: Set[int] = set()
                for path, _ in mr.path_weights:
                    up_nodes.update(path)
                mir_rate = float(mr.packets_bad) / float(max(1, mr.packets_sent))
                seen_upstream = (mr.packets_bad >= 1) and (mir_rate > 10.0 * self.bg_noise_prob)
                next_set = (self.suspects & up_nodes) if seen_upstream else (self.suspects - up_nodes)
                if len(next_set) > 0:
                    self.suspects = next_set
            return

        if isinstance(pert, (FlowLinkDrain, FullLinkDrain)):
            # Check if draining eliminated the symptom on affected pairs
            for rec in window.records:
                if rec.is_probe or rec.is_mirror:
                    continue
                base_r = self.baseline_bad_rate[rec.pair]
                if base_r <= 5.0 * self.bg_noise_prob:
                    continue
                curr_r = float(rec.packets_bad) / float(max(1, rec.packets_sent))
                active_nodes: Set[int] = set()
                for path, _ in rec.path_weights:
                    active_nodes.update(path)
                # Symptom eliminated if bad rate dropped by >75% (or to noise floor)
                eliminated = curr_r <= max(3.0 * self.bg_noise_prob, 0.20 * base_r)
                next_set = (self.suspects - active_nodes) if eliminated else (self.suspects & active_nodes)
                if len(next_set) > 0:
                    self.suspects = next_set
            return

        if isinstance(pert, SubtleWeightShift):
            # Subtle fractional shifts cannot be reliably inverted by binary set-elimination;
            # only prune if bad rate dropped all the way to noise floor (impossible for w > 0).
            return

    def posteriors(self) -> Dict[int, float]:
        assert len(self.suspects) > 0
        w = 1.0 / float(len(self.suspects))
        return {c: w for c in self.suspects}

    def equivalence_set(self, cred_mass: float = 0.95) -> Set[int]:
        return set(self.suspects)


class MultiRoundBayesianPGM(InferenceEngine):
    """Stateful Multi-Round Bayesian Graphical Model fusing telemetry across all perturbed states."""

    def __init__(
        self,
        system: NetworkSystem,
        bg_noise_prob: float = 1.0e-4,
        duty_cycle_prior: float = 1.0,
        excluded_endpoints: Optional[Set[int]] = None,
    ):
        self.system = system
        self.bg_noise_prob = bg_noise_prob
        self.duty_cycle_prior = duty_cycle_prior
        self.excluded_endpoints = excluded_endpoints if excluded_endpoints is not None else set()
        self.candidates: Tuple[int, ...] = ()
        self.log_post: np.ndarray = np.array([], dtype=np.float64)
        self.node_drop_prob: Dict[int, float] = {}
        self._node_excess_bad: Dict[int, float] = {}
        self._node_exposure: Dict[int, float] = {}
        self._history: List[TelemetryWindow] = []
        self.estimated_drop_prob: float = 0.02

    def reset(self, candidate_nodes: Sequence[int]) -> None:
        valid = [c for c in sorted(candidate_nodes) if c not in self.excluded_endpoints]
        assert len(valid) > 0
        self.candidates = tuple(valid)
        self.log_post = np.full(len(valid), -math.log(len(valid)), dtype=np.float64)
        self.node_drop_prob = {c: 0.02 for c in valid}
        self._node_excess_bad = {c: 0.0 for c in valid}
        self._node_exposure = {c: 0.0 for c in valid}
        self._history = []
        self.estimated_drop_prob = 0.02

    def _update_running_mle(self, window: TelemetryWindow) -> None:
        """Update running profile MLE p_hat[c] = sum(excess_bad) / sum(N * hit_w[c]) across anomalous windows."""
        pert = window.perturbation
        active_recs = [
            r for r in window.records
            if (not r.is_probe) and (not r.is_mirror) and r.packets_sent > 0
        ]
        if len(active_recs) == 0:
            return
        for c in self.candidates:
            if isinstance(pert, ComponentReset) and pert.node == c:
                continue
            for r in active_recs:
                bg_expected = float(r.packets_sent) * self.bg_noise_prob
                is_anomalous = float(r.packets_bad) > bg_expected + 3.0 * math.sqrt(max(1.0, bg_expected))
                if not is_anomalous:
                    continue
                hit_w = sum(w for path, w in r.path_weights if c in path)
                if hit_w > 1.0e-9:
                    excess = max(0.0, float(r.packets_bad) - bg_expected)
                    self._node_excess_bad[c] += excess
                    self._node_exposure[c] += float(r.packets_sent) * hit_w
            if self._node_exposure[c] > 0.0:
                self.node_drop_prob[c] = min(
                    0.9999,
                    max(0.0005, self._node_excess_bad[c] / self._node_exposure[c]),
                )

    def _record_log_likelihood(self, rec: TelemetryRecord, node: int, p_drop: float, suppressed: bool) -> float:
        if suppressed:
            return _binom_logpmf(rec.packets_bad, rec.packets_sent, self.bg_noise_prob)

        hit_w = sum(w for path, w in rec.path_weights if node in path)
        if hit_w <= 0.0:
            return _binom_logpmf(rec.packets_bad, rec.packets_sent, self.bg_noise_prob)

        if rec.is_probe:
            lp_hit = _binom_logpmf(rec.packets_bad, rec.packets_sent, p_drop)
            if hit_w >= 1.0 - 1.0e-9:
                return lp_hit
            lp_miss = _binom_logpmf(rec.packets_bad, rec.packets_sent, self.bg_noise_prob)
            return float(logsumexp([math.log(hit_w) + lp_hit, math.log(1.0 - hit_w) + lp_miss]))

        q = hit_w * p_drop + (1.0 - hit_w) * self.bg_noise_prob
        return _binom_logpmf(rec.packets_bad, rec.packets_sent, q)

    def update(self, window: TelemetryWindow) -> None:
        self._history.append(window)
        self._update_running_mle(window)
        alpha = self.duty_cycle_prior

        # Exact joint profile log-posterior across full trajectory H_t = {w_0, ..., w_t}
        # under each candidate's consistent persistent fault rate p_hat[c]!
        total_log_post = np.full(len(self.candidates), -math.log(len(self.candidates)), dtype=np.float64)
        for win in self._history:
            ll_inactive = sum(
                _binom_logpmf(r.packets_bad, r.packets_sent, self.bg_noise_prob)
                for r in win.records
            )
            pert = win.perturbation
            for idx, node in enumerate(self.candidates):
                p_node = self.node_drop_prob[node]
                suppressed = isinstance(pert, ComponentReset) and (pert.node == node)
                ll_active = sum(
                    self._record_log_likelihood(r, node, p_node, suppressed)
                    for r in win.records
                )
                if alpha >= 1.0 - 1.0e-9:
                    total_log_post[idx] += ll_active
                else:
                    total_log_post[idx] += float(
                        logsumexp([math.log(alpha) + ll_active, math.log(1.0 - alpha) + ll_inactive])
                    )

        self.log_post = total_log_post - float(logsumexp(total_log_post))
        if len(self.candidates) > 0:
            probs = np.exp(self.log_post)
            self.estimated_drop_prob = float(
                sum(probs[i] * self.node_drop_prob[self.candidates[i]] for i in range(len(self.candidates)))
            )

    def posteriors(self) -> Dict[int, float]:
        probs = np.exp(self.log_post)
        return {node: float(probs[i]) for i, node in enumerate(self.candidates)}

    def equivalence_set(self, cred_mass: float = 0.95) -> Set[int]:
        """Return minimal credible suspect set capturing `cred_mass` posterior probability,
        grouping ties within 1e-4 log-likelihood so symmetric components stay together cleanly."""
        probs = np.exp(self.log_post)
        order = np.argsort(-probs)
        chosen: Set[int] = set()
        acc = 0.0
        last_lp = None
        for idx in order:
            p_val = float(probs[idx])
            lp_val = float(self.log_post[idx])
            if acc >= cred_mass and (last_lp is None or (last_lp - lp_val) > 0.05):
                break
            if p_val < 1.0e-6 and len(chosen) > 0:
                break
            chosen.add(self.candidates[int(idx)])
            acc += p_val
            last_lp = lp_val
        return chosen
