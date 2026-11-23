"""Game/session engine for the FaultFerence 2D Detective + Wordle game.

Wraps `fives` directly: samples a network fault case, lays out a collision-free
2D server room (with staggered cable sockets & wrapped long WAN chains), scopes
the suspect pool to interior switches, validates micro-actions against SafetyFilter,
supports live Bayesian <-> Set-Intersection hot-swap, and computes FIVES rankings.
"""

import json
import math
import os
import threading
import uuid
from typing import Dict, List, Optional, Sequence, Set, Tuple

import networkx as nx
import numpy as np

from fives import (
    ActiveProbe,
    ComponentReset,
    FailureMode,
    FailureSpec,
    FivesPlanner,
    FlowGroupSplit,
    FlowLinkDrain,
    FullLinkDrain,
    MultiOutcomeEfficacyEstimator,
    MultiRoundBayesianPGM,
    PacketMirror,
    Perturbation,
    SafetyConfig,
    SafetyFilter,
    SetIntersectionInference,
    SubtleWeightShift,
    TwoPhaseImpactEstimator,
    load_campus_prod_system,
    load_edgelist_network,
    run_episode,
)
from fives.inference import InferenceEngine
from fives.systems import NetworkSystem, TelemetryRecord, TelemetryWindow

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOPO_DIR = os.path.join(REPO_ROOT, "faultference", "topologies")
TESTBED_TOPO_DIR = os.path.join(REPO_ROOT, "testbed", "topologies")

TOPOLOGIES = {
    "Clos-k4": "fattree_k4.json",
    "PROD": "campus-str.edgelist",
    "B4": "B4.edgelist",
    "Expander-k10": "rg_deg10_sw125_svr250_os3.edgelist",
    "USCarrier": "UsC.edgelist",
    "Clos-k10": "ft_deg10_sw125_svr250_os3_bidir_false.edgelist",
}

FAILURE_MODES = {
    "silent_drop": FailureMode.SILENT_DROP,
    "blackhole": FailureMode.BLACKHOLE,
    "intermittent": FailureMode.INTERMITTENT,
    "high_latency": FailureMode.HIGH_LATENCY,
}

INFERENCE_MODES = (
    "flock",
    "flock_tr",
    "bayesian",
    "bayesian_tr",
    "set",
    "set_tr",
)

WEAPONS = (
    {"kind": "active_probe", "short": "Ping", "hint": "Test hops to DST", "target": "node"},
    {"kind": "packet_mirror", "short": "Tap", "hint": "Mirror switch", "target": "node"},
    {"kind": "subtle_weight_shift", "short": "Dial 20%", "hint": "Gentle traffic shift", "target": "edge"},
    {"kind": "flow_link_drain", "short": "Detour", "hint": "Reroute this flow", "target": "edge"},
    {"kind": "flow_group_split", "short": "Split", "hint": "Drain half branches", "target": "node"},
    {"kind": "full_link_drain", "short": "Shut Link", "hint": "Cut whole link", "target": "edge"},
    {"kind": "component_reset", "short": "Reboot", "hint": "Restart switch", "target": "node"},
)

FLOWS_PER_PAIR = 400
PACKETS_PER_FLOW = 25

_NET_CACHE: Dict[str, NetworkSystem] = {}
_NET_LOCK = threading.Lock()


class FlockSnapshotInference(InferenceEngine):
    """Single-snapshot passive Bayesian localizer (Flock, CoNEXT '19).

    Scores candidates on a single routing state (the latest window alone) under a
    fixed prior drop rate without cross-round exposure-normalized trajectory fusion.
    """

    def __init__(self, system: NetworkSystem, path_aware: bool, bg_noise_prob: float = 1.0e-4):
        self.system = system
        self.path_aware = path_aware
        self.bg_noise_prob = bg_noise_prob
        self.candidates: Tuple[int, ...] = ()
        self.log_post: np.ndarray = np.array([], dtype=np.float64)

    def reset(self, candidate_nodes: Sequence[int]) -> None:
        self.candidates = tuple(sorted(candidate_nodes))
        self.log_post = np.full(len(self.candidates), -math.log(len(self.candidates)), dtype=np.float64)

    @staticmethod
    def _binom_ll(k: int, n: int, p: float) -> float:
        pc = min(1.0 - 1.0e-12, max(1.0e-12, p))
        lc = math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)
        return lc + k * math.log(pc) + (n - k) * math.log(1.0 - pc)

    def update(self, window: TelemetryWindow) -> None:
        p_prior = 0.025
        ll = np.full(len(self.candidates), -math.log(len(self.candidates)), dtype=np.float64)
        for idx, node in enumerate(self.candidates):
            for r in window.records:
                if r.is_probe and self.path_aware and len(r.traced_path) > 0:
                    q = p_prior if node in r.traced_path else self.bg_noise_prob
                else:
                    hit_w = sum(w for path, w in r.path_weights if node in path)
                    q = hit_w * p_prior + (1.0 - hit_w) * self.bg_noise_prob
                ll[idx] += self._binom_ll(r.packets_bad, r.packets_sent, q)
        m = float(np.max(ll))
        lse = m + math.log(float(np.sum(np.exp(ll - m))))
        self.log_post = ll - lse

    def posteriors(self) -> Dict[int, float]:
        probs = np.exp(self.log_post)
        return {node: float(probs[i]) for i, node in enumerate(self.candidates)}

    def equivalence_set(self, cred_mass: float = 0.95) -> Set[int]:
        probs = np.exp(self.log_post)
        order = np.argsort(-probs)
        chosen: Set[int] = set()
        acc = 0.0
        last_lp = None
        for idx in order:
            lp_val = float(self.log_post[idx])
            if acc >= cred_mass and (last_lp is None or (last_lp - lp_val) > 0.05):
                break
            chosen.add(self.candidates[int(idx)])
            acc += float(probs[idx])
            last_lp = lp_val
        return chosen


class GameSetInference(SetIntersectionInference):
    """Extends SetIntersectionInference to also invert FlowGroupSplit & multi-probe gadget windows."""

    def update(self, window: TelemetryWindow) -> None:
        pert = window.perturbation
        if isinstance(pert, FlowGroupSplit):
            for rec in window.records:
                if rec.is_probe or rec.is_mirror:
                    continue
                base_r = self.baseline_bad_rate[rec.pair]
                if base_r <= 5.0 * self.bg_noise_prob:
                    continue
                curr_r = float(rec.packets_bad) / float(max(1, rec.packets_sent))
                active_nodes: Set[int] = set()
                for path, _ in rec.path_weights:
                    active_nodes.update(path)
                eliminated = curr_r <= max(3.0 * self.bg_noise_prob, 0.20 * base_r)
                next_set = (self.suspects - active_nodes) if eliminated else (self.suspects & active_nodes)
                if len(next_set) > 0:
                    self.suspects = next_set
            return
        probe_recs = [r for r in window.records if r.is_probe]
        if len(probe_recs) > 1:
            # Multi-probe gadget sweep (007 / NetBouncer): apply each probe record sequentially
            cur = set(self.suspects)
            for pr in probe_recs:
                use_trace = self.path_aware or (len(pr.traced_path) > 0 and pert is None)
                sub_nodes: Set[int] = set(pr.traced_path) if use_trace and len(pr.traced_path) > 0 else {
                    n for path, _ in pr.path_weights for n in path
                }
                failed = self._is_anomalous(pr)
                nxt = (cur & sub_nodes) if failed else (cur - sub_nodes)
                if len(nxt) > 0:
                    cur = nxt
            self.suspects = cur
            return
        super().update(window)


