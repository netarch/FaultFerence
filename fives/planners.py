"""Perturbation Sequencing Planners: FIVES (k-lookahead), Exact Optimal B&B, NetPilot, Operator, Random."""

import math
from typing import Dict, FrozenSet, List, Optional, Sequence, Set, Tuple
import numpy as np

from .evaluators import MultiOutcomeEfficacyEstimator, SafetyFilter, TwoPhaseImpactEstimator
from .perturbations import (
    ActiveProbe,
    ComponentReset,
    FlowGroupSplit,
    FlowLinkDrain,
    FullLinkDrain,
    Perturbation,
    SubtleWeightShift,
)
from .systems import NetworkSystem


class Planner:
    name: str = "Planner"

    def select_next(
        self,
        posteriors: Dict[int, float],
        active_pairs: Sequence[Tuple[int, int]],
        tried_keys: Set[Tuple],
        expected_drop_prob: float,
    ) -> Optional[Perturbation]:
        raise NotImplementedError


class FivesPlanner(Planner):
    """FIVES adaptive perturbation planner maximizing multi-outcome efficacy per unit impact/time cost."""

    def __init__(
        self,
        system: NetworkSystem,
        safety_filter: SafetyFilter,
        impact_estimator: TwoPhaseImpactEstimator,
        efficacy_estimator: MultiOutcomeEfficacyEstimator,
        tradeoff_lambda: float = 0.5,
        lookahead_k: int = 1,
        allow_repeat_noisy: bool = False,
        branch_beam_width: int = 8,
    ):
        assert lookahead_k >= 1
        self.name = f"FIVES(k={lookahead_k})"
        self.system = system
        self.safety = safety_filter
        self.impact = impact_estimator
        self.efficacy = efficacy_estimator
        self.tradeoff_lambda = tradeoff_lambda
        self.lookahead_k = lookahead_k
        self.allow_repeat_noisy = allow_repeat_noisy
        self.branch_beam_width = branch_beam_width
        self._p_node_map: Optional[Dict[int, float]] = None

    def set_node_drop_map(self, p_node_map: Optional[Dict[int, float]]) -> None:
        self._p_node_map = p_node_map

    def _safe_candidates(
        self,
        suspects: Set[int],
        active_pairs: Sequence[Tuple[int, int]],
        tried_keys: Set[Tuple],
    ) -> List[Perturbation]:
        raw = self.system.candidate_perturbations(active_pairs, suspects)
        out = []
        for p in raw:
            if (not self.allow_repeat_noisy) and (p.key in tried_keys):
                continue
            if self.safety.is_safe(p, active_pairs):
                out.append(p)
        return out

    def _greedy_score(
        self,
        p: Perturbation,
        posteriors: Dict[int, float],
        active_pairs: Sequence[Tuple[int, int]],
        expected_drop_prob: float,
    ) -> float:
        info_gain, pairs_w = self.efficacy.mutual_information_and_pairs(
            p, posteriors, active_pairs, expected_drop_prob=expected_drop_prob, p_node_map=self._p_node_map
        )
        if info_gain <= 1.0e-9 and pairs_w <= 1.0e-9:
            return 0.0
        cost = self.impact.estimate(p, expected_drop_prob=expected_drop_prob).scalar_cost(self.tradeoff_lambda)
        # Primary objective: expected information gain (bits) per unit scalarized Disruption-TTL cost,
        # with tiny tie-break on differentiated pairs.
        return (info_gain + 1.0e-3 * pairs_w) / cost

    def _lookahead_value(
        self,
        suspects_post: Dict[int, float],
        active_pairs: Sequence[Tuple[int, int]],
        tried_keys: Set[Tuple],
        expected_drop_prob: float,
        depth_left: int,
    ) -> Tuple[Optional[Perturbation], float]:
        """Adaptive k-step lookahead returning (best_action, cumulative_expected_gain_per_cost)."""
        suspects = {c for c, pr in suspects_post.items() if pr > 1.0e-6}
        if len(suspects) <= 1 or depth_left <= 0:
            return None, 0.0

        cands = self._safe_candidates(suspects, active_pairs, tried_keys)
        scored = []
        for p in cands:
            sc = self._greedy_score(p, suspects_post, active_pairs, expected_drop_prob)
            if sc > 0.0:
                scored.append((sc, p))
        if len(scored) == 0:
            return None, 0.0

        scored.sort(key=lambda x: -x[0])
        if depth_left == 1:
            return scored[0][1], scored[0][0]

        top_cands = [p for _, p in scored[: self.branch_beam_width]]
        best_p: Optional[Perturbation] = None
        best_val = -1.0

        s_list = sorted(suspects)
        total_mass = sum(suspects_post[c] for c in s_list)

        for p in top_cands:
            ig, _ = self.efficacy.mutual_information_and_pairs(p, suspects_post, active_pairs, expected_drop_prob)
            c_step = self.impact.estimate(p, expected_drop_prob).scalar_cost(self.tradeoff_lambda)
            buckets = self.efficacy.partition_suspects(p, s_list, active_pairs)
            next_tried = tried_keys | {p.key}

            future_ig = 0.0
            future_cost = 0.0
            for group in buckets.values():
                g_mass = sum(suspects_post[c] for c in group)
                prob_g = g_mass / total_mass
                if len(group) > 1 and prob_g > 1.0e-6:
                    sub_post = {c: suspects_post[c] / g_mass for c in group}
                    sub_p, _ = self._lookahead_value(
                        sub_post, active_pairs, next_tried, expected_drop_prob, depth_left - 1
                    )
                    if sub_p is not None:
                        sub_ig, _ = self.efficacy.mutual_information_and_pairs(
                            sub_p, sub_post, active_pairs, expected_drop_prob
                        )
                        sub_c = self.impact.estimate(sub_p, expected_drop_prob).scalar_cost(self.tradeoff_lambda)
                        future_ig += prob_g * sub_ig
                        future_cost += prob_g * sub_c

            val = (ig + future_ig) / (c_step + future_cost)
            if val > best_val:
                best_val = val
                best_p = p

        return best_p, best_val

    def select_next(
        self,
        posteriors: Dict[int, float],
        active_pairs: Sequence[Tuple[int, int]],
        tried_keys: Set[Tuple],
        expected_drop_prob: float,
    ) -> Optional[Perturbation]:
        best_p, _ = self._lookahead_value(
            posteriors, active_pairs, tried_keys, expected_drop_prob, self.lookahead_k
        )
        return best_p


