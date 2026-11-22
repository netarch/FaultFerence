"""FIVES Extensions: Non-Conflating Parallel Perturbations, Concurrent Multi-Fault Inference, and Confirmation Checks."""

from dataclasses import dataclass
import itertools
import math
from typing import Dict, List, Optional, Sequence, Set, Tuple
import numpy as np
from scipy.special import logsumexp

from .evaluators import MultiOutcomeEfficacyEstimator, SafetyFilter, TwoPhaseImpactEstimator
from .inference import MultiRoundBayesianPGM, SetIntersectionInference, _binom_logpmf
from .perturbations import (
    ActiveProbe,
    ComponentReset,
    FlowGroupSplit,
    FlowLinkDrain,
    FullLinkDrain,
    PacketMirror,
    Perturbation,
    SubtleWeightShift,
)
from .systems import FailureMode, FailureSpec, NetworkSystem, TelemetryRecord, TelemetryWindow


def _joint_paths_under_batch(
    system: NetworkSystem,
    pair: Tuple[int, int],
    control_perts: Sequence[Perturbation],
) -> Tuple[Tuple[Tuple[int, ...], float], ...]:
    """Compute exact post-perturbation path weights under a batch of disjoint-switch prefix control actions."""
    if len(control_perts) == 0:
        return system.paths_under_perturbation(pair, None)
    if len(control_perts) == 1:
        return system.paths_under_perturbation(pair, control_perts[0])

    base_paths = system.shortest_paths(pair[0], pair[1])
    surviving: List[Tuple[Tuple[int, ...], float]] = []
    for path in base_paths:
        edges = {(path[i], path[i + 1]) for i in range(len(path) - 1)}
        dropped = False
        w_mult = 1.0
        for p in control_perts:
            if isinstance(p, FlowLinkDrain) and p.flow_pair == pair:
                if (p.u, p.v) in edges:
                    dropped = True
                    break
            elif isinstance(p, FlowGroupSplit) and p.flow_pair == pair:
                if any((p.u, v) in edges for v in p.drained_nexthops):
                    dropped = True
                    break
            elif isinstance(p, SubtleWeightShift) and p.flow_pair == pair:
                if (p.u, p.v) in edges:
                    w_mult *= p.weight_factor
            elif isinstance(p, FullLinkDrain):
                if (p.u, p.v) in edges or (p.v, p.u) in edges:
                    dropped = True
                    break
        if not dropped:
            surviving.append((path, w_mult))

    if len(surviving) == 0:
        return ()
    tot_w = sum(w for _, w in surviving)
    return tuple((path, w / tot_w) for path, w in surviving)


def _batch_is_jointly_safe(
    system: NetworkSystem,
    safety: SafetyFilter,
    batch: Sequence[Perturbation],
    active_pairs: Sequence[Tuple[int, int]],
) -> bool:
    """Verify that concurrent execution of `batch` preserves >=50% effective path capacity and non-interference."""
    ctrl = [p for p in batch if not isinstance(p, (ActiveProbe, PacketMirror, ComponentReset))]
    resets = [p for p in batch if isinstance(p, ComponentReset)]
    if len(resets) > 1 or (len(resets) == 1 and len(batch) > 1):
        return False
    if any(isinstance(p, FullLinkDrain) for p in ctrl) and len(ctrl) > 1:
        return False

    # Control actions must act on disjoint switches so rules never collide
    ctrl_switches = [p.u for p in ctrl if hasattr(p, "u")]
    if len(ctrl_switches) != len(set(ctrl_switches)):
        return False

    # Active probes cannot run concurrently with routing changes on the same flow pair if paths shift upstream;
    # keep telemetry batches pure-telemetry or paired only when sub-DAGs are untouched, here pure-plane or disjoint:
    has_probe_or_mirror = any(isinstance(p, (ActiveProbe, PacketMirror)) for p in batch)
    if has_probe_or_mirror and len(ctrl) > 0:
        # PacketMirror observes upstream user traffic -> conflates with concurrent control drains on the same pair!
        if any(isinstance(p, PacketMirror) for p in batch):
            return False
        # Switch-originated ActiveProbe (u -> dst) only traverses shortest_paths(u, dst): non-conflating iff
        # no control action in `ctrl` modifies any switch inside shortest_paths(u, dst)!
        ctrl_u_set = set(ctrl_switches)
        for p in batch:
            if isinstance(p, ActiveProbe):
                sub_nodes = {n for sp in system.shortest_paths(p.src_node, p.dst_node) for n in sp}
                if len(sub_nodes & ctrl_u_set) > 0:
                    return False

    # Verify joint effective path capacity >= min_bandwidth_ratio on every active pair
    min_ratio = system.safety.min_bandwidth_ratio
    for pair in active_pairs:
        base_paths = system.shortest_paths(pair[0], pair[1])
        if len(ctrl) > 0:
            pw_joint = _joint_paths_under_batch(system, pair, ctrl)
            if len(pw_joint) == 0:
                return False
            # Effective surviving path count accounting for weight shifts
            eff_surviving = 0.0
            for path in base_paths:
                edges = {(path[i], path[i + 1]) for i in range(len(path) - 1)}
                w_m = 1.0
                ok = True
                for p in ctrl:
                    if isinstance(p, FlowLinkDrain) and p.flow_pair == pair and (p.u, p.v) in edges:
                        ok = False
                        break
                    if isinstance(p, FlowGroupSplit) and p.flow_pair == pair and any((p.u, v) in edges for v in p.drained_nexthops):
                        ok = False
                        break
                    if isinstance(p, SubtleWeightShift) and p.flow_pair == pair and (p.u, p.v) in edges:
                        w_m *= p.weight_factor
                if ok:
                    eff_surviving += w_m
            if (eff_surviving / float(len(base_paths))) < min_ratio - 1.0e-9:
                return False
        if not all(safety.is_safe(p, active_pairs) for p in batch):
            return False
    return True


