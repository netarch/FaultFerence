"""CLI benchmark runner for reproducing all FIVES simulation experiments & ablations."""

import argparse
import json
import os
from typing import Dict, List
import numpy as np

from fives import (
    CheapestFirstOperatorPlanner,
    ExactOptimalPlanner,
    FailureMode,
    FailureSpec,
    FivesPlanner,
    MicroserviceSystem,
    MultiOutcomeEfficacyEstimator,
    MultiRoundBayesianPGM,
    NetPilotPlanner,
    RandomSafePlanner,
    SafetyConfig,
    SafetyFilter,
    SetIntersectionInference,
    TwoPhaseImpactEstimator,
    load_campus_prod_system,
    load_edgelist_network,
    run_episode,
)

REPO_ROOT = "/usr/local/google/home/rahulbothra/faultference"
TOPO_DIR = os.path.join(REPO_ROOT, "faultference", "topologies")


def sample_valid_fault(net, rng: np.random.Generator, num_pairs: int = 1):
    racks = [r for r in net.rack_nodes if r not in net.safety.external_blackbox_nodes]
    for _ in range(500):
        s = int(racks[int(rng.integers(0, len(racks)))])
        d = int(racks[int(rng.integers(0, len(racks)))])
        if s == d:
            continue
        paths = net.shortest_paths(s, d)
        if len(paths) == 0 or len(paths[0]) < 3:
            continue
        interior = sorted({n for p in paths for n in p[1:-1]})
        if len(interior) < 2:
            continue
        culprit = int(interior[int(rng.integers(0, len(interior)))])
        pairs = [(s, d)]
        if num_pairs > 1:
            for _ in range(300):
                s2 = int(racks[int(rng.integers(0, len(racks)))])
                d2 = int(racks[int(rng.integers(0, len(racks)))])
                if s2 != d2 and (s2, d2) not in pairs:
                    if any(culprit in p for p in net.shortest_paths(s2, d2)):
                        pairs.append((s2, d2))
                        if len(pairs) == num_pairs:
                            break
            if len(pairs) < num_pairs:
                continue
        return tuple(pairs), culprit
    raise RuntimeError(f"Failed to sample valid fault in {net.name}")


def summarize_runs(records: List[Dict]) -> Dict[str, float]:
    return {
        "n": len(records),
        "mean_steps": float(np.mean([r["steps"] for r in records])),
        "mean_ttl_sec": float(np.mean([r["ttl"] for r in records])),
        "mean_disruption": float(np.mean([r["disruption"] for r in records])),
        "mean_peak_disruption": float(np.mean([r["peak_disruption"] for r in records])),
        "mean_precision": float(np.mean([r["precision"] for r in records])),
        "mean_recall": float(np.mean([r["recall"] for r in records])),
        "mean_compute_ms": float(np.mean([r["compute_ms"] for r in records])),
    }


def run_topology_benchmark(topo_file: str, name: str, trials: int = 30, drop_prob: float = 0.03) -> Dict:
    net = (
        load_campus_prod_system(os.path.join(TOPO_DIR, topo_file))
        if name == "PROD"
        else load_edgelist_network(os.path.join(TOPO_DIR, topo_file), name=name)
    )
    safety = SafetyFilter(net)
    impact = TwoPhaseImpactEstimator(net)
    eff = MultiOutcomeEfficacyEstimator(net)

    buckets: Dict[str, List[Dict]] = {
        "FIVES": [],
        "Operator": [],
        "NetPilot-Loc": [],
        "NetPilot-Mitig": [],
        "Random": [],
    }
    rng = np.random.default_rng(2026)
    for t in range(trials):
        pairs, culprit = sample_valid_fault(net, rng, num_pairs=1)
        spec = FailureSpec(FailureMode.SILENT_DROP, culprit, pairs, drop_prob=drop_prob)
        seed_ep = 1000 + t

        configs = [
            ("FIVES", FivesPlanner(net, safety, impact, eff, tradeoff_lambda=0.5), MultiRoundBayesianPGM(net, path_aware=False), False),
            ("Operator", CheapestFirstOperatorPlanner(net, safety, impact, eff, np.random.default_rng(seed_ep + 1)), SetIntersectionInference(net, path_aware=False), False),
            ("NetPilot-Loc", NetPilotPlanner(net, safety, impact), SetIntersectionInference(net, path_aware=False), False),
            ("NetPilot-Mitig", NetPilotPlanner(net, safety, impact), SetIntersectionInference(net, path_aware=False), True),
            ("Random", RandomSafePlanner(net, safety, np.random.default_rng(seed_ep + 2)), SetIntersectionInference(net, path_aware=False), False),
        ]
        for label, planner, inf, mitig_stop in configs:
            res = run_episode(
                net,
                spec,
                planner,
                inf,
                impact,
                np.random.default_rng(seed_ep),
                stop_on_symptom_mitigation=mitig_stop,
            )
            buckets[label].append(
                {
                    "steps": res.num_perturbations,
                    "ttl": res.total_ttl_sec,
                    "disruption": res.total_disruption,
                    "peak_disruption": res.peak_step_disruption,
                    "precision": res.precision,
                    "recall": res.recall,
                    "compute_ms": res.total_compute_ms,
                }
            )

    return {k: summarize_runs(v) for k, v in buckets.items()}


def main():
    parser = argparse.ArgumentParser(description="FIVES simulation benchmark runner")
    parser.add_argument("--suite", choices=["quick", "topologies", "prod"], default="quick")
    parser.add_argument("--trials", type=int, default=20)
    parser.add_argument("--out_json", type=str, default="")
    args = parser.parse_args()

    results = {}
    if args.suite in ("quick", "topologies"):
        for fname, label in [
            ("ft_deg10_sw125_svr250_os3_bidir_false.edgelist", "Clos-k10"),
            ("rg_deg10_sw125_svr250_os3.edgelist", "Expander-k10"),
            ("B4.edgelist", "B4"),
            ("UsC.edgelist", "USCarrier"),
        ]:
            results[label] = run_topology_benchmark(fname, label, trials=args.trials)
            print(f"\n=== {label} ===")
            for scheme, stats in results[label].items():
                print(
                    f"  {scheme:15s}: steps={stats['mean_steps']:.2f}, TTL={stats['mean_ttl_sec']:.1f}s, "
                    f"disrupt={stats['mean_disruption']:.2f}, P={stats['mean_precision']:.2f}, R={stats['mean_recall']:.2f}"
                )

    if args.suite in ("quick", "prod"):
        results["PROD"] = run_topology_benchmark("campus-str.edgelist", "PROD", trials=args.trials)
        print("\n=== PROD (1,715 switches, structured vendor/core/capacity constraints) ===")
        for scheme, stats in results["PROD"].items():
            print(
                f"  {scheme:15s}: steps={stats['mean_steps']:.2f}, TTL={stats['mean_ttl_sec']:.1f}s, "
                f"disrupt={stats['mean_disruption']:.2f}, P={stats['mean_precision']:.2f}, R={stats['mean_recall']:.2f}"
            )

    if args.out_json:
        with open(args.out_json, "w") as fp:
            json.dump(results, fp, indent=2)


if __name__ == "__main__":
    main()
