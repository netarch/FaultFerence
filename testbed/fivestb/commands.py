"""EOS and Linux command builders for the testbed. Pure functions: no I/O.

Switch-side snippets are lists of EOS configuration lines, applied by copying them to flash and running
`copy flash:<file> running-config` (the same mechanism as the original rules.sh). Host-side commands
are shell strings run on the traffic server, where each testbed host is a Linux network namespace.
"""

from typing import Dict, List, Tuple

from .topology import TestbedTopology

MIRROR_ACL = "FIVES-MIRROR"
BLACKHOLE_ACL = "FIVES-BH"
DROP_ACL = "FIVES-DROP-ALL"
DROP_CLASS = "FIVES-DROP"
DROP_POLICY = "FIVES-DROP"
IPERF_BASE_PORT = 5201


def eth(port: int) -> str:
    return f"Ethernet{port}"


# ----- base configuration -------------------------------------------------------------------------
def base_config(topo: TestbedTopology, switch: str) -> List[str]:
    """Full EOS config for `switch`: VRFs, routed interfaces with /30s, host gateways, static ECMP routes."""
    lines: List[str] = []
    vrfs = [v for v, sw in topo.vrfs.items() if sw == switch]
    for v in vrfs:
        lines += [f"vrf instance {v}", f"ip routing vrf {v}", ""]
    for h in topo.hosts:
        if h.switch == switch:
            plen = h.prefix.split("/")[1]
            lines += [f"interface {eth(h.port)}", "no switchport", f"vrf {h.vrf}", f"ip address {h.gateway}/{plen}", ""]
    for l in topo.links:
        for vrf in (l.vrf_a, l.vrf_b):
            sw, port, ip = l.endpoint(vrf)
            if sw == switch:
                lines += [f"interface {eth(port)}", f"description fives {vrf}->{l.peer(vrf)}", "no switchport",
                          f"vrf {vrf}", f"ip address {ip}", "no shutdown", ""]
    routes = topo.static_routes()
    for v in vrfs:
        lines += [f"ip route vrf {v} {prefix} {nh}" for prefix, nh in routes[v]]
    return lines


# ----- fault injection ----------------------------------------------------------------------------
def fault_inject(topo: TestbedTopology, vrf: str, mode: str, police_mbps: int, shape_kbps: int) -> Tuple[str, List[str]]:
    """(switch, EOS lines) that make virtual switch `vrf` faulty."""
    sw = topo.vrfs[vrf]
    ifaces = [eth(p) for s, p in topo.vrf_interfaces(vrf)]
    if mode == "blackhole":
        lines = [f"ip access-list {BLACKHOLE_ACL}", "10 deny ip any any", "exit"]
        for i in ifaces:
            lines += [f"interface {i}", f"ip access-group {BLACKHOLE_ACL} in"]
        return sw, lines
    if mode == "silent_drop":
        # EOS has no Bernoulli packet drop; an ingress policer below the offered rate drops a share of
        # packets that depends on the load (TCP adapts, so the loss rate is not a fixed constant).
        lines = [f"ip access-list {DROP_ACL}", "10 permit ip any any", "exit",
                 f"class-map type qos match-any {DROP_CLASS}", f"match ip access-group {DROP_ACL}", "exit",
                 f"policy-map type quality-of-service {DROP_POLICY}", f"class {DROP_CLASS}",
                 f"police rate {police_mbps} mbps burst-size 256 kbytes", "exit", "exit"]
        for i in ifaces:
            lines += [f"interface {i}", f"service-policy type qos input {DROP_POLICY}"]
        return sw, lines
    if mode == "high_latency":
        # EOS has no netem; egress shaping below the offered rate builds a standing queue in the deep
        # 7280 buffers, which inflates the latency of every flow through this VRF.
        lines = []
        for i in ifaces:
            lines += [f"interface {i}", f"shape rate {shape_kbps}"]
        return sw, lines
    raise ValueError(f"unknown fault mode {mode}")


def fault_revert(topo: TestbedTopology, vrf: str, mode: str) -> Tuple[str, List[str]]:
    sw = topo.vrfs[vrf]
    ifaces = [eth(p) for s, p in topo.vrf_interfaces(vrf)]
    if mode == "blackhole":
        lines = []
        for i in ifaces:
            lines += [f"interface {i}", f"no ip access-group {BLACKHOLE_ACL} in"]
        return sw, lines + [f"no ip access-list {BLACKHOLE_ACL}"]
    if mode == "silent_drop":
        lines = []
        for i in ifaces:
            lines += [f"interface {i}", f"no service-policy type qos input {DROP_POLICY}"]
        return sw, lines + [f"no policy-map type quality-of-service {DROP_POLICY}",
                            f"no class-map type qos {DROP_CLASS}", f"no ip access-list {DROP_ACL}"]
    if mode == "high_latency":
        lines = []
        for i in ifaces:
            lines += [f"interface {i}", "no shape rate"]
        return sw, lines
    raise ValueError(f"unknown fault mode {mode}")


# ----- perturbations ------------------------------------------------------------------------------
def link_drain(topo: TestbedTopology, a: str, b: str) -> Dict[str, List[str]]:
    """Per-switch EOS lines that drain VRF link a-b: withdraw static routes using it, then shut it."""
    return _route_diff(topo, (), ((a, b),), shutdown_link=(a, b))