def simulate_multifault_and_batch_window(
    system: NetworkSystem,
    faulty_nodes: Tuple[int, ...],
    affected_pairs: Tuple[Tuple[int, int], ...],
    drop_prob: float,
    bg_noise_prob: float,
    batch: Sequence[Perturbation],
    rng: np.random.Generator,
    flows_per_pair: int = 400,
    packets_per_flow: int = 25,
) -> TelemetryWindow:
    """Simulate a concurrent observation window for a non-conflating batch and >=1 faulty components."""
    fault_set = set(faulty_nodes)
    suppressed = {p.node for p in batch if isinstance(p, ComponentReset)}
    active_faults = fault_set - suppressed
    ctrl = [p for p in batch if not isinstance(p, (ActiveProbe, PacketMirror, ComponentReset))]

    records: List[TelemetryRecord] = []
    for pair in affected_pairs:
        pw = _joint_paths_under_batch(system, pair, ctrl)
        assert len(pw) > 0
        paths = [p for p, _ in pw]
        probs = np.array([w for _, w in pw], dtype=np.float64)
        total_pkts = flows_per_pair * packets_per_flow
        flow_path_idx = rng.choice(len(paths), size=flows_per_pair, p=probs)

        bad_pkts = 0
        for idx_p, path in enumerate(paths):
            cnt_pkts = int(np.sum(flow_path_idx == idx_p)) * packets_per_flow
            if cnt_pkts == 0:
                continue
            n_hits = sum(1 for fn in active_faults if fn in path)
            p_survive = (1.0 - bg_noise_prob) * ((1.0 - drop_prob) ** n_hits)
            bad_pkts += int(rng.binomial(cnt_pkts, 1.0 - p_survive))

        records.append(
            TelemetryRecord(
                pair=pair,
                is_probe=False,
                is_mirror=False,
                mirror_node=-1,
                packets_sent=total_pkts,
                packets_bad=bad_pkts,
                path_weights=pw,
            )
        )

    for p in batch:
        if isinstance(p, ActiveProbe):
            sub_paths = system.shortest_paths(p.src_node, p.dst_node)
            w = 1.0 / float(len(sub_paths))
            pw_probe = tuple((sp, w) for sp in sub_paths)
            chosen_sp = sub_paths[int(rng.integers(0, len(sub_paths)))]
            n_hits = sum(1 for fn in active_faults if fn in chosen_sp)
            p_survive = (1.0 - bg_noise_prob) * ((1.0 - drop_prob) ** n_hits)
            bad_probes = int(rng.binomial(p.num_probes, 1.0 - p_survive))
            records.append(
                TelemetryRecord(
                    pair=p.flow_pair,
                    is_probe=True,
                    is_mirror=False,
                    mirror_node=-1,
                    packets_sent=p.num_probes,
                    packets_bad=bad_probes,
                    path_weights=pw_probe,
                )
            )
        elif isinstance(p, PacketMirror):
            base_paths = system.shortest_paths(p.flow_pair[0], p.flow_pair[1])
            through_m = [path for path in base_paths if p.node in path]
            if len(through_m) > 0:
                up_prefixes = [path[: path.index(p.node) + 1] for path in through_m]
                w = 1.0 / float(len(up_prefixes))
                pw_mir = tuple((up, w) for up in up_prefixes)
                n_mir = 200
                chosen_idx = rng.integers(0, len(up_prefixes), size=n_mir)
                bad_mir = 0
                for idx_u, up in enumerate(up_prefixes):
                    cnt = int(np.sum(chosen_idx == idx_u))
                    if cnt == 0:
                        continue
                    n_hits = sum(1 for fn in active_faults if fn in up)
                    p_survive = (1.0 - bg_noise_prob) * ((1.0 - drop_prob) ** n_hits)
                    bad_mir += int(rng.binomial(cnt, 1.0 - p_survive))
                records.append(
                    TelemetryRecord(
                        pair=p.flow_pair,
                        is_probe=False,
                        is_mirror=True,
                        mirror_node=p.node,
                        packets_sent=n_mir,
                        packets_bad=bad_mir,
                        path_weights=pw_mir,
                    )
                )

    lead_pert = batch[0] if len(batch) > 0 else None
    return TelemetryWindow(perturbation=lead_pert, records=tuple(records), fault_was_active=True)


