"""Closed-loop active fault localization episode runner & evaluation metrics."""

from dataclasses import dataclass
import math
import time
from typing import List, Optional, Sequence, Set, Tuple
import numpy as np

from .evaluators import ImpactBreakdown, TwoPhaseImpactEstimator
from .inference import InferenceEngine
from .perturbations import Perturbation
from .planners import Planner
from .systems import FailureSpec, NetworkSystem


@dataclass(frozen=True)
class StepTrace:
    step_idx: int
    perturbation: Optional[Perturbation]
    impact: ImpactBreakdown
    eq_set: Tuple[int, ...]
    top_posterior: float
    compute_ms: float


@dataclass(frozen=True)
class EpisodeResult:
    planner_name: str
    system_name: str
    faulty_node: int
    initial_eq_size: int
    final_eq_set: Tuple[int, ...]
    num_perturbations: int
    total_ttl_sec: float
    total_disruption: float
    peak_step_disruption: float
    total_compute_ms: float
    precision: float
    recall: float
    stopped_early_mitigated: bool
    trajectory: Tuple[StepTrace, ...]


def _entropy_bits(post: dict) -> float:
    return -sum(p * math.log2(p) for p in post.values() if p > 1.0e-12)


def run_episode(
    system: NetworkSystem,
    failure: FailureSpec,
    planner: Planner,
    inference: InferenceEngine,
    true_impact_estimator: TwoPhaseImpactEstimator,
    rng: np.random.Generator,
    max_steps: int = 40,
    flows_per_pair: int = 400,
    packets_per_flow: int = 25,
    stop_on_symptom_mitigation: bool = False,
    cred_mass: float = 0.95,
    stall_patience: int = 4,
    candidate_pool: Optional[Sequence[int]] = None,
) -> EpisodeResult:
    """Execute a complete closed-loop FIVES / baseline localization episode."""
    if candidate_pool is not None:
        pool = list(candidate_pool)
    else:
        # Components on at least one candidate route of the affected flow pairs
        on_path = {
            n
            for pair in failure.affected_pairs
            for path in system.shortest_paths(pair[0], pair[1])
            for n in path
        }
        pool = sorted(on_path)
    inference.reset(pool)

    max_paths = max(len(system.shortest_paths(pair[0], pair[1])) for pair in failure.affected_pairs)
    eff_flows_per_pair = max(flows_per_pair, 25 * max_paths)

    # Step 0: Initial passive observation window (unchanged system)
    t0 = time.perf_counter()
    win0 = system.simulate_window(
        failure, None, rng, flows_per_pair=eff_flows_per_pair, packets_per_flow=packets_per_flow
    )
    inference.update(win0)
    comp0_ms = (time.perf_counter() - t0) * 1000.0

    eq0 = tuple(sorted(inference.equivalence_set(cred_mass=cred_mass)))
    post0 = inference.posteriors()
    top_p0 = max(post0.values())

    traj: List[StepTrace] = [
        StepTrace(
            step_idx=0,
            perturbation=None,
            impact=ImpactBreakdown(0.0, 0.0, 0.0, 0.0),
            eq_set=eq0,
            top_posterior=top_p0,
            compute_ms=comp0_ms,
        )
    ]

    tried_keys: Set[Tuple] = set()
    total_ttl = 0.0
    total_disrupt = 0.0
    peak_disrupt = 0.0
    total_comp_ms = comp0_ms
    unchanged_rounds = 0
    mitigated_stop = False

    curr_eq = set(eq0)
    curr_h = _entropy_bits(post0)
    eff_max_steps = max(max_steps, int(1.25 * len(eq0)))
    is_bayesian = hasattr(inference, "node_drop_prob")
    for step in range(1, eff_max_steps + 1):
        if len(curr_eq) <= 1:
            break

        t_start = time.perf_counter()
        post = inference.posteriors()
        est_drop = getattr(inference, "estimated_drop_prob", failure.unit_bad_prob(True))
        p_node_map = getattr(inference, "node_drop_prob", None)
        if hasattr(planner, "set_node_drop_map"):
            planner.set_node_drop_map(p_node_map)
        pert = planner.select_next(post, failure.affected_pairs, tried_keys, est_drop)
        plan_ms = (time.perf_counter() - t_start) * 1000.0
        if pert is None:
            total_comp_ms += plan_ms
            break

        tried_keys.add(pert.key)

        # Ground-truth impact (always evaluated on true `true_impact_estimator`, even if planner had noisy costs!)
        step_impact = true_impact_estimator.estimate(pert, expected_drop_prob=failure.unit_bad_prob(True))
        total_ttl += step_impact.total_time_sec
        total_disrupt += step_impact.total_disruption
        peak_disrupt = max(peak_disrupt, step_impact.total_disruption)

        # Simulate post-perturbation telemetry window & update inference
        win = system.simulate_window(
            failure, pert, rng, flows_per_pair=eff_flows_per_pair, packets_per_flow=packets_per_flow
        )
        t_inf = time.perf_counter()
        inference.update(win)
        inf_ms = (time.perf_counter() - t_inf) * 1000.0
        step_comp_ms = plan_ms + inf_ms
        total_comp_ms += step_comp_ms

        next_eq = inference.equivalence_set(cred_mass=cred_mass)
        next_post = inference.posteriors()
        traj.append(
            StepTrace(
                step_idx=step,
                perturbation=pert,
                impact=step_impact,
                eq_set=tuple(sorted(next_eq)),
                top_posterior=max(next_post.values()),
                compute_ms=step_comp_ms,
            )
        )

        # Vanilla NetPilot stop-on-mitigation check: stops as soon as observed application bad-rate vanishes!
        if stop_on_symptom_mitigation:
            app_recs = [r for r in win.records if not r.is_probe and not r.is_mirror]
            symptom_gone = all(
                (float(r.packets_bad) / float(max(1, r.packets_sent))) <= 5.0 * failure.unit_bad_prob(False)
                for r in app_recs
            )
            if symptom_gone:
                curr_eq = next_eq
                mitigated_stop = True
                break

        next_h = _entropy_bits(next_post)
        made_info_progress = (curr_h - next_h) >= 0.002
        curr_h = next_h
        if is_bayesian and next_eq == curr_eq and (not made_info_progress):
            unchanged_rounds += 1
            if unchanged_rounds >= max(stall_patience, 6):
                break
        else:
            unchanged_rounds = 0
            curr_eq = next_eq

    final_eq = tuple(sorted(curr_eq))
    hit = 1.0 if (failure.faulty_node in curr_eq) else 0.0
    precision = hit / float(len(curr_eq)) if len(curr_eq) > 0 else 0.0
    recall = hit

    return EpisodeResult(
        planner_name=planner.name,
        system_name=system.name,
        faulty_node=failure.faulty_node,
        initial_eq_size=len(eq0),
        final_eq_set=final_eq,
        num_perturbations=len(traj) - 1,
        total_ttl_sec=total_ttl,
        total_disruption=total_disrupt,
        peak_step_disruption=peak_disrupt,
        total_compute_ms=total_comp_ms,
        precision=precision,
        recall=recall,
        stopped_early_mitigated=mitigated_stop,
        trajectory=tuple(traj),
    )
