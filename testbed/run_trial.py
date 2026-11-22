"""Run one FIVES localization trial on the Arista testbed and log it to JSON.

The fives planner and Bayesian inference drive the trial; each step applies a perturbation (link drain,
mirror session, or host probe), measures one telemetry window on the hardware, and reverts it.

  python3 run_trial.py topologies/fattree_k8_pruned.json --scenario silent_drop --culprit agg_a2 --inject \
      --window-s 20 --flows 100 --latency-threshold-ms 1.0 --out results/trial_agg_a2.json [--dry-run]

--culprit is the ground truth used to score the result (and the VRF faulted when --inject is given).
With --dry-run nothing touches hardware: commands are printed and telemetry comes from the fives
simulator with the same fault, so the full loop can be tested offline.

Telemetry per window and directed host pair:
  blackhole, high_latency  `--flows` TCP SYNs with incrementing source ports (one ECMP path each);
                           a unit is bad if unanswered (blackhole) or RTT > --latency-threshold-ms
  silent_drop              iperf3 all-to-all; units = sent segments, bad = TCP retransmissions
Probes use a pinned source port plus a TCP traceroute that reveals their path. Mirrors count TCP
lost-segment events (sequence gaps = loss upstream of the mirror point) in the CPU capture.
"""
import argparse
import json
import os
import re
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from fives import (  # noqa: E402
    ActiveProbe, CheapestFirstOperatorPlanner, FailureMode, FailureSpec, FivesPlanner, FullLinkDrain,
    MultiOutcomeEfficacyEstimator, MultiRoundBayesianPGM, NetworkSystem, PacketMirror, Planner,
    SafetyConfig, SafetyFilter, SetIntersectionInference, TelemetryRecord, TelemetryWindow,
    TwoPhaseImpactEstimator, load_edgelist_network, run_episode,
)
from fivestb import commands as C  # noqa: E402
from fivestb.executor import Executor  # noqa: E402
from fivestb.topology import TestbedTopology  # noqa: E402

MSS_BYTES = 1448
# Offline (dry-run) fault parameters: same as the simulator replay.
DRY_RUN_SPECS = {
    "blackhole": dict(mode=FailureMode.BLACKHOLE, drop_prob=1.0, bg_noise_prob=1.0e-6),
    "silent_drop": dict(mode=FailureMode.SILENT_DROP, drop_prob=0.03, bg_noise_prob=1.0e-4),
    "high_latency": dict(mode=FailureMode.HIGH_LATENCY, drop_prob=0.25, latency_inflation_us=50.0,
                         latency_jitter_us=10.0, latency_threshold_us=37.19),
}


def parse_hping(out: str, latency_threshold_ms: float, mode: str):
    sent = int(re.search(r"(\d+) packets transmitted", out).group(1))
    rtts = [float(x) for x in re.findall(r"rtt=([\d.]+) ms", out)]
    bad = sent - len(rtts) if mode == "blackhole" else sum(r > latency_threshold_ms for r in rtts) + sent - len(rtts)
    return sent, bad


def parse_traceroute(out: str, owner, ids, src_vrf: str):
    path = [ids[src_vrf]]
    for line in out.splitlines()[1:]:
        m = re.match(r"\s*\d+\s+([\d.]+)", line)
        if m is None or m.group(1) not in owner:
            break
        node = ids[owner[m.group(1)]]
        if node != path[-1]:
            path.append(node)
    return tuple(path)


