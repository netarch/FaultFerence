"""Perturbation Evaluators: Safety Filter, Two-Phase Impact Estimator, and Multi-Outcome Efficacy Estimator."""

from dataclasses import dataclass
import math
from typing import Dict, List, Optional, Sequence, Set, Tuple
import numpy as np

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
from .systems import NetworkSystem


@dataclass(frozen=True)
class ImpactBreakdown:
    """Two-phase operational footprint: Apply/Unapply phase + Observation phase."""

    apply_time_sec: float
    apply_disruption: float
    obs_time_sec: float
    obs_disruption: float

    @property
    def total_time_sec(self) -> float:
        return self.apply_time_sec + self.obs_time_sec

    @property
    def total_disruption(self) -> float:
        return self.apply_disruption + self.obs_disruption

    def scalar_cost(self, tradeoff_lambda: float) -> float:
        """Combine normalized Disruption and Time-to-Localize via operator weight lambda in [0, 1].

        lambda = 1.0 -> strictly minimize Live Disruption (with small tie-break on time)
        lambda = 0.0 -> strictly minimize Wall-Clock Time-to-Localize
        """
        assert 0.0 <= tradeoff_lambda <= 1.0
        # Normalize time (in tens of seconds) and disruption onto commensurate scales
        norm_d = self.total_disruption
        norm_t = self.total_time_sec / 10.0
        return max(1.0e-4, tradeoff_lambda * norm_d + (1.0 - tradeoff_lambda) * norm_t + 1.0e-3 * (norm_d + norm_t))


class SafetyFilter:
    """Filters candidate perturbations against live operational & vendor safety bounds."""

    def __init__(self, system: NetworkSystem):
        self.system = system

    def is_safe(self, p: Perturbation, active_pairs: Sequence[Tuple[int, int]]) -> bool:
        cfg = self.system.safety

        if isinstance(p, ActiveProbe):
            if p.src_node in cfg.probe_banned_nodes or p.dst_node in cfg.probe_banned_nodes:
                return False
            if p.src_node in cfg.external_blackbox_nodes or p.dst_node in cfg.external_blackbox_nodes:
                return False
            return self.system.check_no_branch(p.flow_pair, p.src_node, p.dst_node)

        if isinstance(p, PacketMirror):
            if p.node in cfg.mirror_banned_nodes or p.node in cfg.external_blackbox_nodes:
                return False
            if p.filtered:
                return p.node in cfg.mirror_filtered_nodes
            if p.node not in cfg.mirror_unfiltered_only_nodes:
                return False
            # Unfiltered mirroring only allowed on low-traffic switches
            nbrs = list(self.system.G.neighbors(p.node))
            if len(nbrs) == 0:
                return False
            mean_load = sum(self.system.edge_loads[(p.node, nb)] for nb in nbrs) / len(nbrs)
            return mean_load <= cfg.max_unfiltered_mirror_load

        if isinstance(p, FlowLinkDrain):
            if p.u in cfg.drain_banned_nodes or p.v in cfg.drain_banned_nodes:
                return False
            if p.u in cfg.external_blackbox_nodes or p.v in cfg.external_blackbox_nodes:
                return False
            pw_base = self.system.shortest_paths(p.flow_pair[0], p.flow_pair[1])
            pw_post = self.system.paths_under_perturbation(p.flow_pair, p)
            if len(pw_post) == 0:
                return False
            # Enforce minimum residual path-capacity ratio for the affected rack pair
            cap_ratio = float(len(pw_post)) / float(len(pw_base))
            return cap_ratio >= cfg.min_bandwidth_ratio

        if isinstance(p, FlowGroupSplit):
            if p.u in cfg.drain_banned_nodes or p.u in cfg.external_blackbox_nodes:
                return False
            if any(v in cfg.drain_banned_nodes or v in cfg.external_blackbox_nodes for v in p.drained_nexthops):
                return False
            pw_base = self.system.shortest_paths(p.flow_pair[0], p.flow_pair[1])
            pw_post = self.system.paths_under_perturbation(p.flow_pair, p)
            if len(pw_post) == 0:
                return False
            cap_ratio = float(len(pw_post)) / float(len(pw_base))
            return cap_ratio >= cfg.min_bandwidth_ratio

        if isinstance(p, SubtleWeightShift):
            if p.u in cfg.external_blackbox_nodes or p.v in cfg.external_blackbox_nodes:
                return False
            base_paths = self.system.shortest_paths(p.flow_pair[0], p.flow_pair[1])
            if len(base_paths) <= 1:
                return False
            uses_uv = sum(
                1 for path in base_paths
                if any(path[i] == p.u and path[i + 1] == p.v for i in range(len(path) - 1))
            )
            if uses_uv == 0 or uses_uv == len(base_paths):
                return False
            # Effective capacity with weight shift remains high (no paths removed!)
            eff_ratio = (uses_uv * p.weight_factor + (len(base_paths) - uses_uv)) / float(len(base_paths))
            return eff_ratio >= cfg.min_bandwidth_ratio

        if isinstance(p, FullLinkDrain):
            if p.u in cfg.drain_banned_nodes or p.v in cfg.drain_banned_nodes:
                return False
            if p.u in cfg.external_blackbox_nodes or p.v in cfg.external_blackbox_nodes:
                return False
            # Check pre-existing bundle health & connectivity for all active pairs
            edge_cap = self.system.edge_capacities[(p.u, p.v)]
            if edge_cap <= cfg.min_bandwidth_ratio * 100.0:
                return False
            for pair in active_pairs:
                pw_base = self.system.shortest_paths(pair[0], pair[1])
                pw_post = self.system.paths_under_perturbation(pair, p)
                if len(pw_post) == 0:
                    return False
                # Check if primary ECMP capacity drops below safety floor
                if pw_post[0][0] in pw_base:
                    if float(len(pw_post)) / float(len(pw_base)) < cfg.min_bandwidth_ratio:
                        return False
            return True

        if isinstance(p, ComponentReset):
            if p.node in cfg.reset_banned_nodes or p.node in cfg.external_blackbox_nodes:
                return False
            for pair in active_pairs:
                if p.node in pair:
                    return False
            if p.node not in self.system._articulation_points:
                return True
            g_mod = self.system.G.copy()
            g_mod.remove_node(p.node)
            for pair in active_pairs:
                if not nx.has_path(g_mod, pair[0], pair[1]):
                    return False
            return True

        raise ValueError(f"Unknown perturbation type: {p}")


