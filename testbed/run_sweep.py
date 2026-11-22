"""Unified Arista testbed sweep runner (`--mode replay` or `--mode hardware [--dry-run]`).

Runs FIVES, path-aware Operator (`Operator-PA`), and `Drain-Sweep` across `blackhole`, `silent_drop`,
and `high_latency` on a testbed topology (default `topologies/fattree_k8_pruned.json`), emitting the
same per-scenario JSON schema (`tb_<scenario>.json`) in both simulator replay and live/dry-run hardware
execution so `summarize_testbed.py` and `plot_testbed.py` work identically on either output.

Usage:
  python3 run_sweep.py --mode replay --outdir out
  python3 run_sweep.py --mode hardware [--dry-run] --reps 1 --outdir out_hw
"""
import argparse
from dataclasses import dataclass
import json
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from fives import (  # noqa: E402
    FailureSpec, FullLinkDrain, MultiOutcomeEfficacyEstimator, SafetyConfig, SafetyFilter,
    TwoPhaseImpactEstimator, load_edgelist_network, run_episode,
)
from fivestb import commands as C  # noqa: E402
from fivestb.executor import Executor  # noqa: E402
from fivestb.topology import TestbedTopology  # noqa: E402
from run_trial import DRY_RUN_SPECS, TestbedSystem, build_scheme  # noqa: E402
from tb import deploy  # noqa: E402

SCHEMES = ("FIVES", "Operator-PA", "Drain-Sweep")
SCENARIO_ORDER = ("blackhole", "silent_drop", "high_latency")
FAULT_LOSS = {"blackhole": 1.0, "silent_drop": 0.03, "high_latency": 0.0}
LAMBDA = 0.5
PACKETS_PER_FLOW = 25
TRANSITION_LOSS_S = 0.2
NIC_RATE_GBPS = 10.0


@dataclass
class _DeployArgs:
    configs: str


@dataclass
class _HardwareWindowArgs:
    workdir: str
    scenario: str
    window_s: int
    flows: int
    latency_threshold_ms: float


def traffic_loss(net, host_pairs, culprit: int, scenario: str, trajectory):
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


def episode_record(net, host_pairs, pair_rate_gbps: float, culprit: int, scenario: str, res, wall_s: float):
    lost, offered = traffic_loss(net, host_pairs, culprit, scenario, res.trajectory)
    kinds = [st.perturbation.kind for st in res.trajectory[1:]]
    return dict(
        steps=res.num_perturbations,
        eq0=res.initial_eq_size,
        final=len(res.final_eq_set),
        precision=res.precision,
        recall=res.recall,
        localized=float(res.final_eq_set == (culprit,)),
        time_s=res.total_ttl_sec,
        lost_pair_s=lost,
        offered_pair_s=offered,
        loss_frac=(lost / offered) if offered > 0 else 0.0,
        lost_gb=lost * pair_rate_gbps / 8.0,
        n_probe=kinds.count("active_probe"),
        n_mirror=kinds.count("packet_mirror"),
        n_drain=kinds.count("full_link_drain"),
        wall_s=wall_s,
    )


