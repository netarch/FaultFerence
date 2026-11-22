# FIVES Arista testbed

Tools to build a virtual Clos fabric on two Arista 7280 switches, inject faults, apply FIVES
perturbations, and run FIVES localization sweeps (either replayed in the simulator or live on the
hardware) with automatic summarization and plot generation.

| File | Purpose |
|---|---|
| `run_all.sh` | single turnkey script: generate pruned Clos + configs, run all 3 scenarios, summarize, and plot |
| `make_pruned_clos.py` | programmatic generator for `topologies/fattree_k{k}_pruned.json` (and optional EOS configs) |
| `topologies/fattree_k8_pruned.json` | default: two-ToR path subgraph of a k=8 fat tree (26 VRFs, 40 links, 16 ECMP paths), hosts on `tor_a` (alice) and `tor_b` (bob) |
| `topologies/fattree_k4.json` | alternative: full k=4 fat tree (20 VRFs, 32 links), hosts on tor0/tor2/tor4/tor6 (one per pod) |
| `topologies/ft_k4.json` | the original `ft_k4` edgelist (15 VRFs, 19 links), same output as the old genconfig.py |
| `genconfig.py` | topology JSON -> `configs/<name>/{alice,bob}.config` + `wiring.txt` (port map) |
| `tb.py` | deploy configs, set up host netns, run traffic, inject/revert faults, drain links, mirror, probe |
| `run_trial.py` | one localization trial on the hardware (`FIVES`, `Operator-PA`, or `Drain-Sweep`), logged to JSON |
| `run_sweep.py` | full 3-scenario x 3-scheme sweep (`--mode replay` or `--mode hardware [--dry-run]`) |
| `summarize_testbed.py` | compute means + 90% CIs (`tb_summary.json` and `tb_table.md`) |
| `plot_testbed.py` | generate vector PDF + PNG plots (`testbed-{steps,time,loss}.{pdf,png}`) |
| `fivestb/` | small library: topology/port/route model, EOS + Linux command builders, executor |
| `test_dry_run.py` | offline tests of every command in dry-run mode (`python3 test_dry_run.py`) |

## Quick start (one-line turnkey pipeline)

From the repository root (or `./run_all.sh` inside `testbed/`):

```bash
# Simulator replay (default: k=8 pruned Clos, 26 VRFs x 3 reps = 78 trials/scenario) + summary + plots
./testbed/run_all.sh

# Preview every SSH/EOS/netns command of the full hardware pipeline without touching switches
./testbed/run_all.sh --mode hardware --dry-run --reps 1 --outdir testbed/out_hw_dry

# Live hardware sweep on alice and bob
./testbed/run_all.sh --mode hardware --reps 3
```

Outputs are written to `testbed/out/` by default (gitignored; override with `--outdir <dir>`):
`tb_{blackhole,silent_drop,high_latency}.json`, `tb_summary.json`, `tb_table.md`, and
`testbed-{steps,time,loss}.{pdf,png}` (plus `hardware_commands.log` in `--mode hardware`).

## Hardware

* Two Arista 7280 switches, `alice` and `bob`, 48 ports each (10G/25G), reachable as `ssh alice` /
  `ssh bob` (login shell = EOS CLI) with clean-slate checkpoints `alice-clean-slate` / `bob-clean-slate`.
* One Linux traffic server with four NICs, each cabled to a switch port and isolated in a netns:

| Host (netns) | NIC | Switch port | VRF (`fattree_k8_pruned`) | Address | Gateway |
|---|---|---|---|---|---|
| alice-host | enp4s0f1 | alice Ethernet1 | tor_a | 192.168.100.2/24 | 192.168.100.1 |
| alice-host2 | enp76s0f1 | alice Ethernet14 | tor_a | 192.168.150.2/24 | 192.168.150.1 |
| bob-host | enp76s0f0 | bob Ethernet1 | tor_b | 192.168.200.2/24 | 192.168.200.1 |
| bob-host2 | enp13s0f1 | bob Ethernet18 | tor_b | 192.168.250.2/24 | 192.168.250.1 |

Each virtual switch is a VRF. A virtual link is a physical cable: between EthernetN on alice and
EthernetN on bob when its two VRFs live on different switches, or a loopback cable between two ports of
the same switch otherwise. Every link is a routed /30 from 172.31.0.0/16; routing is static ECMP (all
shortest-path next hops to every host /24).

## Topology: pruned k=8 fat tree

46 ports per switch remain after the two host ports, so at most 46 inter-VRF links fit (92 free ports,
2 per link). A full k=8 fat tree has 80 switches and 256 links, far above budget, while a full k=4 fat
tree (`topologies/fattree_k4.json`: 20 VRFs, 32 links, 34 ports/switch) has only 4 ECMP paths between
pods. Pruning a k=8 fat tree to the switches and links on shortest paths between a source pod's ToR
(`tor_a` on `alice`) and a destination pod's ToR (`tor_b` on `bob`) preserves the full 5-hop, 16-way
ECMP path fanout of k=8 within the port budget:

