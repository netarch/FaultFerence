"""Offline tests for the testbed tooling: every command in --dry-run mode, no hardware touched.

Run: python3 test_dry_run.py
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

import networkx as nx

HERE = os.path.dirname(os.path.abspath(__file__))
FT8 = os.path.join(HERE, "topologies", "fattree_k8_pruned.json")
FT4 = os.path.join(HERE, "topologies", "fattree_k4.json")
sys.path.insert(0, HERE)
from fivestb import commands as C  # noqa: E402
from fivestb.topology import TestbedTopology  # noqa: E402
from make_pruned_clos import make_pruned_clos  # noqa: E402


def run(*args):
    return subprocess.run([sys.executable, *args], cwd=HERE, check=True, capture_output=True, text=True).stdout


def test_make_pruned_clos_generator():
    with open(FT8) as f:
        expected = json.load(f)
    assert make_pruned_clos(k=8, ports_per_switch=48) == expected
    # k=10 needs 2 + 10 + 50 = 62 ports/switch > 48
    unittest.TestCase().assertRaises(AssertionError, make_pruned_clos, 10, 48)


def test_fattree_k8_pruned_fits_port_budget():
    topo = TestbedTopology.load(FT8)
    assert (len(topo.vrfs), len(topo.links)) == (26, 40)
    for sw, n in topo.physical_switches.items():
        used = sum(h.switch == sw for h in topo.hosts) + sum((l.switch_a == sw) + (l.switch_b == sw) for l in topo.links)
        assert used == 42 <= n
    g = topo.graph()
    paths = list(nx.all_shortest_paths(g, "tor_a", "tor_b"))
    assert len(paths) == 16
    assert all(len(p) == 5 for p in paths)
    assert {v for p in paths for v in p} == set(topo.vrfs)
    routes = topo.static_routes()
    assert len([r for r in routes["tor_a"] if r[0] == "192.168.200.0/24"]) == 4  # four aggs
    # Cross-ToR traffic: 2 alice hosts x 2 bob hosts x 2 directions = 8 iperf streams
    assert len(C.iperf_servers(topo)) == 8
    assert len(C.iperf_clients(topo, 5, 100, "/tmp/x")) - 1 == 8


def test_fattree_k4_fits_port_budget():
    topo = TestbedTopology.load(FT4)
    assert (len(topo.vrfs), len(topo.links)) == (20, 32)
    for sw, n in topo.physical_switches.items():
        used = sum(h.switch == sw for h in topo.hosts) + sum((l.switch_a == sw) + (l.switch_b == sw) for l in topo.links)
        assert used == 34 <= n
    routes = topo.static_routes()
    assert len([r for r in routes["tor0"] if r[0] == "192.168.200.0/24"]) == 2  # two aggs
    assert len(C.iperf_servers(topo)) == 12


def test_drain_withdraws_all_routes_over_link():
    topo = TestbedTopology.load(FT8)
    l = topo.link_between("agg_a2", "core_8")
    nh_core8 = l.endpoint("core_8")[2].split("/")[0]
    withdrawn = [(p, nh) for p, nh in topo.static_routes()["agg_a2"] if nh == nh_core8]
    assert len(withdrawn) > 0
    lines = C.link_drain(topo, "agg_a2", "core_8")[topo.vrfs["agg_a2"]]
    for p, nh in withdrawn:
        assert f"no ip route vrf agg_a2 {p} {nh}" in lines
    assert lines.index("shutdown") > max(lines.index(f"no ip route vrf agg_a2 {p} {nh}") for p, nh in withdrawn)


def test_tb_dry_run_subcommands():
    for args in (["hosts"], ["traffic", "--seconds", "5", "--flows", "100", "--outdir", "/tmp/x"],
                 ["fault", "inject", "--vrf", "agg_a2", "--mode", "blackhole"],
                 ["fault", "revert", "--vrf", "agg_a2", "--mode", "silent_drop"],
                 ["fault", "inject", "--vrf", "core_3", "--mode", "high_latency"],
                 ["drain", "down", "--link", "agg_a2", "core_8"], ["drain", "up", "--link", "agg_a2", "core_8"],
                 ["mirror", "add", "--vrf", "agg_a2"], ["mirror", "remove", "--vrf", "agg_a2"],
                 ["probe", "--src", "alice-host", "--dst", "bob-host", "--sport", "40001", "--count", "10"]):
        out = run("tb.py", FT8, "--dry-run", *args)
        assert len(out.strip()) > 0, args


def test_run_trial_dry_run_localizes():
    with tempfile.TemporaryDirectory() as d:
        for scenario, culprit in (("blackhole", "core_3"), ("silent_drop", "agg_a2"), ("high_latency", "tor_b")):
            out = os.path.join(d, f"{scenario}.json")
            run("run_trial.py", FT8, "--scenario", scenario, "--culprit", culprit, "--inject", "--window-s", "5",
                "--flows", "100", "--latency-threshold-ms", "1.0", "--workdir", os.path.join(d, "w"),
                "--out", out, "--dry-run")
            log = json.load(open(out))
            assert log["recall"] == 1.0, log


def test_legacy_ft_k4_still_generates():
    with tempfile.TemporaryDirectory() as d:
        run("genconfig.py", os.path.join(HERE, "topologies", "ft_k4.json"), "--outdir", d)
        assert "ip route vrf A7 192.168.100.0/24" in open(os.path.join(d, "alice.config")).read()


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print("PASS", name)