class ExactOptimalPlanner(Planner):
    """Exact minimum-expected-cost decision-tree solver via memoized Branch-and-Bound (for |E_0| <= 25)."""

    def __init__(
        self,
        system: NetworkSystem,
        safety_filter: SafetyFilter,
        impact_estimator: TwoPhaseImpactEstimator,
        efficacy_estimator: MultiOutcomeEfficacyEstimator,
        tradeoff_lambda: float = 0.5,
        max_exact_size: int = 25,
    ):
        self.name = "ExactOptimal"
        self.system = system
        self.safety = safety_filter
        self.impact = impact_estimator
        self.efficacy = efficacy_estimator
        self.tradeoff_lambda = tradeoff_lambda
        self.max_exact_size = max_exact_size

    def compute_optimal_tree_cost(
        self,
        suspects: FrozenSet[int],
        posteriors: Dict[int, float],
        active_pairs: Sequence[Tuple[int, int]],
        expected_drop_prob: float,
    ) -> Tuple[Optional[Perturbation], float]:
        assert len(suspects) <= self.max_exact_size, f"|E|={len(suspects)} exceeds max_exact_size={self.max_exact_size}"
        if len(suspects) <= 1:
            return None, 0.0

        raw_cands = [
            p for p in self.system.candidate_perturbations(active_pairs, set(suspects))
            if self.safety.is_safe(p, active_pairs) and not isinstance(p, SubtleWeightShift)
        ]

        # Precompute partition map and scalar cost per unique partition signature on `suspects`
        # Keep only the cheapest perturbation among any two actions inducing the exact same partition of `suspects`!
        dedup_by_part: Dict[Tuple[Tuple[int, ...], ...], Tuple[float, Perturbation]] = {}
        s_sorted = sorted(suspects)
        for p in raw_cands:
            if isinstance(p, ActiveProbe):
                sub_paths = self.system.shortest_paths(p.src_node, p.dst_node)
                # In a deterministic Binary/m-ary Decision Tree, only branch-free probes whose sub_paths
                # hit each suspect w.p. 0 or 1 induce a deterministic partition of `suspects`.
                if any(0 < sum(1 for sp in sub_paths if s in sp) < len(sub_paths) for s in s_sorted):
                    continue
            buckets = self.efficacy.partition_suspects(p, s_sorted, active_pairs)
            if len(buckets) <= 1:
                continue
            canon = tuple(sorted(tuple(sorted(g)) for g in buckets.values()))
            cost = self.impact.estimate(p, expected_drop_prob).scalar_cost(self.tradeoff_lambda)
            if canon not in dedup_by_part or cost < dedup_by_part[canon][0]:
                dedup_by_part[canon] = (cost, p)

        actions = [(cost, p, canon) for canon, (cost, p) in dedup_by_part.items()]
        # Order actions heuristically (greedy info-gain / cost first) so Branch-and-Bound prunes aggressively!
        actions.sort(key=lambda item: item[0] / max(0.1, math.log2(len(item[2]))))

        memo: Dict[FrozenSet[int], Tuple[Optional[Perturbation], float]] = {}

        def solve(curr: FrozenSet[int]) -> Tuple[Optional[Perturbation], float]:
            if len(curr) <= 1:
                return None, 0.0
            if curr in memo:
                return memo[curr]

            c_mass = sum(posteriors[x] for x in curr)
            # Filter actions that genuinely split `curr`
            valid_acts = []
            for cost, p, full_groups in actions:
                sub_groups = [tuple(x for x in g if x in curr) for g in full_groups]
                sub_groups = [sg for sg in sub_groups if len(sg) > 0]
                if len(sub_groups) > 1:
                    valid_acts.append((cost, p, sub_groups))

            if len(valid_acts) == 0:
                # Irreducible equivalence class under admissible menu
                memo[curr] = (None, 0.0)
                return None, 0.0

            best_cost = math.inf
            best_act: Optional[Perturbation] = None
            for cost, p, sub_groups in valid_acts:
                if cost >= best_cost:
                    continue
                acc_cost = cost
                pruned = False
                for sg in sub_groups:
                    if len(sg) > 1:
                        prob_sg = sum(posteriors[x] for x in sg) / c_mass
                        _, child_cost = solve(frozenset(sg))
                        acc_cost += prob_sg * child_cost
                        if acc_cost >= best_cost:
                            pruned = True
                            break
                if not pruned and acc_cost < best_cost:
                    best_cost = acc_cost
                    best_act = p

            memo[curr] = (best_act, best_cost)
            return best_act, best_cost

        return solve(suspects)

    def select_next(
        self,
        posteriors: Dict[int, float],
        active_pairs: Sequence[Tuple[int, int]],
        tried_keys: Set[Tuple],
        expected_drop_prob: float,
    ) -> Optional[Perturbation]:
        suspects = frozenset(c for c, pr in posteriors.items() if pr > 1.0e-6)
        best_p, _ = self.compute_optimal_tree_cost(suspects, posteriors, active_pairs, expected_drop_prob)
        if best_p is not None and best_p.key in tried_keys:
            return None
        return best_p