* **26 VRFs**: `tor_a` + `agg_a0..agg_a3` + `core_0..core_7` (planes 0-1) on `alice`;
  `tor_b` + `agg_b0..agg_b3` + `core_8..core_15` (planes 2-3) on `bob`.
* **40 inter-VRF /30 links**: 4 `tor_a`--`agg_a0..3`, 4 `tor_b`--`agg_b0..3`, 16 `agg_a_p`--`core_(4p+j)`,
  and 16 `core_(4p+j)`--`agg_b_p` (`p` in `0..3`, `j` in `0..3`).
* **Port budget**: 12 loopback cables (24 ports) + 16 cross-switch cables (16 ports) + 2 host ports =
  **42 of 48 ports used on `alice` and 42 of 48 ports used on `bob`** (`Ethernet43..48` spare on each).
  `make_pruned_clos.py` asserts `2 + k + k^2/2 <= ports_per_switch`; k=8 is the largest even k that
  fits on 48-port switches (k=10 needs `62 > 48` ports/switch).

`configs/fattree_k8_pruned/wiring.txt` lists every cable. `topologies/fattree_k4.json` (full k=4 fat
tree across four pods) and `topologies/ft_k4.json` (the original odd-port 15-VRF topology) remain
available as alternatives.

## Manual step-by-step commands

Every command accepts `--dry-run`, which prints the exact switch config snippets and shell commands
and touches nothing (needs `networkx`, `numpy`, `scipy`, `matplotlib`; host tools: `iperf3`, `hping3`,
`traceroute`, `tshark`).

```bash
cd ~/faultference/testbed
T=topologies/fattree_k8_pruned.json

# 1. Generate topology JSON, EOS configs, and configs/fattree_k8_pruned/wiring.txt
python3 make_pruned_clos.py --k 8 --genconfig

# 2. Deploy: roll back to the clean-slate checkpoint, then merge the generated config
python3 tb.py $T deploy --configs configs/fattree_k8_pruned

# 3. Host namespaces (idempotent; safe to rerun)
python3 tb.py $T hosts

# 4. Sanity check: cross-ToR traffic (8 directed host pairs), per-flow iperf3 JSON in results/baseline
python3 tb.py $T traffic --seconds 30 --flows 100 --outdir results/baseline

# 5. Inject a fault on one virtual switch (and revert it later)
python3 tb.py $T fault inject --vrf agg_a2 --mode blackhole      # or silent_drop / high_latency
python3 tb.py $T fault revert --vrf agg_a2 --mode blackhole

# 6. Manual perturbations
python3 tb.py $T drain down --link agg_a2 core_8                 # withdraw routes, then shut the link
python3 tb.py $T drain up   --link agg_a2 core_8
python3 tb.py $T mirror add --vrf agg_a2
python3 tb.py $T mirror capture --vrf agg_a2 --seconds 10 --pcap results/agg_a2.pcap
python3 tb.py $T mirror remove --vrf agg_a2
python3 tb.py $T probe --src alice-host --dst bob-host --sport 40001 --count 200

# 7. One FIVES trial (injects the fault, localizes, reverts, writes JSON)
python3 run_trial.py $T --scenario silent_drop --culprit agg_a2 --inject \
    --window-s 20 --flows 100 --latency-threshold-ms 1.0 --out results/trial_agg_a2.json

# 8. Revert everything
python3 tb.py $T deploy --configs configs/fattree_k8_pruned      # or: configure replace checkpoint:<sw>-clean-slate
```

## Faults and their EOS limits

| Fault | Injection on VRF X (all of X's interfaces) | Exactness |
|---|---|---|
| Black hole | ingress ACL `deny ip any any` | exact |
| Silent drop | ingress QoS policer (`police rate <R> mbps`) below the offered rate | EOS has no Bernoulli packet drop; the loss rate depends on load and TCP's response |
| High latency | egress `shape rate <kbps>` below the offered rate -> standing queue in the deep buffers | EOS has no netem; the added latency depends on load |

An exact fixed-probability drop or fixed added delay needs a Linux box with `tc netem` cabled inline
on one of X's links; this testbed has no spare host-facing ports for that.

## Perturbations

* **Link drain**: compute the static routes without the link, add/remove the difference on both
  switches (make before break), then `shutdown` both ends; undrain reverses it.
* **Mirroring**: `monitor session FIVES-X source <X's ports> tx`, ACL-filtered to host traffic,
  destination `Cpu`; capture with `tcpdump -i mirror0` in the switch bash (check the interface with
  `show monitor session`), then count TCP lost-segment events (loss upstream of X) with tshark.
  Mirroring cannot see black-holed flows (they never arrive) and has no hardware timestamps for latency.
* **Probes**: from a host netns, `hping3` with a pinned source port (one ECMP path) plus a TCP
  traceroute on the same 5-tuple; traceroute hop IPs map to VRFs, so the probe's path is known.
