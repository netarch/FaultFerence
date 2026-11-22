"""Testbed operations: deploy configs, set up hosts, run traffic, inject faults, apply perturbations.

Every subcommand takes --dry-run, which prints the exact commands / config snippets without touching
switches or hosts.

  tb.py TOPO deploy  --configs configs/fattree_k4
  tb.py TOPO hosts
  tb.py TOPO traffic --seconds 30 --flows 64 --outdir results/run1
  tb.py TOPO fault   {inject,revert} --vrf agg3 --mode {blackhole,silent_drop,high_latency}
  tb.py TOPO drain   {down,up} --link agg3 core2
  tb.py TOPO mirror  {add,remove} --vrf agg3
  tb.py TOPO mirror  capture --vrf agg3 --seconds 10 --pcap results/run1/agg3.pcap
  tb.py TOPO probe   --src alice-host --dst bob-host --sport 40001 --count 200
"""
import argparse
import os

from fivestb import commands as C
from fivestb.executor import Executor
from fivestb.topology import TestbedTopology


def deploy(topo, ex, args):
    for sw in topo.physical_switches:
        cfg = os.path.join(args.configs, f"{sw}.config")
        assert os.path.exists(cfg), f"missing {cfg}; run genconfig.py first"
        ex.local(f"scp {cfg} {sw}:/mnt/flash/fives_base.config")
        ex.eos_exec(sw, f"configure replace checkpoint:{sw}-clean-slate")
        ex.eos_exec(sw, "copy flash:fives_base.config running-config")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("topology")
    ap.add_argument("--dry-run", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("deploy")
    p.add_argument("--configs", required=True)
    sub.add_parser("hosts")
    p = sub.add_parser("traffic")
    p.add_argument("--seconds", type=int, required=True)
    p.add_argument("--flows", type=int, required=True)
    p.add_argument("--outdir", required=True)
    p = sub.add_parser("fault")
    p.add_argument("action", choices=["inject", "revert"])
    p.add_argument("--vrf", required=True)
    p.add_argument("--mode", required=True, choices=["blackhole", "silent_drop", "high_latency"])
    p.add_argument("--police-mbps", type=int, default=2000, help="silent_drop: ingress policer rate")
    p.add_argument("--shape-kbps", type=int, default=1000000, help="high_latency: egress shaping rate")
    p = sub.add_parser("drain")
    p.add_argument("action", choices=["down", "up"])
    p.add_argument("--link", nargs=2, required=True, metavar=("VRF_A", "VRF_B"))
    p = sub.add_parser("mirror")
    p.add_argument("action", choices=["add", "remove", "capture"])
    p.add_argument("--vrf", required=True)
    p.add_argument("--seconds", type=int)
    p.add_argument("--pcap")
    p = sub.add_parser("probe")
    p.add_argument("--src", required=True)
    p.add_argument("--dst", required=True)
    p.add_argument("--sport", type=int, required=True)
    p.add_argument("--count", type=int, required=True)
    args = ap.parse_args()

    topo = TestbedTopology.load(args.topology)
    ex = Executor(args.dry_run)
    if args.cmd == "deploy":
        deploy(topo, ex, args)
    elif args.cmd == "hosts":
        for c in C.netns_setup(topo):
            ex.local(c)
    elif args.cmd == "traffic":
        ex.local(f"mkdir -p {args.outdir}")
        for c in C.iperf_servers(topo):
            ex.local(c)
        ex.local("\n".join(C.iperf_clients(topo, args.seconds, args.flows, args.outdir)))
    elif args.cmd == "fault":
        if args.action == "inject":
            sw, lines = C.fault_inject(topo, args.vrf, args.mode, args.police_mbps, args.shape_kbps)
        else:
            sw, lines = C.fault_revert(topo, args.vrf, args.mode)
        ex.eos_config(sw, f"fault_{args.action}", lines)
    elif args.cmd == "drain":
        fn = C.link_drain if args.action == "down" else C.link_undrain
        for sw, lines in fn(topo, *args.link).items():
            ex.eos_config(sw, f"drain_{args.action}", lines)
    elif args.cmd == "mirror":
        if args.action == "capture":
            assert args.seconds is not None and args.pcap is not None, "capture needs --seconds and --pcap"
            sw = topo.vrfs[args.vrf]
            ex.eos_exec(sw, C.mirror_capture(args.seconds, "/mnt/flash/fives_mirror.pcap"))
            ex.local(f"scp {sw}:/mnt/flash/fives_mirror.pcap {args.pcap}")
        else:
            sw, lines = (C.mirror_add if args.action == "add" else C.mirror_remove)(topo, args.vrf)
            ex.eos_config(sw, f"mirror_{args.action}", lines)
    elif args.cmd == "probe":
        for c in C.probe(args.src, topo.host(args.dst).ip, args.sport, args.count):
            print(ex.local(c))


if __name__ == "__main__":
    main()