import networkx as nx  # noqa: E402


class TwoPhaseImpactEstimator:
    """Computes live Disruption and Step Time across Apply/Unapply and Observation phases."""

    def __init__(
        self,
        system: NetworkSystem,
        noise_sigma: float = 0.0,
        noise_rng: Optional[np.random.Generator] = None,
    ):
        self.system = system
        self.noise_sigma = noise_sigma
        self.noise_rng = noise_rng
        self._noise_cache: Dict[Tuple, float] = {}

    def _noise_multiplier(self, key: Tuple) -> float:
        if self.noise_sigma <= 0.0:
            return 1.0
        if key not in self._noise_cache:
            assert self.noise_rng is not None
            self._noise_cache[key] = float(np.exp(self.noise_rng.normal(0.0, self.noise_sigma)))
        return self._noise_cache[key]

    @staticmethod
    def _congestion_penalty(util: float) -> float:
        """Convex M/M/1 queueing delay & drop risk penalty as link utilization approaches 1."""
        u = min(0.96, max(0.01, util))
        return u / (1.0 - u)

    def estimate(self, p: Perturbation, expected_drop_prob: float = 0.02) -> ImpactBreakdown:
        mult = self._noise_multiplier(p.key)

        if isinstance(p, ActiveProbe):
            # Telemetry probe: zero routing churn, minimal switch CPU / probe injection overhead
            apply_t = 1.0
            apply_d = 0.05
            # Observation time scales with number of probes needed to detect `expected_drop_prob`
            obs_t = max(2.0, min(15.0, 2.5 / max(0.01, expected_drop_prob)))
            obs_d = 0.15
            return ImpactBreakdown(apply_t, apply_d * mult, obs_t, obs_d * mult)

        if isinstance(p, PacketMirror):
            apply_t = 2.0
            apply_d = 0.10 if p.filtered else 0.60
            obs_t = max(4.0, min(20.0, 3.0 / max(0.01, expected_drop_prob)))
            obs_d = 0.25 if p.filtered else 1.80
            return ImpactBreakdown(apply_t, apply_d * mult, obs_t, obs_d * mult)

        if isinstance(p, SubtleWeightShift):
            base_paths = self.system.shortest_paths(p.flow_pair[0], p.flow_pair[1])
            n_tot = len(base_paths)
            n_uv = sum(
                1 for path in base_paths
                if any(path[i] == p.u and path[i + 1] == p.v for i in range(len(path) - 1))
            )
            shifted_frac = (1.0 - p.weight_factor) * (float(n_uv) / float(n_tot))
            base_u = self.system.edge_loads[(p.u, p.v)]
            delta_u = 0.06 * shifted_frac
            cong_delta = self._congestion_penalty(base_u + delta_u) - self._congestion_penalty(base_u)
            apply_t = 1.5  # Fast WCMP group-table weight update + rollback
            apply_d = 0.12 * shifted_frac
            # Subtle shift requires slightly longer observation window for statistical power
            obs_t = max(6.0, min(30.0, 4.5 / max(0.01, expected_drop_prob * shifted_frac)))
            obs_d = 0.35 * shifted_frac + 1.5 * cong_delta
            return ImpactBreakdown(apply_t, apply_d * mult, obs_t, obs_d * mult)

        if isinstance(p, FlowLinkDrain):
            base_paths = self.system.shortest_paths(p.flow_pair[0], p.flow_pair[1])
            n_tot = len(base_paths)
            n_uv = sum(
                1 for path in base_paths
                if any(path[i] == p.u and path[i + 1] == p.v for i in range(len(path) - 1))
            )
            rerouted_frac = float(n_uv) / float(max(1, n_tot))
            rem_frac = max(0.1, 1.0 - rerouted_frac)
            base_u = self.system.edge_loads[(p.u, p.v)]
            post_u = base_u + 0.18 * (rerouted_frac / rem_frac)
            cong_delta = self._congestion_penalty(post_u) - self._congestion_penalty(base_u)
            apply_t = 4.0  # Rule programming + TCP flowlet/reordering transient + rollback
            apply_d = 0.80 * rerouted_frac
            obs_t = max(5.0, min(25.0, 3.0 / max(0.01, expected_drop_prob)))
            obs_d = 1.20 * rerouted_frac + 3.5 * cong_delta
            return ImpactBreakdown(apply_t, apply_d * mult, obs_t, obs_d * mult)

        if isinstance(p, FlowGroupSplit):
            base_paths = self.system.shortest_paths(p.flow_pair[0], p.flow_pair[1])
            post_paths = self.system.paths_under_perturbation(p.flow_pair, p)
            n_tot = len(base_paths)
            rerouted_frac = float(n_tot - len(post_paths)) / float(max(1, n_tot))
            rem_frac = max(0.1, 1.0 - rerouted_frac)
            base_u = max(self.system.edge_loads[(p.u, v)] for v in p.drained_nexthops)
            post_u = base_u + 0.18 * (rerouted_frac / rem_frac)
            cong_delta = self._congestion_penalty(post_u) - self._congestion_penalty(base_u)
            apply_t = 4.0  # Single WCMP/PBR group-table programming + rollback
            apply_d = 0.80 * rerouted_frac
            obs_t = max(5.0, min(25.0, 3.0 / max(0.01, expected_drop_prob)))
            obs_d = 1.20 * rerouted_frac + 3.5 * cong_delta
            return ImpactBreakdown(apply_t, apply_d * mult, obs_t, obs_d * mult)

        if isinstance(p, FullLinkDrain):
            base_u = self.system.edge_loads[(p.u, p.v)]
            deg = max(1, self.system.G.degree(p.u) - 1)
            post_u = base_u + (base_u / float(deg))
            cong_delta = self._congestion_penalty(post_u) - self._congestion_penalty(base_u)
            apply_t = 18.0  # Full link drain + IGP convergence + un-drain convergence
            apply_d = 4.50 * base_u
            obs_t = max(8.0, min(30.0, 3.0 / max(0.01, expected_drop_prob)))
            obs_d = 6.0 * base_u + 8.0 * cong_delta
            return ImpactBreakdown(apply_t, apply_d * mult, obs_t, obs_d * mult)

        if isinstance(p, ComponentReset):
            nbrs = list(self.system.G.neighbors(p.node))
            total_load = sum(self.system.edge_loads[(p.node, nb)] for nb in nbrs)
            apply_t = 120.0  # Drain + reboot/swap + table reload
            apply_d = 15.0 + 6.0 * total_load
            obs_t = 15.0
            obs_d = 8.0 + 3.0 * total_load
            return ImpactBreakdown(apply_t, apply_d * mult, obs_t, obs_d * mult)

        raise ValueError(f"Unhandled perturbation {p}")