def select_non_conflating_batch(
    system: NetworkSystem,
    safety: SafetyFilter,
    impact: TwoPhaseImpactEstimator,
    efficacy: MultiOutcomeEfficacyEstimator,
    posteriors: Dict[int, float],
    active_pairs: Sequence[Tuple[int, int]],
    tried_keys: Set[Tuple],
    expected_drop_prob: float,
    batch_size: int,
    tradeoff_lambda: float = 0.5,
    max_step_disruption: Optional[float] = None,
) -> List[Perturbation]:
    """Greedily pack up to `batch_size` mutually non-conflating safe perturbations per round.

    Note: Combining two control drains in the same window conflates their aggregate end-to-end loss shift into a single
    scalar observation, whereas telemetry probes/mirrors produce independent per-action observation streams (records)
    that can be packed both with each other and alongside one upstream-disjoint control action!
    """
    assert batch_size >= 1
    suspects = sorted(c for c, pr in posteriors.items() if pr > 1.0e-6)
    if len(suspects) <= 1:
        return []

    raw = system.candidate_perturbations(active_pairs, set(suspects))
    safe_cands: List[Perturbation] = []
    for p in raw:
        if p.key in tried_keys or not safety.is_safe(p, active_pairs):
            continue
        imp = impact.estimate(p, expected_drop_prob=expected_drop_prob)
        if max_step_disruption is not None and imp.total_disruption > max_step_disruption:
            continue
        safe_cands.append(p)

    if len(safe_cands) == 0:
        return []

    scored = []
    for p in safe_cands:
        ig, pw = efficacy.mutual_information_and_pairs(p, posteriors, active_pairs, expected_drop_prob=expected_drop_prob)
        if ig <= 1.0e-9 and pw <= 1.0e-9:
            continue
        c_val = impact.estimate(p, expected_drop_prob=expected_drop_prob).scalar_cost(tradeoff_lambda)
        scored.append(((ig + 1.0e-3 * pw) / c_val, p))
    if len(scored) == 0:
        return []

    scored.sort(key=lambda x: -x[0])
    p_lead = scored[0][1]
    if batch_size == 1 or isinstance(p_lead, ComponentReset):
        return [p_lead]

    chosen: List[Perturbation] = [p_lead]
    used_probe_origins: Set[int] = (
        {p_lead.src_node if isinstance(p_lead, ActiveProbe) else p_lead.node}
        if isinstance(p_lead, (ActiveProbe, PacketMirror))
        else set()
    )
    cur_disrupt = impact.estimate(p_lead, expected_drop_prob=expected_drop_prob).total_disruption

    sig_map: Dict[int, Tuple] = {}
    b0 = efficacy.partition_suspects(p_lead, suspects, active_pairs)
    for sig_k, grp in b0.items():
        for s in grp:
            sig_map[s] = (sig_k,)

    def _partition_entropy(smap: Dict[int, Tuple]) -> float:
        grp_mass: Dict[Tuple, float] = {}
        tot = sum(posteriors[s] for s in suspects)
        for s in suspects:
            sk = smap[s]
            grp_mass[sk] = (grp_mass[sk] if sk in grp_mass else 0.0) + posteriors[s] / tot
        return -sum(q * math.log2(q) for q in grp_mass.values() if q > 1.0e-12)

    cur_h = _partition_entropy(sig_map)

    # Candidate companions: telemetry probes/mirrors (with separate record streams) + at most 1 control action total
    has_ctrl = not isinstance(p_lead, (ActiveProbe, PacketMirror, ComponentReset))
    companion_pool = [
        p for _, p in scored[1:]
        if isinstance(p, (ActiveProbe, PacketMirror)) or (not has_ctrl and not isinstance(p, ComponentReset))
    ]

    while len(chosen) < batch_size:
        best_next: Optional[Perturbation] = None
        best_next_gain = 1.0e-6
        best_next_smap: Optional[Dict[int, Tuple]] = None

        for p in companion_pool:
            if p in chosen:
                continue
            is_telem = isinstance(p, (ActiveProbe, PacketMirror))
            if (not is_telem) and has_ctrl:
                continue
            if is_telem:
                orig = p.src_node if isinstance(p, ActiveProbe) else p.node
                if orig in used_probe_origins:
                    continue
            imp_p = impact.estimate(p, expected_drop_prob=expected_drop_prob)
            if max_step_disruption is not None and (cur_disrupt + imp_p.total_disruption) > max_step_disruption:
                continue
            trial_batch = chosen + [p]
            if not _batch_is_jointly_safe(system, safety, trial_batch, active_pairs):
                continue

            bp = efficacy.partition_suspects(p, suspects, active_pairs)
            trial_smap: Dict[int, Tuple] = {}
            for sig_k, grp in bp.items():
                for s in grp:
                    trial_smap[s] = sig_map[s] + (sig_k,)
            new_h = _partition_entropy(trial_smap)
            cur_max_t = max(impact.estimate(q, expected_drop_prob=expected_drop_prob).total_time_sec for q in chosen)
            new_max_t = max(cur_max_t, imp_p.total_time_sec)
            marg_cost = max(
                0.02,
                tradeoff_lambda * imp_p.total_disruption + (1.0 - tradeoff_lambda) * ((new_max_t - cur_max_t) / 10.0),
            )
            gain_ratio = (new_h - cur_h) / marg_cost
            if (new_h - cur_h) > 0.05 and gain_ratio > best_next_gain:
                best_next_gain = gain_ratio
                best_next = p
                best_next_smap = trial_smap

        if best_next is None or best_next_smap is None:
            break
        chosen.append(best_next)
        if isinstance(best_next, (ActiveProbe, PacketMirror)):
            used_probe_origins.add(best_next.src_node if isinstance(best_next, ActiveProbe) else best_next.node)
        else:
            has_ctrl = True
        cur_disrupt += impact.estimate(best_next, expected_drop_prob=expected_drop_prob).total_disruption
        sig_map = best_next_smap
        cur_h = _partition_entropy(sig_map)

    return chosen


