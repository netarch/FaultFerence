"""Testbed topology: virtual switches (VRFs) carved out of two physical Arista switches.

A topology spec is a JSON file:

{
  "name": "fattree_k4",
  "physical_switches": {"alice": {"ports": 48}, "bob": {"ports": 48}},
  "port_pool": "all" | [3, 5, ...],          # ports usable for VRF-to-VRF cables (host ports excluded)
  "vrfs": {"tor0": "alice", ...},            # VRF name -> physical switch hosting it
  "links": [["tor0", "agg0"], ...],          # one physical cable per link
  "hosts": [{"name": "alice-host", "nic": "enp4s0f1", "switch": "alice", "port": 1,
             "vrf": "tor0", "prefix": "192.168.100.0/24", "ip": "192.168.100.2",
             "gateway": "192.168.100.1"}, ...]
}

Port allocation is deterministic. A link between VRFs on different physical switches is a cable
between EthernetN on alice and EthernetN on bob (same N on both ends, the lowest N free on both). A
link between two VRFs on the same physical switch is a loopback cable between the two lowest free
ports of that switch. Link i gets the /30 172.31.<4i // 256>.<4i % 256>; the first VRF listed is .1.
"""

from dataclasses import dataclass
import ipaddress
import json
from typing import Dict, List, Tuple

import networkx as nx

LINK_SUPERNET = ipaddress.ip_network("172.31.0.0/16")


@dataclass(frozen=True)
class Host:
    name: str
    nic: str
    switch: str
    port: int
    vrf: str
    prefix: str
    ip: str
    gateway: str


@dataclass(frozen=True)
class Link:
    idx: int
    vrf_a: str
    vrf_b: str
    switch_a: str
    port_a: int
    switch_b: str
    port_b: int
    ip_a: str  # with /30
    ip_b: str  # with /30

    def endpoint(self, vrf: str) -> Tuple[str, int, str]:
        """(physical switch, port, ip/30) of `vrf`'s end of this link."""
        if vrf == self.vrf_a:
            return self.switch_a, self.port_a, self.ip_a
        assert vrf == self.vrf_b, f"{vrf} not on link {self}"
        return self.switch_b, self.port_b, self.ip_b

    def peer(self, vrf: str) -> str:
        assert vrf in (self.vrf_a, self.vrf_b)
        return self.vrf_b if vrf == self.vrf_a else self.vrf_a