class MultiOutcomeEfficacyEstimator:
    """Computes expected suspect-ambiguity reduction across multi-way & probabilistic outcomes."""

    def __init__(self, system: NetworkSystem):
        self.system = system

    def outcome_signature(self, p: Perturbation, culprit: int, active_pairs: Sequence[Tuple[int, int]]) -> Tuple:
        """Compute expected telemetry shift signature induced if `culprit` is the faulty component.

        Components with distinct signatures belong to distinct post-perturbation outcome classes!
        Quantized to 2 decimal places so subtle ECMP weight shifts create well-defined multi-way splits
        proportional to path-weight changes while ignoring floating-point rounding dust.
        """
        if isinstance(p, ComponentReset):
            return ("reset", 1 if culprit == p.node else 0)

        if isinstance(p, ActiveProbe):
            sub_paths = self.system.shortest_paths(p.src_node, p.dst_node)
            hit_frac = sum(1.0 for sp in sub_paths if culprit in sp) / float(len(sub_paths))
            return ("probe", round(hit_frac, 2))

        if isinstance(p, PacketMirror):
            base_paths = self.system.shortest_paths(p.flow_pair[0], p.flow_pair[1])
            through_m = [path for path in base_paths if p.node in path]
            if len(through_m) == 0:
                return ("mirror", 0.0)
            up_hits = sum(
                1.0 for path in through_m if culprit in path[: path.index(p.node) + 1]
            ) / float(len(through_m))
            return ("mirror", round(up_hits, 2))

        # Control-plane perturbations (FlowLinkDrain, SubtleWeightShift, FullLinkDrain):
        # Signature is the vector of relative traffic-share multipliers (post_hit_w / base_hit_w) across active_pairs!
        # Two suspects in different tiers (e.g. Agg vs Core) are only distinguished if their relative traffic share
        # changes differently under `p`!
        sig = []
        for pair in active_pairs:
            pw_base = self.system.paths_under_perturbation(pair, None)
            base_w = sum(w for path, w in pw_base if culprit in path)
            if base_w <= 1.0e-9:
                sig.append(0.0)
            else:
                pw_post = self.system.paths_under_perturbation(pair, p)
                post_w = sum(w for path, w in pw_post if culprit in path)
                sig.append(round(post_w / base_w, 2))
        return ("control",) + tuple(sig)

    def partition_suspects(
        self,
        p: Perturbation,
        suspects: Sequence[int],
        active_pairs: Sequence[Tuple[int, int]],
    ) -> Dict[Tuple, List[int]]:
        """Partition `suspects` in a single pass per path-set (O(|paths| * L + |suspects|))."""
        buckets: Dict[Tuple, List[int]] = {}
        suspect_set = set(suspects)

        if isinstance(p, ComponentReset):
            for s in suspects:
                sig = ("reset", 1 if s == p.node else 0)
                if sig not in buckets:
                    buckets[sig] = []
                buckets[sig].append(s)
            return buckets

        if isinstance(p, ActiveProbe):
            sub_paths = self.system.shortest_paths(p.src_node, p.dst_node)
            inv_n = 1.0 / float(len(sub_paths))
            hit_map: Dict[int, float] = {s: 0.0 for s in suspects}
            for sp in sub_paths:
                for n in sp:
                    if n in suspect_set:
                        hit_map[n] += inv_n
            for s in suspects:
                sig = ("probe", round(hit_map[s], 2))
                if sig not in buckets:
                    buckets[sig] = []
                buckets[sig].append(s)
            return buckets

        if isinstance(p, PacketMirror):
            base_paths = self.system.shortest_paths(p.flow_pair[0], p.flow_pair[1])
            through_m = [path for path in base_paths if p.node in path]
            hit_map = {s: 0.0 for s in suspects}
            if len(through_m) > 0:
                inv_m = 1.0 / float(len(through_m))
                for path in through_m:
                    idx_m = path.index(p.node)
                    for n in path[: idx_m + 1]:
                        if n in suspect_set:
                            hit_map[n] += inv_m
            for s in suspects:
                sig = ("mirror", round(hit_map[s], 2))
                if sig not in buckets:
                    buckets[sig] = []
                buckets[sig].append(s)
            return buckets

        # Control-plane perturbations: single-pass accumulation of base and post traffic weights per pair
        pair_ratios: List[Dict[int, float]] = []
        for pair in active_pairs:
            base_map: Dict[int, float] = {s: 0.0 for s in suspects}
            for path, w in self.system.paths_under_perturbation(pair, None):
                for n in path:
                    if n in suspect_set:
                        base_map[n] += w
            post_map: Dict[int, float] = {s: 0.0 for s in suspects}
            for path, w in self.system.paths_under_perturbation(pair, p):
                for n in path:
                    if n in suspect_set:
                        post_map[n] += w
            ratios = {
                s: (round(post_map[s] / base_map[s], 2) if base_map[s] > 1.0e-9 else 0.0)
                for s in suspects
            }
            pair_ratios.append(ratios)

        for s in suspects:
            sig = ("control",) + tuple(rmap[s] for rmap in pair_ratios)
            if sig not in buckets:
                buckets[sig] = []
            buckets[sig].append(s)
        return buckets

    def expected_suspect_reduction(
        self,
        p: Perturbation,
        posteriors: Dict[int, float],
        active_pairs: Sequence[Tuple[int, int]],
    ) -> float:
        """Modern outline metric: sum_i p_i * k_i, weighted by posterior fault probabilities."""
        suspects = [c for c, pr in posteriors.items() if pr > 1.0e-6]
        n = len(suspects)
        if n <= 1:
            return 0.0
        buckets = self.partition_suspects(p, suspects, active_pairs)
        if len(buckets) <= 1:
            return 0.0

        total_mass = sum(posteriors[c] for c in suspects)
        expected_k = 0.0
        for group in buckets.values():
            p_i = sum(posteriors[c] for c in group) / total_mass
            k_i = n - len(group)
            expected_k += p_i * float(k_i)
        return expected_k

    @staticmethod
    def _bin_entropy(q: float) -> float:
        if q <= 1.0e-12 or q >= 1.0 - 1.0e-12:
            return 0.0
        return -(q * math.log2(q) + (1.0 - q) * math.log2(1.0 - q))

    def mutual_information_and_pairs(
        self,
        p: Perturbation,
        posteriors: Dict[int, float],
        active_pairs: Sequence[Tuple[int, int]],
        expected_drop_prob: float = 0.02,
        p_node_map: Optional[Dict[int, float]] = None,
        flows_per_pair: int = 400,
        packets_per_flow: int = 25,
    ) -> Tuple[float, float]:
        """Compute exact/principled Shannon mutual information I(C; O_p) in bits and weighted differentiated pairs."""
        suspects = [c for c, pr in posteriors.items() if pr > 1.0e-6]
        if len(suspects) <= 1:
            return 0.0, 0.0

        total_mass = sum(posteriors[c] for c in suspects)
        probs = {c: posteriors[c] / total_mass for c in suspects}

        if isinstance(p, ActiveProbe):
            # Single-5-tuple probe hashes onto 1 path in sub_paths -> hits `c` w.p. h_c, misses w.p. (1 - h_c)
            sub_paths = self.system.shortest_paths(p.src_node, p.dst_node)
            q_fail: Dict[int, float] = {}
            for c in suspects:
                p_c = p_node_map[c] if (p_node_map is not None and c in p_node_map) else expected_drop_prob
                detect_c = 1.0 - ((1.0 - p_c) ** p.num_probes)
                h_c = sum(1.0 for sp in sub_paths if c in sp) / float(len(sub_paths))
                q_fail[c] = h_c * detect_c + (1.0 - h_c) * (1.0 - ((1.0 - 1.0e-4) ** p.num_probes))
            q_bar = sum(probs[c] * q_fail[c] for c in suspects)
            mi = self._bin_entropy(q_bar) - sum(probs[c] * self._bin_entropy(q_fail[c]) for c in suspects)
            if mi <= 1.0e-9:
                return 0.0, 0.0
            pairs_w = q_bar * (1.0 - q_bar) * float(len(suspects) * len(suspects))
            return max(0.0, mi), pairs_w

        if isinstance(p, PacketMirror):
            base_paths = self.system.shortest_paths(p.flow_pair[0], p.flow_pair[1])
            through_m = [path for path in base_paths if p.node in path]
            if len(through_m) == 0:
                return 0.0, 0.0
            n_mir = 200
            q_fail = {}
            for c in suspects:
                p_c = p_node_map[c] if (p_node_map is not None and c in p_node_map) else expected_drop_prob
                up_frac = sum(
                    1.0 for path in through_m if c in path[: path.index(p.node) + 1]
                ) / float(len(through_m))
                q_fail[c] = 1.0 - ((1.0 - max(1.0e-4, up_frac * p_c)) ** n_mir)
            q_bar = sum(probs[c] * q_fail[c] for c in suspects)
            mi = self._bin_entropy(q_bar) - sum(probs[c] * self._bin_entropy(q_fail[c]) for c in suspects)
            pairs_w = q_bar * (1.0 - q_bar) * float(len(suspects) * len(suspects))
            return max(0.0, mi), pairs_w

        # Control & Physical perturbations: partition suspects by post-perturbation relative rate multiplier
        buckets = self.partition_suspects(p, suspects, active_pairs)
        if len(buckets) <= 1:
            return 0.0, 0.0

        group_probs = [sum(probs[c] for c in g) for g in buckets.values()]
        h_part = -sum(gp * math.log2(gp) for gp in group_probs if gp > 1.0e-12)

        pair_mass = 0.0
        for i in range(len(group_probs)):
            for j in range(i + 1, len(group_probs)):
                pair_mass += group_probs[i] * group_probs[j]
        weighted_pairs = pair_mass * float(len(suspects) * len(suspects))

        if isinstance(p, ComponentReset):
            return h_part, weighted_pairs

        # Baseline expected bad-packet count per window: N * r_0 ≈ N * (hit_w_0[c] * p_c)
        c0 = suspects[0]
        p_c0 = p_node_map[c0] if (p_node_map is not None and c0 in p_node_map) else expected_drop_prob
        pw0 = self.system.paths_under_perturbation(active_pairs[0], None)
        h0 = max(0.01, sum(w for path, w in pw0 if c0 in path))
        base_obs_rate = h0 * p_c0

        eff_flows = max(flows_per_pair, 25 * len(pw0))
        n_samples = float(eff_flows * packets_per_flow)
        std_noise = math.sqrt(max(1.0, n_samples * base_obs_rate))

        sigs = list(buckets.keys())
        sep_pair_mass = 0.0
        for i in range(len(sigs)):
            for j in range(i + 1, len(sigs)):
                gap_ij = sum(abs(float(sigs[i][k]) - float(sigs[j][k])) for k in range(1, len(sigs[i])))
                z_ij = (n_samples * base_obs_rate * gap_ij) / std_noise
                alpha_ij = math.erf(z_ij / math.sqrt(2.0))
                sep_pair_mass += group_probs[i] * group_probs[j] * alpha_ij

        sep_factor = (sep_pair_mass / pair_mass) if pair_mass > 1.0e-12 else 0.0
        return h_part * sep_factor, weighted_pairs * sep_factor