def run_parallel_episode(
    system: NetworkSystem,
    failure: FailureSpec,
    batch_size: int = 1,
    tradeoff_lambda: float = 0.5,
    max_step_disruption: Optional[float] = None,
    confirm_culprit: bool = False,
    rng_seed: int = 42,
    max_rounds: int = 40,
) -> Dict[str, float]:
    """Run FIVES with concurrent non-conflating batch size `batch_size`, SLA disruption cap, and confirmation check."""
    rng = np.random.default_rng(rng_seed)
    safety = SafetyFilter(system)
    impact = TwoPhaseImpactEstimator(system)
    efficacy = MultiOutcomeEfficacyEstimator(system)
    excluded = {ep for pair in failure.affected_pairs for ep in pair}
    inf = MultiRoundBayesianPGM(system, bg_noise_prob=failure.bg_noise_prob, excluded_endpoints=excluded)

    pool = sorted({
        n
        for pair in failure.affected_pairs
        for path in system.shortest_paths(pair[0], pair[1])
        for n in path
    })
    inf.reset(pool)
    max_paths = max(len(system.shortest_paths(pair[0], pair[1])) for pair in failure.affected_pairs)
    eff_flows = max(400, 25 * max_paths)

    win0 = simulate_multifault_and_batch_window(
        system, (failure.faulty_node,), failure.affected_pairs,
        failure.drop_prob, failure.bg_noise_prob, (), rng, flows_per_pair=eff_flows
    )
    inf.update(win0)
    curr_eq = inf.equivalence_set()
    tried_keys: Set[Tuple] = set()
    rounds = 0
    total_actions = 0
    total_ttl = 0.0
    total_disrupt = 0.0
    peak_disrupt = 0.0

    for _ in range(max_rounds):
        if len(curr_eq) <= 1:
            break
        post = inf.posteriors()
        batch = select_non_conflating_batch(
            system, safety, impact, efficacy, post, failure.affected_pairs,
            tried_keys, inf.estimated_drop_prob, batch_size=batch_size,
            tradeoff_lambda=tradeoff_lambda, max_step_disruption=max_step_disruption,
        )
        if len(batch) == 0:
            break
        for p in batch:
            tried_keys.add(p.key)

        imps = [impact.estimate(p, expected_drop_prob=failure.drop_prob) for p in batch]
        round_ttl = max(im.total_time_sec for im in imps)
        round_disrupt = sum(im.total_disruption for im in imps)
        rounds += 1
        total_actions += len(batch)
        total_ttl += round_ttl
        total_disrupt += round_disrupt
        peak_disrupt = max(peak_disrupt, round_disrupt)

        win = simulate_multifault_and_batch_window(
            system, (failure.faulty_node,), failure.affected_pairs,
            failure.drop_prob, failure.bg_noise_prob, batch, rng, flows_per_pair=eff_flows
        )
        inf.update(win)
        curr_eq = inf.equivalence_set()

    if confirm_culprit and len(curr_eq) == 1:
        top_c = next(iter(curr_eq))
        if inf.posteriors()[top_c] < 0.99:
            cands_v = [
                p for p in system.candidate_perturbations(failure.affected_pairs, set(inf.candidates))
                if p.key not in tried_keys and safety.is_safe(p, failure.affected_pairs)
            ]
            if len(cands_v) > 0:
                p_ver = cands_v[0]
                im_v = impact.estimate(p_ver, expected_drop_prob=failure.drop_prob)
                rounds += 1
                total_actions += 1
                total_ttl += im_v.total_time_sec
                total_disrupt += im_v.total_disruption
                win_v = simulate_multifault_and_batch_window(
                    system, (failure.faulty_node,), failure.affected_pairs,
                    failure.drop_prob, failure.bg_noise_prob, [p_ver], rng, flows_per_pair=eff_flows
                )
                inf.update(win_v)
                curr_eq = inf.equivalence_set()

    hit = 1.0 if failure.faulty_node in curr_eq else 0.0
    false_positive = 1.0 if (len(curr_eq) == 1 and failure.faulty_node not in curr_eq) else 0.0
    return {
        "rounds": float(rounds),
        "actions": float(total_actions),
        "ttl": total_ttl,
        "disruption": total_disrupt,
        "peak_disruption": peak_disrupt,
        "precision": hit / float(len(curr_eq)),
        "recall": hit,
        "false_positive": false_positive,
    }


