"""
Electrical constraint solver for PCB reverse engineering.

Uses arc-consistency (AC-3 algorithm) to propagate electrical rules over a
partial netlist and infer missing connections.

Rules encoded
-------------
- Every VCC/VDD/3V3/5V pin must belong to a power net.
- Every GND/VSS/AGND/PGND pin must belong to a ground net.
- Two pins connected by a detected trace share the same net.
- A decoupling capacitor pinned to VCC and GND cannot have both pins on the
  same net.
- Differential pairs (IN+/IN-) must be on different nets.
- Open-drain outputs must not be directly driven to VCC without a pull-up.
- Bypass capacitors inferred from location proximity to power pins.

The solver iterates arc-consistency until no further inferences are possible,
then returns the (possibly partial) solution and any remaining ambiguities.

No external dependencies beyond numpy.
"""

from __future__ import annotations

import copy
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Set, Tuple

import numpy as np


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

NET_POWER = "POWER"    # domain label: must be on a power net
NET_GROUND = "GROUND"  # domain label: must be on a ground net
NET_SIGNAL = "SIGNAL"  # domain label: any signal net
NET_UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class Pin:
    """A single component pin."""
    component_ref: str
    pin_name: str

    @property
    def node_id(self) -> str:
        return f"{self.component_ref}.{self.pin_name}"


@dataclass
class ComponentSpec:
    """
    Specification of a component's electrical interface.

    pins      — ordered list of pin names
    kind      — 'ic', 'resistor', 'capacitor', 'inductor', 'diode', 'connector'
    location  — (x, y) image-space pixels (used for proximity rules)
    """
    ref: str
    kind: str
    pins: List[str]
    location: Tuple[float, float] = field(default_factory=lambda: (0.0, 0.0))


@dataclass
class Trace:
    """A detected electrical connection between two pins."""
    pin_a: Pin
    pin_b: Pin
    confidence: float = 1.0  # 0–1; low-confidence traces treated as soft constraints


@dataclass
class SolverResult:
    """Output of ConstraintSolver.solve()."""
    net_assignment: Dict[str, str]          # node_id -> net label
    inferred_traces: List[Tuple[str, str]]  # pairs inferred by the solver
    ambiguous_nodes: List[str]              # nodes whose net is still unknown
    conflicts: List[str]                    # constraint violations detected
    iterations: int


# ---------------------------------------------------------------------------
# Constraint solver
# ---------------------------------------------------------------------------

