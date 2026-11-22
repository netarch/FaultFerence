"""Arista testbed replay in the fives simulator: FIVES vs path-aware Operator vs drain sweep.

Topology: pruned k=8 fat tree carved as 26 VRFs on two Arista 7280s
(testbed/topologies/fattree_k8_pruned.json): 2 ToRs (tor_a on alice, tor_b on bob), 8 aggs
(agg_a0..3, agg_b0..3), 16 cores (core_0..7 on alice, core_8..15 on bob), 40 /30 links, 16
equal-cost 5-hop paths between tor_a and tor_b.

Traffic: cross-pod iperf3 flows between the 2 alice hosts (tor_a) and 2 bob hosts (tor_b) = 8
directed cross-ToR host pairs (4 a->b, 4 b->a), all monitored, with FLOWS_PER_PAIR = 400 (>= 25x
the 16 ECMP paths, i.e., 100 parallel streams on each of the 4 same-direction host pairs). One
faulty VRF per trial; each of the 26 virtual switches is the culprit in REPS_PER_SWITCH = 3 trials
per scenario (n = 78 trials per scenario).

Perturbation menu (what the testbed can do): full link drain (static-route withdrawal + shutdown),
active probes from host netns only (tor_a / tor_b; traceroute reveals the probe path), ACL-filtered
port mirroring on any VRF. No flow-scoped drains, weight shifts, group splits, or resets.

Schemes:
  FIVES        PairSplitPlanner (lambda=0.5) + MultiRoundBayesianPGM(path_aware=True)
  Operator-PA  CheapestFirstOperatorPlanner + SetIntersectionInference(path_aware=True)
  Drain-Sweep  drain suspect-adjacent links one at a time (lowest link id first) + the same inference

Traffic-loss model over the localization period (sum of TwoPhaseImpactEstimator step durations):
  fault loss      traffic share of each cross-pod host pair through the culprit (under the step's
                  routing) x FAULT_LOSS[scenario]; high latency drops nothing
  drain loss      each drain has 2 route transitions (drain, undrain); in each, the traffic share of
                  every cross-pod host pair on paths using the drained link is lost for
                  TRANSITION_LOSS_S seconds
  probes/mirrors  no loss to production traffic
  loss_frac = lost pair-seconds / offered pair-seconds (8 cross-pod host pairs x period);
  lost_gb = lost * PAIR_RATE_GBPS / 8.0, where PAIR_RATE_GBPS = 5.0 Gbps per directed cross-pod
  host pair (10 Gbps per host NIC split across 2 remote destinations; 8 pairs x 5 Gbps = 40 Gbps =
  4 hosts x 10 Gbps = 5.0 GB/s total offered).

Usage: run_testbed.py <scenario> <out_json>
"""
import json
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.expanduser("~/faultference"))
sys.path.insert(0, os.path.expanduser("~/faultference/testbed"))
from fives import (  # noqa: E402
    CheapestFirstOperatorPlanner, FailureMode, FailureSpec, FivesPlanner, FullLinkDrain,
    MultiOutcomeEfficacyEstimator, MultiRoundBayesianPGM, Planner, SafetyConfig, SafetyFilter,
    SetIntersectionInference, TwoPhaseImpactEstimator, load_edgelist_network, run_episode,
)
from fivestb.topology import TestbedTopology  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
TOPO_JSON = os.path.expanduser("~/faultference/testbed/topologies/fattree_k8_pruned.json")
LAMBDA = 0.5
REPS_PER_SWITCH = 3
FLOWS_PER_PAIR = 400        # >= 25 * 16 ECMP paths (100 iperf streams x 4 same-direction host pairs)
PACKETS_PER_FLOW = 25       # loss-telemetry samples per flow per window (silent drop)
TRANSITION_LOSS_S = 0.2     # traffic blackout on rerouted flows per route transition
PAIR_RATE_GBPS = 10.0 / 2.0  # 10G host NIC split over 2 remote cross-pod destinations = 5.0 Gbps
SCENARIOS = {
    "blackhole": dict(mode=FailureMode.BLACKHOLE, drop_prob=1.0, bg_noise_prob=1.0e-6),
    "silent_drop": dict(mode=FailureMode.SILENT_DROP, drop_prob=0.03, bg_noise_prob=1.0e-4),
    "high_latency": dict(mode=FailureMode.HIGH_LATENCY, drop_prob=0.25, latency_inflation_us=50.0,
                         latency_jitter_us=10.0, latency_threshold_us=37.19),
}
FAULT_LOSS = {"blackhole": 1.0, "silent_drop": 0.03, "high_latency": 0.0}


class PairSplitPlanner(FivesPlanner):
    """FIVES with the thesis's pair-split score (separated pair mass per unit cost)."""

    def _greedy_score(self, p, posteriors, active_pairs, expected_drop_prob):
        _, pairs_w = self.efficacy.mutual_information_and_pairs(
            p, posteriors, active_pairs, expected_drop_prob=expected_drop_prob, p_node_map=self._p_node_map)
        if pairs_w <= 1.0e-9:
            return 0.0
        return pairs_w / self.impact.estimate(p, expected_drop_prob=expected_drop_prob).scalar_cost(self.tradeoff_lambda)