class TestbedTopology:
    """Parsed topology spec with port map, link addressing, and static ECMP routes."""

    def __init__(self, spec: Dict):
        self.name: str = spec["name"]
        self.physical_switches: Dict[str, int] = {k: int(v["ports"]) for k, v in spec["physical_switches"].items()}
        self.vrfs: Dict[str, str] = dict(spec["vrfs"])
        self.hosts: Tuple[Host, ...] = tuple(Host(**h) for h in spec["hosts"])
        for vrf, sw in self.vrfs.items():
            assert sw in self.physical_switches, f"VRF {vrf} on unknown switch {sw}"
        host_ports = {(h.switch, h.port) for h in self.hosts}
        assert len(host_ports) == len(self.hosts), "two hosts share a port"
        for h in self.hosts:
            assert self.vrfs[h.vrf] == h.switch, f"host {h.name} cabled to {h.switch} but VRF {h.vrf} is elsewhere"
            assert ipaddress.ip_address(h.ip) in ipaddress.ip_network(h.prefix)
            assert ipaddress.ip_address(h.gateway) in ipaddress.ip_network(h.prefix)

        free: Dict[str, List[int]] = {}
        for sw, nports in self.physical_switches.items():
            pool = list(range(1, nports + 1)) if spec["port_pool"] == "all" else [int(p) for p in spec["port_pool"]]
            assert all(1 <= p <= nports for p in pool)
            free[sw] = [p for p in pool if (sw, p) not in host_ports]

        links: List[Link] = []
        seen = set()
        for idx, (a, b) in enumerate(spec["links"]):
            assert a in self.vrfs and b in self.vrfs and a != b, f"bad link {a}-{b}"
            key = frozenset((a, b))
            assert key not in seen, f"duplicate link {a}-{b}"
            seen.add(key)
            sa, sb = self.vrfs[a], self.vrfs[b]
            if sa != sb:
                common = sorted(set(free[sa]) & set(free[sb]))
                assert len(common) > 0, f"no common free port for cross-switch link {a}-{b}"
                pa = pb = common[0]
                free[sa].remove(pa)
                free[sb].remove(pb)
            else:
                assert len(free[sa]) >= 2, f"no two free ports on {sa} for loop link {a}-{b}"
                pa, pb = free[sa][0], free[sa][1]
                free[sa] = free[sa][2:]
            net = list(LINK_SUPERNET.subnets(new_prefix=30))[idx]
            hosts_ip = list(net.hosts())
            links.append(Link(idx, a, b, sa, pa, sb, pb, f"{hosts_ip[0]}/30", f"{hosts_ip[1]}/30"))
        self.links: Tuple[Link, ...] = tuple(links)
        self.free_ports = {sw: tuple(p) for sw, p in free.items()}

    @classmethod
    def load(cls, path: str) -> "TestbedTopology":
        with open(path) as f:
            return cls(json.load(f))

    # ----- graph views -------------------------------------------------------------------------
    def graph(self, drained: Tuple[Tuple[str, str], ...] = ()) -> nx.Graph:
        """VRF graph plus host leaves, without the `drained` VRF links."""
        g = nx.Graph()
        g.add_nodes_from(self.vrfs)
        drained_set = {frozenset(e) for e in drained}
        for l in self.links:
            if frozenset((l.vrf_a, l.vrf_b)) not in drained_set:
                g.add_edge(l.vrf_a, l.vrf_b)
        for h in self.hosts:
            g.add_edge(h.name, h.vrf)
        return g

    def link_between(self, a: str, b: str) -> Link:
        matches = [l for l in self.links if {l.vrf_a, l.vrf_b} == {a, b}]
        assert len(matches) == 1, f"no unique link {a}-{b}"
        return matches[0]

    def host(self, name: str) -> Host:
        matches = [h for h in self.hosts if h.name == name]
        assert len(matches) == 1, f"unknown host {name}"
        return matches[0]

    def vrf_interfaces(self, vrf: str) -> List[Tuple[str, int]]:
        """(physical switch, port) of every interface of `vrf`, host-facing ones included."""
        out = [l.endpoint(vrf)[:2] for l in self.links if vrf in (l.vrf_a, l.vrf_b)]
        out += [(h.switch, h.port) for h in self.hosts if h.vrf == vrf]
        return sorted(out)

    def static_routes(self, drained: Tuple[Tuple[str, str], ...] = ()) -> Dict[str, List[Tuple[str, str]]]:
        """Per VRF, sorted (host prefix, next-hop IP) static routes: all shortest-path next hops (ECMP)."""
        g = self.graph(drained)
        routes: Dict[str, List[Tuple[str, str]]] = {v: [] for v in self.vrfs}
        for h in self.hosts:
            for vrf in self.vrfs:
                if vrf == h.vrf:
                    continue  # connected
                assert nx.has_path(g, vrf, h.name), f"{vrf} cannot reach {h.name} with drained={drained}"
                next_hops = sorted({p[1] for p in nx.all_shortest_paths(g, vrf, h.name)})
                for nh in next_hops:
                    nh_ip = self.link_between(vrf, nh).endpoint(nh)[2].split("/")[0]
                    routes[vrf].append((h.prefix, nh_ip))
        return {v: sorted(r) for v, r in routes.items()}

    def ip_owner(self) -> Dict[str, str]:
        """Interface IP -> VRF, for mapping traceroute hops to virtual switches."""
        owner = {}
        for l in self.links:
            owner[l.ip_a.split("/")[0]] = l.vrf_a
            owner[l.ip_b.split("/")[0]] = l.vrf_b
        for h in self.hosts:
            owner[h.gateway] = h.vrf
        return owner

    # ----- FIVES simulator view ----------------------------------------------------------------
    def node_ids(self) -> Dict[str, int]:
        """Stable VRF -> integer id (spec order) for the fives simulator."""
        return {v: i for i, v in enumerate(self.vrfs)}

    def write_fives_edgelist(self, path: str) -> None:
        """Integer edgelist in the fives / faultference format (`u v` links, `host->rack` lines)."""
        ids = self.node_ids()
        lines = [f"{ids[l.vrf_a]} {ids[l.vrf_b]}" for l in self.links]
        lines += [f"{10000 + i}->{ids[h.vrf]}" for i, h in enumerate(self.hosts)]
        with open(path, "w") as f:
            f.write("\n".join(lines) + "\n")
