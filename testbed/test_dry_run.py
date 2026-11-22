"""Offline tests for the testbed tooling: every command in --dry-run mode, no hardware touched.

Run: python3 test_dry_run.py
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FT = os.path.join(HERE, "topologies", "fattree_k4.json")
sys.path.insert(0, HERE)
from fivestb import commands as C  # noqa: E402
from fivestb.topology import TestbedTopology  # noqa: E402


def run(*args):
    return subprocess.run([sys.executable, *args], cwd=HERE, check=True, capture_output=True, text=True).stdout


def test_fattree_fits_port_budget():
    topo = TestbedTopology.load(FT)
    assert (len(topo.vrfs), len(topo.links)) == (20, 32)
    for sw, n in topo.physical_switches.items():
        used = sum(h.switch == sw for h in topo.hosts) + sum((l.switch_a == sw) + (l.switch_b == sw) for l in topo.links)
        assert used == 34 <= n
    # tor0 reaches a remote pod via both of its aggs (ECMP)
    routes = topo.static_routes()
    assert len([r for r in routes["tor0"] if r[0] == "192.168.200.0/24"]) == 2  # two aggs


def test_drain_withdraws_all_routes_over_link():
    topo = TestbedTopology.load(FT)
    l = topo.link_between("agg3", "core2")
    nh_core2 = l.endpoint("core2")[2].split("/")[0]
    withdrawn = [(p, nh) for p, nh in topo.static_routes()["agg3"] if nh == nh_core2]
    assert len(withdrawn) > 0
    lines = C.link_drain(topo, "agg3", "core2")[topo.vrfs["agg3"]]
    for p, nh in withdrawn:
        assert f"no ip route vrf agg3 {p} {nh}" in lines
    assert lines.index("shutdown") > max(lines.index(f"no ip route vrf agg3 {p} {nh}") for p, nh in withdrawn)


def test_tb_dry_run_subcommands():
    for args in (["hosts"], ["traffic", "--seconds", "5", "--flows", "8", "--outdir", "/tmp/x"],
                 ["fault", "inject", "--vrf", "agg3", "--mode", "blackhole"],
                 ["fault", "revert", "--vrf", "agg3", "--mode", "silent_drop"],
                 ["fault", "inject", "--vrf", "core1", "--mode", "high_latency"],
                 ["drain", "down", "--link", "agg3", "core2"], ["drain", "up", "--link", "agg3", "core2"],
                 ["mirror", "add", "--vrf", "agg3"], ["mirror", "remove", "--vrf", "agg3"],
                 ["probe", "--src", "alice-host", "--dst", "bob-host", "--sport", "40001", "--count", "10"]):
        out = run("tb.py", FT, "--dry-run", *args)
        assert len(out.strip()) > 0, args


def test_run_trial_dry_run_localizes():
    with tempfile.TemporaryDirectory() as d:
        for scenario, culprit in (("blackhole", "core2"), ("silent_drop", "agg3"), ("high_latency", "tor4")):
            out = os.path.join(d, f"{scenario}.json")
            run("run_trial.py", FT, "--scenario", scenario, "--culprit", culprit, "--inject", "--window-s", "5",
                "--flows", "16", "--latency-threshold-ms", "1.0", "--workdir", os.path.join(d, "w"),
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