class DrainSweepPlanner(Planner):
    """Drain links adjacent to current suspects one at a time, in fixed (u, v) order."""

    name = "DrainSweep"

    def __init__(self, system, safety_filter, efficacy):
        self.system, self.safety, self.efficacy = system, safety_filter, efficacy

    def select_next(self, posteriors, active_pairs, tried_keys, expected_drop_prob):
        suspects = sorted(c for c, pr in posteriors.items() if pr > 1.0e-6)
        if len(suspects) <= 1:
            return None
        for p in self.system.candidate_perturbations(active_pairs, set(suspects)):
            if (isinstance(p, FullLinkDrain) and p.key not in tried_keys and (p.u in suspects or p.v in suspects)
                    and self.safety.is_safe(p, active_pairs)
                    and len(self.efficacy.partition_suspects(p, suspects, active_pairs)) > 1):
                return p
        return None


def traffic_loss(net, host_pairs, culprit, scenario, trajectory):
    lost = offered = 0.0
    for st in trajectory[1:]:
        dur = st.impact.total_time_sec
        for pair in host_pairs:
            hit = sum(w for path, w in net.paths_under_perturbation(pair, st.perturbation) if culprit in path)
            lost += dur * hit * FAULT_LOSS[scenario]
            if isinstance(st.perturbation, FullLinkDrain):
                u, v = st.perturbation.u, st.perturbation.v
                moved = sum(w for path, w in net.paths_under_perturbation(pair, None)
                            if any({path[i], path[i + 1]} == {u, v} for i in range(len(path) - 1)))
                lost += 2 * TRANSITION_LOSS_S * moved
            offered += dur
    return lost, offered


def main():
    scenario, out = sys.argv[1], sys.argv[2]
    topo = TestbedTopology.load(TOPO_JSON)
    edgelist = os.path.join(HERE, f"fattree_k8_pruned_{scenario}.edgelist")
    topo.write_fives_edgelist(edgelist)
    ids = topo.node_ids()
    host_tors = frozenset(ids[h.vrf] for h in topo.hosts)
    all_sw = frozenset(ids.values())
    net = load_edgelist_network(edgelist, name="testbed-fattree-k8-pruned", safety=SafetyConfig(
        probe_banned_nodes=all_sw - host_tors, enable_subtle_weight_shifts=False, enable_group_splits=False,
        enable_flow_link_drains=False, enable_packet_mirror=True, mirror_filtered_nodes=all_sw,
        enable_component_reset=False))
    s, imp, eff = SafetyFilter(net), TwoPhaseImpactEstimator(net), MultiOutcomeEfficacyEstimator(net)
    tor_pairs = tuple((a, b) for a in sorted(host_tors) for b in sorted(host_tors) if a != b)
    host_pairs = tuple((ids[sh.vrf], ids[dh.vrf]) for sh in topo.hosts for dh in topo.hosts if sh.vrf != dh.vrf)
    assert len(host_pairs) == 8, f"expected 8 cross-pod host pairs, got {len(host_pairs)}"
    culprits = sorted({n for pr in tor_pairs for path in net.shortest_paths(*pr) for n in path})
    assert len(culprits) == 26, f"expected 26 switches on cross-pod paths, got {len(culprits)}"
    rows = []
    for t in range(len(culprits) * REPS_PER_SWITCH):
        culprit = culprits[t % len(culprits)]
        spec = FailureSpec(faulty_node=culprit, affected_pairs=tor_pairs, **SCENARIOS[scenario])
        bg = spec.unit_bad_prob(False)
        rec = {"trial": t, "culprit": culprit, "culprit_vrf": list(ids)[culprit]}
        for name, pl, inf in [
            ("FIVES", PairSplitPlanner(net, s, imp, eff, tradeoff_lambda=LAMBDA),
             MultiRoundBayesianPGM(net, path_aware=True, bg_noise_prob=bg)),
            ("Operator-PA", CheapestFirstOperatorPlanner(net, s, imp, eff, np.random.default_rng(1000 + t)),
             SetIntersectionInference(net, path_aware=True, bg_noise_prob=bg)),
            ("Drain-Sweep", DrainSweepPlanner(net, s, eff), SetIntersectionInference(net, path_aware=True, bg_noise_prob=bg)),
        ]:
            t0 = time.perf_counter()
            res = run_episode(net, spec, pl, inf, imp, np.random.default_rng(900 + t),
                              flows_per_pair=FLOWS_PER_PAIR, packets_per_flow=PACKETS_PER_FLOW)
            lost, offered = traffic_loss(net, host_pairs, culprit, scenario, res.trajectory)
            kinds = [st.perturbation.kind for st in res.trajectory[1:]]
            rec[name] = dict(
                steps=res.num_perturbations, eq0=res.initial_eq_size, final=len(res.final_eq_set),
                precision=res.precision, recall=res.recall, localized=float(res.final_eq_set == (culprit,)),
                time_s=res.total_ttl_sec, lost_pair_s=lost, offered_pair_s=offered,
                loss_frac=(lost / offered) if offered > 0 else 0.0,
                lost_gb=lost * PAIR_RATE_GBPS / 8.0,
                n_probe=kinds.count("active_probe"), n_mirror=kinds.count("packet_mirror"),
                n_drain=kinds.count("full_link_drain"), wall_s=time.perf_counter() - t0,
            )
        rows.append(rec)
        print(scenario, t, rec["culprit_vrf"], {k: (v["steps"], v["final"], v["recall"], round(v["time_s"]),
                                                    round(v["loss_frac"], 4))
                                                for k, v in rec.items() if isinstance(v, dict)}, flush=True)
    json.dump(rows, open(out, "w"), indent=1)


if __name__ == "__main__":
    main()
