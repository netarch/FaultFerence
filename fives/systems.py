"""General Equivalent System representations: Networks (DC Clos, Expanders, WAN, PROD) & Microservices."""

from dataclasses import dataclass
from enum import Enum
import itertools
from typing import Dict, FrozenSet, List, Optional, Sequence, Set, Tuple
import networkx as nx
import numpy as np
from scipy.stats import norm

from .perturbations import (
    ActiveProbe,
    ComponentReset,
    FlowGroupSplit,
    FlowLinkDrain,
    FullLinkDrain,
    PacketMirror,
    Perturbation,
    SubtleWeightShift,
)

HOST_OFFSET = 10000


class FailureMode(Enum):
    """Fault models of the faulty switch.

    BLACKHOLE:     flow-level; a flow hashed through the faulty switch is lost with prob `drop_prob`.
    SILENT_DROP:   packet-level silent drop / corruption; each packet through the faulty switch is
                   dropped or corrupted with prob `drop_prob`.
    HIGH_LATENCY:  flow-level; a flow through the faulty switch has its latency inflated by
                   `latency_inflation_us` with prob `drop_prob`. Every flow's latency also carries
                   Gaussian jitter (std `latency_jitter_us`) around its path baseline, and telemetry
                   marks a flow bad iff its excess latency over the baseline exceeds
                   `latency_threshold_us`. Background false alarms come from the jitter tail.
    INTERMITTENT:  SILENT_DROP that is active in a window with prob `duty_cycle`.
    """

    BLACKHOLE = "blackhole"
    SILENT_DROP = "silent_drop"
    HIGH_LATENCY = "high_latency"
    INTERMITTENT = "intermittent"


@dataclass(frozen=True)
class FailureSpec:
    mode: FailureMode
    faulty_node: int
    affected_pairs: Tuple[Tuple[int, int], ...]
    drop_prob: float  # HIGH_LATENCY: fraction of flows through the faulty switch that are inflated
    bg_noise_prob: float = 1.0e-4  # unused by HIGH_LATENCY (jitter tail is the noise source)
    duty_cycle: float = 1.0  # < 1.0 for intermittent gray failures
    latency_inflation_us: float = 0.0
    latency_jitter_us: float = 0.0
    latency_threshold_us: float = 0.0

    def __post_init__(self) -> None:
        assert 0.0 <= self.drop_prob <= 1.0, f"drop_prob {self.drop_prob} not in [0, 1]"
        assert 0.0 <= self.bg_noise_prob < 1.0, f"bg_noise_prob {self.bg_noise_prob} not in [0, 1)"
        assert 0.0 < self.duty_cycle <= 1.0, f"duty_cycle {self.duty_cycle} not in (0, 1]"
        latency_fields = (self.latency_inflation_us, self.latency_jitter_us, self.latency_threshold_us)
        if self.mode == FailureMode.HIGH_LATENCY:
            assert all(x > 0.0 for x in latency_fields), (
                f"HIGH_LATENCY needs positive inflation/jitter/threshold, got {latency_fields}"
            )
        else:
            assert all(x == 0.0 for x in latency_fields), f"latency fields set for mode {self.mode}"

    def unit_bad_prob(self, hits_fault: bool) -> float:
        """Probability that one observation unit (flow, packet, probe) is reported bad."""
        if self.mode == FailureMode.HIGH_LATENCY:
            p_jitter_only = float(norm.sf(self.latency_threshold_us / self.latency_jitter_us))
            if not hits_fault:
                return p_jitter_only
            p_inflated = float(
                norm.sf((self.latency_threshold_us - self.latency_inflation_us) / self.latency_jitter_us)
            )
            return self.drop_prob * p_inflated + (1.0 - self.drop_prob) * p_jitter_only
        return self.drop_prob if hits_fault else self.bg_noise_prob


