# FIVES Arista testbed

Tools to build a virtual Clos fabric on two Arista 7280 switches, inject faults, apply FIVES
perturbations, and run FIVES localization trials on the hardware.

| File | Purpose |
|---|---|
| `topologies/fattree_k4.json` | k=4 fat tree (20 VRFs, 32 links), hosts on tor0/tor2/tor4/tor6 (one per pod) |
| `topologies/ft_k4.json` | the original `ft_k4` edgelist (15 VRFs, 19 links), same output as the old genconfig.py |
| `genconfig.py` | topology JSON -> `configs/<name>/{alice,bob}.config` + `wiring.txt` (port map) |
| `tb.py` | deploy configs, set up host netns, run traffic, inject/revert faults, drain links, mirror, probe |
| `run_trial.py` | one FIVES localization trial on the hardware (fives planner + inference), logged to JSON |
| `fivestb/` | small library: topology/port/route model, EOS + Linux command builders, executor |
| `test_dry_run.py` | offline tests of every command in dry-run mode (`python3 test_dry_run.py`) |

Every command accepts `--dry-run`, which prints the exact switch config snippets and shell commands
and touches nothing. Run everything from this directory with Python 3 (needs `networkx`, `numpy`,
`scipy`; `run_trial.py` imports `../fives`). Host tools: `iperf3`, `hping3`, `traceroute`, `tshark`.

## Hardware

* Two Arista 7280 switches, `alice` and `bob`, 48 ports each (10G/25G), reachable as `ssh alice` /
  `ssh bob` (login shell = EOS CLI) with clean-slate checkpoints `alice-clean-slate` / `bob-clean-slate`.
* One Linux traffic server with four NICs, each cabled to a switch port and isolated in a netns:

| Host (netns) | NIC | Switch port | Address | Gateway |
|---|---|---|---|---|
| alice-host | enp4s0f1 | alice Ethernet1 | 192.168.100.2/24 | 192.168.100.1 |
| alice-host2 | enp76s0f1 | alice Ethernet14 | 192.168.150.2/24 | 192.168.150.1 |
| bob-host | enp76s0f0 | bob Ethernet1 | 192.168.200.2/24 | 192.168.200.1 |
| bob-host2 | enp13s0f1 | bob Ethernet18 | 192.168.250.2/24 | 192.168.250.1 |

Each virtual switch is a VRF. A virtual link is a physical cable: between EthernetN on alice and
EthernetN on bob when its two VRFs live on different switches, or a loopback cable between two ports of
the same switch otherwise. Every link is a routed /30 from 172.31.0.0/16; routing is static ECMP (all
shortest-path next hops to every host /24).

## Topology: k=4 fat tree

46 ports per switch remain after the host ports, so at most 46 VRF links fit (92 free ports, 2 per
link). With hosts on four ToRs in four different pods:

* k=4 fat tree: 8 ToR + 8 agg + 4 core = 20 VRFs, 16 + 16 = 32 links. Fits (34 ports used per switch).
* k=6 fat tree: 45 VRFs, 54 + 54 = 108 links. Does not fit. So k=4 is the largest k-ary fat tree.
* Non-uniform 3-tier Clos variants with more switches do fit (e.g. 4 pods x 3 ToRs x 2 aggs + 2 planes
  x 2 cores: 24 VRFs, 40 links), but the extra ToRs have no hosts, so they carry no traffic and add no
  path diversity between the four hosts.

Placement: pods 0-1 and core0-1 on alice, pods 2-3 and core2-3 on bob. ToR-agg links stay inside a
switch (loopback cables); 8 agg-core links cross between the switches. `configs/fattree_k4/wiring.txt`
lists every cable.

Note: the old `genconfig.py` only used the 23 odd ports 3..47 and required every link to cross between
alice and bob. A k=4 fat tree cannot be built under those rules (32 > 23 links, and its 2-colouring would
put all ToRs on one switch while hosts hang off both). The new generator uses all free ports and allows
loopback cables. `topologies/ft_k4.json` keeps the old port rule and reproduces the old configs exactly.

## Step by step

```bash
cd ~/faultference/testbed
T=topologies/fattree_k4.json

# 1. Generate configs and cable the switches per configs/fattree_k4/wiring.txt
python3 genconfig.py $T

# 2. Deploy: roll back to the clean-slate checkpoint, then merge the generated config
python3 tb.py $T deploy --configs configs/fattree_k4

# 3. Host namespaces (idempotent; safe to rerun)
python3 tb.py $T hosts

# 4. Sanity check: all-to-all traffic, per-flow iperf3 JSON in results/baseline
python3 tb.py $T traffic --seconds 30 --flows 64 --outdir results/baseline

# 5. Inject a fault on one virtual switch (and revert it later)
python3 tb.py $T fault inject --vrf agg3 --mode blackhole      # or silent_drop / high_latency
python3 tb.py $T fault revert --vrf agg3 --mode blackhole

# 6. Manual perturbations
python3 tb.py $T drain down --link agg3 core2                  # withdraw routes, then shut the link
python3 tb.py $T drain up   --link agg3 core2
python3 tb.py $T mirror add --vrf agg3
python3 tb.py $T mirror capture --vrf agg3 --seconds 10 --pcap results/agg3.pcap
python3 tb.py $T mirror remove --vrf agg3
python3 tb.py $T probe --src alice-host --dst bob-host --sport 40001 --count 200

# 7. One FIVES trial (injects the fault, localizes, reverts, writes JSON)
python3 run_trial.py $T --scenario silent_drop --culprit agg3 --inject \
    --window-s 20 --flows 64 --latency-threshold-ms 1.0 --out results/trial_agg3.json

# 8. Revert everything
python3 tb.py $T deploy --configs configs/fattree_k4               # or: configure replace checkpoint:<sw>-clean-slate
```

Add `--dry-run` (before the subcommand for `tb.py`) to any step to see what it would do. Test the trial
loop offline with
`python3 run_trial.py $T --scenario blackhole --culprit core2 --window-s 10 --flows 64 --latency-threshold-ms 1.0 --out /tmp/t.json --dry-run`:
it prints every command and uses simulated telemetry with the same fault.

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

## Collecting results

`run_trial.py` writes the trial (scenario, culprit, final suspect set, precision/recall, steps,
estimated time, per-step perturbation and suspect set) to `--out`. Raw telemetry goes to
`--workdir/windowNN/` (iperf3 JSON, hping3 output, mirror pcaps).