def _load_clos_k4(path: str, rng_seed: int = 42) -> NetworkSystem:
    """Load the 20-switch k=4 FatTree testbed topology with realistic tier constraints."""
    with open(path, "r") as fp:
        spec = json.load(fp)

    names = list(spec["vrfs"].keys())
    name_to_id = {nm: idx for idx, nm in enumerate(names)}
    id_to_name = {idx: nm for idx, nm in enumerate(names)}

    g = nx.Graph()
    for u_nm, v_nm in spec["links"]:
        g.add_edge(name_to_id[u_nm], name_to_id[v_nm])

    rng = np.random.default_rng(rng_seed)
    edge_caps: Dict[Tuple[int, int], float] = {}
    edge_loads: Dict[Tuple[int, int], float] = {}
    for u, v in g.edges():
        load = float(rng.uniform(0.22, 0.48))
        edge_caps[(u, v)] = 100.0
        edge_caps[(v, u)] = 100.0
        edge_loads[(u, v)] = load
        edge_loads[(v, u)] = load

    tors = [idx for idx, nm in id_to_name.items() if nm.startswith("tor")]
    aggs = [idx for idx, nm in id_to_name.items() if nm.startswith("agg")]
    cores = [idx for idx, nm in id_to_name.items() if nm.startswith("core")]

    safety = SafetyConfig(
        min_bandwidth_ratio=0.50,
        drain_banned_nodes=frozenset({name_to_id["core0"]}),
        reset_banned_nodes=frozenset(cores),
        probe_banned_nodes=frozenset(),
        mirror_filtered_nodes=frozenset(aggs),
        mirror_unfiltered_only_nodes=frozenset(),
        mirror_banned_nodes=frozenset(tors + cores),
        external_blackbox_nodes=frozenset(),
        enable_subtle_weight_shifts=True,
        enable_group_splits=True,
        enable_packet_mirror=True,
        enable_component_reset=True,
    )
    return NetworkSystem(
        name="Clos-k4",
        graph=g,
        switch_nodes=sorted(id_to_name.keys()),
        rack_nodes=sorted(tors),
        node_names=id_to_name,
        edge_capacities=edge_caps,
        edge_loads=edge_loads,
        safety=safety,
        dlb_routing=False,
    )


def get_network(name: str) -> NetworkSystem:
    with _NET_LOCK:
        if name not in _NET_CACHE:
            fname = TOPOLOGIES[name]
            if name == "Clos-k4":
                net = _load_clos_k4(os.path.join(TESTBED_TOPO_DIR, fname))
            elif name == "PROD":
                net = load_campus_prod_system(os.path.join(TOPO_DIR, fname))
            else:
                net = load_edgelist_network(os.path.join(TOPO_DIR, fname), name=name)
            _NET_CACHE[name] = net
        return _NET_CACHE[name]


def _name(net: NetworkSystem, n: int) -> str:
    raw = net.node_names[n] if n in net.node_names else f"sw-{n}"
    return raw[3:] if raw.startswith("bd-bd-") else raw


# --------------------------------------------------------------------------------------
# Perturbation <-> JSON (with human-friendly labels & 2D room anchors)
# --------------------------------------------------------------------------------------

def action_to_json(net: NetworkSystem, p: Perturbation, multi_pair: bool = False) -> Dict:
    d: Dict = {
        "kind": p.kind,
        "plane": p.plane.value,
        "raw_label": p.short_name(),
        "key": repr(p.key),
    }
    if isinstance(p, ActiveProbe):
        s_nm, d_nm = _name(net, p.src_node), _name(net, p.dst_node)
        pair_s = f" ({_name(net, p.flow_pair[0])}→{_name(net, p.flow_pair[1])})" if multi_pair else ""
        d["icon"] = "active_probe"
        d["title"] = f"Ping {s_nm} → {d_nm}"
        d["subtitle"] = f"Test hops to receiver{pair_s}"
        d["params"] = {"src": p.src_node, "dst": p.dst_node, "pair": list(p.flow_pair), "num_probes": p.num_probes}
        d["anchor"] = {"type": "node", "id": p.src_node}
        d["nodes"] = [p.src_node, p.dst_node]
        d["edges"] = []
    elif isinstance(p, PacketMirror):
        n_nm = _name(net, p.node)
        mode_s = "filtered" if p.filtered else "raw"
        pair_s = f" · {_name(net, p.flow_pair[0])}→{_name(net, p.flow_pair[1])}" if multi_pair else ""
        d["icon"] = "packet_mirror"
        d["title"] = f"Tap @ {n_nm}"
        d["subtitle"] = f"Check {mode_s} packets here{pair_s}"
        d["params"] = {"node": p.node, "filtered": p.filtered, "pair": list(p.flow_pair)}
        d["anchor"] = {"type": "node", "id": p.node}
        d["nodes"] = [p.node]
        d["edges"] = []
    elif isinstance(p, SubtleWeightShift):
        u_nm, v_nm = _name(net, p.u), _name(net, p.v)
        a, b = (p.u, p.v) if p.u < p.v else (p.v, p.u)
        d["icon"] = "subtle_weight_shift"
        d["title"] = f"Dial 20% {u_nm} → {v_nm}"
        d["subtitle"] = "Gently nudge 80% of flow elsewhere"
        d["params"] = {"u": p.u, "v": p.v, "w": p.weight_factor, "pair": list(p.flow_pair)}
        d["anchor"] = {"type": "edge", "u": a, "v": b}
        d["nodes"] = []
        d["edges"] = [[p.u, p.v]]
    elif isinstance(p, FlowLinkDrain):
        u_nm, v_nm = _name(net, p.u), _name(net, p.v)
        a, b = (p.u, p.v) if p.u < p.v else (p.v, p.u)
        d["icon"] = "flow_link_drain"
        d["title"] = f"Detour {u_nm} → {v_nm}"
        d["subtitle"] = "Move broken flow off this link"
        d["params"] = {"u": p.u, "v": p.v, "pair": list(p.flow_pair)}
        d["anchor"] = {"type": "edge", "u": a, "v": b}
        d["nodes"] = []
        d["edges"] = [[p.u, p.v]]
    elif isinstance(p, FlowGroupSplit):
        u_nm = _name(net, p.u)
        nh_names = ", ".join(_name(net, v) for v in p.drained_nexthops)
        d["icon"] = "flow_group_split"
        d["title"] = f"Split @ {u_nm}"
        d["subtitle"] = f"Drain half of branches ({nh_names})"
        d["params"] = {"u": p.u, "nexthops": list(p.drained_nexthops), "pair": list(p.flow_pair)}
        d["anchor"] = {"type": "node", "id": p.u}
        d["nodes"] = [p.u]
        d["edges"] = [[p.u, v] for v in p.drained_nexthops]
    elif isinstance(p, FullLinkDrain):
        u_nm, v_nm = _name(net, p.u), _name(net, p.v)
        a, b = (p.u, p.v) if p.u < p.v else (p.v, p.u)
        d["icon"] = "full_link_drain"
        d["title"] = f"Shut Link {u_nm} ↔ {v_nm}"
        d["subtitle"] = "Cut link for ALL traffic"
        d["params"] = {"u": p.u, "v": p.v}
        d["anchor"] = {"type": "edge", "u": a, "v": b}
        d["nodes"] = []
        d["edges"] = [[p.u, p.v]]
    elif isinstance(p, ComponentReset):
        n_nm = _name(net, p.node)
        d["icon"] = "component_reset"
        d["title"] = f"Reboot {n_nm}"
        d["subtitle"] = "Restart switch (heavy outage!)"
        d["params"] = {"node": p.node}
        d["anchor"] = {"type": "node", "id": p.node}
        d["nodes"] = [p.node]
        d["edges"] = []
    else:
        raise ValueError(f"Unknown perturbation {p}")
    return d


def action_from_json(d: Dict) -> Perturbation:
    k = d["kind"]
    a = d["params"]
    if k == "active_probe":
        return ActiveProbe(int(a["src"]), int(a["dst"]), (int(a["pair"][0]), int(a["pair"][1])), int(a["num_probes"]))
    if k == "packet_mirror":
        return PacketMirror(int(a["node"]), bool(a["filtered"]), (int(a["pair"][0]), int(a["pair"][1])))
    if k == "flow_link_drain":
        return FlowLinkDrain(int(a["u"]), int(a["v"]), (int(a["pair"][0]), int(a["pair"][1])))
    if k == "flow_group_split":
        return FlowGroupSplit(int(a["u"]), tuple(int(x) for x in a["nexthops"]), (int(a["pair"][0]), int(a["pair"][1])))
    if k == "subtle_weight_shift":
        return SubtleWeightShift(int(a["u"]), int(a["v"]), float(a["w"]), (int(a["pair"][0]), int(a["pair"][1])))
    if k == "full_link_drain":
        return FullLinkDrain(int(a["u"]), int(a["v"]))
    if k == "component_reset":
        return ComponentReset(int(a["node"]))
    raise ValueError(f"Unknown action kind {k}")


