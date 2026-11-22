"""Thin wrapper around `testbed/run_sweep.py` for single-scenario replay invocation.

Usage: python3 run_testbed.py <scenario> <out_json>
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TESTBED_DIR = os.path.abspath(os.path.join(HERE, "..", "..", "..", "testbed"))
sys.path.insert(0, TESTBED_DIR)
from fivestb.topology import TestbedTopology  # noqa: E402
from run_sweep import run_scenario  # noqa: E402


def main():
    scenario, out = sys.argv[1], sys.argv[2]
    topo = TestbedTopology.load(os.path.join(TESTBED_DIR, "topologies", "fattree_k8_pruned.json"))
    run_scenario(
        topo=topo, mode="replay", dry_run=False, scenario=scenario, reps=3,
        flows_per_pair=400, window_s=10, latency_threshold_ms=1.0,
        police_mbps=2000, shape_kbps=1000000, outdir=HERE, out_json=out,
    )


if __name__ == "__main__":
    main()
