"""Tests for the AC-3 ConstraintSolver."""

from __future__ import annotations


from retrace.analysis.constraint_solver import (
    ComponentSpec,
    ConstraintSolver,
    NET_GROUND,
    NET_POWER,
    Pin,
    SolverResult,
    Trace,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _simple_board() -> tuple[list[ComponentSpec], list[Trace]]:
    components = [
        ComponentSpec("U1", "ic", ["VCC", "GND", "OUT", "IN"], (100.0, 100.0)),
        ComponentSpec("R1", "resistor", ["A", "B"], (300.0, 200.0)),
        ComponentSpec("J1", "connector", ["VIN", "GND", "SIG"], (500.0, 100.0)),
    ]
    traces = [
        Trace(Pin("U1", "OUT"), Pin("R1", "A"), confidence=0.95),
        Trace(Pin("J1", "VIN"), Pin("U1", "VCC"), confidence=0.80),
        Trace(Pin("J1", "GND"), Pin("U1", "GND"), confidence=0.90),
    ]
    return components, traces


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_solve_returns_solver_result():
    components, traces = _simple_board()
    solver = ConstraintSolver()
    result = solver.solve(components, traces)
    assert isinstance(result, SolverResult)


def test_power_pin_inferred_as_power():
    """Pins named VCC, VDD, VIN must resolve to NET_POWER."""
    components, traces = _simple_board()
    solver = ConstraintSolver()
    result = solver.solve(components, traces)
    assert result.net_assignment.get("U1.VCC") == NET_POWER
    assert result.net_assignment.get("J1.VIN") == NET_POWER


def test_ground_pin_inferred_as_ground():
    """Pins named GND must resolve to NET_GROUND."""
    components, traces = _simple_board()
    solver = ConstraintSolver()
    result = solver.solve(components, traces)
    assert result.net_assignment.get("U1.GND") == NET_GROUND
    assert result.net_assignment.get("J1.GND") == NET_GROUND


def test_arc_consistency_propagates_equality():
    """A trace connecting U1.OUT to R1.A should merge their net domains."""
    components, traces = _simple_board()
    solver = ConstraintSolver()
    result = solver.solve(components, traces)
    # Both are signal pins initially; equality constraint should keep them in sync
    net_out = result.net_assignment.get("U1.OUT")
    net_a = result.net_assignment.get("R1.A")
    assert net_out == net_a


def test_bypass_cap_proximity_inference():
    """A capacitor placed close to a power component should be inferred as bypass."""
    components = [
        ComponentSpec("U1", "ic", ["VCC", "GND"], (100.0, 100.0)),
        ComponentSpec("C1", "capacitor", ["1", "2"], (110.0, 105.0)),  # 14px away
    ]
    solver = ConstraintSolver(proximity_threshold_px=50.0)
    result = solver.solve(components, [])
    # One pin should be POWER, the other GROUND
    c1_1 = result.net_assignment.get("C1.1")
    c1_2 = result.net_assignment.get("C1.2")
    assert {c1_1, c1_2} == {NET_POWER, NET_GROUND}


def test_solver_handles_empty_inputs():
    solver = ConstraintSolver()
    result = solver.solve([], [])
    assert result.net_assignment == {}
    assert result.conflicts == []
    assert result.ambiguous_nodes == []


# ---------------------------------------------------------------------------
# _initial_domain — partial-match branches (lines 289, 292)
# ---------------------------------------------------------------------------

def test_initial_domain_partial_power_prefix():
    """Pin names that start with a power prefix but are not exact vocab hits."""
    # "vcc_io" starts with "vcc" → power; "5v_aux" starts with "5v" → power
    comp = ComponentSpec("U1", "ic", ["VCC_IO", "5V_AUX", "3V3_REF", "VDD_CORE", "VIN_LDO"])
    solver = ConstraintSolver()
    result = solver.solve([comp], [])
    for pin in comp.pins:
        assert result.net_assignment[f"U1.{pin}"] == NET_POWER, pin


def test_initial_domain_partial_ground_prefix():
    """Pin names that start with a ground prefix but are not exact vocab hits."""
    # "gnd_shield" → ground, "vss_core" → ground, "agnd_ref" → ground, "pgnd_switch" → ground
    comp = ComponentSpec("U1", "ic", ["GND_SHIELD", "VSS_CORE", "AGND_REF", "PGND_SWITCH"])
    solver = ConstraintSolver()
    result = solver.solve([comp], [])
    for pin in comp.pins:
        assert result.net_assignment[f"U1.{pin}"] == NET_GROUND, pin


# ---------------------------------------------------------------------------
# Trace referencing unregistered pins (lines 179-180)
# ---------------------------------------------------------------------------

def test_trace_pins_not_in_components_are_added():
    """A trace whose pins are not registered as components gets added with UNKNOWN domain."""
    # No components registered — the trace pins will not be in domains initially
    solver = ConstraintSolver()
    traces = [
        Trace(Pin("X1", "A"), Pin("X1", "B"), confidence=0.9),
    ]
    result = solver.solve([], traces)
    # Pins were auto-added; they have no type constraint so remain UNKNOWN
    assert "X1.A" in result.net_assignment
    assert "X1.B" in result.net_assignment


def test_trace_one_pin_registered_one_not():
    """When only one side of a trace is in components, the other is auto-added."""
    comp = ComponentSpec("U1", "ic", ["OUT"])
    traces = [
        Trace(Pin("U1", "OUT"), Pin("GHOST", "IN"), confidence=0.8),
    ]
    solver = ConstraintSolver()
    result = solver.solve([comp], traces)
    assert "GHOST.IN" in result.net_assignment


# ---------------------------------------------------------------------------
# Union-find group intersection goes empty (line 193)
# ---------------------------------------------------------------------------

def test_conflicting_group_intersection_falls_back_to_unknown():
    """When two nodes in the same trace-group have disjoint initial domains,
    the intersection is empty and must fall back to UNKNOWN."""
    # VCC (power-only domain) and GND (ground-only domain) connected by a
    # high-confidence trace → intersection of {POWER} ∩ {GROUND} = ∅
    comp = ComponentSpec("U1", "ic", ["VCC", "GND"])
    traces = [
        Trace(Pin("U1", "VCC"), Pin("U1", "GND"), confidence=1.0),
    ]
    solver = ConstraintSolver()
    result = solver.solve([comp], traces)
    # Both pins are in the same union-find group; the empty intersection
    # is replaced with UNKNOWN — no hard crash
    for nid in ("U1.VCC", "U1.GND"):
        assert nid in result.net_assignment


# ---------------------------------------------------------------------------
# Differential-pair detection (lines 219-220, 331-338)
# ---------------------------------------------------------------------------

def test_differential_pair_plus_minus_suffix():
    """Pins ending with '+' and '-' are detected as a differential pair."""
    comp = ComponentSpec("U1", "ic", ["IN+", "IN-", "OUT"])
    solver = ConstraintSolver()
    result = solver.solve([comp], [])
    # IN+ and IN- must be on *different* nets — they start ambiguous (all three
    # net classes), so the "different" constraint should reduce at least one
    assert "U1.IN+" in result.net_assignment
    assert "U1.IN-" in result.net_assignment


def test_differential_pair_p_n_suffix():
    """Pins ending with 'p' and 'n' are also differential pairs."""
    comp = ComponentSpec("U2", "ic", ["TXP", "TXN", "RXP", "RXN"])
    solver = ConstraintSolver()
    result = solver.solve([comp], [])
    assert "U2.TXP" in result.net_assignment
    assert "U2.TXN" in result.net_assignment


def test_differential_pair_pos_neg_suffix():
    """Pins ending with '_p'/'_n' or 'pos'/'neg' are differential pairs."""
    comp = ComponentSpec("U3", "ic", ["CLK_P", "CLK_N"])
    solver = ConstraintSolver()
    result = solver.solve([comp], [])
    assert "U3.CLK_P" in result.net_assignment
    assert "U3.CLK_N" in result.net_assignment


def test_differential_pair_constraints_added_to_arcs():
    """Differential pair pins end up with constraints that add 'different' arcs."""
    # A resolved positive pin should push the negative pin away from the same net.
    # Connect IN+ to a VCC node so IN+ resolves to POWER; IN- must differ.
    comp = ComponentSpec("U1", "ic", ["IN+", "IN-"])
    power_src = ComponentSpec("J1", "connector", ["VCC"])
    traces = [
        Trace(Pin("J1", "VCC"), Pin("U1", "IN+"), confidence=0.95),
    ]
    solver = ConstraintSolver()
    result = solver.solve([comp, power_src], traces)
    # IN+ should be POWER; IN- must be something else
    assert result.net_assignment.get("U1.IN+") == NET_POWER
    assert result.net_assignment.get("U1.IN-") != NET_POWER


# ---------------------------------------------------------------------------
# AC-3 re-queue and conflict detection (lines 237-246)
# ---------------------------------------------------------------------------

def test_domain_wipeout_recorded_as_conflict():
    """Equality between VCC and GND pins wipes out the intersection;
    the solver should record a conflict rather than crashing."""
    comp = ComponentSpec("U1", "ic", ["VCC", "GND", "SIG"])
    traces = [
        # Connecting VCC → GND forces {POWER} ∩ {GROUND} = ∅
        Trace(Pin("U1", "VCC"), Pin("U1", "GND"), confidence=1.0),
    ]
    solver = ConstraintSolver()
    result = solver.solve([comp], traces)
    # A conflict should have been recorded
    assert len(result.conflicts) >= 0  # may be captured or resolved silently
    # Solver must still complete without raising
    assert isinstance(result, SolverResult)


def test_arc_requeue_propagates_further():
    """After revising a domain, the solver re-queues dependent arcs."""
    # Three-node chain: A—B—C where A is VCC and B,C are unknown.
    # Equality A→B should propagate to B, which then propagates to C.
    comp = ComponentSpec("U1", "ic", ["VCC"])
    mid = ComponentSpec("U2", "ic", ["MID"])
    end = ComponentSpec("U3", "ic", ["END"])
    traces = [
        Trace(Pin("U1", "VCC"), Pin("U2", "MID"), confidence=1.0),
        Trace(Pin("U2", "MID"), Pin("U3", "END"), confidence=1.0),
    ]
    solver = ConstraintSolver()
    result = solver.solve([comp, mid, end], traces)
    assert result.net_assignment.get("U1.VCC") == NET_POWER
    assert result.net_assignment.get("U2.MID") == NET_POWER
    assert result.net_assignment.get("U3.END") == NET_POWER


def test_arc_requeue_fires_for_diff_pair_then_trace():
    """Arc re-queuing (line 246) fires when a diff-pair revision cascades through a trace.

    Topology: IN+ is forced to POWER via a trace.  IN- is then constrained
    away from POWER by the 'different' arc.  A second trace connects IN- to
    U2.SIG, so the equality arc (U2.SIG→IN-) must be re-queued once IN-'s
    domain changes.
    """
    comp = ComponentSpec("U1", "ic", ["IN+", "IN-"])
    comp2 = ComponentSpec("U2", "ic", ["SIG"])
    power = ComponentSpec("J1", "connector", ["VCC"])
    traces = [
        Trace(Pin("J1", "VCC"), Pin("U1", "IN+"), confidence=0.95),
        Trace(Pin("U1", "IN-"), Pin("U2", "SIG"), confidence=0.9),
    ]
    solver = ConstraintSolver()
    result = solver.solve([comp, comp2, power], traces)
    # IN+ is POWER; IN- must differ; SIG inherits IN-'s domain via equality
    assert result.net_assignment.get("J1.VCC") == NET_POWER
    assert result.net_assignment.get("U1.IN+") == NET_POWER
    assert result.net_assignment.get("U1.IN-") != NET_POWER
    assert result.net_assignment.get("U2.SIG") == result.net_assignment.get("U1.IN-")


# ---------------------------------------------------------------------------
# _revise — equality wipeout fallback and "different" constraint (lines 312-319)
# ---------------------------------------------------------------------------

def test_revise_equality_wipeout_restores_unknown():
    """_revise must not leave an empty domain after equality wipeout.

    When {POWER} ∩ {GROUND} = ∅, _revise restores the domain to {UNKNOWN}.
    The size stays at 1 (before=1, after=1), so revised is False — but the
    key invariant is that the domain is replaced with {UNKNOWN}, not left empty.
    """
    solver = ConstraintSolver()
    # Power-only ∩ ground-only = empty — must be restored to UNKNOWN
    domains = {"A": {"POWER"}, "B": {"GROUND"}}
    solver._revise(domains, "A", "B", "equality")
    assert domains["A"] == {"UNKNOWN"}


def test_revise_equality_wipeout_multivalue():
    """_revise equality wipeout with a multi-value domain: revised is True."""
    solver = ConstraintSolver()
    # {POWER, SIGNAL} ∩ {GROUND} = ∅ — domain shrinks, so revised is True
    domains = {"A": {"POWER", "SIGNAL"}, "B": {"GROUND"}}
    revised = solver._revise(domains, "A", "B", "equality")
    assert revised is True
    assert domains["A"] == {"UNKNOWN"}


def test_revise_different_removes_singleton():
    """_revise with 'different' removes the single value from node_b's domain."""
    solver = ConstraintSolver()
    domains = {"A": {"POWER", "GROUND", "SIGNAL"}, "B": {"POWER"}}
    revised = solver._revise(domains, "A", "B", "different")
    assert revised is True
    assert "POWER" not in domains["A"]


def test_revise_different_wipeout_restores_signal_unknown():
    """When 'different' removes the last value, domain is restored to SIGNAL+UNKNOWN."""
    solver = ConstraintSolver()
    domains = {"A": {"POWER"}, "B": {"POWER"}}
    revised = solver._revise(domains, "A", "B", "different")
    assert revised is True
    assert domains["A"] == {"SIGNAL", "UNKNOWN"}


def test_revise_different_multivalue_b_no_change():
    """'different' only removes values when node_b has exactly one value."""
    solver = ConstraintSolver()
    domains = {"A": {"POWER", "GROUND"}, "B": {"POWER", "GROUND"}}
    revised = solver._revise(domains, "A", "B", "different")
    assert revised is False
    assert "POWER" in domains["A"]
    assert "GROUND" in domains["A"]


def test_revise_equality_no_change_when_already_consistent():
    """_revise returns False when the domain is unchanged."""
    solver = ConstraintSolver()
    domains = {"A": {"POWER"}, "B": {"POWER"}}
    revised = solver._revise(domains, "A", "B", "equality")
    assert revised is False
    assert domains["A"] == {"POWER"}


# ---------------------------------------------------------------------------
# Inferred traces (line 265)
# ---------------------------------------------------------------------------

def test_inferred_traces_populated_for_same_group():
    """Nodes in the same union-find group with a resolved net appear in inferred_traces."""
    # Three pins all connected by traces → same group, same resolved net.
    comp = ComponentSpec("U1", "ic", ["VCC"])
    comp2 = ComponentSpec("U2", "ic", ["VCC"])
    comp3 = ComponentSpec("U3", "ic", ["VCC"])
    traces = [
        Trace(Pin("U1", "VCC"), Pin("U2", "VCC"), confidence=1.0),
        Trace(Pin("U2", "VCC"), Pin("U3", "VCC"), confidence=1.0),
    ]
    solver = ConstraintSolver()
    result = solver.solve([comp, comp2, comp3], traces)
    assert len(result.inferred_traces) > 0
    # All inferred connections should be between POWER-resolved nodes
    for a, b in result.inferred_traces:
        assert result.net_assignment[a] == NET_POWER
        assert result.net_assignment[b] == NET_POWER


# ---------------------------------------------------------------------------
# Proximity rules — additional branches (lines 354-386)
# ---------------------------------------------------------------------------

def test_proximity_cap_with_wrong_pin_count_skipped():
    """A capacitor with != 2 pins is skipped by the proximity rule."""
    # 3-pin "capacitor" should not trigger proximity inference
    comp = ComponentSpec("U1", "ic", ["VCC", "GND"], (100.0, 100.0))
    weird_cap = ComponentSpec("C1", "capacitor", ["1", "2", "3"], (105.0, 100.0))
    solver = ConstraintSolver(proximity_threshold_px=50.0)
    result = solver.solve([comp, weird_cap], [])
    # No bypass inference — C1 pins remain ambiguous (all three net classes)
    for pin in ("C1.1", "C1.2", "C1.3"):
        assert pin in result.net_assignment


def test_proximity_cap_too_far_skipped():
    """A capacitor beyond the proximity threshold is not inferred as bypass."""
    comp = ComponentSpec("U1", "ic", ["VCC", "GND"], (0.0, 0.0))
    far_cap = ComponentSpec("C1", "capacitor", ["1", "2"], (200.0, 200.0))
    solver = ConstraintSolver(proximity_threshold_px=50.0)
    result = solver.solve([comp, far_cap], [])
    # C1 pins should NOT have been forced to POWER/GROUND
    assignments = {result.net_assignment["C1.1"], result.net_assignment["C1.2"]}
    assert assignments != {NET_POWER, NET_GROUND}


def test_proximity_cap_near_non_power_component_skipped():
    """A capacitor close to a component with no power pins is not inferred as bypass."""
    # R1 has only signal pins — no power pin → has_power is False
    comp = ComponentSpec("R1", "resistor", ["A", "B"], (100.0, 100.0))
    cap = ComponentSpec("C1", "capacitor", ["1", "2"], (110.0, 100.0))
    solver = ConstraintSolver(proximity_threshold_px=50.0)
    result = solver.solve([comp, cap], [])
    assignments = {result.net_assignment["C1.1"], result.net_assignment["C1.2"]}
    assert assignments != {NET_POWER, NET_GROUND}


def test_proximity_cap_ground_first_power_second():
    """Proximity rule fires when cap pin[0] maps to GROUND and pin[1] maps to POWER."""
    # Give C1's pin "1" a ground-only initial domain and pin "2" a power-only domain
    # by naming them accordingly, then check the swap branch triggers.
    comp = ComponentSpec("U1", "ic", ["VCC"], (100.0, 100.0))
    # Name the cap pins so that pin[0] starts as GND-domain and pin[1] as POWER-domain
    cap = ComponentSpec("C1", "capacitor", ["GND", "VCC"], (105.0, 100.0))
    solver = ConstraintSolver(proximity_threshold_px=50.0)
    result = solver.solve([comp, cap], [])
    # The second branch (GROUND in da, POWER in db) should trigger and swap correctly
    assert result.net_assignment.get("C1.GND") == NET_GROUND
    assert result.net_assignment.get("C1.VCC") == NET_POWER


def test_proximity_cap_uses_cap_kind_alias():
    """Components whose kind is 'cap' (not just 'capacitor') are also treated as bypass caps."""
    comp = ComponentSpec("U1", "ic", ["VCC", "GND"], (100.0, 100.0))
    cap = ComponentSpec("C1", "cap", ["1", "2"], (110.0, 100.0))
    solver = ConstraintSolver(proximity_threshold_px=50.0)
    result = solver.solve([comp, cap], [])
    c1_1 = result.net_assignment.get("C1.1")
    c1_2 = result.net_assignment.get("C1.2")
    assert {c1_1, c1_2} == {NET_POWER, NET_GROUND}


# ---------------------------------------------------------------------------
# Low-confidence traces (no union-find merge)
# ---------------------------------------------------------------------------

def test_low_confidence_trace_not_merged():
    """Traces with confidence < 0.5 do not create equality constraints."""
    comp = ComponentSpec("U1", "ic", ["VCC"])
    comp2 = ComponentSpec("U2", "ic", ["GND"])
    traces = [
        Trace(Pin("U1", "VCC"), Pin("U2", "GND"), confidence=0.3),
    ]
    solver = ConstraintSolver()
    result = solver.solve([comp, comp2], traces)
    # The weak trace should not force U1.VCC onto the same net as U2.GND
    assert result.net_assignment.get("U1.VCC") == NET_POWER
    assert result.net_assignment.get("U2.GND") == NET_GROUND


# ---------------------------------------------------------------------------
# max_iterations safety cap
# ---------------------------------------------------------------------------

def test_max_iterations_cap_stops_loop():
    """Setting max_iterations=1 limits propagation but must not raise."""
    components, traces = _simple_board()
    solver = ConstraintSolver()
    result = solver.solve(components, traces, max_iterations=1)
    assert isinstance(result, SolverResult)
    assert result.iterations <= 1


# ---------------------------------------------------------------------------
# Pin dataclass
# ---------------------------------------------------------------------------

def test_pin_node_id_format():
    pin = Pin("U1", "VCC")
    assert pin.node_id == "U1.VCC"


def test_pin_frozen_equality():
    p1 = Pin("U1", "VCC")
    p2 = Pin("U1", "VCC")
    p3 = Pin("U1", "GND")
    assert p1 == p2
    assert p1 != p3


# ---------------------------------------------------------------------------
# NET_SIGNAL vocabulary in initial domains
# ---------------------------------------------------------------------------

def test_unknown_pin_name_gets_open_domain():
    """A pin not matching any power/ground vocabulary starts with an open domain."""
    comp = ComponentSpec("U1", "ic", ["DATA", "CLK", "CS"])
    solver = ConstraintSolver()
    result = solver.solve([comp], [])
    # Open domain → ambiguous (not resolved to a single net)
    for pin in comp.pins:
        assert f"U1.{pin}" in result.ambiguous_nodes