@dataclass(frozen=True)
class SafetyConfig:
    """Structured operational & vendor constraints on admissible perturbations."""

    min_bandwidth_ratio: float = 0.50
    drain_banned_nodes: FrozenSet[int] = frozenset()
    reset_banned_nodes: FrozenSet[int] = frozenset()
    probe_banned_nodes: FrozenSet[int] = frozenset()
    mirror_filtered_nodes: FrozenSet[int] = frozenset()
    mirror_unfiltered_only_nodes: FrozenSet[int] = frozenset()
    mirror_banned_nodes: FrozenSet[int] = frozenset()
    external_blackbox_nodes: FrozenSet[int] = frozenset()
    max_unfiltered_mirror_load: float = 0.35
    enable_subtle_weight_shifts: bool = True
    enable_group_splits: bool = True
    enable_packet_mirror: bool = False
    enable_component_reset: bool = True


@dataclass(frozen=True)
class TelemetryRecord:
    """Aggregated telemetry for one traffic class / probe stream during an observation window."""

    pair: Tuple[int, int]
    is_probe: bool
    is_mirror: bool
    mirror_node: int
    packets_sent: int
    packets_bad: int
    path_weights: Tuple[Tuple[Tuple[int, ...], float], ...]


@dataclass(frozen=True)
class TelemetryWindow:
    perturbation: Optional[Perturbation]
    records: Tuple[TelemetryRecord, ...]
    fault_was_active: bool