def _binom_logpmf_vec(k: int, n: int, p_arr: np.ndarray) -> np.ndarray:
    p_c = np.clip(p_arr, 1.0e-12, 1.0 - 1.0e-12)
    log_c = math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)
    return log_c + k * np.log(p_c) + (n - k) * np.log(1.0 - p_c)


class PairFaultBayesianPGM:
    """Vectorized joint 2-fault Bayesian inference over unordered culprit pairs {c_1, c_2} subseteq E_0."""

    def __init__(
        self,
        system: NetworkSystem,
        candidates: Sequence[int],
        bg_noise_prob: float = 1.0e-4,
    ):
        self.system = system
        self.bg_noise_prob = bg_noise_prob
        self.nodes: Tuple[int, ...] = tuple(sorted(candidates))
        self.node_to_idx: Dict[int, int] = {c: i for i, c in enumerate(self.nodes)}
        self.pairs: Tuple[Tuple[int, int], ...] = tuple(itertools.combinations(self.nodes, 2))
        assert len(self.pairs) > 0
        self.idx1 = np.array([self.node_to_idx[c1] for c1, _ in self.pairs], dtype=np.int32)
        self.idx2 = np.array([self.node_to_idx[c2] for _, c2 in self.pairs], dtype=np.int32)
        self.log_post = np.full(len(self.pairs), -math.log(len(self.pairs)), dtype=np.float64)
        self._pair_excess: np.ndarray = np.zeros(len(self.pairs), dtype=np.float64)
        self._pair_exposure: np.ndarray = np.zeros(len(self.pairs), dtype=np.float64)
        self._pair_theta: np.ndarray = np.full(len(self.pairs), 0.03, dtype=np.float64)
        self._history: List[TelemetryWindow] = []
        self.estimated_drop_prob: float = 0.03

    def update(self, window: TelemetryWindow) -> None:
        self._history.append(window)
        n_nodes = len(self.nodes)

        for r in window.records:
            if r.is_probe or r.is_mirror or r.packets_sent <= 0:
                continue
            bg_exp = float(r.packets_sent) * self.bg_noise_prob
            if float(r.packets_bad) <= bg_exp + 3.0 * math.sqrt(max(1.0, bg_exp)):
                continue
            excess = max(0.0, float(r.packets_bad) - bg_exp)
            nh = np.zeros(n_nodes, dtype=np.float64)
            for path, w in r.path_weights:
                for n in path:
                    if n in self.node_to_idx:
                        nh[self.node_to_idx[n]] += w
            tot_h = nh[self.idx1] + nh[self.idx2]
            mask = tot_h > 1.0e-9
            self._pair_excess[mask] += excess
            self._pair_exposure[mask] += float(r.packets_sent) * tot_h[mask]

        valid_mask = self._pair_exposure > 0.0
        if np.any(valid_mask):
            self._pair_theta[valid_mask] = np.clip(
                self._pair_excess[valid_mask] / self._pair_exposure[valid_mask], 0.001, 0.95
            )

        total_lp = np.full(len(self.pairs), -math.log(len(self.pairs)), dtype=np.float64)
        th = self._pair_theta
        q1_vec = 1.0 - (1.0 - self.bg_noise_prob) * (1.0 - th)
        q2_vec = 1.0 - (1.0 - self.bg_noise_prob) * ((1.0 - th) ** 2)

        for win in self._history:
            sup_node = win.perturbation.node if isinstance(win.perturbation, ComponentReset) else -1
            for r in win.records:
                n_paths = len(r.path_weights)
                # Build binary (n_nodes, n_paths) incidence matrix & (n_paths,) weights
                inc = np.zeros((n_nodes, n_paths), dtype=np.float64)
                ws = np.array([w for _, w in r.path_weights], dtype=np.float64)
                for j, (sp, _) in enumerate(r.path_weights):
                    for n in sp:
                        if n != sup_node and n in self.node_to_idx:
                            inc[self.node_to_idx[n], j] = 1.0
                # For each pair: fraction of paths hitting both (b2) vs exactly one (b1) vs neither (b0)
                in1 = inc[self.idx1]  # (n_pairs, n_paths)
                in2 = inc[self.idx2]
                both_w = (in1 * in2) @ ws
                one_w = ((in1 + in2) - 2.0 * (in1 * in2)) @ ws
                zero_w = np.maximum(0.0, 1.0 - one_w - both_w)

                if r.is_probe:
                    lp0 = _binom_logpmf(r.packets_bad, r.packets_sent, self.bg_noise_prob)
                    lp1 = _binom_logpmf_vec(r.packets_bad, r.packets_sent, q1_vec)
                    lp2 = _binom_logpmf_vec(r.packets_bad, r.packets_sent, q2_vec)
                    # Mixture probability in log space
                    p_mix = (
                        zero_w * math.exp(lp0 - max(lp0, float(np.max(lp1)), float(np.max(lp2))))
                    )
                    m_shift = np.maximum(lp0, np.maximum(lp1, lp2))
                    mix_val = (
                        zero_w * np.exp(lp0 - m_shift)
                        + one_w * np.exp(lp1 - m_shift)
                        + both_w * np.exp(lp2 - m_shift)
                    )
                    total_lp += m_shift + np.log(np.maximum(1.0e-300, mix_val))
                else:
                    q_eff = zero_w * self.bg_noise_prob + one_w * q1_vec + both_w * q2_vec
                    total_lp += _binom_logpmf_vec(r.packets_bad, r.packets_sent, q_eff)

        self.log_post = total_lp - float(logsumexp(total_lp))
        probs = np.exp(self.log_post)
        self.estimated_drop_prob = float(np.sum(probs * self._pair_theta))

    def marginal_node_posteriors(self) -> Dict[int, float]:
        probs = np.exp(self.log_post)
        marg = {c: 0.0 for c in self.nodes}
        for idx, (c1, c2) in enumerate(self.pairs):
            p_val = float(probs[idx])
            marg[c1] += 0.5 * p_val
            marg[c2] += 0.5 * p_val
        return marg

    def pair_posteriors_and_credible_nodes(self, cred_mass: float = 0.95) -> Tuple[np.ndarray, Tuple[int, int], Set[int]]:
        probs = np.exp(self.log_post)
        order = np.argsort(-probs)
        top_pair = self.pairs[int(order[0])]
        acc = 0.0
        cred_nodes: Set[int] = set()
        for idx in order:
            p_val = float(probs[idx])
            if acc >= cred_mass and p_val < 0.02:
                break
            c1, c2 = self.pairs[int(idx)]
            cred_nodes.add(c1)
            cred_nodes.add(c2)
            acc += p_val
        return probs, top_pair, cred_nodes


