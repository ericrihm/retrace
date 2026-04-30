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