# --------------------------------------------------------------------------------------
# Constraint explanation (mirrors SafetyFilter.is_safe, asserted on every check)
# --------------------------------------------------------------------------------------

def violation_reason(net: NetworkSystem, p: Perturbation, pairs: Sequence[Tuple[int, int]]) -> Optional[str]:
    cfg = net.safety
    if isinstance(p, ActiveProbe):
        for n in (p.src_node, p.dst_node):
            if n in cfg.probe_banned_nodes:
                return f"No probe support on {_name(net, n)}"
            if n in cfg.external_blackbox_nodes:
                return f"External peer ({_name(net, n)})"
        if not net.check_no_branch(p.flow_pair, p.src_node, p.dst_node):
            return "Ping paths branch off flow"
        return None

    if isinstance(p, PacketMirror):
        if p.node in cfg.mirror_banned_nodes or p.node in cfg.external_blackbox_nodes:
            return f"No tap hardware on {_name(net, p.node)}"
        if p.filtered:
            return None if p.node in cfg.mirror_filtered_nodes else f"No filtered tap on {_name(net, p.node)}"
        if p.node not in cfg.mirror_unfiltered_only_nodes:
            return f"No raw tap on {_name(net, p.node)}"
        nbrs = list(net.G.neighbors(p.node))
        if len(nbrs) == 0:
            return "Isolated switch"
        mean_load = sum(net.edge_loads[(p.node, nb)] for nb in nbrs) / len(nbrs)
        if mean_load > cfg.max_unfiltered_mirror_load:
            return f"Too busy for raw tap ({mean_load:.0%} > {cfg.max_unfiltered_mirror_load:.0%})"
        return None

    if isinstance(p, (FlowLinkDrain, FlowGroupSplit)):
        touched = [p.u, p.v] if isinstance(p, FlowLinkDrain) else [p.u] + list(p.drained_nexthops)
        for n in touched:
            if n in cfg.drain_banned_nodes:
                return f"Protected switch ({_name(net, n)})"
            if n in cfg.external_blackbox_nodes:
                return f"External peer ({_name(net, n)})"
        base = net.shortest_paths(p.flow_pair[0], p.flow_pair[1])
        post = net.paths_under_perturbation(p.flow_pair, p)
        if len(post) == 0:
            return "Would cut all paths"
        ratio = len(post) / len(base)
        if ratio < cfg.min_bandwidth_ratio:
            return f"Drops capacity below {cfg.min_bandwidth_ratio:.0%}"
        return None

    if isinstance(p, SubtleWeightShift):
        for n in (p.u, p.v):
            if n in cfg.external_blackbox_nodes:
                return f"External peer ({_name(net, n)})"
        base = net.shortest_paths(p.flow_pair[0], p.flow_pair[1])
        if len(base) <= 1:
            return "Single path — can't shift"
        uses = sum(1 for path in base if any(path[i] == p.u and path[i + 1] == p.v for i in range(len(path) - 1)))
        if uses == 0 or uses == len(base):
            return "Shared bottleneck — shift is no-op"
        eff = (uses * p.weight_factor + (len(base) - uses)) / len(base)
        if eff < cfg.min_bandwidth_ratio:
            return f"Drops capacity below {cfg.min_bandwidth_ratio:.0%}"
        return None

    if isinstance(p, FullLinkDrain):
        for n in (p.u, p.v):
            if n in cfg.drain_banned_nodes:
                return f"Protected switch ({_name(net, n)})"
            if n in cfg.external_blackbox_nodes:
                return f"External peer ({_name(net, n)})"
        cap = net.edge_capacities[(p.u, p.v)]
        if cap <= cfg.min_bandwidth_ratio * 100.0:
            return "Link bundle already degraded"
        for pair in pairs:
            base = net.shortest_paths(pair[0], pair[1])
            post = net.paths_under_perturbation(pair, p)
            if len(post) == 0:
                return "Would cut active traffic"
            if post[0][0] in base and len(post) / len(base) < cfg.min_bandwidth_ratio:
                return f"Drops capacity below {cfg.min_bandwidth_ratio:.0%}"
        return None

    if isinstance(p, ComponentReset):
        if p.node in cfg.reset_banned_nodes:
            return f"Protected spine ({_name(net, p.node)})"
        if p.node in cfg.external_blackbox_nodes:
            return f"External peer ({_name(net, p.node)})"
        for pair in pairs:
            if p.node in pair:
                return f"Flow endpoint ({_name(net, p.node)})"
        if p.node in net._articulation_points:
            g = net.G.copy()
            g.remove_node(p.node)
            for pair in pairs:
                if not nx.has_path(g, pair[0], pair[1]):
                    return "Single point of failure"
        return None

    raise ValueError(f"Unknown perturbation {p}")


def check_action(net: NetworkSystem, safety: SafetyFilter, p: Perturbation, pairs) -> Optional[str]:
    reason = violation_reason(net, p, pairs)
    ok = safety.is_safe(p, pairs)
    assert (reason is None) == ok, f"violation_reason mismatch on {p}: reason={reason}, safe={ok}"
    return reason


# --------------------------------------------------------------------------------------
# Scenario sampling & collision-free 2D floorplan layout
# --------------------------------------------------------------------------------------

def sample_fault(
    net: NetworkSystem,
    rng: np.random.Generator,
    num_pairs: int,
) -> Tuple[Tuple[Tuple[int, int], ...], int]:
    racks = [r for r in net.rack_nodes if r not in net.safety.external_blackbox_nodes]
    # Aim for 5..15 interior suspects with <= 9 hop distance so rooms & Wordle columns fit crisply
    for max_pool, max_hops in ((17, 9), (60, 30)):
        for _ in range(1000):
            s = int(racks[int(rng.integers(0, len(racks)))])
            d = int(racks[int(rng.integers(0, len(racks)))])
            if s == d:
                continue
            paths = net.shortest_paths(s, d)
            if len(paths) < 2 or len(paths[0]) < 3 or len(paths[0]) > max_hops:
                continue
            interior = sorted({n for p in paths for n in p[1:-1]})
            if len(interior) < (3 if max_pool == 17 else 2):
                continue
            culprit = int(interior[int(rng.integers(0, len(interior)))])
            pairs = [(s, d)]
            for _ in range(300):
                if len(pairs) == num_pairs:
                    break
                s2 = int(racks[int(rng.integers(0, len(racks)))])
                d2 = int(racks[int(rng.integers(0, len(racks)))])
                if s2 != d2 and (s2, d2) not in pairs and any(culprit in p for p in net.shortest_paths(s2, d2)):
                    pairs.append((s2, d2))
            if len(pairs) < num_pairs:
                continue
            pool = {n for pair in pairs for p in net.shortest_paths(*pair) for n in p}
            if len(pool) <= max_pool:
                return tuple(pairs), culprit
    raise RuntimeError(f"Failed to sample a multi-path fault in {net.name}")


