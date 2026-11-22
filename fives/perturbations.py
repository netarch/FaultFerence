"""Three-plane perturbation taxonomy and concrete perturbation primitives."""

from dataclasses import dataclass
from enum import Enum
from typing import Tuple


class PerturbationPlane(Enum):
    TELEMETRY = "telemetry"
    CONTROL = "control"
    PHYSICAL = "physical"


@dataclass(frozen=True)
class Perturbation:
    plane: PerturbationPlane
    kind: str
    key: Tuple

    def short_name(self) -> str:
        raise NotImplementedError


@dataclass(frozen=True)
class ActiveProbe(Perturbation):
    """Switch-to-switch or switch-to-rack 5-tuple spoofed active probe."""

    src_node: int
    dst_node: int
    flow_pair: Tuple[int, int]
    num_probes: int

    def __init__(self, src_node: int, dst_node: int, flow_pair: Tuple[int, int], num_probes: int = 200):
        object.__setattr__(self, "plane", PerturbationPlane.TELEMETRY)
        object.__setattr__(self, "kind", "active_probe")
        object.__setattr__(self, "key", ("active_probe", src_node, dst_node, flow_pair))
        object.__setattr__(self, "src_node", src_node)
        object.__setattr__(self, "dst_node", dst_node)
        object.__setattr__(self, "flow_pair", flow_pair)
        object.__setattr__(self, "num_probes", num_probes)

    def short_name(self) -> str:
        return f"Probe({self.src_node}->{self.dst_node}, pair={self.flow_pair})"


@dataclass(frozen=True)
class PacketMirror(Perturbation):
    """Filtered or unfiltered packet mirroring / ACL hit counter on a component."""

    node: int
    filtered: bool
    flow_pair: Tuple[int, int]

    def __init__(self, node: int, filtered: bool, flow_pair: Tuple[int, int]):
        object.__setattr__(self, "plane", PerturbationPlane.TELEMETRY)
        object.__setattr__(self, "kind", "packet_mirror")
        object.__setattr__(self, "key", ("packet_mirror", node, filtered, flow_pair))
        object.__setattr__(self, "node", node)
        object.__setattr__(self, "filtered", filtered)
        object.__setattr__(self, "flow_pair", flow_pair)

    def short_name(self) -> str:
        mode = "filt" if self.filtered else "raw"
        return f"Mirror({self.node}, {mode})"


@dataclass(frozen=True)
class FlowLinkDrain(Perturbation):
    """Flow-scoped control rule removing directed hop (u, v) for specific flow pair(s)."""

    u: int
    v: int
    flow_pair: Tuple[int, int]

    def __init__(self, u: int, v: int, flow_pair: Tuple[int, int]):
        object.__setattr__(self, "plane", PerturbationPlane.CONTROL)
        object.__setattr__(self, "kind", "flow_link_drain")
        object.__setattr__(self, "key", ("flow_link_drain", u, v, flow_pair))
        object.__setattr__(self, "u", u)
        object.__setattr__(self, "v", v)
        object.__setattr__(self, "flow_pair", flow_pair)

    def short_name(self) -> str:
        return f"FlowDrain({self.u}->{self.v}, pair={self.flow_pair})"


@dataclass(frozen=True)
class FlowGroupSplit(Perturbation):
    """Prefix-scoped WCMP/PBR next-hop-group override draining a subset of next-hops at `u`."""

    u: int
    drained_nexthops: Tuple[int, ...]
    flow_pair: Tuple[int, int]

    def __init__(self, u: int, drained_nexthops: Tuple[int, ...], flow_pair: Tuple[int, int]):
        nh_sorted = tuple(sorted(set(drained_nexthops)))
        assert len(nh_sorted) >= 2
        object.__setattr__(self, "plane", PerturbationPlane.CONTROL)
        object.__setattr__(self, "kind", "flow_group_split")
        object.__setattr__(self, "key", ("flow_group_split", u, nh_sorted, flow_pair))
        object.__setattr__(self, "u", u)
        object.__setattr__(self, "drained_nexthops", nh_sorted)
        object.__setattr__(self, "flow_pair", flow_pair)

    def short_name(self) -> str:
        return f"GroupSplit({self.u}->!{list(self.drained_nexthops)}, pair={self.flow_pair})"


@dataclass(frozen=True)
class SubtleWeightShift(Perturbation):
    """Subtle control perturbation scaling next-hop / replica weight by factor in (0, 1)."""

    u: int
    v: int
    weight_factor: float
    flow_pair: Tuple[int, int]

    def __init__(self, u: int, v: int, weight_factor: float, flow_pair: Tuple[int, int]):
        assert 0.0 < weight_factor < 1.0
        object.__setattr__(self, "plane", PerturbationPlane.CONTROL)
        object.__setattr__(self, "kind", "subtle_weight_shift")
        object.__setattr__(self, "key", ("subtle_weight_shift", u, v, round(weight_factor, 3), flow_pair))
        object.__setattr__(self, "u", u)
        object.__setattr__(self, "v", v)
        object.__setattr__(self, "weight_factor", weight_factor)
        object.__setattr__(self, "flow_pair", flow_pair)

    def short_name(self) -> str:
        return f"WeightShift({self.u}->{self.v}, w={self.weight_factor:.2f})"


@dataclass(frozen=True)
class FullLinkDrain(Perturbation):
    """Global link drain / IGP cost-out rerouting all transit traffic across (u, v)."""

    u: int
    v: int

    def __init__(self, u: int, v: int):
        a, b = (u, v) if u < v else (v, u)
        object.__setattr__(self, "plane", PerturbationPlane.CONTROL)
        object.__setattr__(self, "kind", "full_link_drain")
        object.__setattr__(self, "key", ("full_link_drain", a, b))
        object.__setattr__(self, "u", u)
        object.__setattr__(self, "v", v)

    def short_name(self) -> str:
        return f"FullDrain({self.u}<->{self.v})"


@dataclass(frozen=True)
class ComponentReset(Perturbation):
    """Physical/state perturbation rebooting, resetting, or swapping component `node`."""

    node: int

    def __init__(self, node: int):
        object.__setattr__(self, "plane", PerturbationPlane.PHYSICAL)
        object.__setattr__(self, "kind", "component_reset")
        object.__setattr__(self, "key", ("component_reset", node))
        object.__setattr__(self, "node", node)

    def short_name(self) -> str:
        return f"Reset({self.node})"