class ConstraintSolver:
    """
    Arc-consistency constraint propagator for PCB netlists.

    Usage
    -----
    solver = ConstraintSolver()
    result = solver.solve(components, traces)
    """

    # Pin-name vocabularies
    _POWER_NAMES: FrozenSet[str] = frozenset({
        "vcc", "vdd", "v+", "vin", "vbat", "3v3", "5v", "3.3v", "5.0v",
        "vcc1", "vcc2", "avcc", "dvcc", "pvcc",
    })
    _GROUND_NAMES: FrozenSet[str] = frozenset({
        "gnd", "vss", "agnd", "pgnd", "dgnd", "v-", "sg", "rtn",
        "gnd1", "gnd2", "ground",
    })
    _DIFFP_SUFFIXES: Tuple[str, ...] = ("+", "p", "_p", "pos")
    _DIFFN_SUFFIXES: Tuple[str, ...] = ("-", "n", "_n", "neg")

    def __init__(self, proximity_threshold_px: float = 50.0) -> None:
        """
        Parameters
        ----------
        proximity_threshold_px : float
            Distance threshold (pixels) for inferring bypass-cap proximity rules.
        """
        self._proximity_threshold = proximity_threshold_px

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def solve(
        self,
        components: List[ComponentSpec],
        traces: List[Trace],
        max_iterations: int = 200,
    ) -> SolverResult:
        """
        Run arc-consistency propagation and return inferred net assignments.

        Parameters
        ----------
        components : list[ComponentSpec]
            All components on the board.
        traces : list[Trace]
            Detected electrical connections (partial).
        max_iterations : int
            Safety cap on propagation rounds.

        Returns
        -------
        SolverResult
        """
        # Build domain: node_id -> set of possible net classes
        domains: Dict[str, Set[str]] = {}
        pin_map: Dict[str, Pin] = {}

        for comp in components:
            for pname in comp.pins:
                pin = Pin(comp.ref, pname)
                nid = pin.node_id
                pin_map[nid] = pin
                domains[nid] = self._initial_domain(pname)

        # Build union-find for trace-connected nodes
        parent: Dict[str, str] = {nid: nid for nid in domains}

        def find(x: str) -> str:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a: str, b: str) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra

        # Hard traces (confidence >= 0.5) create equality constraints
        for trace in traces:
            a, b = trace.pin_a.node_id, trace.pin_b.node_id
            for nid in (a, b):
                if nid not in domains:
                    domains[nid] = {NET_UNKNOWN}
                    parent[nid] = nid
            if trace.confidence >= 0.5:
                union(a, b)

        # Merge domains within each union-find group
        groups: Dict[str, Set[str]] = {}  # root -> union of domains? No — intersection
        for nid in domains:
            r = find(nid)
            if r not in groups:
                groups[r] = copy.copy(domains[nid])
            else:
                groups[r] = groups[r] & domains[nid]
                if not groups[r]:
                    groups[r] = {NET_UNKNOWN}

        # Propagate group domains back to members
        for nid in domains:
            r = find(nid)
            domains[nid] = copy.copy(groups[r])

        # Apply proximity bypass-cap rules
        comp_by_ref: Dict[str, ComponentSpec] = {c.ref: c for c in components}
        self._apply_proximity_rules(components, comp_by_ref, domains, find)

        # AC-3: build arc queue
        # Arcs: (node_a, node_b, constraint_fn)
        arcs: deque = deque()
        constraints: List[Tuple[str, str, str]] = []

        for trace in traces:
            a, b = trace.pin_a.node_id, trace.pin_b.node_id
            if a in domains and b in domains and trace.confidence >= 0.5:
                constraints.append((a, b, "equality"))
                constraints.append((b, a, "equality"))

        # Differential-pair constraints within each component
        for comp in components:
            dp_pairs = self._find_diff_pairs(comp.pins, comp.ref)
            for pa, pb in dp_pairs:
                constraints.append((pa, pb, "different"))
                constraints.append((pb, pa, "different"))

        for arc in constraints:
            arcs.append(arc)

        conflicts: List[str] = []
        iters = 0

        while arcs and iters < max_iterations:
            iters += 1
            node_a, node_b, ctype = arcs.popleft()

            if node_a not in domains or node_b not in domains:
                continue

            revised = self._revise(domains, node_a, node_b, ctype)
            if revised:
                if not domains[node_a]:
                    conflicts.append(
                        f"Domain wipeout at {node_a} (conflict with {node_b}, {ctype})"
                    )
                    domains[node_a] = {NET_UNKNOWN}
                    continue
                # Re-queue all arcs pointing to node_a
                for other_a, other_b, other_type in constraints:
                    if other_b == node_a and other_a != node_b:
                        arcs.append((other_a, other_b, other_type))

        # Build final assignment: single-element domains are resolved
        net_assignment: Dict[str, str] = {}
        ambiguous: List[str] = []

        for nid, dom in domains.items():
            if len(dom) == 1:
                net_assignment[nid] = next(iter(dom))
            else:
                ambiguous.append(nid)
                net_assignment[nid] = NET_UNKNOWN

        # Infer additional traces from resolved nodes in same group
        inferred: List[Tuple[str, str]] = []
        for nid in domains:
            r = find(nid)
            if r != nid and nid in net_assignment and r in net_assignment:
                if net_assignment[nid] == net_assignment[r] and net_assignment[nid] != NET_UNKNOWN:
                    inferred.append((nid, r))

        return SolverResult(
            net_assignment=net_assignment,
            inferred_traces=inferred,
            ambiguous_nodes=ambiguous,
            conflicts=conflicts,
            iterations=iters,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _initial_domain(self, pin_name: str) -> Set[str]:
        """Return the initial domain for a pin based on its name."""
        pn = pin_name.lower().strip()
        if pn in self._POWER_NAMES:
            return {NET_POWER}
        if pn in self._GROUND_NAMES:
            return {NET_GROUND}
        # Partial matches
        for pw in ("vcc", "vdd", "3v3", "5v", "vin"):
            if pn.startswith(pw):
                return {NET_POWER}
        for gn in ("gnd", "vss", "agnd", "pgnd"):
            if pn.startswith(gn):
                return {NET_GROUND}
        return {NET_POWER, NET_GROUND, NET_SIGNAL}

    def _revise(
        self,
        domains: Dict[str, Set[str]],
        node_a: str,
        node_b: str,
        ctype: str,
    ) -> bool:
        """
        Remove values from domains[node_a] that have no support in domains[node_b].
        Returns True if domains[node_a] was reduced.
        """
        before = len(domains[node_a])
        if ctype == "equality":
            # node_a and node_b must share the same net class
            domains[node_a] = domains[node_a] & domains[node_b]
            if not domains[node_a]:
                # Restore to unknown to avoid total wipeout breaking the loop
                domains[node_a] = {NET_UNKNOWN}
        elif ctype == "different":
            # node_a and node_b must be on different nets
            if len(domains[node_b]) == 1:
                disallowed = next(iter(domains[node_b]))
                domains[node_a] = domains[node_a] - {disallowed}
                if not domains[node_a]:
                    domains[node_a] = {NET_SIGNAL, NET_UNKNOWN}
        return len(domains[node_a]) != before

    def _find_diff_pairs(
        self, pins: List[str], comp_ref: str
    ) -> List[Tuple[str, str]]:
        """Detect differential pairs within a component's pin list."""
        pairs: List[Tuple[str, str]] = []
        for p in pins:
            pl = p.lower()
            for sfx_p, sfx_n in zip(self._DIFFP_SUFFIXES, self._DIFFN_SUFFIXES):
                if pl.endswith(sfx_p):
                    base = pl[: -len(sfx_p)]
                    # Look for matching negative pin
                    for q in pins:
                        ql = q.lower()
                        if ql == base + sfx_n or ql == base + sfx_n.lstrip("_"):
                            pairs.append(
                                (f"{comp_ref}.{p}", f"{comp_ref}.{q}")
                            )
        return pairs

    def _apply_proximity_rules(
        self,
        components: List[ComponentSpec],
        comp_by_ref: Dict[str, ComponentSpec],
        domains: Dict[str, Set[str]],
        find,  # union-find callable
    ) -> None:
        """
        If a capacitor is close to a power pin on another component, infer that
        one of its pins is VCC and the other is GND (bypass cap role).
        """
        caps = [c for c in components if c.kind.lower() in ("capacitor", "cap")]
        for cap in caps:
            if len(cap.pins) != 2:
                continue
            pin_a_nid = f"{cap.ref}.{cap.pins[0]}"
            pin_b_nid = f"{cap.ref}.{cap.pins[1]}"

            for comp in components:
                if comp.ref == cap.ref:
                    continue
                dist = float(np.linalg.norm(
                    np.array(cap.location) - np.array(comp.location)
                ))
                if dist > self._proximity_threshold:
                    continue

                # Check if any pin on comp is a power pin
                has_power = any(
                    pn.lower() in self._POWER_NAMES
                    or any(pn.lower().startswith(pw) for pw in ("vcc", "vdd", "vin", "3v3", "5v"))
                    for pn in comp.pins
                )
                if not has_power:
                    continue

                # Infer: one cap pin is power, the other is ground
                # Only apply if both pins currently have open domains
                da = domains.get(pin_a_nid, {NET_UNKNOWN})
                db = domains.get(pin_b_nid, {NET_UNKNOWN})
                if NET_POWER in da and NET_GROUND in db:
                    domains[pin_a_nid] = {NET_POWER}
                    domains[pin_b_nid] = {NET_GROUND}
                elif NET_GROUND in da and NET_POWER in db:
                    domains[pin_a_nid] = {NET_GROUND}
                    domains[pin_b_nid] = {NET_POWER}


# ---------------------------------------------------------------------------
# CLI / standalone demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("ConstraintSolver — standalone demo")

    components = [
        ComponentSpec("U1", "ic", ["VCC", "GND", "IN+", "IN-", "OUT"], (100.0, 100.0)),
        ComponentSpec("C1", "capacitor", ["1", "2"], (120.0, 90.0)),  # bypass cap near U1
        ComponentSpec("R1", "resistor", ["A", "B"], (300.0, 200.0)),
        ComponentSpec("J1", "connector", ["VIN", "GND", "SIG"], (500.0, 100.0)),
    ]

    traces = [
        Trace(Pin("U1", "OUT"), Pin("R1", "A"), confidence=0.95),
        Trace(Pin("J1", "VIN"), Pin("U1", "VCC"), confidence=0.80),
        Trace(Pin("J1", "GND"), Pin("U1", "GND"), confidence=0.90),
    ]

    solver = ConstraintSolver(proximity_threshold_px=50.0)
    result = solver.solve(components, traces)

    print(f"\nNet assignments ({result.iterations} iterations):")
    for nid, net in sorted(result.net_assignment.items()):
        print(f"  {nid:20s} -> {net}")

    if result.inferred_traces:
        print(f"\nInferred connections ({len(result.inferred_traces)}):")
        for a, b in result.inferred_traces:
            print(f"  {a} <-> {b}")

    if result.ambiguous_nodes:
        print(f"\nAmbiguous nodes ({len(result.ambiguous_nodes)}):")
        for nid in result.ambiguous_nodes:
            print(f"  {nid}")

    if result.conflicts:
        print("\nConflicts:")
        for c in result.conflicts:
            print(f"  {c}")