def link_undrain(topo: TestbedTopology, a: str, b: str) -> Dict[str, List[str]]:
    """Inverse of link_drain: bring the link up, then restore the full static route set."""
    return _route_diff(topo, ((a, b),), (), noshutdown_link=(a, b))


def _route_diff(topo, before, after, shutdown_link=None, noshutdown_link=None) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {sw: [] for sw in topo.physical_switches}
    if noshutdown_link is not None:
        l = topo.link_between(*noshutdown_link)
        for vrf in (l.vrf_a, l.vrf_b):
            sw, port, _ = l.endpoint(vrf)
            out[sw] += [f"interface {eth(port)}", "no shutdown", "exit"]
    r0, r1 = topo.static_routes(before), topo.static_routes(after)
    for vrf, sw in topo.vrfs.items():
        add, rem = sorted(set(r1[vrf]) - set(r0[vrf])), sorted(set(r0[vrf]) - set(r1[vrf]))
        out[sw] += [f"ip route vrf {vrf} {p} {nh}" for p, nh in add]  # make before break
        out[sw] += [f"no ip route vrf {vrf} {p} {nh}" for p, nh in rem]
    if shutdown_link is not None:
        l = topo.link_between(*shutdown_link)
        for vrf in (l.vrf_a, l.vrf_b):
            sw, port, _ = l.endpoint(vrf)
            out[sw] += [f"interface {eth(port)}", "shutdown", "exit"]
    return {sw: lines for sw, lines in out.items() if lines}


def mirror_add(topo: TestbedTopology, vrf: str) -> Tuple[str, List[str]]:
    """Mirror everything VRF `vrf` transmits (ACL-filtered to host traffic) to the switch CPU."""
    sw = topo.vrfs[vrf]
    session = f"FIVES-{vrf}"
    lines = [f"ip access-list {MIRROR_ACL}", "10 permit ip 192.168.0.0/16 192.168.0.0/16", "exit"]
    for s, p in topo.vrf_interfaces(vrf):
        lines.append(f"monitor session {session} source {eth(p)} tx")
    lines += [f"monitor session {session} ip access-group {MIRROR_ACL}", f"monitor session {session} destination Cpu"]
    return sw, lines


def mirror_remove(topo: TestbedTopology, vrf: str) -> Tuple[str, List[str]]:
    return topo.vrfs[vrf], [f"no monitor session FIVES-{vrf}"]


def mirror_capture(seconds: int, remote_pcap: str) -> str:
    """EOS exec command capturing the CPU mirror interface (check its name with `show monitor session`)."""
    return f"bash timeout {seconds} sudo tcpdump -i mirror0 -w {remote_pcap}"


# ----- host-side commands -------------------------------------------------------------------------
def netns_setup(topo: TestbedTopology) -> List[str]:
    """Idempotent: (re)create each host netns, move its NIC in, address it, route 192.168/16 via its VRF."""
    cmds = []
    for h in topo.hosts:
        plen = h.prefix.split("/")[1]
        ns = f"sudo ip netns exec {h.name}"
        cmds += [
            f"sudo ip netns add {h.name} 2>/dev/null || true",
            f"ip link show {h.nic} >/dev/null 2>&1 && sudo ip link set {h.nic} netns {h.name} || true",
            f"{ns} ip addr replace {h.ip}/{plen} dev {h.nic}",
            f"{ns} ip link set {h.nic} up",
            f"{ns} ip route replace 192.168.0.0/16 via {h.gateway} dev {h.nic}",
        ]
    return cmds


def iperf_servers(topo: TestbedTopology) -> List[str]:
    """One iperf3 server per (destination, source) pair: iperf3 serves one client at a time."""
    cmds = []
    for di, d in enumerate(topo.hosts):
        for si, s in enumerate(topo.hosts):
            if si != di:
                cmds.append(f"sudo ip netns exec {d.name} iperf3 -s -D -p {IPERF_BASE_PORT + si}")
    return cmds


def iperf_clients(topo: TestbedTopology, seconds: int, flows: int, outdir: str) -> List[str]:
    """All-to-all: every host runs `flows` parallel TCP streams (random source ports) to every other host."""
    cmds = []
    for si, s in enumerate(topo.hosts):
        for d in topo.hosts:
            if d.name != s.name:
                cmds.append(f"sudo ip netns exec {s.name} iperf3 -c {d.ip} -p {IPERF_BASE_PORT + si} -P {flows} "
                            f"-t {seconds} -J > {outdir}/iperf_{s.name}_{d.name}.json &")
    return cmds + ["wait"]


def probe(src_host: str, dst_ip: str, sport: int, count: int) -> List[str]:
    """Fixed-5-tuple probe: TCP SYNs with a pinned source port (one ECMP path) plus a Paris-style traceroute."""
    ns = f"sudo ip netns exec {src_host}"
    return [f"{ns} hping3 -S -p {IPERF_BASE_PORT} -s {sport} -k -c {count} -i u10000 {dst_ip}",
            f"{ns} traceroute -n -q 1 -T -p {IPERF_BASE_PORT} --sport={sport} {dst_ip}"]