def compute_room_layout(
    net: NetworkSystem,
    room_nodes: Sequence[int],
    pairs: Sequence[Tuple[int, int]],
) -> Tuple[List[int], List[Tuple[int, int]], Dict[int, Tuple[float, float]], Dict[Tuple[int, int], float]]:
    """Lay out the active flow DAG cleanly with wrapped columns & staggered cable sockets."""
    nodes = sorted(room_nodes)
    node_set = set(nodes)
    dag_edges: Set[Tuple[int, int]] = set()
    for pair in pairs:
        for path in net.shortest_paths(*pair):
            for i in range(len(path) - 1):
                a, b = path[i], path[i + 1]
                if a in node_set and b in node_set:
                    dag_edges.add((a, b) if a < b else (b, a))
    sub = nx.Graph()
    sub.add_nodes_from(nodes)
    sub.add_edges_from(dag_edges)

    src = pairs[0][0]
    dist = nx.single_source_shortest_path_length(sub, src)
    layers: Dict[int, List[int]] = {}
    max_d = max(dist.values()) if len(dist) > 0 else 1
    for n in nodes:
        d = dist[n] if n in dist else max_d // 2
        if d not in layers:
            layers[d] = []
        layers[d].append(n)

    pos: Dict[int, Tuple[float, float]] = {}
    sorted_cols = sorted(layers.keys())
    total_cols = len(sorted_cols)
    # If > 8 hop columns (long WAN path), wrap into a 2-aisle U-turn so racks never crowd horizontally!
    wrap = total_cols > 8
    top_count = (total_cols + 1) // 2 if wrap else total_cols

    for col_idx, d in enumerate(sorted_cols):
        members = layers[d]
        if col_idx > 0:
            def bary(n: int) -> Tuple[float, int]:
                placed = [pos[nb][1] for nb in sub.neighbors(n) if nb in pos]
                mean_y = sum(placed) / len(placed) if len(placed) > 0 else 0.5
                return (mean_y, n)
            members.sort(key=bary)
        else:
            members.sort()

        if not wrap:
            x_raw = col_idx / float(max(1, total_cols - 1)) if total_cols > 1 else 0.5
            x_base = 0.12 + 0.76 * x_raw
            # Split oversize columns (> 8 switches, e.g. 25-core Clos) into sub-columns
            if len(members) <= 8:
                for row_idx, n in enumerate(members):
                    y_raw = (row_idx + 1) / float(len(members) + 1)
                    pos[n] = (x_base, 0.20 + 0.60 * y_raw)
            else:
                sub_cols = math.ceil(len(members) / 7.0)
                for m_idx, n in enumerate(members):
                    sc = m_idx % sub_cols
                    sr = m_idx // sub_cols
                    rows_in_sc = math.ceil((len(members) - sc) / float(sub_cols))
                    dx = (sc - (sub_cols - 1) / 2.0) * 0.065
                    y_raw = (sr + 1) / float(rows_in_sc + 1)
                    pos[n] = (min(0.90, max(0.10, x_base + dx)), 0.18 + 0.64 * y_raw)
        else:
            if col_idx < top_count:
                x = 0.12 + 0.76 * (col_idx / float(max(1, top_count - 1)))
                for row_idx, n in enumerate(members):
                    y = 0.16 + 0.26 * ((row_idx + 1) / float(len(members) + 1))
                    pos[n] = (x, y)
            else:
                bot_idx = col_idx - top_count
                bot_total = total_cols - top_count
                x_raw = 1.0 - (bot_idx / float(max(1, bot_total - 1))) if bot_total > 1 else 0.5
                x = 0.12 + 0.76 * x_raw
                for row_idx, n in enumerate(members):
                    y = 0.56 + 0.26 * ((row_idx + 1) / float(len(members) + 1))
                    pos[n] = (x, y)

    edges = sorted(dag_edges)
    # Assign non-colliding `socket_t` along each cable so crossing bipartite X-cables never share a socket!
    socket_t: Dict[Tuple[int, int], float] = {}
    placed_pts: List[Tuple[float, float]] = [(pos[n][0], pos[n][1]) for n in nodes]
    candidates_t = (0.50, 0.35, 0.65, 0.27, 0.73, 0.42, 0.58)
    for u, v in edges:
        ax, ay = pos[u]
        bx, by = pos[v]
        best_t = 0.50
        best_clear = -1.0
        for ct in candidates_t:
            px = ax + (bx - ax) * ct
            py = ay + (by - ay) * ct
            min_d = min(math.hypot(px - qx, py - qy) for qx, qy in placed_pts)
            if min_d > best_clear + 1.0e-6:
                best_clear = min_d
                best_t = ct
            if min_d >= 0.045:
                best_t = ct
                break
        socket_t[(u, v)] = round(best_t, 3)
        placed_pts.append((ax + (bx - ax) * best_t, ay + (by - ay) * best_t))

    return nodes, edges, pos, socket_t


def build_background_context(
    net: NetworkSystem,
    active_nodes: Sequence[int],
    active_pos: Dict[int, Tuple[float, float]],
    pairs: Sequence[Tuple[int, int]],
) -> Tuple[List[Dict], List[Dict]]:
    """Build active hosts (`host-a`, `host-b`) + greyed-out neighboring switches & hosts."""
    active_set = set(active_nodes)
    bg_nodes: List[Dict] = []
    bg_edges: List[Dict] = []
    coord_by_key: Dict[str, Tuple[float, float]] = {f"sw:{n}": active_pos[n] for n in active_nodes}

    # 1. Active endpoint hosts attached to each flow pair's SRC and DST ToRs
    src0, dst0 = pairs[0][0], pairs[0][1]
    sx, sy = active_pos[src0]
    dx, dy = active_pos[dst0]
    bg_nodes.append({"key": "host:a", "name": "host-a", "kind": "host", "active": True, "x": 0.01, "y": sy})
    coord_by_key["host:a"] = (0.01, sy)
    bg_edges.append({"a": "host:a", "b": f"sw:{src0}", "active": True})

    dst_x = 0.99 if dx > 0.5 else 0.01
    bg_nodes.append({"key": "host:b", "name": "host-b", "kind": "host", "active": True, "x": dst_x, "y": dy})
    coord_by_key["host:b"] = (dst_x, dy)
    bg_edges.append({"a": f"sw:{dst0}", "b": "host:b", "active": True})

    # 2. Sample up to 8 real off-path neighboring switches from `net.G`
    ring1 = sorted({nb for n in active_nodes for nb in net.G.neighbors(n) if nb not in active_set})
    ring2 = sorted({nb2 for nb in ring1 for nb2 in net.G.neighbors(nb) if nb2 not in active_set and nb2 not in ring1})
    cand_sw = (ring1 + ring2)[:8]

    # Sort candidate off-path switches by the mean x of their active neighbors
    def anchor_x(sw: int) -> float:
        act_nbs = [active_pos[nb][0] for nb in net.G.neighbors(sw) if nb in active_set]
        if len(act_nbs) > 0:
            return sum(act_nbs) / len(act_nbs)
        ring_nbs = [
            active_pos[nb2][0]
            for nb in net.G.neighbors(sw)
            for nb2 in net.G.neighbors(nb)
            if nb2 in active_set
        ]
        return sum(ring_nbs) / len(ring_nbs) if len(ring_nbs) > 0 else 0.5

    cand_sw.sort(key=lambda sw: (round(anchor_x(sw), 3), sw))
    top_sw = cand_sw[0::2]
    bot_sw = cand_sw[1::2]

    for idx, sw in enumerate(top_sw):
        bx = 0.16 + 0.68 * ((idx + 0.5) / max(1, len(top_sw)))
        by = 0.065
        k = f"sw:{sw}"
        bg_nodes.append({"key": k, "name": _name(net, sw), "kind": "switch", "active": False, "x": round(bx, 4), "y": by})
        coord_by_key[k] = (bx, by)

    for idx, sw in enumerate(bot_sw):
        # Leave x < 0.20 clear on the bottom-left for the Detective's Forensics Desk!
        bx = 0.24 + 0.64 * ((idx + 0.5) / max(1, len(bot_sw)))
        by = 0.925
        k = f"sw:{sw}"
        bg_nodes.append({"key": k, "name": _name(net, sw), "kind": "switch", "active": False, "x": round(bx, 4), "y": by})
        coord_by_key[k] = (bx, by)

    # Real topology links connecting bg_switches to active_nodes or each other
    chosen_bg_set = set(cand_sw)
    seen_e: Set[Tuple[str, str]] = set()
    for sw in cand_sw:
        # Keep up to 2 cleanest links per background switch so background stays airy
        nbs = [nb for nb in net.G.neighbors(sw) if nb in active_set or nb in chosen_bg_set]
        nbs.sort(key=lambda nb: abs(coord_by_key[f"sw:{sw}"][0] - coord_by_key[f"sw:{nb}"][0]))
        for nb in nbs[:2]:
            ka, kb = f"sw:{sw}", f"sw:{nb}"
            pair_k = (ka, kb) if ka < kb else (kb, ka)
            if pair_k not in seen_e:
                seen_e.add(pair_k)
                bg_edges.append({"a": ka, "b": kb, "active": False})

    # 3. Greyed-out neighboring hosts hanging off perimeter switches / outer ToRs
    rack_set = set(net.rack_nodes)
    host_attach = [sw for sw in cand_sw if sw in rack_set][:3]
    if len(host_attach) < 2:
        host_attach = cand_sw[:2]
    for h_i, sw in enumerate(host_attach):
        sx_b, sy_b = coord_by_key[f"sw:{sw}"]
        hx = max(0.02, sx_b - 0.09) if sx_b < 0.5 else min(0.98, sx_b + 0.09)
        hy = sy_b
        hk = f"host:bg{h_i + 1}"
        bg_nodes.append({"key": hk, "name": f"host-{h_i + 1}", "kind": "host", "active": False, "x": round(hx, 4), "y": round(hy, 4)})
        coord_by_key[hk] = (hx, hy)
        bg_edges.append({"a": hk, "b": f"sw:{sw}", "active": False})

    # Resolve coordinates onto bg_edges directly for zero-lookup canvas rendering
    resolved_edges = [
        {
            "x1": round(coord_by_key[e["a"]][0], 4),
            "y1": round(coord_by_key[e["a"]][1], 4),
            "x2": round(coord_by_key[e["b"]][0], 4),
            "y2": round(coord_by_key[e["b"]][1], 4),
            "active": e["active"],
        }
        for e in bg_edges
    ]
    return bg_nodes, resolved_edges


