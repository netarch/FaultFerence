"""Generate alice/bob EOS configs and the cabling port map for a testbed topology spec.

Usage: python3 genconfig.py topologies/fattree_k8_pruned.json [--outdir configs/fattree_k8_pruned]
Writes <outdir>/alice.config, <outdir>/bob.config and <outdir>/wiring.txt.
"""
import argparse
import os

from fivestb.commands import base_config
from fivestb.topology import TestbedTopology


def wiring(topo: TestbedTopology) -> str:
    lines = [f"# {topo.name}: {len(topo.vrfs)} VRFs, {len(topo.links)} VRF links", "", "# hosts"]
    lines += [f"{h.switch} Ethernet{h.port:<3} <-> {h.name} ({h.nic}, {h.ip}) [vrf {h.vrf}]" for h in topo.hosts]
    lines += ["", "# VRF links (cable between the two ports)"]
    lines += [f"{l.switch_a} Ethernet{l.port_a:<3} [{l.vrf_a} {l.ip_a}] <-> {l.switch_b} Ethernet{l.port_b:<3} "
              f"[{l.vrf_b} {l.ip_b}]" for l in topo.links]
    used = {sw: sum(h.switch == sw for h in topo.hosts) + sum((l.switch_a == sw) + (l.switch_b == sw) for l in topo.links)
            for sw in topo.physical_switches}
    lines += ["", f"# ports used: {used}"]
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("topology", help="topology spec JSON")
    ap.add_argument("--outdir", help="default: configs/<topology name>")
    args = ap.parse_args()
    topo = TestbedTopology.load(args.topology)
    outdir = args.outdir if args.outdir is not None else os.path.join("configs", topo.name)
    os.makedirs(outdir, exist_ok=True)
    for sw in topo.physical_switches:
        with open(os.path.join(outdir, f"{sw}.config"), "w") as f:
            f.write("\n".join(base_config(topo, sw)) + "\n")
    with open(os.path.join(outdir, "wiring.txt"), "w") as f:
        f.write(wiring(topo))
    print(f"wrote {outdir}/{{{','.join(topo.physical_switches)}}}.config and wiring.txt")


if __name__ == "__main__":
    main()
