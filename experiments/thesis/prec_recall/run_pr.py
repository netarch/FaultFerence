"""Absolute precision / recall sweep: FIVES vs Operator per failure scenario and topology.

One process = one (topology, scenario, shard). Each shard runs trials [shard*TPS, (shard+1)*TPS) and
writes shard_<topo>_<scenario>_<shard>.json after every trial.

Schemes (same construction as run_opt.py / run_meta.py):
  FIVES        PairSplitPlanner (separated pair mass per unit cost), lambda=0.5, MultiRoundBayesianPGM
  Operator     CheapestFirstOperatorPlanner, SetIntersectionInference(path_aware=False) (legacy)
  Operator-PA  CheapestFirstOperatorPlanner, SetIntersectionInference(path_aware=True): probe verdicts
               apply only to the traced probe path; probe/mirror badness by binomial test (alpha=1e-3)
Both inference engines are given the scenario's true background bad-unit rate
(spec.unit_bad_prob(False)).

Metrics (fives.runner.run_episode definitions, final suspect set S, true faulty switch f):
  recall    = 1 if f in S else 0
  precision = recall / |S|
  localized = 1 if S == {f} else 0
  steps     = number of perturbations applied

Usage: run_pr.py <topo_label> <scenario> <shard> <trials_per_shard> <out_json> <schemes, e.g. FIVES,Operator>
"""
import json
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.expanduser("~/faultference"))
from fives import (  # noqa: E402
    CheapestFirstOperatorPlanner, FailureMode, FailureSpec, FivesPlanner, MultiOutcomeEfficacyEstimator,
    MultiRoundBayesianPGM, SafetyConfig, SafetyFilter, SetIntersectionInference, TwoPhaseImpactEstimator,
    load_edgelist_network, run_episode,
)
from fives.experiments import TOPO_DIR, sample_valid_fault  # noqa: E402

LAMBDA = 0.5

TOPOLOGIES = {
    "Clos-K10": "ft_deg10_sw125_svr250_os3_bidir_false.edgelist",
    "Clos-K14": "ft_deg14_sw245_svr686_os3_bidir_false.edgelist",
    "Clos-K20": "ft_deg20_sw500_svr2000_os3_bidir_false.edgelist",
    "RRG-K10": "rg_deg10_sw125_svr250_os3.edgelist",
    "RRG-K14": "rg_deg14_sw245_svr686_os3.edgelist",
    "RRG-K20": "rg_deg20_sw500_svr2000_os3.edgelist",
    "B4": "B4.edgelist",
    "UsCarrier": "UsC.edgelist",
    "ASN2k": "ASN2k.edgelist",
    "Kdl": "Kdl.edgelist",
}

# Scenario parameters. blackhole = run_opt.py; silent_drop = run_meta.py / experiments.py.
SCENARIOS = {
    "blackhole": dict(mode=FailureMode.BLACKHOLE, drop_prob=1.0, bg_noise_prob=1.0e-6),
    "silent_drop": dict(mode=FailureMode.SILENT_DROP, drop_prob=0.03, bg_noise_prob=1.0e-4),
    # 25% of flows through the faulty switch get +50us; jitter N(0, 10us); SLO threshold 37.19us over
    # path baseline => background false-alarm rate 1.0e-4/flow, P(bad | through fault) = 0.225.
    "high_latency": dict(mode=FailureMode.HIGH_LATENCY, drop_prob=0.25, latency_inflation_us=50.0,
                         latency_jitter_us=10.0, latency_threshold_us=37.19),
}
SCENARIO_SEED = {"blackhole": 1, "silent_drop": 2, "high_latency": 3}


class PairSplitPlanner(FivesPlanner):
    """FIVES with the thesis's pair-split score (separated pair mass per unit cost)."""

    def _greedy_score(self, p, posteriors, active_pairs, expected_drop_prob):
        _, pairs_w = self.efficacy.mutual_information_and_pairs(
            p, posteriors, active_pairs, expected_drop_prob=expected_drop_prob, p_node_map=self._p_node_map)
        if pairs_w <= 1.0e-9:
            return 0.0
        return pairs_w / self.impact.estimate(p, expected_drop_prob=expected_drop_prob).scalar_cost(self.tradeoff_lambda)


def main():
    topo, scenario, shard, tps, out = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), sys.argv[5]
    schemes = sys.argv[6].split(",")
    assert len(schemes) > 0 and set(schemes) <= {"FIVES", "Operator", "Operator-PA"}, schemes
    net = load_edgelist_network(
        os.path.join(TOPO_DIR, TOPOLOGIES[topo]), name=topo,
        safety=SafetyConfig(enable_subtle_weight_shifts=False, enable_group_splits=False),
    )
    s, imp, eff = SafetyFilter(net), TwoPhaseImpactEstimator(net), MultiOutcomeEfficacyEstimator(net)
    topo_seed = sum(ord(c) * (i + 1) for i, c in enumerate(topo))
    rows = []
    for t in range(shard * tps, (shard + 1) * tps):
        rng_fault = np.random.default_rng([topo_seed, SCENARIO_SEED[scenario], t])
        pairs, culprit = sample_valid_fault(net, rng_fault, 1)
        spec = FailureSpec(faulty_node=culprit, affected_pairs=pairs, **SCENARIOS[scenario])
        bg = spec.unit_bad_prob(False)
        rec = {"trial": t, "culprit": int(culprit), "pair": [int(x) for x in pairs[0]],
               "n_paths": len(net.shortest_paths(*pairs[0]))}
        builders = {
            "FIVES": lambda: (PairSplitPlanner(net, s, imp, eff, tradeoff_lambda=LAMBDA),
                              MultiRoundBayesianPGM(net, path_aware=False, bg_noise_prob=bg)),
            "Operator": lambda: (CheapestFirstOperatorPlanner(net, s, imp, eff, np.random.default_rng(1000 + t)),
                                 SetIntersectionInference(net, path_aware=False, bg_noise_prob=bg)),
            "Operator-PA": lambda: (CheapestFirstOperatorPlanner(net, s, imp, eff, np.random.default_rng(1000 + t)),
                                    SetIntersectionInference(net, path_aware=True, bg_noise_prob=bg)),
        }
        for name in schemes:
            pl, inf = builders[name]()
            t0 = time.perf_counter()
            res = run_episode(net, spec, pl, inf, imp, np.random.default_rng(900 + t))
            rec[name] = dict(
                steps=res.num_perturbations, eq0=res.initial_eq_size, final=len(res.final_eq_set),
                precision=res.precision, recall=res.recall,
                localized=float(res.final_eq_set == (spec.faulty_node,)),
                cost=sum(st.impact.scalar_cost(LAMBDA) for st in res.trajectory[1:]),
                ttl_s=res.total_ttl_sec, disruption=res.total_disruption, wall_s=time.perf_counter() - t0,
            )
        rows.append(rec)
        print(topo, scenario, t, {k: (v["steps"], v["eq0"], v["final"], v["recall"]) for k, v in rec.items()
                                  if isinstance(v, dict)}, flush=True)
        json.dump(rows, open(out, "w"), indent=1)


if __name__ == "__main__":
    main()