def run_scenario(topo: TestbedTopology, mode: str, dry_run: bool, scenario: str, reps: int,
                 flows_per_pair: int, window_s: int, latency_threshold_ms: float,
                 police_mbps: int, shape_kbps: int, outdir: str, out_json: str) -> None:
    os.makedirs(outdir, exist_ok=True)
    edgelist = os.path.join(outdir, f"{topo.name}_{scenario}.edgelist")
    topo.write_fives_edgelist(edgelist)

    ids = topo.node_ids()
    vrf_of = {i: v for v, i in ids.items()}
    host_tors = frozenset(ids[h.vrf] for h in topo.hosts)
    all_sw = frozenset(ids.values())
    base_net = load_edgelist_network(edgelist, name=f"testbed-{topo.name}", safety=SafetyConfig(
        probe_banned_nodes=all_sw - host_tors, enable_subtle_weight_shifts=False, enable_group_splits=False,
        enable_flow_link_drains=False, enable_packet_mirror=True, mirror_filtered_nodes=all_sw,
        enable_component_reset=False))

    tor_pairs = tuple((a, b) for a in sorted(host_tors) for b in sorted(host_tors) if a != b)
    host_pairs = tuple((ids[sh.vrf], ids[dh.vrf]) for sh in topo.hosts for dh in topo.hosts if sh.vrf != dh.vrf)
    assert len(host_pairs) > 0 and len(host_pairs) % len(tor_pairs) == 0
    n_remote = sum(1 for dh in topo.hosts if dh.vrf != topo.hosts[0].vrf)
    assert all(sum(1 for dh in topo.hosts if dh.vrf != sh.vrf) == n_remote for sh in topo.hosts)
    pair_rate_gbps = NIC_RATE_GBPS / float(n_remote)
    culprits = sorted({n for pr in tor_pairs for path in base_net.shortest_paths(*pr) for n in path})

    ex = None
    hw_args = None
    if mode == "hardware":
        ex = Executor(dry_run)
        host_pairs_per_tor = len(host_pairs) // len(tor_pairs)
        flows_per_host_pair = max(1, flows_per_pair // host_pairs_per_tor)
        hw_args = _HardwareWindowArgs(
            workdir=os.path.join(outdir, "hw_work"),
            scenario=scenario,
            window_s=window_s,
            flows=flows_per_host_pair,
            latency_threshold_ms=latency_threshold_ms,
        )
        net = TestbedSystem(base_net, topo, ex, hw_args)
        if scenario == "silent_drop":
            for cmd in C.iperf_servers(topo):
                ex.local(cmd)
    else:
        net = base_net

    s, imp, eff = SafetyFilter(net), TwoPhaseImpactEstimator(net), MultiOutcomeEfficacyEstimator(net)
    rows = []
    for t in range(len(culprits) * reps):
        culprit = culprits[t % len(culprits)]
        culprit_vrf = vrf_of[culprit]
        spec = FailureSpec(faulty_node=culprit, affected_pairs=tor_pairs, **DRY_RUN_SPECS[scenario])
        bg = spec.unit_bad_prob(False)
        rec = {"trial": t, "culprit": culprit, "culprit_vrf": culprit_vrf}

        if mode == "hardware":
            sw, lines = C.fault_inject(topo, culprit_vrf, scenario, police_mbps, shape_kbps)
            ex.eos_config(sw, "fault_inject", lines)

        for scheme in SCHEMES:
            if mode == "hardware":
                hw_args.workdir = os.path.join(outdir, "hw_work", f"{scenario}_t{t:03d}_{scheme}")
                net.window_idx = 0
            pl, inf = build_scheme(scheme, net, s, imp, eff, bg, op_seed=1000 + t, tradeoff_lambda=LAMBDA)
            t0 = time.perf_counter()
            res = run_episode(net, spec, pl, inf, imp, np.random.default_rng(900 + t),
                              flows_per_pair=flows_per_pair, packets_per_flow=PACKETS_PER_FLOW)
            rec[scheme] = episode_record(net, host_pairs, pair_rate_gbps, culprit, scenario, res,
                                         time.perf_counter() - t0)

        if mode == "hardware":
            sw, lines = C.fault_revert(topo, culprit_vrf, scenario)
            ex.eos_config(sw, "fault_revert", lines)

        rows.append(rec)
        summary_msg = {k: (v["steps"], v["final"], v["recall"], round(v["time_s"]), round(v["loss_frac"], 4))
                       for k, v in rec.items() if isinstance(v, dict)}
        print(f"[{mode}] {scenario} trial={t} culprit={culprit_vrf} {summary_msg}", file=sys.stderr, flush=True)

    if mode == "hardware" and scenario == "silent_drop":
        ex.local("sudo pkill -x iperf3")

    os.makedirs(os.path.dirname(os.path.abspath(out_json)), exist_ok=True)
    with open(out_json, "w") as f:
        json.dump(rows, f, indent=1)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--topology", default=os.path.join(HERE, "topologies", "fattree_k8_pruned.json"))
    ap.add_argument("--configs", help="EOS config dir for hardware deploy (default: configs/<topology name>)")
    ap.add_argument("--mode", choices=["replay", "hardware"], default="replay")
    ap.add_argument("--dry-run", action="store_true", help="hardware mode: print EOS/Linux commands without executing")
    ap.add_argument("--scenario", choices=["all", *SCENARIO_ORDER], default="all")
    ap.add_argument("--reps", type=int, default=3, help="trials per virtual switch per scenario (default: 3)")
    ap.add_argument("--flows", type=int, default=400, help="monitored TCP flows per directed ToR pair (default: 400)")
    ap.add_argument("--window-s", type=int, default=10, help="hardware observation window duration in seconds")
    ap.add_argument("--latency-threshold-ms", type=float, default=1.0, help="hardware SYN RTT threshold in ms")
    ap.add_argument("--police-mbps", type=int, default=2000, help="hardware silent_drop ingress policer rate")
    ap.add_argument("--shape-kbps", type=int, default=1000000, help="hardware high_latency egress shaping rate")
    ap.add_argument("--outdir", default=os.path.join(HERE, "out"))
    ap.add_argument("--out", help="explicit output JSON path when running a single --scenario")
    args = ap.parse_args()

    topo = TestbedTopology.load(args.topology)
    os.makedirs(args.outdir, exist_ok=True)

    if args.mode == "hardware":
        cfg_dir = args.configs if args.configs is not None else os.path.join(HERE, "configs", topo.name)
        ex_init = Executor(args.dry_run)
        deploy(topo, ex_init, _DeployArgs(configs=cfg_dir))
        for cmd in C.netns_setup(topo):
            ex_init.local(cmd)

    scenarios = SCENARIO_ORDER if args.scenario == "all" else (args.scenario,)
    assert args.out is None or len(scenarios) == 1, "--out can only be used with a single --scenario"
    for scen in scenarios:
        out_json = args.out if args.out is not None else os.path.join(args.outdir, f"tb_{scen}.json")
        run_scenario(
            topo=topo, mode=args.mode, dry_run=args.dry_run, scenario=scen, reps=args.reps,
            flows_per_pair=args.flows, window_s=args.window_s, latency_threshold_ms=args.latency_threshold_ms,
            police_mbps=args.police_mbps, shape_kbps=args.shape_kbps, outdir=args.outdir, out_json=out_json,
        )


if __name__ == "__main__":
    main()