def _entropy_bits(post: Dict[int, float]) -> float:
    return -sum(p * math.log2(p) for p in post.values() if p > 1.0e-12)


def _make_engine(net: NetworkSystem, mode: str, duty_cycle: float) -> InferenceEngine:
    prior = 0.7 if duty_cycle < 1.0 else 1.0
    if mode in ("flock", "bayesian"):
        return MultiRoundBayesianPGM(net, path_aware=False, duty_cycle_prior=prior)
    if mode in ("flock_tr", "bayesian_tr"):
        return MultiRoundBayesianPGM(net, path_aware=True, duty_cycle_prior=prior)
    if mode == "set":
        return GameSetInference(net, path_aware=False)
    if mode == "set_tr":
        return GameSetInference(net, path_aware=True)
    raise ValueError(f"Unknown inference mode {mode}")


# --------------------------------------------------------------------------------------
# GameSession
# --------------------------------------------------------------------------------------

class GameSession:
    def __init__(
        self,
        topology: str,
        failure_mode: str,
        inference: str,
        seed: int,
        num_pairs: int,
        drop_prob: float,
        cred_mass: float,
    ):
        self.id = uuid.uuid4().hex[:12]
        self.lock = threading.Lock()
        self.topology = topology
        self.inference_mode = inference
        self.seed = seed
        self.cred_mass = cred_mass
        self.net = get_network(topology)
        self.safety = SafetyFilter(self.net)
        self.impact = TwoPhaseImpactEstimator(self.net)
        self.efficacy = MultiOutcomeEfficacyEstimator(self.net)

        sample_rng = np.random.default_rng(seed)
        pairs, culprit = sample_fault(self.net, sample_rng, num_pairs)
        mode = FAILURE_MODES[failure_mode]
        if mode == FailureMode.INTERMITTENT:
            self.failure = FailureSpec(mode, culprit, pairs, drop_prob=drop_prob, duty_cycle=0.65)
        elif mode == FailureMode.HIGH_LATENCY:
            self.failure = FailureSpec(
                mode,
                culprit,
                pairs,
                drop_prob=max(drop_prob, 0.08),
                latency_inflation_us=1000.0,
                latency_jitter_us=10.0,
                latency_threshold_us=37.19,
            )
        else:
            self.failure = FailureSpec(mode, culprit, pairs, drop_prob=drop_prob, duty_cycle=1.0)

        raw_room = sorted({n for pair in pairs for path in self.net.shortest_paths(*pair) for n in path})
        _, self.edges, self.pos, self.socket_t = compute_room_layout(self.net, raw_room, pairs)
        self.bg_nodes, self.bg_edges = build_background_context(self.net, raw_room, self.pos, pairs)
        self.nodes: List[int] = sorted(raw_room, key=lambda n: (round(self.pos[n][0], 4), round(self.pos[n][1], 4), n))
        endpoints = {n for pair in pairs for n in pair}
        # Only interior switches can be faulty (endpoints are measurement rack ToRs)
        self.pool: List[int] = [n for n in self.nodes if n not in endpoints]

        max_paths = max(len(self.net.shortest_paths(*pair)) for pair in pairs)
        self.flows_per_pair = max(FLOWS_PER_PAIR, 25 * max_paths)

        # Shared episode RNG seed so live FIVES #1 play matches FIVES Par on the same trajectory!
        self.rng = np.random.default_rng(seed + 1000)
        win0 = self.net.simulate_window(self.failure, None, self.rng, self.flows_per_pair, PACKETS_PER_FLOW)
        self.windows: List[TelemetryWindow] = [win0]
        self.raw_events: List[Dict] = [
            {
                "step": 0,
                "move_num": 0,
                "status": "observe",
                "action": None,
                "window_idx": 0,
                "time": 0.0,
                "disruption": 0.0,
                "fives_rank": None,
                "reason": None,
            }
        ]
        self.tried: Set[Tuple] = set()
        self.last_control_pert: Optional[Perturbation] = None
        self.n_actions = 0
        self.n_rejected = 0
        self.total_time = 0.0
        self.total_disruption = 0.0
        self.last_lambda = 0.5
        self.last_k = 1
        self.accused_node: Optional[int] = None

        self.engine: InferenceEngine = _make_engine(self.net, inference, self.failure.duty_cycle)
        self.eq_set: Set[int] = set()
        self.history: List[Dict] = []
        self._rebuild_inference()
        self.par = self._compute_fives_par()

    def _compute_fives_par(self) -> Dict:
        ppf = self._effective_packets_per_flow()
        flows_pp = self.flows_per_pair

        class _FlowAwareFivesPlanner(FivesPlanner):
            def _greedy_score(self, p, posteriors, active_pairs, expected_drop_prob) -> float:
                ig, pw = self.efficacy.mutual_information_and_pairs(
                    p, posteriors, active_pairs, expected_drop_prob=expected_drop_prob,
                    p_node_map=self._p_node_map, flows_per_pair=flows_pp, packets_per_flow=ppf,
                )
                if ig <= 1.0e-9 and pw <= 1.0e-9:
                    return 0.0
                cost = self.impact.estimate(p, expected_drop_prob=expected_drop_prob).scalar_cost(self.tradeoff_lambda)
                return (ig + 1.0e-3 * pw) / cost

        par_planner = _FlowAwareFivesPlanner(
            self.net, self.safety, self.impact, self.efficacy, tradeoff_lambda=0.5, lookahead_k=1
        )
        par_inf = MultiRoundBayesianPGM(
            self.net, path_aware=False, duty_cycle_prior=0.7 if self.failure.duty_cycle < 1.0 else 1.0
        )
        ep = run_episode(
            self.net,
            self.failure,
            par_planner,
            par_inf,
            self.impact,
            np.random.default_rng(self.seed + 1000),
            flows_per_pair=self.flows_per_pair,
            packets_per_flow=PACKETS_PER_FLOW,
            cred_mass=self.cred_mass,
            candidate_pool=self.pool,
        )
        return {
            "moves": ep.num_perturbations,
            "time_sec": ep.total_ttl_sec,
            "disruption": ep.total_disruption,
            "localized": len(ep.final_eq_set) == 1 and (self.failure.faulty_node in ep.final_eq_set),
        }

    def _rebuild_inference(self) -> None:
        self.engine = _make_engine(self.net, self.inference_mode, self.failure.duty_cycle)
        self.engine.reset(self.pool)
        built: List[Dict] = []
        curr_eq = set(self.pool)
        for ev in self.raw_events:
            before = set(curr_eq)
            if ev["status"] == "accuse":
                acc = ev["accused_node"]
                curr_eq = {acc}
                tel = []
                fault_act = True
            elif ev["window_idx"] is not None:
                win = self.windows[ev["window_idx"]]
                self.engine.update(win)
                curr_eq = set(self.engine.equivalence_set(cred_mass=self.cred_mass))
                tel = self._telemetry_json(win)
                fault_act = win.fault_was_active
            else:
                tel = []
                fault_act = True
            post_snap = self.engine.posteriors()
            if ev["status"] == "accuse":
                post_map = {str(n): (1.0 if n == ev["accused_node"] else 0.0) for n in self.pool}
            else:
                post_map = {str(n): round(post_snap[n], 4) if n in post_snap else 0.0 for n in self.pool}
            built.append(
                {
                    "step": ev["step"],
                    "move_num": ev["move_num"],
                    "status": ev["status"],
                    "action": ev["action"],
                    "reason": ev["reason"],
                    "note": ev["note"] if "note" in ev else None,
                    "telemetry": tel,
                    "fault_active": fault_act,
                    "eq_before": len(before),
                    "eq_after": len(curr_eq),
                    "eq_nodes": sorted(curr_eq),
                    "removed": sorted(before - curr_eq),
                    "posteriors": post_map,
                    "time": ev["time"],
                    "disruption": ev["disruption"],
                    "fives_rank": ev["fives_rank"],
                }
            )
        self.eq_set = curr_eq
        self.history = built

    def set_inference(self, mode: str) -> Dict:
        assert mode in INFERENCE_MODES, f"Invalid inference mode {mode}"
        self.inference_mode = mode
        self._rebuild_inference()
        return self.state_json()

    def _telemetry_json(self, win: TelemetryWindow) -> List[Dict]:
        out = []
        for r in win.records:
            kind = "probe" if r.is_probe else ("mirror" if r.is_mirror else "flow")
            out.append(
                {
                    "kind": kind,
                    "pair": list(r.pair),
                    "sent": r.packets_sent,
                    "bad": r.packets_bad,
                    "rate": r.packets_bad / max(1, r.packets_sent),
                    "traced_path": list(r.traced_path),
                }
            )
        return out

    def _est_drop(self) -> float:
        if isinstance(self.engine, MultiRoundBayesianPGM):
            return self.engine.estimated_drop_prob
        return self.failure.unit_bad_prob(True)

    def _status(self) -> str:
        if len(self.eq_set) == 1:
            return "localized" if self.failure.faulty_node in self.eq_set else "mislocalized"
        if self.failure.faulty_node not in self.eq_set:
            return "culprit_eliminated"
        return "playing"

    def _edge_flow_weights(self) -> Dict[Tuple[int, int], float]:
        weights: Dict[Tuple[int, int], float] = {e: 0.0 for e in self.edges}
        pairs = self.failure.affected_pairs
        for pair in pairs:
            pw = self.net.paths_under_perturbation(pair, self.last_control_pert)
            for path, w in pw:
                for i in range(len(path) - 1):
                    a, b = (path[i], path[i + 1]) if path[i] < path[i + 1] else (path[i + 1], path[i])
                    if (a, b) in weights:
                        weights[(a, b)] += w / float(len(pairs))
        return weights

    def stats(self) -> Dict:
        post = self.engine.posteriors()
        return {
            "actions": self.n_actions,
            "rejected": self.n_rejected,
            "time_sec": self.total_time,
            "disruption": self.total_disruption,
            "eq_size": len(self.eq_set),
            "initial_eq_size": self.history[0]["eq_after"],
            "pool_size": len(self.pool),
            "entropy_bits": _entropy_bits(post),
            "top_posterior": max(post.values()),
            "status": self._status(),
        }

    def state_json(self) -> Dict:
        net = self.net
        cfg = net.safety
        post = self.engine.posteriors()
        endpoints = {n for pair in self.failure.affected_pairs for n in pair}
        srcs = {pair[0] for pair in self.failure.affected_pairs}
        dsts = {pair[1] for pair in self.failure.affected_pairs}
        nodes = []
        for n in self.nodes:
            tags = []
            if n in cfg.drain_banned_nodes:
                tags.append("no-drain")
            if n in cfg.reset_banned_nodes:
                tags.append("no-reset")
            if n in cfg.probe_banned_nodes:
                tags.append("no-probe")
            if n in cfg.external_blackbox_nodes:
                tags.append("blackbox")
            role = "src" if n in srcs else ("dst" if n in dsts else "switch")
            nodes.append(
                {
                    "id": n,
                    "name": _name(net, n),
                    "role": role,
                    "is_endpoint": n in endpoints,
                    "in_pool": n in self.pool,
                    "x": self.pos[n][0],
                    "y": self.pos[n][1],
                    "suspect": n in self.eq_set,
                    "posterior": post[n] if n in post else 0.0,
                    "tags": tags,
                }
            )
        ew = self._edge_flow_weights()
        edges = [
            {
                "u": u,
                "v": v,
                "socket_t": self.socket_t[(u, v)],
                "flow_weight": round(ew[(u, v)], 4),
                "load": round(net.edge_loads[(u, v)], 3),
                "cap": round(net.edge_capacities[(u, v)], 1),
            }
            for u, v in self.edges
        ]
        anim_paths = []
        for pair in self.failure.affected_pairs:
            for path, w in net.paths_under_perturbation(pair, self.last_control_pert):
                if w > 1.0e-4:
                    anim_paths.append({"nodes": list(path), "weight": round(w, 4)})

        flow0 = [r for r in self.history[0]["telemetry"] if r["kind"] == "flow"]
        base_rate = sum(r["rate"] for r in flow0) / max(1, len(flow0))
        ruled_out_total = max(0, len(net.switch_nodes) - len(self.pool))

        return {
            "id": self.id,
            "topology": self.topology,
            "seed": self.seed,
            "inference": self.inference_mode,
            "baseline_loss_rate": round(base_rate, 5),
            "total_switches": len(net.switch_nodes),
            "ruled_out_off_path": ruled_out_total,
            "failure": {
                "mode": self.failure.mode.value,
                "culprit": self.failure.faulty_node,
                "culprit_name": _name(net, self.failure.faulty_node),
                "pairs": [[p[0], p[1]] for p in self.failure.affected_pairs],
                "pair_names": [[_name(net, p[0]), _name(net, p[1])] for p in self.failure.affected_pairs],
                "drop_prob": self.failure.drop_prob,
            },
            "nodes": nodes,
            "bg_nodes": self.bg_nodes,
            "bg_edges": self.bg_edges,
            "suspect_ids": list(self.pool),
            "edges": edges,
            "eq_set": sorted(self.eq_set),
            "stats": self.stats(),
            "par": self.par,
            "history": self.history,
        }

    # ---------------- candidate actions & execution ----------------
    def candidate_actions(self) -> List[Dict]:
        pairs = self.failure.affected_pairs
        multi = len(pairs) > 1
        cands = list(self.net.candidate_perturbations(pairs, set(self.pool)))
        seen = {p.key for p in cands}

        def add(p: Perturbation) -> None:
            if p.key not in seen:
                seen.add(p.key)
                cands.append(p)

        for pair in pairs:
            dst = pair[1]
            for n in self.nodes:
                if n != dst:
                    add(ActiveProbe(n, dst, pair))
                if self.net.safety.enable_packet_mirror and n not in pair:
                    filt = n not in self.net.safety.mirror_unfiltered_only_nodes
                    add(PacketMirror(n, filt, pair))
        if self.net.safety.enable_component_reset:
            for n in self.pool:
                add(ComponentReset(n))

        plane_order = {"telemetry": 0, "control": 1, "physical": 2}
        out = []
        for p in cands:
            d = action_to_json(self.net, p, multi_pair=multi)
            d["violation"] = check_action(self.net, self.safety, p, pairs)
            imp = self.impact.estimate(p, expected_drop_prob=self._est_drop())
            d["est_time"] = round(imp.total_time_sec, 2)
            d["est_disruption"] = round(imp.total_disruption, 3)
            d["tried"] = p.key in self.tried
            out.append(d)
        # Safe actions first on hotkeys 1..4, locked actions right below so players can inspect/test them
        out.sort(key=lambda d: (d["violation"] is not None, plane_order[d["plane"]], d["est_disruption"], d["title"]))
        return out

    def apply(self, action: Dict) -> Dict:
        if self._status() != "playing":
            return {"result": self.history[-1], "state": self.state_json()}

        p = action_from_json(action)
        pairs = self.failure.affected_pairs
        multi = len(pairs) > 1
        rank_info = self._fives_rank_of(p)
        reason = check_action(self.net, self.safety, p, pairs)
        step = len(self.raw_events)

        if reason is not None:
            self.n_rejected += 1
            ev = {
                "step": step,
                "move_num": self.n_actions,
                "status": "rejected",
                "action": action_to_json(self.net, p, multi_pair=multi),
                "window_idx": None,
                "time": 0.0,
                "disruption": 0.0,
                "fives_rank": rank_info,
                "reason": reason,
            }
            self.raw_events.append(ev)
            self._rebuild_inference()
            return {"result": self.history[-1], "state": self.state_json()}

        imp = self.impact.estimate(p, expected_drop_prob=self.failure.drop_prob)
        win = self.net.simulate_window(self.failure, p, self.rng, self.flows_per_pair, PACKETS_PER_FLOW)
        win_idx = len(self.windows)
        self.windows.append(win)
        self.tried.add(p.key)
        # Each perturbation rolls back after its observation window; reflect only the latest step's routing
        self.last_control_pert = p if p.plane.value == "control" else None
        self.n_actions += 1
        self.total_time += imp.total_time_sec
        self.total_disruption += imp.total_disruption

        ev = {
            "step": step,
            "move_num": self.n_actions,
            "status": "applied",
            "action": action_to_json(self.net, p, multi_pair=multi),
            "window_idx": win_idx,
            "time": round(imp.total_time_sec, 2),
            "disruption": round(imp.total_disruption, 3),
            "fives_rank": rank_info,
            "reason": None,
        }
        self.raw_events.append(ev)
        self._rebuild_inference()
        return {"result": self.history[-1], "state": self.state_json()}

    def run_gadget(self, gadget: str) -> Dict:
        """Execute a classic forensics investigation tool (Flock, 007, NetBouncer)."""
        if self._status() != "playing":
            return {"result": self.history[-1], "state": self.state_json()}

        step = len(self.raw_events)
        net = self.net
        cfg = net.safety
        pairs = self.failure.affected_pairs

        if gadget == "flock":
            # Passive log correlation at the Forensics Desk (zero live traffic disruption)
            tiers: Dict[float, List[str]] = {}
            for sw in sorted(self.eq_set):
                share = sum(
                    sum(w for path, w in net.paths_under_perturbation(pair, None) if sw in path)
                    for pair in pairs
                ) / float(len(pairs))
                key_s = round(share, 2)
                if key_s not in tiers:
                    tiers[key_s] = []
                tiers[key_s].append(_name(net, sw))
            tier_desc = " · ".join(
                f"{int(round(sh * 100))}% share: {', '.join(sws[:3])}{'…' if len(sws) > 3 else ''}"
                for sh, sws in sorted(tiers.items(), key=lambda x: -x[0])
            )
            note = f"Flock tied ({tier_desc}) — perturb to split"
            self.total_time += 1.5
            ev = {
                "step": step,
                "move_num": self.n_actions,
                "status": "gadget",
                "action": {
                    "kind": "flock",
                    "plane": "telemetry",
                    "icon": "flock",
                    "title": "Flock Log Scan",
                    "subtitle": "passive Bayesian correlation",
                    "anchor": {"type": "desk"},
                    "nodes": [],
                    "edges": [],
                },
                "window_idx": None,
                "time": 1.5,
                "disruption": 0.0,
                "fives_rank": None,
                "reason": None,
                "note": note,
            }
            self.raw_events.append(ev)
            self._rebuild_inference()
            return {"result": self.history[-1], "state": self.state_json()}

        if gadget == "007":
            # 007 (NSDI '18): host 5-tuple traceroutes on bad flows + hop-normalized voting
            blocked_nodes = [
                n for n in self.nodes if n in cfg.probe_banned_nodes or n in cfg.external_blackbox_nodes
            ]
            act_meta = {
                "kind": "gadget_007",
                "plane": "telemetry",
                "icon": "gadget_007",
                "title": "007 Traceroute Vote",
                "subtitle": "5-tuple traceroutes on dropped flows",
                "anchor": {"type": "desk"},
                "nodes": [],
                "edges": [],
            }
            if len(blocked_nodes) > 0:
                self.n_rejected += 1
                b_nm = _name(net, blocked_nodes[0])
                ev = {
                    "step": step,
                    "move_num": self.n_actions,
                    "status": "rejected",
                    "action": act_meta,
                    "window_idx": None,
                    "time": 0.0,
                    "disruption": 0.0,
                    "fives_rank": None,
                    "reason": f"Blocked: {b_nm} drops traceroutes",
                }
                self.raw_events.append(ev)
                self._rebuild_inference()
                return {"result": self.history[-1], "state": self.state_json()}

            fault_active = True
            if self.failure.mode == FailureMode.INTERMITTENT:
                fault_active = bool(self.rng.random() < self.failure.duty_cycle)

            recs: List[TelemetryRecord] = []
            votes: Dict[int, float] = {sw: 0.0 for sw in self.pool}
            traced_bad = 0
            for pair in pairs:
                base_paths = net.shortest_paths(pair[0], pair[1])
                n_paths = len(base_paths)
                samples_per_path = max(12, 48 // n_paths)
                for sp in base_paths:
                    hits = fault_active and (self.failure.faulty_node in sp)
                    p_bad = self.failure.unit_bad_prob(hits)
                    n_units = samples_per_path * self._effective_packets_per_flow()
                    k_bad = int(self.rng.binomial(n_units, p_bad))
                    if k_bad > 0:
                        traced_bad += k_bad
                        interior_hops = [n for n in sp[1:-1] if n in votes]
                        for h_sw in interior_hops:
                            votes[h_sw] += float(k_bad) / float(max(1, len(interior_hops)))
                    recs.append(
                        TelemetryRecord(
                            pair=pair,
                            is_probe=True,
                            is_mirror=False,
                            mirror_node=-1,
                            packets_sent=n_units,
                            packets_bad=k_bad,
                            path_weights=((sp, 1.0),),
                            traced_path=sp,
                        )
                    )

            win = TelemetryWindow(perturbation=None, records=tuple(recs), fault_was_active=fault_active)
            win_idx = len(self.windows)
            self.windows.append(win)
            self.last_control_pert = None
            self.n_actions += 1
            self.total_time += 6.0
            self.total_disruption += 0.30

            top_votes = sorted(votes.items(), key=lambda kv: -kv[1])[:2]
            if traced_bad == 0:
                note = "007: 0 bad flows this round"
            else:
                v_str = ", ".join(_name(net, sw) for sw, v in top_votes if v > 0)
                note = f"007 top votes: {v_str}"

            ev = {
                "step": step,
                "move_num": self.n_actions,
                "status": "applied",
                "action": act_meta,
                "window_idx": win_idx,
                "time": 6.0,
                "disruption": 0.30,
                "fives_rank": None,
                "reason": None,
                "note": note,
            }
            self.raw_events.append(ev)
            self._rebuild_inference()
            return {"result": self.history[-1], "state": self.state_json()}

        if gadget == "netbouncer":
            # NetBouncer (NSDI '19): IP-in-IP switch-bouncing sweep across all suspect switches
            act_meta = {
                "kind": "netbouncer",
                "plane": "telemetry",
                "icon": "netbouncer",
                "title": "NetBouncer Sweep",
                "subtitle": "IP-in-IP bounce off every suspect",
                "anchor": {"type": "desk"},
                "nodes": [],
                "edges": [],
            }
            blocked_nodes = [
                n for n in self.nodes if n in cfg.probe_banned_nodes or n in cfg.external_blackbox_nodes
            ]
            if self.topology in ("PROD", "B4", "USCarrier") or len(blocked_nodes) > 0:
                self.n_rejected += 1
                ev = {
                    "step": step,
                    "move_num": self.n_actions,
                    "status": "rejected",
                    "action": act_meta,
                    "window_idx": None,
                    "time": 0.0,
                    "disruption": 0.0,
                    "fives_rank": None,
                    "reason": "Blocked: no IP-in-IP bounce hardware",
                }
                self.raw_events.append(ev)
                self._rebuild_inference()
                return {"result": self.history[-1], "state": self.state_json()}

            fault_active = True
            if self.failure.mode == FailureMode.INTERMITTENT:
                fault_active = bool(self.rng.random() < self.failure.duty_cycle)

            targets = sorted(self.eq_set)
            src = pairs[0][0]
            recs = []
            hit_switches: List[str] = []
            for sw in targets:
                sub_paths = net.shortest_paths(src, sw)
                w = 1.0 / float(len(sub_paths))
                pw_sub = tuple((sp, w) for sp in sub_paths)
                chosen_sp = sub_paths[int(self.rng.integers(0, len(sub_paths)))]
                hits = fault_active and (self.failure.faulty_node in chosen_sp)
                k_bad = int(self.rng.binomial(200, self.failure.unit_bad_prob(hits)))
                if k_bad >= 2:
                    hit_switches.append(_name(net, sw))
                recs.append(
                    TelemetryRecord(
                        pair=pairs[0],
                        is_probe=True,
                        is_mirror=False,
                        mirror_node=-1,
                        packets_sent=200,
                        packets_bad=k_bad,
                        path_weights=pw_sub,
                        traced_path=chosen_sp,
                    )
                )

            step_t = round(3.5 * len(targets), 2)
            step_d = round(0.28 * len(targets), 3)
            win = TelemetryWindow(perturbation=None, records=tuple(recs), fault_was_active=fault_active)
            win_idx = len(self.windows)
            self.windows.append(win)
            self.last_control_pert = None
            self.n_actions += 1
            self.total_time += step_t
            self.total_disruption += step_d

            note = (
                f"Bounced {len(targets)} switches — drops on {', '.join(hit_switches[:3])}"
                if len(hit_switches) > 0
                else f"Bounced {len(targets)} switches — 0 drops"
            )
            ev = {
                "step": step,
                "move_num": self.n_actions,
                "status": "applied",
                "action": act_meta,
                "window_idx": win_idx,
                "time": step_t,
                "disruption": step_d,
                "fives_rank": None,
                "reason": None,
                "note": note,
            }
            self.raw_events.append(ev)
            self._rebuild_inference()
            return {"result": self.history[-1], "state": self.state_json()}

        raise ValueError(f"Unknown gadget '{gadget}'")

    def accuse(self, node_id: int) -> Dict:
        """Make a direct detective arrest on `node_id`."""
        if self._status() != "playing":
            return {"result": self.history[-1], "state": self.state_json()}
        assert node_id in self.pool, f"Node {node_id} is not an interior suspect"
        self.accused_node = node_id
        self.n_actions += 1
        step = len(self.raw_events)
        nm = _name(self.net, node_id)
        correct = node_id == self.failure.faulty_node
        ev = {
            "step": step,
            "move_num": self.n_actions,
            "status": "accuse",
            "accused_node": node_id,
            "action": {
                "kind": "accuse",
                "plane": "telemetry",
                "icon": "accuse",
                "title": f"Accuse {nm}",
                "subtitle": "final culprit arrest",
                "anchor": {"type": "node", "id": node_id},
                "nodes": [node_id],
                "edges": [],
            },
            "window_idx": None,
            "time": 0.0,
            "disruption": 0.0,
            "fives_rank": None,
            "reason": None,
            "note": f"Arrested {nm} — {'guilty!' if correct else 'innocent!'}",
        }
        self.raw_events.append(ev)
        self._rebuild_inference()
        return {"result": self.history[-1], "state": self.state_json()}

    # ---------------- FIVES inspector ----------------
    def _planner(self, tradeoff_lambda: float, k: int) -> FivesPlanner:
        pl = FivesPlanner(
            self.net,
            self.safety,
            self.impact,
            self.efficacy,
            tradeoff_lambda=tradeoff_lambda,
            lookahead_k=k,
        )
        if isinstance(self.engine, MultiRoundBayesianPGM):
            pl.set_node_drop_map(self.engine.node_drop_prob)
        return pl

    def _effective_packets_per_flow(self) -> int:
        # Flow-level modes (BLACKHOLE, HIGH_LATENCY) emit 1 observation unit per flow, not 25 packets
        if self.failure.mode in (FailureMode.BLACKHOLE, FailureMode.HIGH_LATENCY):
            return 1
        return PACKETS_PER_FLOW

    def _ranking(self, pl: FivesPlanner) -> List[Tuple[float, float, Perturbation]]:
        post = self.engine.posteriors()
        suspects = {c for c, pr in post.items() if pr > 1.0e-6}
        if len(suspects) <= 1:
            return []
        est = self._est_drop()
        pairs = self.failure.affected_pairs
        is_set_mode = self.inference_mode in ("set", "set_tr")
        ppf = self._effective_packets_per_flow()

        out: List[Tuple[float, float, Perturbation]] = []
        for p in pl._safe_candidates(suspects, pairs, self.tried):
            if is_set_mode and isinstance(p, SubtleWeightShift):
                continue
            ig, pairs_w = self.efficacy.mutual_information_and_pairs(
                p,
                post,
                pairs,
                expected_drop_prob=est,
                p_node_map=pl._p_node_map,
                flows_per_pair=self.flows_per_pair,
                packets_per_flow=ppf,
            )
            if ig <= 1.0e-9 and pairs_w <= 1.0e-9:
                sc = 0.0
            else:
                cost = self.impact.estimate(p, expected_drop_prob=est).scalar_cost(pl.tradeoff_lambda)
                sc = (ig + 1.0e-3 * pairs_w) / cost
            out.append((sc, ig, p))

        out.sort(key=lambda t: -t[0])
        if pl.lookahead_k > 1 and len(out) > 1:
            # Promote the k-step lookahead winner to #1 so badge, footsteps, and `Do #1` always match
            best_p, best_val = pl._lookahead_value(post, pairs, self.tried, est, pl.lookahead_k)
            if best_p is not None and not (is_set_mode and isinstance(best_p, SubtleWeightShift)):
                for idx, (sc, ig, q) in enumerate(out):
                    if q.key == best_p.key:
                        out.pop(idx)
                        out.insert(0, (max(best_val, out[0][0] + 1e-6) if len(out) > 0 else best_val, ig, q))
                        break
        return out

    def _fives_rank_of(self, p: Perturbation) -> Dict:
        ranking = self._ranking(self._planner(self.last_lambda, self.last_k))
        useful = [t for t in ranking if t[0] > 0.0]
        for i, (_, _, q) in enumerate(useful):
            if q.key == p.key:
                return {"rank": i + 1, "of": len(useful)}
        return {"rank": None, "of": len(useful)}

    def fives(self, tradeoff_lambda: float, k: int, top: int) -> Dict:
        self.last_lambda = tradeoff_lambda
        self.last_k = k
        pl = self._planner(tradeoff_lambda, k)
        ranking = [t for t in self._ranking(pl) if t[0] > 0.0]
        est = self._est_drop()
        multi = len(self.failure.affected_pairs) > 1
        rows = []
        for sc, ig, p in ranking[:top]:
            imp = self.impact.estimate(p, expected_drop_prob=est)
            d = action_to_json(self.net, p, multi_pair=multi)
            buckets = self.efficacy.partition_suspects(p, sorted(self.eq_set), self.failure.affected_pairs)
            part_sizes = sorted((len(g) for g in buckets.values()), reverse=True)
            part_groups = [
                [_name(self.net, s) for s in grp]
                for grp in sorted(buckets.values(), key=lambda g: -len(g))
            ]
            d.update(
                {
                    "score": round(sc, 3),
                    "info_gain_bits": round(ig, 3),
                    "est_time": round(imp.total_time_sec, 2),
                    "est_disruption": round(imp.total_disruption, 3),
                    "cost": round(imp.scalar_cost(tradeoff_lambda), 3),
                    "partition": part_sizes,
                    "partition_groups": part_groups,
                }
            )
            rows.append(d)
        best = rows[0] if len(rows) > 0 else None
        return {
            "lambda": tradeoff_lambda,
            "k": k,
            "est_drop_prob": est,
            "n_safe": len(ranking),
            "ranking": rows,
            "best": best,
        }


class SessionStore:
    def __init__(self, max_sessions: int = 64):
        self._sessions: Dict[str, GameSession] = {}
        self._order: List[str] = []
        self._lock = threading.Lock()
        self.max_sessions = max_sessions

    def add(self, s: GameSession) -> None:
        with self._lock:
            self._sessions[s.id] = s
            self._order.append(s.id)
            while len(self._order) > self.max_sessions:
                old = self._order.pop(0)
                del self._sessions[old]

    def get(self, sid: str) -> GameSession:
        with self._lock:
            return self._sessions[sid]