def _select_pair_splitting_action(
    system: NetworkSystem,
    safety: SafetyFilter,
    impact: TwoPhaseImpactEstimator,
    inf_pair: PairFaultBayesianPGM,
    active_pairs: Sequence[Tuple[int, int]],
    tried_keys: Set[Tuple],
    tradeoff_lambda: float = 0.5,
) -> Optional[Perturbation]:
    """Select safe perturbation maximizing expected entropy over active pair hypotheses per unit cost."""
    probs, _, cred_nodes = inf_pair.pair_posteriors_and_credible_nodes()
    active_pair_idxs = [i for i, pr in enumerate(probs) if pr > 1.0e-4]
    if len(active_pair_idxs) <= 1:
        return None

    raw = system.candidate_perturbations(active_pairs, cred_nodes)
    best_p: Optional[Perturbation] = None
    best_sc = 0.0

    sub_probs = probs[active_pair_idxs]
    sub_probs = sub_probs / np.sum(sub_probs)
    act_c1 = [inf_pair.pairs[i][0] for i in active_pair_idxs]
    act_c2 = [inf_pair.pairs[i][1] for i in active_pair_idxs]

    for p in raw:
        if p.key in tried_keys or not safety.is_safe(p, active_pairs):
            continue
        # Partition active pairs by expected loss-rate signature under p
        buckets: Dict[Tuple, float] = {}
        if isinstance(p, ActiveProbe):
            sps = system.shortest_paths(p.src_node, p.dst_node)
            inv_s = 1.0 / float(len(sps))
            nh = {c: 0.0 for c in inf_pair.nodes}
            for sp in sps:
                for n in sp:
                    if n in nh:
                        nh[n] += inv_s
            for pr_w, c1, c2 in zip(sub_probs, act_c1, act_c2):
                sig = ("prb", round(min(1.0, nh[c1] + nh[c2]), 2))
                buckets[sig] = (buckets[sig] if sig in buckets else 0.0) + float(pr_w)
        elif isinstance(p, ComponentReset):
            for pr_w, c1, c2 in zip(sub_probs, act_c1, act_c2):
                sig = ("rst", 1 if (p.node == c1 or p.node == c2) else 0)
                buckets[sig] = (buckets[sig] if sig in buckets else 0.0) + float(pr_w)
        else:
            # Control perturbation: expected pair exposure shift relative to baseline
            sigs_per_pair_flow: List[Dict[int, float]] = []
            base_per_flow: List[Dict[int, float]] = []
            for fp in active_pairs:
                pw_b = system.paths_under_perturbation(fp, None)
                pw_p = system.paths_under_perturbation(fp, p)
                nb = {c: 0.0 for c in inf_pair.nodes}
                np_w = {c: 0.0 for c in inf_pair.nodes}
                for path, w in pw_b:
                    for n in path:
                        if n in nb:
                            nb[n] += w
                for path, w in pw_p:
                    for n in path:
                        if n in np_w:
                            np_w[n] += w
                base_per_flow.append(nb)
                sigs_per_pair_flow.append(np_w)

            for pr_w, c1, c2 in zip(sub_probs, act_c1, act_c2):
                ratios = []
                for nb, np_w in zip(base_per_flow, sigs_per_pair_flow):
                    b_sum = nb[c1] + nb[c2]
                    p_sum = np_w[c1] + np_w[c2]
                    ratios.append(round(p_sum / b_sum, 2) if b_sum > 1.0e-9 else 0.0)
                sig = ("ctrl",) + tuple(ratios)
                buckets[sig] = (buckets[sig] if sig in buckets else 0.0) + float(pr_w)

        if len(buckets) <= 1:
            continue
        h_split = -sum(q * math.log2(q) for q in buckets.values() if q > 1.0e-12)
        c_val = impact.estimate(p, expected_drop_prob=inf_pair.estimated_drop_prob).scalar_cost(tradeoff_lambda)
        sc = h_split / c_val
        if sc > best_sc:
            best_sc = sc
            best_p = p

    return best_p


