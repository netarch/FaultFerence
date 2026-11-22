"""Factorized Menu x Inference x Sequencer ablation for FIVES (§6.5)."""

import json
import multiprocessing as mp
import os
from typing import Dict, List, Tuple
import numpy as np

from fives import (
    CheapestFirstOperatorPlanner,
    FailureMode,
    FailureSpec,
    FivesPlanner,
    FlowGroupSplit,
    MicroserviceSystem,
    MultiOutcomeEfficacyEstimator,
    MultiRoundBayesianPGM,
    NetPilotPlanner,
    SafetyConfig,
    SafetyFilter,
    SetIntersectionInference,
    SubtleWeightShift,
    TwoPhaseImpactEstimator,
    load_campus_prod_system,
    load_edgelist_network,
    run_episode,
)
from fives.experiments import REPO_ROOT, TOPO_DIR, sample_valid_fault, summarize_runs


class TradMenuFivesPlanner(FivesPlanner):
    """FIVES planner restricted to the exact traditional perturbation menu available to Operator."""

    def _safe_candidates(self, suspects, active_pairs, tried_keys):
        base = super()._safe_candidates(suspects, active_pairs, tried_keys)
        return [p for p in base if not isinstance(p, (SubtleWeightShift, FlowGroupSplit))]


def _eval_ablation_domain(args: Tuple[str, str, int]) -> Tuple[str, Dict]:
    fname, label, trials = args
    variants = [
        "Operator (Trad + Pass/Fail)",
        "Operator + Bayesian (Trad)",
        "NetPilot-Loc (Mitig + Pass/Fail)",
        "NetPilot-Loc + Bayesian",
        "FIVES (Trad Menu Only)",
        "FIVES (Full Menu)",
    ]
    buckets: Dict[str, List[Dict]] = {v: [] for v in variants}

    if label == "Microservices":
        ms = MicroserviceSystem()
        s_m, i_m, e_m = SafetyFilter(ms), TwoPhaseImpactEstimator(ms), MultiOutcomeEfficacyEstimator(ms)
        for comp in range(1, 10):
            for rep in range(4):
                spec = FailureSpec(
                    FailureMode.HIGH_LATENCY, comp, ((0, 10),), drop_prob=0.12,
                    latency_inflation_us=1000.0, latency_jitter_us=10.0, latency_threshold_us=37.19,
                )
                seed_m = 9500 + comp * 10 + rep
                runs_cfg = [
                    ("Operator (Trad + Pass/Fail)", CheapestFirstOperatorPlanner(ms, s_m, i_m, e_m, np.random.default_rng(seed_m + 1)), SetIntersectionInference(ms, path_aware=False)),
                    ("Operator + Bayesian (Trad)", CheapestFirstOperatorPlanner(ms, s_m, i_m, e_m, np.random.default_rng(seed_m + 1)), MultiRoundBayesianPGM(ms, path_aware=False, excluded_endpoints={0, 10})),
                    ("NetPilot-Loc (Mitig + Pass/Fail)", NetPilotPlanner(ms, s_m, i_m), SetIntersectionInference(ms, path_aware=False)),
                    ("NetPilot-Loc + Bayesian", NetPilotPlanner(ms, s_m, i_m), MultiRoundBayesianPGM(ms, path_aware=False, excluded_endpoints={0, 10})),
                    ("FIVES (Trad Menu Only)", TradMenuFivesPlanner(ms, s_m, i_m, e_m, tradeoff_lambda=0.7), MultiRoundBayesianPGM(ms, path_aware=False, excluded_endpoints={0, 10})),
                    ("FIVES (Full Menu)", FivesPlanner(ms, s_m, i_m, e_m, tradeoff_lambda=0.7), MultiRoundBayesianPGM(ms, path_aware=False, excluded_endpoints={0, 10})),
                ]
                for vname, pl, inf in runs_cfg:
                    rx = run_episode(ms, spec, pl, inf, i_m, np.random.default_rng(seed_m), candidate_pool=list(range(1, 10)))
                    buckets[vname].append({
                        "steps": rx.num_perturbations, "ttl": rx.total_ttl_sec,
                        "disruption": rx.total_disruption, "peak_disruption": rx.peak_step_disruption,
                        "precision": rx.precision, "recall": rx.recall, "compute_ms": rx.total_compute_ms,
                    })
        return label, {k: summarize_runs(v) for k, v in buckets.items()}

    net = (
        load_campus_prod_system(os.path.join(TOPO_DIR, fname))
        if label == "PROD"
        else load_edgelist_network(os.path.join(TOPO_DIR, fname), name=label)
    )
    s_n, i_n, e_n = SafetyFilter(net), TwoPhaseImpactEstimator(net), MultiOutcomeEfficacyEstimator(net)
    base_seed = 42424 + sum(ord(c) for c in label)

    for t in range(trials):
        rng_f = np.random.default_rng(base_seed + t * 71)
        pairs, culprit = sample_valid_fault(net, rng_f, 1)
        spec = FailureSpec(FailureMode.SILENT_DROP, culprit, pairs, drop_prob=0.03)
        seed_ep = 6200 + t
        runs_cfg = [
            ("Operator (Trad + Pass/Fail)", CheapestFirstOperatorPlanner(net, s_n, i_n, e_n, np.random.default_rng(seed_ep + 1)), SetIntersectionInference(net, path_aware=False)),
            ("Operator + Bayesian (Trad)", CheapestFirstOperatorPlanner(net, s_n, i_n, e_n, np.random.default_rng(seed_ep + 1)), MultiRoundBayesianPGM(net, path_aware=False)),
            ("NetPilot-Loc (Mitig + Pass/Fail)", NetPilotPlanner(net, s_n, i_n), SetIntersectionInference(net, path_aware=False)),
            ("NetPilot-Loc + Bayesian", NetPilotPlanner(net, s_n, i_n), MultiRoundBayesianPGM(net, path_aware=False)),
            ("FIVES (Trad Menu Only)", TradMenuFivesPlanner(net, s_n, i_n, e_n, tradeoff_lambda=0.5), MultiRoundBayesianPGM(net, path_aware=False)),
            ("FIVES (Full Menu)", FivesPlanner(net, s_n, i_n, e_n, tradeoff_lambda=0.5), MultiRoundBayesianPGM(net, path_aware=False)),
        ]
        for vname, pl, inf in runs_cfg:
            rx = run_episode(net, spec, pl, inf, i_n, np.random.default_rng(seed_ep))
            buckets[vname].append({
                "steps": rx.num_perturbations, "ttl": rx.total_ttl_sec,
                "disruption": rx.total_disruption, "peak_disruption": rx.peak_step_disruption,
                "precision": rx.precision, "recall": rx.recall, "compute_ms": rx.total_compute_ms,
            })

    return label, {k: summarize_runs(v) for k, v in buckets.items()}


def main():
    jobs = [
        ("ft_deg14_sw245_svr686_os3_bidir_false.edgelist", "Clos-k14", 30),
        ("UsC.edgelist", "USCarrier", 30),
        ("campus-str.edgelist", "PROD", 30),
        ("", "Microservices", 36),
    ]
    with mp.Pool(processes=4) as pool:
        res_pairs = pool.map(_eval_ablation_domain, jobs)

    out = {lbl: stats for lbl, stats in res_pairs}
    out_path = os.path.join(REPO_ROOT, "results", "component_ablation.json")
    with open(out_path, "w") as fp:
        json.dump(out, fp, indent=2)

    for lbl, stats in res_pairs:
        print(f"=== {lbl} ===")
        for vname, st in stats.items():
            print(
                f"  {vname:34s}: steps={st['mean_steps']:5.2f}, TTL={st['mean_ttl_sec']:6.1f}s, "
                f"disrupt={st['mean_disruption']:6.2f}, P/R={st['mean_precision']:.2f}/{st['mean_recall']:.2f}"
            )


if __name__ == "__main__":
    main()