class NetPilotPlanner(Planner):
    """Cost-aware fault mitigation / trial-and-error baseline inspired by NetPilot (Wu et al., SIGCOMM '12).

    Evaluates mitigation-capable control & physical actions (FlowLinkDrain, FullLinkDrain, ComponentReset),
    scoring each by (fault_bypass_probability / disruption_cost). Cannot exploit pure telemetry probes or
    subtle non-mitigating weight shifts.
    """

    def __init__(
        self,
        system: NetworkSystem,
        safety_filter: SafetyFilter,
        impact_estimator: TwoPhaseImpactEstimator,
        tradeoff_lambda: float = 0.5,
    ):
        self.name = "NetPilot-Adapted"
        self.system = system
        self.safety = safety_filter
        self.impact = impact_estimator
        self.tradeoff_lambda = tradeoff_lambda

    def select_next(
        self,
        posteriors: Dict[int, float],
        active_pairs: Sequence[Tuple[int, int]],
        tried_keys: Set[Tuple],
        expected_drop_prob: float,
    ) -> Optional[Perturbation]:
        suspects = {c for c, pr in posteriors.items() if pr > 1.0e-6}
        if len(suspects) <= 1:
            return None

        cands = [
            p for p in self.system.candidate_perturbations(active_pairs, suspects)
            if isinstance(p, (FlowLinkDrain, FullLinkDrain, ComponentReset))
            and (p.key not in tried_keys)
            and self.safety.is_safe(p, active_pairs)
        ]
        if len(cands) == 0:
            return None

        best_p: Optional[Perturbation] = None
        best_score = -1.0
        total_mass = sum(posteriors[c] for c in suspects)

        for p in cands:
            # Estimate probability that applying `p` mitigates the observed failure symptom
            if isinstance(p, ComponentReset):
                mitig_prob = (posteriors[p.node] / total_mass) if p.node in suspects else 0.0
            else:
                # Fraction of suspect posterior mass bypassed when `p` reroutes traffic
                mitig_prob = 0.0
                for c in suspects:
                    still_hit = any(
                        any(c in path for path, _ in self.system.paths_under_perturbation(pair, p))
                        for pair in active_pairs
                    )
                    if not still_hit:
                        mitig_prob += posteriors[c] / total_mass
                # Even partial bypass reduces drop rate proportionally (NetPilot impact-confidence heuristic)
                if mitig_prob == 0.0:
                    for c in suspects:
                        base_hit = sum(
                            sum(w for path, w in self.system.paths_under_perturbation(pair, None) if c in path)
                            for pair in active_pairs
                        ) / len(active_pairs)
                        post_hit = sum(
                            sum(w for path, w in self.system.paths_under_perturbation(pair, p) if c in path)
                            for pair in active_pairs
                        ) / len(active_pairs)
                        if post_hit < base_hit - 1.0e-6:
                            mitig_prob += 0.25 * (base_hit - post_hit) * (posteriors[c] / total_mass)

            if mitig_prob <= 0.0:
                continue
            cost = self.impact.estimate(p, expected_drop_prob).scalar_cost(self.tradeoff_lambda)
            score = mitig_prob / cost
            if score > best_score:
                best_score = score
                best_p = p

        return best_p