def run_two_fault_episode(
    system: NetworkSystem,
    faulty_pair: Tuple[int, int],
    affected_pairs: Tuple[Tuple[int, int], ...],
    drop_prob: float = 0.04,
    mode: str = "fives",
    rng_seed: int = 42,
    max_steps: int = 25,
) -> Dict[str, float]:
    """Localize two simultaneous gray faults on `system` under FIVES Pair-Bayesian vs. Operator pass/fail."""
    rng = np.random.default_rng(rng_seed)
    safety = SafetyFilter(system)
    impact = TwoPhaseImpactEstimator(system)
    efficacy = MultiOutcomeEfficacyEstimator(system)
    excluded = {ep for pair in affected_pairs for ep in pair}
    pool = sorted({
        n
        for pair in affected_pairs
        for path in system.shortest_paths(pair[0], pair[1])
        for n in path
        if n not in excluded
    })
    max_paths = max(len(system.shortest_paths(pair[0], pair[1])) for pair in affected_pairs)
    eff_flows = max(400, 25 * max_paths)

    win0 = simulate_multifault_and_batch_window(
        system, faulty_pair, affected_pairs, drop_prob, 1.0e-4, (), rng, flows_per_pair=eff_flows
    )

    tried_keys: Set[Tuple] = set()
    steps = 0
    total_ttl = 0.0
    total_disrupt = 0.0

    if mode == "operator":
        inf_op = SetIntersectionInference(system)
        inf_op.reset(pool)
        inf_op.update(win0)
        rng_op = np.random.default_rng(rng_seed + 999)
        for _ in range(max_steps):
            suspects = inf_op.equivalence_set()
            if len(suspects) <= 2:
                break
            raw = [
                p for p in system.candidate_perturbations(affected_pairs, suspects)
                if p.key not in tried_keys and safety.is_safe(p, affected_pairs)
                and not isinstance(p, (SubtleWeightShift, FlowGroupSplit))
            ]
            splitting = [p for p in raw if len(efficacy.partition_suspects(p, sorted(suspects), affected_pairs)) > 1]
            if len(splitting) == 0:
                break
            splitting.sort(key=lambda p: (round(impact.estimate(p, drop_prob).scalar_cost(0.5), 4), rng_op.random()))
            p_sel = splitting[0]
            tried_keys.add(p_sel.key)
            im = impact.estimate(p_sel, drop_prob)
            steps += 1
            total_ttl += im.total_time_sec
            total_disrupt += im.total_disruption
            win = simulate_multifault_and_batch_window(
                system, faulty_pair, affected_pairs, drop_prob, 1.0e-4, [p_sel], rng, flows_per_pair=eff_flows
            )
            inf_op.update(win)

        ret = inf_op.equivalence_set()
        hits = len(ret & set(faulty_pair))
        return {
            "steps": float(steps),
            "ttl": total_ttl,
            "disruption": total_disrupt,
            "recall": float(hits) / 2.0,
            "precision": float(hits) / float(max(1, len(ret))),
            "exact_pair": 1.0 if ret == set(faulty_pair) else 0.0,
        }

    inf_pair = PairFaultBayesianPGM(system, pool)
    inf_pair.update(win0)
    unchanged = 0
    _, _, cred_nodes = inf_pair.pair_posteriors_and_credible_nodes()

    for _ in range(max_steps):
        if len(cred_nodes) <= 2:
            break
        p_sel = _select_pair_splitting_action(
            system, safety, impact, inf_pair, affected_pairs, tried_keys, tradeoff_lambda=0.5
        )
        if p_sel is None:
            break
        tried_keys.add(p_sel.key)
        im = impact.estimate(p_sel, drop_prob)
        steps += 1
        total_ttl += im.total_time_sec
        total_disrupt += im.total_disruption
        win = simulate_multifault_and_batch_window(
            system, faulty_pair, affected_pairs, drop_prob, 1.0e-4, [p_sel], rng, flows_per_pair=eff_flows
        )
        inf_pair.update(win)
        _, _, next_cred = inf_pair.pair_posteriors_and_credible_nodes()
        if next_cred == cred_nodes:
            unchanged += 1
            if unchanged >= 5:
                break
        else:
            unchanged = 0
            cred_nodes = next_cred

    _, top_pair, final_cred = inf_pair.pair_posteriors_and_credible_nodes()
    ret_set = final_cred if len(final_cred) >= 2 else set(top_pair)
    hits = len(ret_set & set(faulty_pair))
    return {
        "steps": float(steps),
        "ttl": total_ttl,
        "disruption": total_disrupt,
        "recall": float(hits) / 2.0,
        "precision": float(hits) / float(len(ret_set)),
        "exact_pair": 1.0 if set(top_pair) == set(faulty_pair) else 0.0,
    }