class NetworkSystem:
    """General network fabric supporting ECMP, DLB/AR, multi-links, and structured PROD constraints."""

    def __init__(
        self,
        name: str,
        graph: nx.Graph,
        switch_nodes: Sequence[int],
        rack_nodes: Sequence[int],
        node_names: Dict[int, str],
        edge_capacities: Dict[Tuple[int, int], float],
        edge_loads: Dict[Tuple[int, int], float],
        safety: SafetyConfig,
        dlb_routing: bool = False,
    ):
        self.name = name
        self.G = graph
        self.switch_nodes: Tuple[int, ...] = tuple(sorted(switch_nodes))
        self.switch_set: FrozenSet[int] = frozenset(self.switch_nodes)
        self.rack_nodes: Tuple[int, ...] = tuple(sorted(rack_nodes))
        self.node_names = node_names
        self.edge_capacities = edge_capacities
        self.edge_loads = edge_loads
        self.safety = safety
        self.dlb_routing = dlb_routing
        self._shortest_paths_cache: Dict[Tuple[int, int], Tuple[Tuple[int, ...], ...]] = {}
        self._no_branch_cache: Dict[Tuple[Tuple[int, int], int, int], bool] = {}
        self._articulation_points: FrozenSet[int] = frozenset(nx.articulation_points(graph))

    def shortest_paths(self, src_sw: int, dst_sw: int, max_ecmp_paths: int = 256) -> Tuple[Tuple[int, ...], ...]:
        key = (src_sw, dst_sw)
        if key not in self._shortest_paths_cache:
            if src_sw == dst_sw:
                paths = ((src_sw,),)
            elif not nx.has_path(self.G, src_sw, dst_sw):
                paths = ()
            else:
                paths = tuple(
                    tuple(p)
                    for p in itertools.islice(nx.all_shortest_paths(self.G, source=src_sw, target=dst_sw), max_ecmp_paths)
                )
            self._shortest_paths_cache[key] = paths
        return self._shortest_paths_cache[key]

    def paths_under_perturbation(
        self,
        pair: Tuple[int, int],
        perturbation: Optional[Perturbation],
    ) -> Tuple[Tuple[Tuple[int, ...], float], ...]:
        """Return (node_path, normalized_probability) for `pair` under `perturbation`."""
        base_paths = self.shortest_paths(pair[0], pair[1])
        assert len(base_paths) > 0, f"Disconnected pair {pair} in {self.name}"

        if isinstance(perturbation, FlowLinkDrain) and perturbation.flow_pair == pair:
            u, v = perturbation.u, perturbation.v
            kept = [
                p for p in base_paths
                if not any((p[i] == u and p[i + 1] == v) for i in range(len(p) - 1))
            ]
            if len(kept) == 0:
                return ()
            w = 1.0 / len(kept)
            return tuple((p, w) for p in kept)

        if isinstance(perturbation, FlowGroupSplit) and perturbation.flow_pair == pair:
            u = perturbation.u
            drained_set = set(perturbation.drained_nexthops)
            kept = [
                p for p in base_paths
                if not any((p[i] == u and p[i + 1] in drained_set) for i in range(len(p) - 1))
            ]
            if len(kept) == 0:
                return ()
            w = 1.0 / len(kept)
            return tuple((p, w) for p in kept)

        if isinstance(perturbation, FullLinkDrain):
            u, v = perturbation.u, perturbation.v
            kept = [
                p for p in base_paths
                if not any(
                    (p[i] == u and p[i + 1] == v) or (p[i] == v and p[i + 1] == u)
                    for i in range(len(p) - 1)
                )
            ]
            if len(kept) > 0:
                w = 1.0 / len(kept)
                return tuple((p, w) for p in kept)
            # Recompute IGP shortest paths when all primary ECMP paths used (u, v)
            g_mod = self.G.copy()
            if g_mod.has_edge(u, v):
                g_mod.remove_edge(u, v)
            if not nx.has_path(g_mod, pair[0], pair[1]):
                return ()
            rerouted = tuple(
                tuple(p)
                for p in itertools.islice(nx.all_shortest_paths(g_mod, source=pair[0], target=pair[1]), 256)
            )
            w = 1.0 / len(rerouted)
            return tuple((p, w) for p in rerouted)

        if isinstance(perturbation, SubtleWeightShift) and perturbation.flow_pair == pair:
            u, v = perturbation.u, perturbation.v
            factor = perturbation.weight_factor
            raw_weights = []
            for p in base_paths:
                uses_uv = any((p[i] == u and p[i + 1] == v) for i in range(len(p) - 1))
                raw_weights.append(factor if uses_uv else 1.0)
            total = sum(raw_weights)
            assert total > 0.0
            return tuple((p, rw / total) for p, rw in zip(base_paths, raw_weights))

        w = 1.0 / len(base_paths)
        return tuple((p, w) for p in base_paths)

    def check_no_branch(self, flow_pair: Tuple[int, int], probe_src: int, probe_dst: int) -> bool:
        """Exact ECMP branching check: ensures probe_src->probe_dst cannot diverge from flow_pair paths."""
        if self.dlb_routing:
            # Under per-packet adaptive routing without deterministic 5-tuple hashing,
            # only single-path subtrees are branch-free.
            sub_paths = self.shortest_paths(probe_src, probe_dst)
            return len(sub_paths) == 1

        ckey = (flow_pair, probe_src, probe_dst)
        if ckey in self._no_branch_cache:
            return self._no_branch_cache[ckey]

        sub_paths = self.shortest_paths(probe_src, probe_dst)
        if len(sub_paths) == 0:
            self._no_branch_cache[ckey] = False
            return False

        sub_nodes: Set[int] = set()
        for sp in sub_paths:
            sub_nodes.update(sp)

        flow_paths = self.shortest_paths(flow_pair[0], flow_pair[1])
        ok = True
        for fp in flow_paths:
            for i in range(len(fp) - 1):
                a, b = fp[i], fp[i + 1]
                # Incoming branch into interior of sub_nodes
                if b != probe_src and (b in sub_nodes) and (a not in sub_nodes):
                    bypasses_b = any(b not in sp for sp in sub_paths)
                    if bypasses_b:
                        ok = False
                        break
                # Outgoing branch out of sub_nodes before probe_dst
                if a != probe_dst and (a in sub_nodes) and (b not in sub_nodes):
                    ok = False
                    break
            if not ok:
                break

        self._no_branch_cache[ckey] = ok
        return ok

    def candidate_perturbations(
        self,
        active_pairs: Sequence[Tuple[int, int]],
        suspects: Set[int],
    ) -> List[Perturbation]:
        """Enumerate candidate perturbations across Telemetry, Control, and Physical planes."""
        cands: List[Perturbation] = []
        seen: Set[Tuple] = set()

        def add(p: Perturbation) -> None:
            if p.key not in seen:
                seen.add(p.key)
                cands.append(p)

        relevant_edges: Set[Tuple[int, int]] = set()
        for pair in active_pairs:
            paths = self.shortest_paths(pair[0], pair[1])
            for path in paths:
                if not any(n in suspects for n in path):
                    continue
                dst_sw = path[-1]
                # 1. Telemetry: 5-tuple Active Probes along path to dst_sw
                for idx in range(len(path) - 1):
                    u, v = path[idx], path[idx + 1]
                    relevant_edges.add((u, v))
                    if u != dst_sw and self.check_no_branch(pair, u, dst_sw):
                        add(ActiveProbe(u, dst_sw, pair))

                # 2. Telemetry: Selective Packet Mirroring on suspect / path switches
                if self.safety.enable_packet_mirror:
                    for sw in path:
                        if sw in suspects:
                            if sw in self.safety.mirror_filtered_nodes:
                                add(PacketMirror(sw, True, pair))
                            elif sw in self.safety.mirror_unfiltered_only_nodes:
                                add(PacketMirror(sw, False, pair))

                # 3. Control: Flow-scoped drains & Subtle ECMP/WCMP weight shifts
                if len(paths) > 1:
                    for idx in range(len(path) - 1):
                        u, v = path[idx], path[idx + 1]
                        add(FlowLinkDrain(u, v, pair))
                        if self.safety.enable_subtle_weight_shifts:
                            add(SubtleWeightShift(u, v, 0.20, pair))

            # 3b. Control: Prefix-scoped WCMP/PBR next-hop-group binary splits at multi-path fanout switches
            if len(paths) > 2 and self.safety.enable_group_splits:
                u_to_nhs: Dict[int, Set[int]] = {}
                u_nh_hits: Dict[Tuple[int, int], int] = {}
                for path in paths:
                    for idx in range(len(path) - 1):
                        u, v = path[idx], path[idx + 1]
                        if u not in u_to_nhs:
                            u_to_nhs[u] = set()
                        u_to_nhs[u].add(v)
                        hits = sum(1 for n in path[idx + 1 :] if n in suspects)
                        if (u, v) not in u_nh_hits:
                            u_nh_hits[(u, v)] = 0
                        u_nh_hits[(u, v)] += hits
                for u, nh_set in sorted(u_to_nhs.items()):
                    max_drain = len(nh_set) // 2
                    if max_drain < 2:
                        continue
                    min_h = min(u_nh_hits[(u, v)] for v in nh_set)
                    active_nhs = sorted(v for v in nh_set if u_nh_hits[(u, v)] > min_h)
                    if len(active_nhs) == 0:
                        active_nhs = sorted(v for v in nh_set if u_nh_hits[(u, v)] > 0)
                    if len(active_nhs) >= 3:
                        half = min(max_drain, max(2, len(active_nhs) // 2))
                        add(FlowGroupSplit(u, tuple(active_nhs[:half]), pair))

        # 4. Control: Global Full Link Drains (when flow-scoped rules are unsupported or single-prefix)
        for u, v in sorted(relevant_edges):
            add(FullLinkDrain(u, v))

        # 5. Physical: Component Reset / Replace on remaining suspects
        if self.safety.enable_component_reset:
            for sw in sorted(suspects):
                add(ComponentReset(sw))

        return cands

    def simulate_window(
        self,
        failure: FailureSpec,
        perturbation: Optional[Perturbation],
        rng: np.random.Generator,
        flows_per_pair: int = 400,
        packets_per_flow: int = 25,
    ) -> TelemetryWindow:
        """Simulate a telemetry observation window under `perturbation`."""
        fault_active = True
        if failure.mode == FailureMode.INTERMITTENT:
            fault_active = bool(rng.random() < failure.duty_cycle)

        # ComponentReset temporarily swaps/resets `perturbation.node`: if it IS the faulty node, fault disappears!
        fault_suppressed = (
            isinstance(perturbation, ComponentReset) and perturbation.node == failure.faulty_node
        )

        records: List[TelemetryRecord] = []

        # 1. End-to-end application flow telemetry for each monitored pair
        for pair in failure.affected_pairs:
            pw = self.paths_under_perturbation(pair, perturbation)
            assert len(pw) > 0, f"Perturbation {perturbation} disconnected {pair}"
            paths = [p for p, _ in pw]
            probs = np.array([w for _, w in pw], dtype=np.float64)

            total_pkts = flows_per_pair * packets_per_flow
            if self.dlb_routing:
                # Per-packet load balancing across paths
                pkt_path_idx = rng.choice(len(paths), size=total_pkts, p=probs)
                bad_pkts = 0
                for idx_p, path in enumerate(paths):
                    cnt = int(np.sum(pkt_path_idx == idx_p))
                    if cnt == 0:
                        continue
                    hits_fault = (
                        fault_active
                        and (not fault_suppressed)
                        and (failure.faulty_node in path)
                    )
                    p_bad = failure.unit_bad_prob(hits_fault)
                    bad_pkts += int(rng.binomial(cnt, p_bad))
                records.append(
                    TelemetryRecord(
                        pair=pair,
                        is_probe=False,
                        is_mirror=False,
                        mirror_node=-1,
                        packets_sent=total_pkts,
                        packets_bad=bad_pkts,
                        path_weights=pw,
                    )
                )
            else:
                # Per-flow ECMP / WCMP hashing across paths
                flow_path_idx = rng.choice(len(paths), size=flows_per_pair, p=probs)
                if failure.mode in (FailureMode.BLACKHOLE, FailureMode.HIGH_LATENCY):
                    # Flow-level blackhole / MTU drop or flow latency SLO (1 observation unit = 1 flow)
                    bad_flows = 0
                    for idx_p, path in enumerate(paths):
                        cnt = int(np.sum(flow_path_idx == idx_p))
                        if cnt == 0:
                            continue
                        hits_fault = (
                            fault_active
                            and (not fault_suppressed)
                            and (failure.faulty_node in path)
                        )
                        p_bad = failure.unit_bad_prob(hits_fault)
                        bad_flows += int(rng.binomial(cnt, p_bad))
                    records.append(
                        TelemetryRecord(
                            pair=pair,
                            is_probe=False,
                            is_mirror=False,
                            mirror_node=-1,
                            packets_sent=flows_per_pair,
                            packets_bad=bad_flows,
                            path_weights=pw,
                        )
                    )
                else:
                    # Packet-level silent drop / corruption
                    bad_pkts = 0
                    for idx_p, path in enumerate(paths):
                        cnt_pkts = int(np.sum(flow_path_idx == idx_p)) * packets_per_flow
                        if cnt_pkts == 0:
                            continue
                        hits_fault = (
                            fault_active
                            and (not fault_suppressed)
                            and (failure.faulty_node in path)
                        )
                        p_bad = failure.unit_bad_prob(hits_fault)
                        bad_pkts += int(rng.binomial(cnt_pkts, p_bad))
                    records.append(
                        TelemetryRecord(
                            pair=pair,
                            is_probe=False,
                            is_mirror=False,
                            mirror_node=-1,
                            packets_sent=total_pkts,
                            packets_bad=bad_pkts,
                            path_weights=pw,
                        )
                    )

        # 2. Telemetry-plane observations (ActiveProbe or PacketMirror)
        if isinstance(perturbation, ActiveProbe):
            sub_paths = self.shortest_paths(perturbation.src_node, perturbation.dst_node)
            assert len(sub_paths) > 0
            w = 1.0 / len(sub_paths)
            pw_probe = tuple((sp, w) for sp in sub_paths)
            # Crafted with matching 5-tuple -> hashes to 1 deterministic path in sub_paths
            chosen_sp = sub_paths[int(rng.integers(0, len(sub_paths)))]
            hits_fault = fault_active and (failure.faulty_node in chosen_sp)
            p_bad = failure.unit_bad_prob(hits_fault)
            bad_probes = int(rng.binomial(perturbation.num_probes, p_bad))
            records.append(
                TelemetryRecord(
                    pair=perturbation.flow_pair,
                    is_probe=True,
                    is_mirror=False,
                    mirror_node=-1,
                    packets_sent=perturbation.num_probes,
                    packets_bad=bad_probes,
                    path_weights=pw_probe,
                )
            )
        elif isinstance(perturbation, PacketMirror):
            # Packet mirror at switch `m` observes whether packets arriving/departing `m` are already corrupted/dropped upstream (including `m`) vs downstream!
            base_paths = self.shortest_paths(perturbation.flow_pair[0], perturbation.flow_pair[1])
            through_m = [p for p in base_paths if perturbation.node in p]
            if len(through_m) > 0:
                # Upstream prefix up to and including `perturbation.node`
                up_prefixes = [p[: p.index(perturbation.node) + 1] for p in through_m]
                w = 1.0 / len(up_prefixes)
                pw_mir = tuple((up, w) for up in up_prefixes)
                n_mir = 200
                chosen_idx = rng.integers(0, len(up_prefixes), size=n_mir)
                bad_mir = 0
                for idx_u, up in enumerate(up_prefixes):
                    cnt = int(np.sum(chosen_idx == idx_u))
                    if cnt == 0:
                        continue
                    hits_fault = fault_active and (failure.faulty_node in up)
                    p_bad = failure.unit_bad_prob(hits_fault)
                    bad_mir += int(rng.binomial(cnt, p_bad))
                records.append(
                    TelemetryRecord(
                        pair=perturbation.flow_pair,
                        is_probe=False,
                        is_mirror=True,
                        mirror_node=perturbation.node,
                        packets_sent=n_mir,
                        packets_bad=bad_mir,
                        path_weights=pw_mir,
                    )
                )

        return TelemetryWindow(
            perturbation=perturbation,
            records=tuple(records),
            fault_was_active=fault_active,
        )


def load_edgelist_network(
    edgelist_path: str,
    name: str,
    safety: Optional[SafetyConfig] = None,
    dlb_routing: bool = False,
    rng_seed: int = 42,
) -> NetworkSystem:
    """Load standard .edgelist network (FatTree, Random Regular, B4, UsC, Kdl)."""
    g = nx.Graph()
    racks: Set[int] = set()
    switches: Set[int] = set()

    with open(edgelist_path, "r") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            if "->" in line:
                lhs, rhs = line.split("->")
                host = int(lhs.strip())
                rack = int(rhs.strip())
                assert host >= HOST_OFFSET
                racks.add(rack)
                switches.add(rack)
            else:
                parts = line.split()
                u, v = int(parts[0]), int(parts[1])
                assert u < HOST_OFFSET and v < HOST_OFFSET
                switches.add(u)
                switches.add(v)
                g.add_edge(u, v)

    if len(racks) == 0:
        racks = set(switches)

    rng = np.random.default_rng(rng_seed)
    edge_caps: Dict[Tuple[int, int], float] = {}
    edge_loads: Dict[Tuple[int, int], float] = {}
    for u, v in g.edges():
        cap = 100.0
        load = float(rng.uniform(0.18, 0.52))
        edge_caps[(u, v)] = cap
        edge_caps[(v, u)] = cap
        edge_loads[(u, v)] = load
        edge_loads[(v, u)] = load

    node_names = {sw: f"sw-{sw}" for sw in switches}
    cfg = safety if safety is not None else SafetyConfig()
    return NetworkSystem(
        name=name,
        graph=g,
        switch_nodes=sorted(switches),
        rack_nodes=sorted(racks),
        node_names=node_names,
        edge_capacities=edge_caps,
        edge_loads=edge_loads,
        safety=cfg,
        dlb_routing=dlb_routing,
    )


def load_campus_prod_system(
    campus_str_path: str,
    rng_seed: int = 42,
) -> NetworkSystem:
    """Load PROD (`campus-str.edgelist`) with faithful named structural & vendor constraints.

    Directly models the real PROD operational properties from Section 6.4:
    1. Pre-existing link failures (`# failed` lines in `campus-str.edgelist` reduce parallel bundle capacity).
    2. Core (`core*`) and critical DC (`rtr-dcldc`, `rtr-acbdc`, `sw-dcldc*`) ban invasive drains & resets.
    3. External peering (`ncsa*`, `NCSA*`, `ext*`) are black-box (zero perturbations allowed).
    4. Multi-vendor switch capabilities across access/building/distribution layers:
       - Vendor A (Arista, `dist*` & `rtr-*`): supports active probes & ingress filtered mirroring.
       - Vendor B (HPE, `bd-*`): allows unfiltered mirroring only when load <= 0.35, no filtered mirroring.
       - Vendor C (Cisco/Aruba, `sw-*`, `rs-*`): supports flow drains & probes, no mirroring on edge.
    5. 50% minimum residual capacity bound across parallel bundles / cut edges.
    """
    node_to_id: Dict[str, int] = {}
    id_to_node: Dict[int, str] = {}
    bundle_total: Dict[Tuple[int, int], int] = {}
    bundle_failed: Dict[Tuple[int, int], int] = {}

    def get_id(label: str) -> int:
        if label not in node_to_id:
            nid = len(node_to_id)
            node_to_id[label] = nid
            id_to_node[nid] = label
        return node_to_id[label]

    with open(campus_str_path, "r") as f:
        for raw in f:
            comment = ""
            line = raw
            if "#" in raw:
                line, comment = raw.split("#", 1)
            tokens = line.strip().split()
            if len(tokens) < 2:
                continue
            if "host" in comment.lower():
                continue
            u = get_id(tokens[0])
            v = get_id(tokens[1])
            if u == v:
                continue
            key = (u, v) if u < v else (v, u)
            bundle_total[key] = bundle_total[key] + 1 if key in bundle_total else 1
            if "failed" in comment.lower():
                bundle_failed[key] = bundle_failed[key] + 1 if key in bundle_failed else 1

    g = nx.Graph()
    edge_caps: Dict[Tuple[int, int], float] = {}
    rng = np.random.default_rng(rng_seed)
    edge_loads: Dict[Tuple[int, int], float] = {}

    for (u, v), tot in bundle_total.items():
        failed_cnt = bundle_failed[(u, v)] if (u, v) in bundle_failed else 0
        live_cnt = tot - failed_cnt
        if live_cnt <= 0:
            continue
        g.add_edge(u, v)
        # Capacity normalized to planned bundle size `tot` so pre-existing failures already consume headroom!
        cap_ratio = float(live_cnt) / float(tot)
        load = float(rng.uniform(0.20, 0.55)) * cap_ratio
        edge_caps[(u, v)] = cap_ratio * 100.0
        edge_caps[(v, u)] = cap_ratio * 100.0
        edge_loads[(u, v)] = load
        edge_loads[(v, u)] = load

    # Restrict to largest connected component so all rack pairs are mutually routable
    largest_cc = max(nx.connected_components(g), key=len)
    g = g.subgraph(largest_cc).copy()
    switches = sorted(largest_cc)

    drain_banned: Set[int] = set()
    reset_banned: Set[int] = set()
    probe_banned: Set[int] = set()
    mirror_filt: Set[int] = set()
    mirror_unfilt: Set[int] = set()
    mirror_banned: Set[int] = set()
    external_peers: Set[int] = set()
    racks: Set[int] = set()

    for sw in switches:
        nm = id_to_node[sw]
        low = nm.lower()
        if any(tag in low for tag in ("ncsa", "ext1", "ext2")):
            external_peers.add(sw)
            drain_banned.add(sw)
            reset_banned.add(sw)
            probe_banned.add(sw)
            mirror_banned.add(sw)
            racks.add(sw)
            continue

        if low.startswith("core") or "dcldc" in low or "acbdc" in low or "admin" in low or "swanlund" in low:
            # Core & critical DC / administrative buildings ban invasive drains & reboots
            drain_banned.add(sw)
            reset_banned.add(sw)

        if low.startswith("core"):
            mirror_banned.add(sw)
        elif low.startswith("dist") or low.startswith("rtr-"):
            # Vendor A (Arista): supports active probes + filtered ingress mirroring
            mirror_filt.add(sw)
        elif low.startswith("bd-"):
            # Vendor B (HPE): unfiltered mirroring only (subject to load <= 0.35), no probe origination
            mirror_unfilt.add(sw)
            probe_banned.add(sw)
        else:
            # Access/edge switches (`sw-*`, `rs-*`): edge racks hosting endpoints
            racks.add(sw)
            mirror_banned.add(sw)

    safety = SafetyConfig(
        min_bandwidth_ratio=0.50,
        drain_banned_nodes=frozenset(drain_banned),
        reset_banned_nodes=frozenset(reset_banned),
        probe_banned_nodes=frozenset(probe_banned),
        mirror_filtered_nodes=frozenset(mirror_filt),
        mirror_unfiltered_only_nodes=frozenset(mirror_unfilt),
        mirror_banned_nodes=frozenset(mirror_banned),
        external_blackbox_nodes=frozenset(external_peers),
        max_unfiltered_mirror_load=0.35,
        enable_subtle_weight_shifts=True,
        enable_packet_mirror=True,
        enable_component_reset=True,
    )

    return NetworkSystem(
        name="PROD",
        graph=g,
        switch_nodes=switches,
        rack_nodes=sorted(racks),
        node_names=id_to_node,
        edge_capacities=edge_caps,
        edge_loads=edge_loads,
        safety=safety,
        dlb_routing=False,
    )


class MicroserviceSystem(NetworkSystem):
    """9-component multi-tier microservice architecture demonstrating FIVES's cross-domain generality.

    Tiers:
      - Ingress (node 0) -> API Layer: `core-1` (1), `core-2` (2)
      - Backend Layer: `registry-1` (3), `registry-2` (4), `registry-3` (5)
      - Cache Layer: `redis-primary` (6), `redis-replica` (7)
      - DB Layer: `postgres-primary` (8), `postgres-replica` (9) -> Response Sink (10)

    Perturbations map 1:1 onto the exact same FIVES planes:
      - Control (SubtleWeightShift / FlowLinkDrain): Istio L7 traffic shifts & cache/replica read-path overrides
      - Telemetry (PacketMirror / ActiveProbe): Distributed trace / synthetic canary probes
      - Physical (ComponentReset): Pod restart (high disruption: dropped connections + cache cold-start)
    """

    COMPONENT_LABELS = {
        0: "ingress-gw",
        1: "core-1",
        2: "core-2",
        3: "registry-1",
        4: "registry-2",
        5: "registry-3",
        6: "redis-primary",
        7: "redis-replica",
        8: "postgres-primary",
        9: "postgres-replica",
        10: "egress-sink",
    }

    def __init__(self, rng_seed: int = 42):
        g = nx.Graph()
        # Ingress -> API
        for api in (1, 2):
            g.add_edge(0, api)
            # API -> Registry
            for reg in (3, 4, 5):
                g.add_edge(api, reg)
        # Registry -> Cache
        for reg in (3, 4, 5):
            for cache in (6, 7):
                g.add_edge(reg, cache)
        # Cache -> DB
        for cache in (6, 7):
            for db in (8, 9):
                g.add_edge(cache, db)
        # DB -> Response sink
        for db in (8, 9):
            g.add_edge(db, 10)

        rng = np.random.default_rng(rng_seed)
        edge_caps = {}
        edge_loads = {}
        for u, v in g.edges():
            edge_caps[(u, v)] = 100.0
            edge_caps[(v, u)] = 100.0
            ld = float(rng.uniform(0.25, 0.45))
            edge_loads[(u, v)] = ld
            edge_loads[(v, u)] = ld

        # Ingress (0) and Egress (10) are virtual measurement endpoints; 1..9 are the 9 service components
        safety = SafetyConfig(
            min_bandwidth_ratio=0.40,
            drain_banned_nodes=frozenset(),
            reset_banned_nodes=frozenset({0, 10, 8}),  # Never restart primary Postgres DB!
            probe_banned_nodes=frozenset({0, 10}),
            mirror_filtered_nodes=frozenset({1, 2, 3, 4, 5}),
            mirror_unfiltered_only_nodes=frozenset(),
            mirror_banned_nodes=frozenset({0, 6, 7, 8, 9, 10}),
            external_blackbox_nodes=frozenset({0, 10}),
            enable_subtle_weight_shifts=True,
            enable_packet_mirror=False,
            enable_component_reset=True,
        )
        super().__init__(
            name="Microservices",
            graph=g,
            switch_nodes=list(range(0, 11)),
            rack_nodes=[0, 10],
            node_names=dict(self.COMPONENT_LABELS),
            edge_capacities=edge_caps,
            edge_loads=edge_loads,
            safety=safety,
            dlb_routing=False,
        )
