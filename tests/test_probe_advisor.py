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


# ---------------------------------------------------------------------------
# Tests: update() propagation
# ---------------------------------------------------------------------------

def test_update_propagates_resolved_to_group_members():
    """When a union root is resolved, all members of the group are propagated."""
    advisor = _make_advisor()
    # First merge U1.GND and C1.GND into the same union group
    advisor.update("U1.GND", Measurement("U1.GND", continuity_to="C1.GND"))
    # Verify both sides are resolved to the same net
    assert advisor._resolved.get("C1.GND") == advisor._resolved.get("U1.GND")

    # Propagation test: a node in _counts whose root is resolved but the node
    # itself is not yet in _resolved should be propagated by the loop on line 212.
    advisor2 = ProbeAdvisor(net_labels=["VCC", "GND"])
    comps = [Component("U1", "IC", ["A", "B", "C"], (0.0, 0.0))]
    advisor2.add_components(comps)
    # Resolve U1.A
    advisor2.update("U1.A", Measurement("U1.A", voltage=5.0))
    # Manually make U1.C point to U1.A as its parent (mimicking a union),
    # but do NOT put U1.C in _resolved. U1.C is in _counts because add_components
    # registered it.
    advisor2._parent["U1.C"] = "U1.A"
    # Triggering any other update will run the propagation loop over all _counts keys
    # including U1.C whose root (U1.A) is resolved but U1.C is not.
    advisor2.update("U1.B", Measurement("U1.B", voltage=5.0))
    # The propagation loop (line 212) should have resolved U1.C
    assert "U1.C" in advisor2._resolved
    assert advisor2._resolved["U1.C"] == "VCC"


# ---------------------------------------------------------------------------
# Tests: _expected_info_gain edge case
# ---------------------------------------------------------------------------

def test_expected_info_gain_zero_for_resolved_node():
    """A collapsed (near-zero entropy) node returns EIG of 0."""
    advisor = ProbeAdvisor(net_labels=["VCC", "GND", "NET_A"])
    advisor._counts["test_node"] = np.array([1e9, 0.0, 0.0])
    advisor._parent["test_node"] = "test_node"
    eig = advisor._expected_info_gain("test_node")
    assert eig == 0.0


# ---------------------------------------------------------------------------
# Tests: _apply_pin_name_priors with resolved nodes
# ---------------------------------------------------------------------------

def test_apply_pin_priors_skips_resolved_nodes():
    """Resolved nodes are skipped during prior application."""
    advisor = ProbeAdvisor(net_labels=["VCC", "GND"])
    comp = Component("U1", "IC", ["VCC"], (0.0, 0.0))
    advisor.add_components([comp])
    # Resolve U1.VCC before calling _apply_pin_name_priors again
    advisor._resolved["U1.VCC"] = "VCC"
    original_counts = advisor._counts["U1.VCC"].copy()
    advisor._apply_pin_name_priors()
    # Counts should not change because the node was skipped
    assert np.array_equal(advisor._counts["U1.VCC"], original_counts)


# ---------------------------------------------------------------------------
# Tests: _boost_label edge cases
# ---------------------------------------------------------------------------

def test_boost_label_new_label_extends_all_counts():
    """Adding a new label via _boost_label extends all existing count arrays."""
    advisor = ProbeAdvisor(net_labels=["VCC", "GND"])
    comp = Component("U1", "IC", ["OUT"], (0.0, 0.0))
    advisor.add_components([comp])
    initial_label_count = len(advisor._labels)
    # Boost with a brand-new label
    advisor._boost_label("U1.OUT", "NET_NEW", factor=5.0)
    assert len(advisor._labels) == initial_label_count + 1
    assert "NET_NEW" in advisor._labels
    # All count arrays should have been extended
    for nid, arr in advisor._counts.items():
        assert len(arr) == len(advisor._labels)


def test_boost_label_node_not_in_counts():
    """_boost_label initialises counts for a node that has no entry yet."""
    advisor = ProbeAdvisor(net_labels=["VCC", "GND"])
    advisor._boost_label("phantom_node", "VCC", factor=3.0)
    assert "phantom_node" in advisor._counts
    idx = advisor._labels.index("VCC")
    assert advisor._counts["phantom_node"][idx] > advisor._alpha


def test_boost_label_short_count_array_gets_padded():
    """If a node's count array is shorter than labels, _boost_label pads it."""
    advisor = ProbeAdvisor(net_labels=["VCC", "GND"])
    comp = Component("U1", "IC", ["OUT"], (0.0, 0.0))
    advisor.add_components([comp])
    # Manually truncate the count array to simulate misalignment
    advisor._counts["U1.OUT"] = np.array([1.0])  # shorter than label count
    advisor._boost_label("U1.OUT", "VCC", factor=2.0)
    assert len(advisor._counts["U1.OUT"]) == len(advisor._labels)


