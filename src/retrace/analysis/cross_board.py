"""
Cross-board pattern recognition for PCB reverse engineering.

Maintains a persistent knowledge base of subcircuit patterns seen across
multiple boards.  When a new board is presented, the engine searches for
subgraph-isomorphic matches against known patterns and annotates the board
with functional block labels.

Pattern representation
----------------------
A pattern is a small attributed graph:
  - Nodes: component roles (e.g. "LDO", "input_cap", "output_cap")
  - Edges: electrical connections between node pins

Matching strategy
-----------------
1. For each known pattern, enumerate all subsets of board components whose
   kind/attributes are compatible with the pattern's node types.
2. Verify edge conditions (trace connectivity or spatial proximity).
3. Score the match by (attribute similarity) × (confidence of detected traces).
4. Return ranked matches above a configurable threshold.

The knowledge base is stored as a plain Python dict and can be persisted to
JSON or pickle externally; this module carries no I/O.

No external dependencies beyond numpy.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Any

import numpy as np

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class BoardComponent:
    """A component instance on a board being analysed."""
    ref: str
    kind: str                           # 'ic', 'resistor', 'capacitor', 'diode', …
    pins: list[str]
    location: tuple[float, float]
    attributes: dict[str, Any] = field(default_factory=dict)
    # e.g. {"package": "SOT-23", "value": "10uF", "footprint": "0402"}


@dataclass
class BoardTrace:
    """A detected trace between two component-pins."""
    ref_a: str
    pin_a: str
    ref_b: str
    pin_b: str
    confidence: float = 1.0


@dataclass
class PatternNode:
    """One role within a subcircuit pattern."""
    role: str                           # e.g. "regulator", "input_cap"
    kind_options: list[str]             # acceptable component kinds
    required_pins: list[str] = field(default_factory=list)
    attribute_hints: dict[str, Any] = field(default_factory=dict)
    # e.g. {"value_range_uf": (0.1, 100)}


@dataclass
class PatternEdge:
    """A required electrical connection between two pattern roles."""
    role_a: str
    pin_a: str                          # pin name on role_a (or "" for any)
    role_b: str
    pin_b: str                          # pin name on role_b (or "" for any)
    required: bool = True               # False = preferred but not mandatory


@dataclass
class SubcircuitPattern:
    """
    A reusable subcircuit archetype stored in the knowledge base.

    Examples: LDO power supply, H-bridge motor driver, RC low-pass filter,
    crystal oscillator, RS-232 transceiver, …
    """
    name: str
    description: str
    nodes: list[PatternNode]
    edges: list[PatternEdge]
    seen_count: int = 0                 # how many boards this pattern appeared on
    confidence_sum: float = 0.0        # cumulative match confidence


@dataclass
class PatternMatch:
    """A detected instance of a known pattern on a board."""
    pattern_name: str
    description: str
    component_roles: dict[str, str]     # role -> component ref
    score: float                        # 0–1
    is_partial: bool                    # True if some optional edges missing


@dataclass
class BoardAnalysis:
    """Result of cross-board analysis for a single board."""
    matches: list[PatternMatch]
    novel_components: list[str]         # refs that matched no known pattern
    coverage: float                     # fraction of components in a match


# ---------------------------------------------------------------------------
# Built-in pattern definitions
# ---------------------------------------------------------------------------

def _builtin_patterns() -> list[SubcircuitPattern]:
    """Return a small library of common subcircuit patterns."""
    return [
        SubcircuitPattern(
            name="ldo_supply",
            description="LDO voltage regulator with input and output bypass caps",
            nodes=[
                PatternNode("ldo", ["ic", "regulator"], ["VIN", "GND", "VOUT"]),
                PatternNode("input_cap", ["capacitor"], ["1", "2"],
                            {"role_hint": "input_bypass"}),
                PatternNode("output_cap", ["capacitor"], ["1", "2"],
                            {"role_hint": "output_bypass"}),
            ],
            edges=[
                PatternEdge("ldo", "VIN", "input_cap", "", required=True),
                PatternEdge("ldo", "VOUT", "output_cap", "", required=True),
                PatternEdge("ldo", "GND", "input_cap", "", required=False),
                PatternEdge("ldo", "GND", "output_cap", "", required=False),
            ],
        ),
        SubcircuitPattern(
            name="rc_lowpass",
            description="First-order RC low-pass filter",
            nodes=[
                PatternNode("resistor", ["resistor"], ["A", "B", "1", "2"]),
                PatternNode("capacitor", ["capacitor"], ["1", "2"]),
            ],
            edges=[
                PatternEdge("resistor", "", "capacitor", "", required=True),
            ],
        ),
        SubcircuitPattern(
            name="decoupling_pair",
            description="Parallel bulk + ceramic decoupling cap pair",
            nodes=[
                PatternNode("bulk_cap", ["capacitor"], ["1", "2"],
                            {"role_hint": "bulk"}),
                PatternNode("ceramic_cap", ["capacitor"], ["1", "2"],
                            {"role_hint": "ceramic"}),
            ],
            edges=[
                PatternEdge("bulk_cap", "", "ceramic_cap", "", required=True),
            ],
        ),
        SubcircuitPattern(
            name="pull_up_resistor",
            description="Pull-up resistor from VCC to a signal line",
            nodes=[
                PatternNode("resistor", ["resistor"], ["A", "B", "1", "2"]),
            ],
            edges=[],  # single-node pattern; matched by pin-net heuristic
        ),
        SubcircuitPattern(
            name="crystal_oscillator",
            description="Crystal with two load capacitors",
            nodes=[
                PatternNode("crystal", ["crystal", "resonator", "ic"], []),
                PatternNode("cap_a", ["capacitor"], ["1", "2"]),
                PatternNode("cap_b", ["capacitor"], ["1", "2"]),
            ],
            edges=[
                PatternEdge("crystal", "", "cap_a", "", required=True),
                PatternEdge("crystal", "", "cap_b", "", required=True),
            ],
        ),
        SubcircuitPattern(
            name="buck_converter",
            description="Switching buck regulator: IC + inductor + output cap + catch diode",
            nodes=[
                PatternNode("regulator_ic", ["ic", "regulator"], [],
                            {"role_hint": "switching_regulator"}),
                PatternNode("inductor", ["inductor", "ferrite"], [],
                            {"role_hint": "power_inductor"}),
                PatternNode("output_cap", ["capacitor"], ["1", "2"],
                            {"role_hint": "output_filter"}),
                PatternNode("catch_diode", ["diode"], [],
                            {"role_hint": "schottky_catch"}),
            ],
            edges=[
                PatternEdge("regulator_ic", "", "inductor", "", required=True),
                PatternEdge("inductor", "", "output_cap", "", required=True),
                PatternEdge("regulator_ic", "", "catch_diode", "", required=True),
                PatternEdge("output_cap", "", "catch_diode", "", required=False),
            ],
        ),
        SubcircuitPattern(
            name="usb_esd_protection",
            description="ESD diode array protecting USB data lines near connector",
            nodes=[
                PatternNode("esd_array", ["ic", "diode"], [],
                            {"role_hint": "esd_tvs"}),
                PatternNode("usb_connector", ["connector", "ic"], [],
                            {"role_hint": "usb_connector"}),
            ],
            edges=[
                PatternEdge("usb_connector", "", "esd_array", "", required=True),
            ],
        ),
        SubcircuitPattern(
            name="i2c_pullup_pair",
            description="Matched pull-up resistors on I2C SDA and SCL lines",
            nodes=[
                PatternNode("sda_pullup", ["resistor"], ["A", "B", "1", "2"],
                            {"role_hint": "sda_pullup"}),
                PatternNode("scl_pullup", ["resistor"], ["A", "B", "1", "2"],
                            {"role_hint": "scl_pullup"}),
            ],
            edges=[
                PatternEdge("sda_pullup", "", "scl_pullup", "", required=True),
            ],
        ),
        SubcircuitPattern(
            name="spi_flash_circuit",
            description="SPI NOR flash with decoupling cap and CS pull-up",
            nodes=[
                PatternNode("flash_ic", ["ic", "flash"], [],
                            {"role_hint": "spi_flash"}),
                PatternNode("decoupling_cap", ["capacitor"], ["1", "2"],
                            {"role_hint": "vcc_decoupling"}),
                PatternNode("cs_pullup", ["resistor"], ["A", "B", "1", "2"],
                            {"role_hint": "cs_pullup"}),
            ],
            edges=[
                PatternEdge("flash_ic", "", "decoupling_cap", "", required=True),
                PatternEdge("flash_ic", "", "cs_pullup", "", required=True),
                PatternEdge("decoupling_cap", "", "cs_pullup", "", required=False),
            ],
        ),
        SubcircuitPattern(
            name="uart_level_shifter",
            description="Level-shift IC between MCU UART and external connector",
            nodes=[
                PatternNode("level_shift_ic", ["ic"], [],
                            {"role_hint": "level_shifter"}),
                PatternNode("connector", ["connector", "ic"], [],
                            {"role_hint": "uart_connector"}),
            ],
            edges=[
                PatternEdge("level_shift_ic", "", "connector", "", required=True),
            ],
        ),
        SubcircuitPattern(
            name="h_bridge",
            description="H-bridge motor driver: 4 FETs/transistors for bidirectional motor control",
            nodes=[
                PatternNode("high_side_a", ["ic", "transistor", "mosfet"], [],
                            {"role_hint": "high_side_switch"}),
                PatternNode("low_side_a", ["ic", "transistor", "mosfet"], [],
                            {"role_hint": "low_side_switch"}),
                PatternNode("high_side_b", ["ic", "transistor", "mosfet"], [],
                            {"role_hint": "high_side_switch"}),
                PatternNode("low_side_b", ["ic", "transistor", "mosfet"], [],
                            {"role_hint": "low_side_switch"}),
            ],
            edges=[
                PatternEdge("high_side_a", "", "low_side_a", "", required=True),
                PatternEdge("high_side_b", "", "low_side_b", "", required=True),
                PatternEdge("high_side_a", "", "high_side_b", "", required=False),
                PatternEdge("low_side_a", "", "low_side_b", "", required=False),
            ],
        ),
        SubcircuitPattern(
            name="reset_circuit",
            description="RC network on MCU reset pin (power-on reset delay)",
            nodes=[
                PatternNode("reset_resistor", ["resistor"], ["A", "B", "1", "2"],
                            {"role_hint": "reset_pullup"}),
                PatternNode("reset_cap", ["capacitor"], ["1", "2"],
                            {"role_hint": "reset_filter"}),
            ],
            edges=[
                PatternEdge("reset_resistor", "", "reset_cap", "", required=True),
            ],
        ),
        SubcircuitPattern(
            name="usb_connector_circuit",
            description="USB connector with ESD protection, series resistors, and decoupling",
            nodes=[
                PatternNode("usb_conn", ["connector", "ic"], [],
                            {"role_hint": "usb_connector"}),
                PatternNode("dp_resistor", ["resistor"], ["A", "B", "1", "2"],
                            {"role_hint": "usb_dp_series"}),
                PatternNode("dm_resistor", ["resistor"], ["A", "B", "1", "2"],
                            {"role_hint": "usb_dm_series"}),
                PatternNode("decoupling_cap", ["capacitor"], ["1", "2"],
                            {"role_hint": "vbus_decoupling"}),
            ],
            edges=[
                PatternEdge("usb_conn", "", "dp_resistor", "", required=True),
                PatternEdge("usb_conn", "", "dm_resistor", "", required=True),
                PatternEdge("usb_conn", "", "decoupling_cap", "", required=False),
                PatternEdge("dp_resistor", "", "dm_resistor", "", required=False),
            ],
        ),
        SubcircuitPattern(
            name="differential_pair_termination",
            description="Matched termination resistors on a differential signal pair",
            nodes=[
                PatternNode("term_resistor_p", ["resistor"], ["A", "B", "1", "2"],
                            {"role_hint": "diff_p_term"}),
                PatternNode("term_resistor_n", ["resistor"], ["A", "B", "1", "2"],
                            {"role_hint": "diff_n_term"}),
            ],
            edges=[
                PatternEdge("term_resistor_p", "", "term_resistor_n", "", required=True),
            ],
        ),
        SubcircuitPattern(
            name="power_indicator_led",
            description="LED with current-limiting resistor on a power rail",
            nodes=[
                PatternNode("led", ["led", "diode"], [],
                            {"role_hint": "indicator_led"}),
                PatternNode("current_resistor", ["resistor"], ["A", "B", "1", "2"],
                            {"role_hint": "current_limit"}),
            ],
            edges=[
                PatternEdge("current_resistor", "", "led", "", required=True),
            ],
        ),
    ]


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class CrossBoardEngine:
    """
    Cross-board pattern recognition engine.

    Workflow
    --------
    1. Instantiate (optionally load a saved knowledge base).
    2. Call ``analyse(components, traces)`` for each new board.
    3. Optionally call ``record_pattern(pattern)`` to add novel patterns.
    4. Export / import state via ``to_dict()`` / ``from_dict()``.

    Parameters
    ----------
    match_threshold : float
        Minimum score (0–1) to report a match.
    proximity_px : float
        Max pixel distance to treat two components as electrically adjacent
        even without an explicit trace (spatial edge heuristic).
    """

    def __init__(
        self,
        match_threshold: float = 0.5,
        proximity_px: float = 80.0,
    ) -> None:
        self._threshold = match_threshold
        self._proximity = proximity_px
        self._patterns: list[SubcircuitPattern] = _builtin_patterns()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyse(
        self,
        components: list[BoardComponent],
        traces: list[BoardTrace],
    ) -> BoardAnalysis:
        """
        Search for known patterns in the board and return matches.

        Parameters
        ----------
        components : list[BoardComponent]
        traces : list[BoardTrace]

        Returns
        -------
        BoardAnalysis
        """
        adjacency = self._build_adjacency(components, traces)
        all_matches: list[PatternMatch] = []
        matched_refs: set[str] = set()

        for pattern in self._patterns:
            matches = self._match_pattern(pattern, components, adjacency)
            for m in matches:
                all_matches.append(m)
                matched_refs.update(m.component_roles.values())
                # Update pattern statistics
                pattern.seen_count += 1
                pattern.confidence_sum += m.score

        # Deduplicate: if a component appears in multiple matches, prefer highest score
        all_matches = self._deduplicate(all_matches)
        all_matches.sort(key=lambda m: m.score, reverse=True)

        novel = [c.ref for c in components if c.ref not in matched_refs]
        coverage = len(matched_refs) / max(len(components), 1)

        return BoardAnalysis(
            matches=all_matches,
            novel_components=novel,
            coverage=coverage,
        )

    def record_pattern(self, pattern: SubcircuitPattern) -> None:
        """Add or replace a pattern in the knowledge base."""
        for i, existing in enumerate(self._patterns):
            if existing.name == pattern.name:
                self._patterns[i] = pattern
                return
        self._patterns.append(pattern)

    def list_patterns(self) -> list[str]:
        """Return names of all known patterns."""
        return [p.name for p in self._patterns]

    def pattern_stats(self) -> dict[str, dict[str, Any]]:
        """Return seen_count and mean confidence for each pattern."""
        out: dict[str, dict[str, Any]] = {}
        for p in self._patterns:
            mean_conf = p.confidence_sum / p.seen_count if p.seen_count > 0 else 0.0
            out[p.name] = {
                "seen_count": p.seen_count,
                "mean_confidence": round(mean_conf, 4),
                "description": p.description,
            }
        return out

    def to_dict(self) -> dict[str, Any]:
        """Serialise knowledge base to a plain dict (JSON-serialisable)."""
        def pat_to_d(p: SubcircuitPattern) -> dict:
            return {
                "name": p.name,
                "description": p.description,
                "seen_count": p.seen_count,
                "confidence_sum": p.confidence_sum,
                "nodes": [
                    {
                        "role": n.role,
                        "kind_options": n.kind_options,
                        "required_pins": n.required_pins,
                        "attribute_hints": n.attribute_hints,
                    }
                    for n in p.nodes
                ],
                "edges": [
                    {
                        "role_a": e.role_a, "pin_a": e.pin_a,
                        "role_b": e.role_b, "pin_b": e.pin_b,
                        "required": e.required,
                    }
                    for e in p.edges
                ],
            }
        return {"patterns": [pat_to_d(p) for p in self._patterns]}

    @classmethod
    def from_dict(cls: type[CrossBoardEngine], data: dict[str, Any], **kwargs: Any) -> CrossBoardEngine:
        """Restore a CrossBoardEngine from a serialised dict."""
        engine = cls(**kwargs)
        engine._patterns = []
        for pd in data.get("patterns", []):
            nodes = [
                PatternNode(
                    role=n["role"],
                    kind_options=n["kind_options"],
                    required_pins=n.get("required_pins", []),
                    attribute_hints=n.get("attribute_hints", {}),
                )
                for n in pd["nodes"]
            ]
            edges = [
                PatternEdge(
                    role_a=e["role_a"], pin_a=e["pin_a"],
                    role_b=e["role_b"], pin_b=e["pin_b"],
                    required=e.get("required", True),
                )
                for e in pd["edges"]
            ]
            engine._patterns.append(SubcircuitPattern(
                name=pd["name"],
                description=pd["description"],
                nodes=nodes,
                edges=edges,
                seen_count=pd.get("seen_count", 0),
                confidence_sum=pd.get("confidence_sum", 0.0),
            ))
        return engine

    # ------------------------------------------------------------------
    # Internal matching
    # ------------------------------------------------------------------

    def _build_adjacency(
        self,
        components: list[BoardComponent],
        traces: list[BoardTrace],
    ) -> dict[str, set[str]]:
        """
        Build adjacency: ref -> set of refs connected by trace or proximity.
        """
        adj: dict[str, set[str]] = {c.ref: set() for c in components}

        # Trace-based adjacency
        for t in traces:
            if t.confidence >= 0.4:
                adj[t.ref_a].add(t.ref_b)
                adj[t.ref_b].add(t.ref_a)

        # Proximity-based adjacency
        locs = {c.ref: np.array(c.location) for c in components}
        refs = list(locs.keys())
        for i, ra in enumerate(refs):
            for rb in refs[i + 1:]:
                dist = float(np.linalg.norm(locs[ra] - locs[rb]))
                if dist <= self._proximity:
                    adj[ra].add(rb)
                    adj[rb].add(ra)

        return adj

    def _match_pattern(
        self,
        pattern: SubcircuitPattern,
        components: list[BoardComponent],
        adjacency: dict[str, set[str]],
    ) -> list[PatternMatch]:
        """
        Find all instances of `pattern` in the board component graph.

        Uses exhaustive enumeration for patterns with <= 6 nodes.
        For larger patterns a greedy approach is used.
        """
        n_roles = len(pattern.nodes)
        if n_roles == 0:
            return []

        # Candidate components per role
        candidates_per_role: dict[str, list[BoardComponent]] = {}
        for pnode in pattern.nodes:
            cands = [
                c for c in components
                if c.kind.lower() in [k.lower() for k in pnode.kind_options]
                or pnode.kind_options == []
            ]
            candidates_per_role[pnode.role] = cands

        roles = [pn.role for pn in pattern.nodes]
        matches: list[PatternMatch] = []

        # Generate all candidate assignments
        candidate_lists = [candidates_per_role[r] for r in roles]
        if any(len(cl) == 0 for cl in candidate_lists):
            return []

        # Cap combinatorial explosion: skip if too many candidates
        total_combos = 1
        for cl in candidate_lists:
            total_combos *= len(cl)
        if total_combos > 10_000:
            # Prune: only use the n closest candidates per role
            candidate_lists = [cl[:4] for cl in candidate_lists]

        for combo in itertools.product(*candidate_lists):
            refs = [c.ref for c in combo]
            # Reject if the same component assigned to two roles
            if len(set(refs)) < len(refs):
                continue

            role_assignment: dict[str, str] = {
                roles[i]: combo[i].ref for i in range(len(roles))
            }
            score, is_partial = self._score_assignment(
                pattern, role_assignment, adjacency
            )
            if score >= self._threshold:
                matches.append(PatternMatch(
                    pattern_name=pattern.name,
                    description=pattern.description,
                    component_roles=role_assignment,
                    score=score,
                    is_partial=is_partial,
                ))

        return matches

    def _score_assignment(
        self,
        pattern: SubcircuitPattern,
        role_assignment: dict[str, str],
        adjacency: dict[str, set[str]],
    ) -> tuple[float, bool]:
        """
        Score a candidate role assignment.

        Returns (score 0–1, is_partial).
        """
        required_edges = [e for e in pattern.edges if e.required]
        optional_edges = [e for e in pattern.edges if not e.required]

        req_satisfied = 0
        for edge in required_edges:
            ref_a = role_assignment.get(edge.role_a)
            ref_b = role_assignment.get(edge.role_b)
            if ref_a and ref_b and ref_b in adjacency.get(ref_a, set()):
                req_satisfied += 1

        if required_edges and req_satisfied < len(required_edges):
            # Allow partial match only if >= 50% required edges satisfied
            ratio = req_satisfied / len(required_edges)
            if ratio < 0.5:
                return 0.0, True

        opt_satisfied = sum(
            1 for e in optional_edges
            if role_assignment.get(e.role_a) and role_assignment.get(e.role_b)
            and role_assignment[e.role_b] in adjacency.get(role_assignment[e.role_a], set())
        )

        total_edges = len(required_edges) + len(optional_edges)
        edge_score = (req_satisfied + opt_satisfied) / max(total_edges, 1)

        # Boost for single-node patterns (no edges to satisfy)
        if total_edges == 0:
            edge_score = 0.7

        is_partial = req_satisfied < len(required_edges)
        return float(np.clip(edge_score, 0.0, 1.0)), is_partial

    def _deduplicate(self, matches: list[PatternMatch]) -> list[PatternMatch]:
        """
        Remove duplicate matches: if two matches of the same pattern share all
        components, keep only the higher-scored one.
        """
        seen: dict[tuple[str, frozenset[str]], PatternMatch] = {}
        for m in matches:
            key = (m.pattern_name, frozenset(m.component_roles.values()))
            if key not in seen or m.score > seen[key].score:
                seen[key] = m
        return list(seen.values())


# ---------------------------------------------------------------------------
# CLI / standalone demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover
    print("CrossBoardEngine — standalone demo")

    engine = CrossBoardEngine(match_threshold=0.4, proximity_px=80.0)
    print(f"Known patterns: {engine.list_patterns()}")

    # Simulate board 1: LDO supply + RC filter
    comps_b1 = [
        BoardComponent("U1", "ic", ["VIN", "GND", "VOUT"], (100.0, 100.0)),
        BoardComponent("C1", "capacitor", ["1", "2"], (130.0, 90.0)),   # input bypass
        BoardComponent("C2", "capacitor", ["1", "2"], (70.0, 110.0)),   # output bypass
        BoardComponent("R1", "resistor", ["A", "B"], (300.0, 200.0)),
        BoardComponent("C3", "capacitor", ["1", "2"], (340.0, 195.0)),  # RC cap
    ]
    traces_b1 = [
        BoardTrace("U1", "VIN", "C1", "1", 0.9),
        BoardTrace("U1", "VOUT", "C2", "1", 0.85),
        BoardTrace("R1", "B", "C3", "1", 0.92),
    ]

    result1 = engine.analyse(comps_b1, traces_b1)
    print(f"\nBoard 1 — {len(result1.matches)} matches, coverage={result1.coverage:.0%}")
    for m in result1.matches:
        roles_str = ", ".join(f"{r}={c}" for r, c in m.component_roles.items())
        partial_tag = " [partial]" if m.is_partial else ""
        print(f"  [{m.score:.2f}] {m.pattern_name}{partial_tag}: {roles_str}")
    print(f"  Novel: {result1.novel_components}")

    # Simulate board 2: same LDO topology but different refs
    comps_b2 = [
        BoardComponent("VR1", "ic", ["VIN", "GND", "VOUT"], (200.0, 150.0)),
        BoardComponent("CA1", "capacitor", ["1", "2"], (230.0, 140.0)),
        BoardComponent("CB1", "capacitor", ["1", "2"], (170.0, 160.0)),
        BoardComponent("Q1", "ic", ["B", "C", "E"], (400.0, 300.0)),  # novel
    ]
    traces_b2 = [
        BoardTrace("VR1", "VIN", "CA1", "1", 0.88),
        BoardTrace("VR1", "VOUT", "CB1", "1", 0.91),
    ]

    result2 = engine.analyse(comps_b2, traces_b2)
    print(f"\nBoard 2 — {len(result2.matches)} matches, coverage={result2.coverage:.0%}")
    for m in result2.matches:
        roles_str = ", ".join(f"{r}={c}" for r, c in m.component_roles.items())
        print(f"  [{m.score:.2f}] {m.pattern_name}: {roles_str}")
    print(f"  Novel: {result2.novel_components}")

    print("\nPattern knowledge base stats:")
    for name, stats in engine.pattern_stats().items():
        if stats["seen_count"] > 0:
            print(f"  {name}: seen={stats['seen_count']}, mean_conf={stats['mean_confidence']:.3f}")

    # Round-trip serialisation
    d = engine.to_dict()
    engine2 = CrossBoardEngine.from_dict(d)
    print(f"\nRestored engine has {len(engine2.list_patterns())} patterns.")


# ── Cross-Board Lineage ──────────────────────────────────────────


def compute_board_similarity(
    comps_a: list[BoardComponent],
    comps_b: list[BoardComponent],
) -> float:
    """Compute weighted Jaccard similarity between two boards.

    IC part numbers and markings are weighted 2× relative to passives.
    Fuzzy matching (SequenceMatcher ≥ 0.7) is used for IC markings.
    """
    from difflib import SequenceMatcher

    if not comps_a or not comps_b:
        return 0.0

    def _sig(c: BoardComponent) -> tuple[str, str]:
        pn = c.attributes.get("part_number", "") if c.attributes else ""
        return (c.kind, pn)

    sigs_a = {_sig(c) for c in comps_a if _sig(c)[1]}
    sigs_b = {_sig(c) for c in comps_b if _sig(c)[1]}

    if not sigs_a and not sigs_b:
        kinds_a = {c.kind for c in comps_a}
        kinds_b = {c.kind for c in comps_b}
        union = kinds_a | kinds_b
        if not union:
            return 0.0
        return len(kinds_a & kinds_b) / len(union)

    ic_markings_a = [c.attributes.get("marking", "") for c in comps_a
                     if c.kind == "ic" and c.attributes.get("marking")]
    ic_markings_b = [c.attributes.get("marking", "") for c in comps_b
                     if c.kind == "ic" and c.attributes.get("marking")]

    exact_inter = len(sigs_a & sigs_b)
    exact_union = len(sigs_a | sigs_b)

    fuzzy_matches = 0
    used_b: set[int] = set()
    for ma in ic_markings_a:
        for j, mb in enumerate(ic_markings_b):
            if j in used_b:
                continue
            if SequenceMatcher(None, ma.lower(), mb.lower()).ratio() >= 0.7:
                fuzzy_matches += 1
                used_b.add(j)
                break

    ic_weight = 2.0
    passive_inter = max(0, exact_inter - fuzzy_matches)
    weighted_inter = passive_inter + fuzzy_matches * ic_weight
    weighted_union = max(1, exact_union + fuzzy_matches * (ic_weight - 1))

    return min(1.0, weighted_inter / weighted_union)


def build_lineage_tree(
    boards: dict[str, list[BoardComponent]],
    threshold: float = 0.15,
) -> list[tuple[str, str, float]]:
    """Build a lineage tree from multiple boards.

    Returns (board_a, board_b, similarity) tuples sorted by similarity
    descending.  Only includes pairs with similarity >= threshold.
    """
    names = list(boards.keys())
    edges: list[tuple[str, str, float]] = []

    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            sim = compute_board_similarity(boards[names[i]], boards[names[j]])
            if sim >= threshold:
                edges.append((names[i], names[j], sim))

    edges.sort(key=lambda e: e[2], reverse=True)
    return edges
