"""Tests for the Bayesian ProbeAdvisor."""

from __future__ import annotations

import math

import numpy as np
import pytest

from retrace.analysis.probe_advisor import (
    Component,
    Measurement,
    ProbeAdvisor,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_advisor() -> ProbeAdvisor:
    advisor = ProbeAdvisor(net_labels=["VCC", "GND", "NET_A"])
    components = [
        Component("U1", "IC", ["VCC", "GND", "OUT", "IN"], (100.0, 100.0)),
        Component("R1", "resistor", ["1", "2"], (200.0, 150.0)),
        Component("C1", "capacitor", ["VCC", "GND"], (300.0, 200.0)),
    ]
    advisor.add_components(components)
    return advisor


# ---------------------------------------------------------------------------
# Tests: entropy calculation
# ---------------------------------------------------------------------------

def test_entropy_uniform_distribution():
    """Uniform distribution over 3 labels should have entropy == log2(3)."""
    advisor = ProbeAdvisor(net_labels=["VCC", "GND", "NET_A"])
    # Manually create a node with equal counts
    advisor._counts["test_node"] = np.array([1.0, 1.0, 1.0])
    H = advisor._entropy("test_node")
    assert abs(H - math.log2(3)) < 0.01


def test_entropy_collapsed_distribution():
    """All probability mass on one label gives entropy == 0."""
    advisor = ProbeAdvisor(net_labels=["VCC", "GND", "NET_A"])
    advisor._counts["test_node"] = np.array([1e9, 0.0, 0.0])
    H = advisor._entropy("test_node")
    assert H < 0.001


def test_entropy_unknown_node_returns_nonzero():
    """Unknown node with default Dirichlet prior should have positive entropy."""
    advisor = ProbeAdvisor(net_labels=["VCC", "GND", "NET_A"])
    H = advisor._entropy("nonexistent_node")
    assert H > 0.0


# ---------------------------------------------------------------------------
# Tests: recommend()
# ---------------------------------------------------------------------------

def test_recommend_returns_list():
    advisor = _make_advisor()
    recs = advisor.recommend(top_k=5)
    assert isinstance(recs, list)


def test_recommend_sorted_descending():
    advisor = _make_advisor()
    recs = advisor.recommend(top_k=10)
    eigs = [r.expected_info_gain for r in recs]
    assert eigs == sorted(eigs, reverse=True)


def test_recommend_top_k_respected():
    advisor = _make_advisor()
    recs = advisor.recommend(top_k=3)
    assert len(recs) <= 3


def test_recommend_excludes_resolved():
    advisor = _make_advisor()
    # Resolve U1.VCC
    advisor.update("U1.VCC", Measurement("U1.VCC", voltage=5.0))
    recs = advisor.recommend()
    node_ids = [r.node_id for r in recs]
    assert "U1.VCC" not in node_ids


# ---------------------------------------------------------------------------
# Tests: update() mechanism
# ---------------------------------------------------------------------------

def test_update_voltage_resolves_vcc():
    advisor = _make_advisor()
    advisor.update("U1.VCC", Measurement("U1.VCC", voltage=5.0))
    assert "U1.VCC" in advisor._resolved
    assert advisor._resolved["U1.VCC"] == "VCC"


def test_update_continuity_merges_nodes():
    advisor = _make_advisor()
    advisor.update("U1.GND", Measurement("U1.GND", continuity_to="C1.GND"))
    # Both should be resolved to the same net
    assert "U1.GND" in advisor._resolved
    assert "C1.GND" in advisor._resolved
    assert advisor._resolved["U1.GND"] == advisor._resolved["C1.GND"]


def test_update_unknown_node_raises():
    advisor = _make_advisor()
    with pytest.raises(ValueError, match="Unknown probe point"):
        advisor.update("DOES_NOT_EXIST.PIN", Measurement("DOES_NOT_EXIST.PIN"))