class TestbedSystem(NetworkSystem):
    """NetworkSystem whose telemetry windows are measured on the testbed instead of simulated."""

    def __init__(self, base: NetworkSystem, topo: TestbedTopology, ex: Executor, args):
        super().__init__(base.name, base.G, base.switch_nodes, base.rack_nodes, base.node_names,
                         base.edge_capacities, base.edge_loads, base.safety, base.dlb_routing)
        self.topo, self.ex, self.args = topo, ex, args
        self.ids = topo.node_ids()
        self.vrf_of = {i: v for v, i in self.ids.items()}
        self.hosts_on = {}
        for h in topo.hosts:
            tid = self.ids[h.vrf]
            if tid not in self.hosts_on:
                self.hosts_on[tid] = []
            self.hosts_on[tid].append(h)
        self.window_idx = 0

    def simulate_window(self, failure, perturbation, rng, flows_per_pair=400, packets_per_flow=25):
        a, ex, w = self.args, self.ex, self.window_idx
        self.window_idx += 1
        outdir = os.path.join(a.workdir, f"window{w:02d}")
        ex.local(f"mkdir -p {outdir}")
        self._apply(perturbation, revert=False)
        if a.scenario == "silent_drop":
            ex.local("\n".join(C.iperf_clients(self.topo, a.window_s, a.flows, outdir)))
        else:
            for s in self.topo.hosts:
                for d in self.topo.hosts:
                    if d.vrf != s.vrf:
                        ex.local(f"sudo ip netns exec {s.name} hping3 -S -p {C.IPERF_BASE_PORT} -c {a.flows} "
                                 f"-i u2000 {d.ip} > {outdir}/syn_{s.name}_{d.name}.txt 2>&1 || true")
        probe_out = None
        if isinstance(perturbation, ActiveProbe):
            src, dst = self.hosts_on[perturbation.src_node][0], self.hosts_on[perturbation.dst_node][0]
            hp, tr = C.probe(src.name, dst.ip, 40000 + w, perturbation.num_probes)
            probe_out = (ex.local(hp + " || true"), ex.local(tr), src.vrf)
        pcap = None
        if isinstance(perturbation, PacketMirror):
            sw = self.topo.vrfs[self.vrf_of[perturbation.node]]
            ex.eos_exec(sw, C.mirror_capture(a.window_s, "/mnt/flash/fives_mirror.pcap"))
            pcap = os.path.join(outdir, "mirror.pcap")
            ex.local(f"scp {sw}:/mnt/flash/fives_mirror.pcap {pcap}")
        self._apply(perturbation, revert=True)
        if ex.dry_run:
            return super().simulate_window(failure, perturbation, rng, flows_per_pair, packets_per_flow)
        return self._measure(perturbation, outdir, probe_out, pcap)

    def _apply(self, p, revert: bool) -> None:
        if isinstance(p, FullLinkDrain):
            a, b = self.vrf_of[p.u], self.vrf_of[p.v]
            fn = C.link_undrain if revert else C.link_drain
            for sw, lines in fn(self.topo, a, b).items():
                self.ex.eos_config(sw, "drain", lines)
        elif isinstance(p, PacketMirror):
            vrf = self.vrf_of[p.node]
            sw, lines = (C.mirror_remove if revert else C.mirror_add)(self.topo, vrf)
            self.ex.eos_config(sw, "mirror", lines)
        else:
            assert p is None or isinstance(p, ActiveProbe), f"perturbation {p} not available on the testbed"

    def _measure(self, p, outdir, probe_out, pcap) -> TelemetryWindow:
        a = self.args
        by_pair = {}
        for s in self.topo.hosts:
            for d in self.topo.hosts:
                if d.vrf == s.vrf:
                    continue
                pair = (self.ids[s.vrf], self.ids[d.vrf])
                if a.scenario == "silent_drop":
                    streams = json.load(open(f"{outdir}/iperf_{s.name}_{d.name}.json"))["end"]["streams"]
                    sent = sum(st["sender"]["bytes"] for st in streams) // MSS_BYTES
                    bad = sum(st["sender"]["retransmits"] for st in streams)
                else:
                    sent, bad = parse_hping(open(f"{outdir}/syn_{s.name}_{d.name}.txt").read(),
                                            a.latency_threshold_ms, a.scenario)
                if pair not in by_pair:
                    by_pair[pair] = [0, 0]
                by_pair[pair][0] += int(sent)
                by_pair[pair][1] += int(bad)
        recs = [
            TelemetryRecord(pair=pair, is_probe=False, is_mirror=False, mirror_node=-1,
                            packets_sent=counts[0], packets_bad=counts[1],
                            path_weights=self.paths_under_perturbation(pair, p), traced_path=())
            for pair, counts in by_pair.items()
        ]
        if probe_out is not None:
            hp_out, tr_out, src_vrf = probe_out
            sent, bad = parse_hping(hp_out, a.latency_threshold_ms, "blackhole" if a.scenario != "high_latency"
                                    else "high_latency")
            subs = self.shortest_paths(p.src_node, p.dst_node)
            traced = parse_traceroute(tr_out, self.topo.ip_owner(), self.ids, src_vrf)
            assert traced in subs, f"traceroute path {traced} is not an ECMP path {subs}"
            recs.append(TelemetryRecord(pair=p.flow_pair, is_probe=True, is_mirror=False, mirror_node=-1,
                                        packets_sent=sent, packets_bad=bad,
                                        path_weights=tuple((sp, 1.0 / len(subs)) for sp in subs), traced_path=traced))
        if pcap is not None:
            srcs = " || ".join(f"ip.src=={h.ip}" for h in self.hosts_on[p.flow_pair[0]])
            dsts = " || ".join(f"ip.dst=={h.ip}" for h in self.hosts_on[p.flow_pair[1]])
            flt = f"({srcs}) && ({dsts})"
            n_pkts = int(self.ex.local(f"tshark -r {pcap} -Y '{flt}' | wc -l"))
            n_lost = int(self.ex.local(f"tshark -r {pcap} -Y '{flt} && tcp.analysis.lost_segment' | wc -l"))
            through = [pth for pth in self.shortest_paths(*p.flow_pair) if p.node in pth]
            ups = [pth[: pth.index(p.node) + 1] for pth in through]
            recs.append(TelemetryRecord(pair=p.flow_pair, is_probe=False, is_mirror=True, mirror_node=p.node,
                                        packets_sent=n_pkts, packets_bad=n_lost,
                                        path_weights=tuple((u, 1.0 / len(ups)) for u in ups), traced_path=()))
        return TelemetryWindow(perturbation=p, records=tuple(recs), fault_was_active=True)


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