# ---------------------------------------------------------------------------
# Tests: _measurement_to_label branches
# ---------------------------------------------------------------------------

def test_measurement_to_label_continuity_to_resolved_root():
    """continuity_to a node whose root is already resolved returns that net."""
    advisor = _make_advisor()
    advisor.update("U1.VCC", Measurement("U1.VCC", voltage=5.0))
    # Now ask what label a continuity measurement to U1.VCC gives
    m = Measurement("R1.1", continuity_to="U1.VCC")
    label = advisor._measurement_to_label(m)
    assert label == "VCC"


def test_measurement_to_label_continuity_to_unresolved():
    """continuity_to an unresolved node returns a NET_<node_id> label."""
    advisor = _make_advisor()
    m = Measurement("R1.1", continuity_to="R1.2")
    label = advisor._measurement_to_label(m)
    assert label == "NET_R1.2"


def test_measurement_to_label_voltage_low():
    """Voltage < 0.3 maps to GND."""
    advisor = _make_advisor()
    m = Measurement("R1.1", voltage=0.1)
    assert advisor._measurement_to_label(m) == "GND"


def test_measurement_to_label_voltage_mid_range():
    """Voltage between 0.3 and 4.5 maps to NET_<rounded>V."""
    advisor = _make_advisor()
    m = Measurement("R1.1", voltage=3.3)
    label = advisor._measurement_to_label(m)
    assert label == "NET_3.3V"


def test_measurement_to_label_resistance_low():
    """Resistance < 5 ohm maps to GND."""
    advisor = _make_advisor()
    m = Measurement("R1.1", resistance=2.0)
    assert advisor._measurement_to_label(m) == "GND"


def test_measurement_to_label_fallback_unknown():
    """A measurement with no voltage, resistance, or continuity returns NET_UNKNOWN."""
    advisor = _make_advisor()
    m = Measurement("R1.1")
    assert advisor._measurement_to_label(m) == "NET_UNKNOWN"


# ---------------------------------------------------------------------------
# Tests: _find with unknown node
# ---------------------------------------------------------------------------

def test_find_initialises_unknown_node():
    """_find on an unknown node creates a self-parent entry."""
    advisor = ProbeAdvisor(net_labels=["VCC", "GND"])
    result = advisor._find("brand_new_node")
    assert result == "brand_new_node"
    assert advisor._parent["brand_new_node"] == "brand_new_node"


# ---------------------------------------------------------------------------
# Tests: _union edge cases
# ---------------------------------------------------------------------------

def test_union_same_root_is_noop():
    """Union of two nodes already in the same group is a no-op."""
    advisor = _make_advisor()
    # Force A and B into the same group first
    advisor._union("U1.VCC", "C1.VCC")
    counts_before = advisor._counts[advisor._find("U1.VCC")].copy()
    advisor._union("U1.VCC", "C1.VCC")  # second call — same root
    counts_after = advisor._counts[advisor._find("U1.VCC")]
    assert np.array_equal(counts_before, counts_after)


def test_union_aligns_unequal_count_arrays():
    """_union pads count arrays when they have different lengths (both directions)."""
    advisor = ProbeAdvisor(net_labels=["VCC", "GND"])

    # Case 1: ca shorter than cb (hits len(ca) < n branch, line 338)
    advisor._parent["node_a"] = "node_a"
    advisor._parent["node_b"] = "node_b"
    advisor._counts["node_a"] = np.array([1.0, 1.0])       # 2 elements (shorter)
    advisor._counts["node_b"] = np.array([1.0, 1.0, 1.0])  # 3 elements
    advisor._union("node_a", "node_b")
    root = advisor._find("node_a")
    assert len(advisor._counts[root]) == 3

    # Case 2: cb shorter than ca (hits len(cb) < n branch, line 340)
    advisor2 = ProbeAdvisor(net_labels=["VCC", "GND"])
    advisor2._parent["node_c"] = "node_c"
    advisor2._parent["node_d"] = "node_d"
    advisor2._counts["node_c"] = np.array([1.0, 1.0, 1.0])  # 3 elements
    advisor2._counts["node_d"] = np.array([1.0, 1.0])        # 2 elements (shorter)
    advisor2._union("node_c", "node_d")
    root2 = advisor2._find("node_c")
    assert len(advisor2._counts[root2]) == 3
