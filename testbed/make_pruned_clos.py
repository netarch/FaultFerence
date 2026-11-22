"""Programmatic generator for a two-ToR pruned k-ary FatTree (Clos) on alice and bob.

Retains only the virtual switches and routed /30 links on shortest paths between a source pod's ToR
(`tor_a` on alice) and a destination pod's ToR (`tor_b` on bob):
  - VRFs (2 + k + k^2/4): 2 ToRs, k aggs (k/2 per pod), k^2/4 cores (k/2 planes x k/2 cores/plane)
  - Inter-VRF links (k + k^2/2): k/2 tor_a--agg_a, k/2 tor_b--agg_b, k^2/4 agg_a--core, k^2/4 core--agg_b
  - Equal-cost 5-hop paths between tor_a and tor_b: k^2/4
  - Ports per switch (balanced split + 2 host ports/switch): 2 + k + k^2/2 (42/48 for k=8; 62 > 48 for k=10)

Usage:
  python3 make_pruned_clos.py [--k 8] [--ports-per-switch 48] [--out topologies/fattree_k8_pruned.json] [--genconfig]
"""
import argparse
import json
import os
from typing import Dict

from fivestb.commands import base_config
from fivestb.topology import TestbedTopology
from genconfig import wiring

HERE = os.path.dirname(os.path.abspath(__file__))


def make_pruned_clos(k: int = 8, ports_per_switch: int = 48) -> Dict:
    assert k >= 4 and k % 2 == 0, f"k must be an even integer >= 4, got {k}"
    n_planes = k // 2
    n_cores = n_planes * n_planes
    ports_needed_per_switch = 2 + k + (k * k) // 2
    assert ports_needed_per_switch <= ports_per_switch, (
        f"pruned k={k} Clos requires {ports_needed_per_switch} ports/switch, exceeding budget {ports_per_switch}"
    )

    vrfs: Dict[str, str] = {"tor_a": "alice", "tor_b": "bob"}
    for p in range(n_planes):
        vrfs[f"agg_a{p}"] = "alice"
    for p in range(n_planes):
        vrfs[f"agg_b{p}"] = "bob"
    for c in range(n_cores):
        vrfs[f"core_{c}"] = "alice" if c < n_cores // 2 else "bob"

    links = []
    for p in range(n_planes):
        links.append(["tor_a", f"agg_a{p}"])
    for p in range(n_planes):
        links.append(["tor_b", f"agg_b{p}"])
    for p in range(n_planes):
        for j in range(n_planes):
            links.append([f"agg_a{p}", f"core_{p * n_planes + j}"])
    for p in range(n_planes):
        for j in range(n_planes):
            links.append([f"core_{p * n_planes + j}", f"agg_b{p}"])

    spec = {
        "name": f"fattree_k{k}_pruned",
        "physical_switches": {
            "alice": {"ports": ports_per_switch},
            "bob": {"ports": ports_per_switch},
        },
        "port_pool": "all",
        "vrfs": vrfs,
        "links": links,
        "hosts": [
            {
                "name": "alice-host",
                "nic": "enp4s0f1",
                "switch": "alice",
                "port": 1,
                "prefix": "192.168.100.0/24",
                "ip": "192.168.100.2",
                "gateway": "192.168.100.1",
                "vrf": "tor_a",
            },
            {
                "name": "alice-host2",
                "nic": "enp76s0f1",
                "switch": "alice",
                "port": 14,
                "prefix": "192.168.150.0/24",
                "ip": "192.168.150.2",
                "gateway": "192.168.150.1",
                "vrf": "tor_a",
            },
            {
                "name": "bob-host",
                "nic": "enp76s0f0",
                "switch": "bob",
                "port": 1,
                "prefix": "192.168.200.0/24",
                "ip": "192.168.200.2",
                "gateway": "192.168.200.1",
                "vrf": "tor_b",
            },
            {
                "name": "bob-host2",
                "nic": "enp13s0f1",
                "switch": "bob",
                "port": 18,
                "prefix": "192.168.250.0/24",
                "ip": "192.168.250.2",
                "gateway": "192.168.250.1",
                "vrf": "tor_b",
            },
        ],
    }

    topo = TestbedTopology(spec)
    for sw, cap in topo.physical_switches.items():
        used = sum(h.switch == sw for h in topo.hosts) + sum((l.switch_a == sw) + (l.switch_b == sw) for l in topo.links)
        assert used <= cap, f"{sw} uses {used} ports > {cap}"
    return spec


def write_configs(topo: TestbedTopology, outdir: str) -> None:
    os.makedirs(outdir, exist_ok=True)
    for sw in topo.physical_switches:
        with open(os.path.join(outdir, f"{sw}.config"), "w") as f:
            f.write("\n".join(base_config(topo, sw)) + "\n")
    with open(os.path.join(outdir, "wiring.txt"), "w") as f:
        f.write(wiring(topo))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--k", type=int, default=8, help="even FatTree degree k (default: 8)")
    ap.add_argument("--ports-per-switch", type=int, default=48, help="ports per physical Arista switch (default: 48)")
    ap.add_argument("--out", help="output topology JSON (default: topologies/fattree_k<k>_pruned.json)")
    ap.add_argument("--genconfig", action="store_true", help="also generate EOS configs and wiring.txt")
    ap.add_argument("--config-outdir", help="config output directory (default: configs/fattree_k<k>_pruned)")
    args = ap.parse_args()

    spec = make_pruned_clos(k=args.k, ports_per_switch=args.ports_per_switch)
    out_json = args.out if args.out is not None else os.path.join(HERE, "topologies", f"{spec['name']}.json")
    os.makedirs(os.path.dirname(os.path.abspath(out_json)), exist_ok=True)
    with open(out_json, "w") as f:
        json.dump(spec, f, indent=1)
        f.write("\n")
    print(f"wrote {out_json}")

    if args.genconfig:
        topo = TestbedTopology(spec)
        cfg_dir = args.config_outdir if args.config_outdir is not None else os.path.join(HERE, "configs", topo.name)
        write_configs(topo, cfg_dir)
        print(f"wrote {cfg_dir}/{{{','.join(topo.physical_switches)}}}.config and wiring.txt")


if __name__ == "__main__":
    main()