class CheapestFirstOperatorPlanner(Planner):
    """Operator baseline: picks lowest-disruption safe traditional action intersecting current suspects."""

    def __init__(
        self,
        system: NetworkSystem,
        safety_filter: SafetyFilter,
        impact_estimator: TwoPhaseImpactEstimator,
        efficacy_estimator: MultiOutcomeEfficacyEstimator,
        rng: np.random.Generator,
        tradeoff_lambda: float = 0.5,
    ):
        self.name = "Operator(Cheapest)"
        self.system = system
        self.safety = safety_filter
        self.impact = impact_estimator
        self.efficacy = efficacy_estimator
        self.rng = rng
        self.tradeoff_lambda = tradeoff_lambda

    def select_next(
        self,
        posteriors: Dict[int, float],
        active_pairs: Sequence[Tuple[int, int]],
        tried_keys: Set[Tuple],
        expected_drop_prob: float,
    ) -> Optional[Perturbation]:
        suspects = sorted(c for c, pr in posteriors.items() if pr > 1.0e-6)
        if len(suspects) <= 1:
            return None

        # Human operators do not manually reason about subtle fractional ECMP weight shifts or multi-hop posterior bisections
        cands = [
            p for p in self.system.candidate_perturbations(active_pairs, set(suspects))
            if not isinstance(p, (SubtleWeightShift, FlowGroupSplit))
            and (p.key not in tried_keys)
            and self.safety.is_safe(p, active_pairs)
        ]
        # Filter to actions that touch at least one current suspect (basic topological sanity check)
        relevant = []
        for p in cands:
            if isinstance(p, ComponentReset) and p.node in suspects:
                relevant.append(p)
            elif isinstance(p, ActiveProbe):
                sub_nodes = {n for sp in self.system.shortest_paths(p.src_node, p.dst_node) for n in sp}
                if len(sub_nodes & set(suspects)) > 0:
                    relevant.append(p)
            else:
                buckets = self.efficacy.partition_suspects(p, suspects, active_pairs)
                if len(buckets) > 1:
                    relevant.append(p)

        if len(relevant) == 0:
            return None

        costs = [self.impact.estimate(p, expected_drop_prob).scalar_cost(self.tradeoff_lambda) for p in relevant]
        min_c = min(costs)
        # Operator picks uniformly among tied/near-tied cheapest actions (within 10% cost)
        cheapest_pool = [p for p, c in zip(relevant, costs) if c <= 1.10 * min_c]
        return cheapest_pool[int(self.rng.integers(0, len(cheapest_pool)))]


class RandomSafePlanner(Planner):
    """Unbiased random baseline selecting uniformly among all safe traditional perturbations (no oracle pre-filter)."""

    def __init__(
        self,
        system: NetworkSystem,
        safety_filter: SafetyFilter,
        rng: np.random.Generator,
    ):
        self.name = "Random(Safe)"
        self.system = system
        self.safety = safety_filter
        self.rng = rng

    def select_next(
        self,
        posteriors: Dict[int, float],
        active_pairs: Sequence[Tuple[int, int]],
        tried_keys: Set[Tuple],
        expected_drop_prob: float,
    ) -> Optional[Perturbation]:
        suspects = {c for c, pr in posteriors.items() if pr > 1.0e-6}
        if len(suspects) <= 1:
            return None
        cands = [
            p for p in self.system.candidate_perturbations(active_pairs, suspects)
            if not isinstance(p, (SubtleWeightShift, FlowGroupSplit))
            and (p.key not in tried_keys)
            and self.safety.is_safe(p, active_pairs)
        ]
        if len(cands) == 0:
            return None
        return cands[int(self.rng.integers(0, len(cands)))]