def build_scheme(scheme: str, net, safety, impact, efficacy, bg_noise_prob: float, op_seed: int,
                 tradeoff_lambda: float = 0.5):
    if scheme == "FIVES":
        return (PairSplitPlanner(net, safety, impact, efficacy, tradeoff_lambda=tradeoff_lambda),
                MultiRoundBayesianPGM(net, path_aware=True, bg_noise_prob=bg_noise_prob))
    if scheme == "Operator-PA":
        return (CheapestFirstOperatorPlanner(net, safety, impact, efficacy, np.random.default_rng(op_seed)),
                SetIntersectionInference(net, path_aware=True, bg_noise_prob=bg_noise_prob))
    if scheme == "Drain-Sweep":
        return (DrainSweepPlanner(net, safety, efficacy),
                SetIntersectionInference(net, path_aware=True, bg_noise_prob=bg_noise_prob))
    raise ValueError(f"unknown scheme {scheme}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("topology")
    ap.add_argument("--scenario", required=True, choices=sorted(DRY_RUN_SPECS))
    ap.add_argument("--culprit", required=True, help="faulty VRF (ground truth)")
    ap.add_argument("--scheme", default="FIVES", choices=["FIVES", "Operator-PA", "Drain-Sweep"])
    ap.add_argument("--inject", action="store_true", help="inject the fault before and revert it after the trial")
    ap.add_argument("--window-s", type=int, required=True)
    ap.add_argument("--flows", type=int, required=True)
    ap.add_argument("--latency-threshold-ms", type=float, required=True)
    ap.add_argument("--police-mbps", type=int, default=2000, help="silent_drop injection: ingress policer rate")
    ap.add_argument("--shape-kbps", type=int, default=1000000, help="high_latency injection: egress shaping rate")
    ap.add_argument("--workdir", default="results/work")
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    topo = TestbedTopology.load(args.topology)
    assert args.culprit in topo.vrfs, f"unknown VRF {args.culprit}"
    ex = Executor(args.dry_run)
    ids = topo.node_ids()
    edgelist = os.path.join(args.workdir, f"{topo.name}.edgelist")
    os.makedirs(args.workdir, exist_ok=True)
    topo.write_fives_edgelist(edgelist)
    host_tors = frozenset(ids[h.vrf] for h in topo.hosts)
    all_sw = frozenset(ids.values())
    base = load_edgelist_network(edgelist, name=topo.name, safety=SafetyConfig(
        probe_banned_nodes=all_sw - host_tors, enable_subtle_weight_shifts=False, enable_group_splits=False,
        enable_flow_link_drains=False, enable_packet_mirror=True, mirror_filtered_nodes=all_sw,
        enable_component_reset=False))
    net = TestbedSystem(base, topo, ex, args)
    pairs = tuple((a, b) for a in sorted(host_tors) for b in sorted(host_tors) if a != b)
    spec = FailureSpec(faulty_node=ids[args.culprit], affected_pairs=pairs, **DRY_RUN_SPECS[args.scenario])
    s, imp, eff = SafetyFilter(net), TwoPhaseImpactEstimator(net), MultiOutcomeEfficacyEstimator(net)
    pl, inf = build_scheme(args.scheme, net, s, imp, eff, spec.unit_bad_prob(False), op_seed=1000 + args.seed)

    if args.scenario == "silent_drop":
        for c in C.iperf_servers(topo):
            ex.local(c)
    if args.inject:
        sw, lines = C.fault_inject(topo, args.culprit, args.scenario, args.police_mbps, args.shape_kbps)
        ex.eos_config(sw, "fault_inject", lines)
    res = run_episode(net, spec, pl, inf, imp, np.random.default_rng(args.seed), flows_per_pair=args.flows)
    if args.inject:
        sw, lines = C.fault_revert(topo, args.culprit, args.scenario)
        ex.eos_config(sw, "fault_revert", lines)
    if args.scenario == "silent_drop":
        ex.local("sudo pkill -x iperf3")

    vrf = {i: v for v, i in ids.items()}
    log = dict(topology=topo.name, scenario=args.scenario, culprit=args.culprit, dry_run=args.dry_run,
               final_suspects=[vrf[n] for n in res.final_eq_set], precision=res.precision, recall=res.recall,
               steps=res.num_perturbations, est_time_s=res.total_ttl_sec,
               trajectory=[dict(step=st.step_idx, perturbation=None if st.perturbation is None
                                else st.perturbation.short_name(), suspects=[vrf[n] for n in st.eq_set])
                           for st in res.trajectory])
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    json.dump(log, open(args.out, "w"), indent=1)
    print(json.dumps({k: log[k] for k in ("culprit", "final_suspects", "steps", "precision", "recall")}))


if __name__ == "__main__":
    main()
