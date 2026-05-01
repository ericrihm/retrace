"""Tests for src/retrace/analysis/cross_board.py — no ML dependencies."""

from __future__ import annotations

import pytest

from retrace.analysis.cross_board import (
    BoardAnalysis,
    BoardComponent,
    BoardTrace,
    CrossBoardEngine,
    PatternMatch,
    PatternNode,
    SubcircuitPattern,
)

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _make_ldo_board():
    """Synthetic LDO supply board: IC + two caps wired to it."""
    components = [
        BoardComponent("U1", "ic", ["VIN", "GND", "VOUT"], (100.0, 100.0)),
        BoardComponent("C1", "capacitor", ["1", "2"], (130.0, 90.0)),
        BoardComponent("C2", "capacitor", ["1", "2"], (70.0, 110.0)),
    ]
    traces = [
        BoardTrace("U1", "VIN", "C1", "1", confidence=0.9),
        BoardTrace("U1", "VOUT", "C2", "1", confidence=0.85),
    ]
    return components, traces


def _make_rc_board():
    """Synthetic RC low-pass filter: one resistor, one cap, close together."""
    components = [
        BoardComponent("R1", "resistor", ["A", "B"], (300.0, 200.0)),
        BoardComponent("C3", "capacitor", ["1", "2"], (340.0, 195.0)),
    ]
    traces = [
        BoardTrace("R1", "B", "C3", "1", confidence=0.92),
    ]
    return components, traces


# ---------------------------------------------------------------------------
# Instantiation & built-in pattern count
# ---------------------------------------------------------------------------

class TestEngineInstantiation:
    def test_default_instantiation(self):
        engine = CrossBoardEngine()
        assert engine is not None

    def test_builtin_pattern_count(self):
        engine = CrossBoardEngine()
        patterns = engine.list_patterns()
        # Built-in library ships 15 patterns (5 original + 10 new)
        assert len(patterns) == 15

    def test_builtin_pattern_names(self):
        engine = CrossBoardEngine()
        names = engine.list_patterns()
        assert "ldo_supply" in names
        assert "rc_lowpass" in names
        assert "decoupling_pair" in names
        assert "pull_up_resistor" in names
        assert "crystal_oscillator" in names

    def test_custom_threshold(self):
        engine = CrossBoardEngine(match_threshold=0.8, proximity_px=50.0)
        # Verify it constructs without error; threshold stored internally
        assert engine is not None


# ---------------------------------------------------------------------------
# Pattern matching with synthetic components
# ---------------------------------------------------------------------------

class TestPatternMatching:
    def test_ldo_supply_match(self):
        engine = CrossBoardEngine(match_threshold=0.5, proximity_px=80.0)
        comps, traces = _make_ldo_board()
        result = engine.analyse(comps, traces)
        assert isinstance(result, BoardAnalysis)
        pattern_names = [m.pattern_name for m in result.matches]
        assert "ldo_supply" in pattern_names

    def test_rc_lowpass_match(self):
        engine = CrossBoardEngine(match_threshold=0.5, proximity_px=80.0)
        comps, traces = _make_rc_board()
        result = engine.analyse(comps, traces)
        pattern_names = [m.pattern_name for m in result.matches]
        assert "rc_lowpass" in pattern_names

    def test_match_has_correct_fields(self):
        engine = CrossBoardEngine(match_threshold=0.5, proximity_px=80.0)
        comps, traces = _make_ldo_board()
        result = engine.analyse(comps, traces)
        assert len(result.matches) >= 1
        m = result.matches[0]
        assert isinstance(m, PatternMatch)
        assert isinstance(m.pattern_name, str)
        assert isinstance(m.description, str)
        assert isinstance(m.component_roles, dict)
        assert 0.0 <= m.score <= 1.0
        assert isinstance(m.is_partial, bool)

    def test_coverage_between_zero_and_one(self):
        engine = CrossBoardEngine(match_threshold=0.5, proximity_px=80.0)
        comps, traces = _make_ldo_board()
        result = engine.analyse(comps, traces)
        assert 0.0 <= result.coverage <= 1.0

    def test_novel_components_are_refs(self):
        engine = CrossBoardEngine(match_threshold=0.5, proximity_px=80.0)
        comps = [
            BoardComponent("Q1", "transistor", ["B", "C", "E"], (500.0, 500.0)),
        ]
        result = engine.analyse(comps, [])
        # transistor matches no built-in pattern → should be novel
        assert "Q1" in result.novel_components

    def test_matches_sorted_by_score_descending(self):
        engine = CrossBoardEngine(match_threshold=0.3, proximity_px=80.0)
        comps = (
            _make_ldo_board()[0]
            + _make_rc_board()[0]
        )
        traces = _make_ldo_board()[1] + _make_rc_board()[1]
        result = engine.analyse(comps, traces)
        scores = [m.score for m in result.matches]
        assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# Edge cases: empty inputs
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_components_and_traces(self):
        engine = CrossBoardEngine()
        result = engine.analyse([], [])
        assert result.matches == []
        assert result.novel_components == []
        assert result.coverage == 0.0

    def test_empty_traces_only(self):
        engine = CrossBoardEngine(match_threshold=0.5, proximity_px=80.0)
        comps, _ = _make_ldo_board()
        # Without traces the LDO pattern may still partially match via proximity
        result = engine.analyse(comps, [])
        assert isinstance(result, BoardAnalysis)

    def test_single_component_no_trace(self):
        engine = CrossBoardEngine(match_threshold=0.5)
        comps = [BoardComponent("R99", "resistor", ["A", "B"], (10.0, 10.0))]
        result = engine.analyse(comps, [])
        # pull_up_resistor is a single-node pattern with no edges (score=0.7)
        assert isinstance(result, BoardAnalysis)

    def test_low_confidence_trace_ignored(self):
        """Traces with confidence < 0.4 must not contribute to adjacency."""
        engine = CrossBoardEngine(match_threshold=0.9, proximity_px=0.0)
        comps = [
            BoardComponent("R1", "resistor", ["A", "B"], (0.0, 0.0)),
            BoardComponent("C1", "capacitor", ["1", "2"], (1000.0, 1000.0)),
        ]
        traces = [BoardTrace("R1", "A", "C1", "1", confidence=0.1)]
        result = engine.analyse(comps, traces)
        # High threshold + ignored trace → rc_lowpass should not match
        rc_matches = [m for m in result.matches if m.pattern_name == "rc_lowpass"]
        assert rc_matches == []


# ---------------------------------------------------------------------------
# seen_count increments across process_board calls
# ---------------------------------------------------------------------------

class TestSeenCount:
    def test_seen_count_increments(self):
        engine = CrossBoardEngine(match_threshold=0.5, proximity_px=80.0)
        comps, traces = _make_ldo_board()

        stats_before = engine.pattern_stats()
        ldo_before = stats_before["ldo_supply"]["seen_count"]

        engine.analyse(comps, traces)
        stats_after = engine.pattern_stats()
        ldo_after = stats_after["ldo_supply"]["seen_count"]

        assert ldo_after > ldo_before

    def test_seen_count_increments_across_multiple_calls(self):
        engine = CrossBoardEngine(match_threshold=0.5, proximity_px=80.0)
        comps, traces = _make_ldo_board()

        for _ in range(3):
            engine.analyse(comps, traces)

        stats = engine.pattern_stats()
        assert stats["ldo_supply"]["seen_count"] >= 3

    def test_mean_confidence_increases_after_match(self):
        engine = CrossBoardEngine(match_threshold=0.5, proximity_px=80.0)
        comps, traces = _make_ldo_board()

        engine.analyse(comps, traces)
        stats = engine.pattern_stats()
        # At least one match recorded → mean_confidence > 0
        assert stats["ldo_supply"]["mean_confidence"] > 0.0

    def test_mean_confidence_nonzero_after_match(self):
        engine = CrossBoardEngine(match_threshold=0.5, proximity_px=80.0)
        comps, traces = _make_ldo_board()
        engine.analyse(comps, traces)
        stats = engine.pattern_stats()
        assert stats["ldo_supply"]["mean_confidence"] > 0.0


# ---------------------------------------------------------------------------
# to_dict / from_dict round-trip
# ---------------------------------------------------------------------------

class TestSerialization:
    def test_to_dict_returns_dict(self):
        engine = CrossBoardEngine()
        d = engine.to_dict()
        assert isinstance(d, dict)
        assert "patterns" in d

    def test_to_dict_pattern_count(self):
        engine = CrossBoardEngine()
        d = engine.to_dict()
        assert len(d["patterns"]) == 15

    def test_from_dict_roundtrip_pattern_names(self):
        engine = CrossBoardEngine()
        d = engine.to_dict()
        engine2 = CrossBoardEngine.from_dict(d)
        assert engine2.list_patterns() == engine.list_patterns()

    def test_from_dict_preserves_seen_count(self):
        engine = CrossBoardEngine(match_threshold=0.5, proximity_px=80.0)
        comps, traces = _make_ldo_board()
        engine.analyse(comps, traces)
        engine.analyse(comps, traces)

        d = engine.to_dict()
        engine2 = CrossBoardEngine.from_dict(d)
        stats = engine2.pattern_stats()
        assert stats["ldo_supply"]["seen_count"] >= 2

    def test_from_dict_preserves_seen_count_and_mean_confidence(self):
        engine = CrossBoardEngine(match_threshold=0.5, proximity_px=80.0)
        comps, traces = _make_ldo_board()
        engine.analyse(comps, traces)

        d = engine.to_dict()
        original_mean = engine.pattern_stats()["ldo_supply"]["mean_confidence"]
        original_seen = engine.pattern_stats()["ldo_supply"]["seen_count"]
        engine2 = CrossBoardEngine.from_dict(d)
        assert engine2.pattern_stats()["ldo_supply"]["seen_count"] == original_seen
        assert abs(engine2.pattern_stats()["ldo_supply"]["mean_confidence"] - original_mean) < 1e-6

    def test_from_dict_empty_patterns(self):
        engine = CrossBoardEngine.from_dict({"patterns": []})
        assert engine.list_patterns() == []

    def test_roundtrip_with_custom_pattern(self):
        engine = CrossBoardEngine()
        custom = SubcircuitPattern(
            name="test_pattern",
            description="A test pattern",
            nodes=[PatternNode("r", ["resistor"], ["1", "2"])],
            edges=[],
            seen_count=7,
            confidence_sum=4.2,
        )
        engine.record_pattern(custom)
        d = engine.to_dict()
        engine2 = CrossBoardEngine.from_dict(d)
        assert "test_pattern" in engine2.list_patterns()
        assert engine2.pattern_stats()["test_pattern"]["seen_count"] == 7


# ---------------------------------------------------------------------------
# Pattern scoring logic
# ---------------------------------------------------------------------------

class TestScoringLogic:
    def test_single_node_no_edges_score_is_0_7(self):
        """Single-node pattern with no edges gets the 0.7 boost."""
        engine = CrossBoardEngine(match_threshold=0.5, proximity_px=0.0)
        comps = [BoardComponent("R1", "resistor", ["A", "B"], (10.0, 10.0))]
        result = engine.analyse(comps, [])
        pull_up_matches = [m for m in result.matches if m.pattern_name == "pull_up_resistor"]
        assert len(pull_up_matches) >= 1
        assert pytest.approx(pull_up_matches[0].score, abs=0.01) == 0.7

    def test_record_pattern_replaces_existing(self):
        engine = CrossBoardEngine()
        original_count = len(engine.list_patterns())
        replacement = SubcircuitPattern(
            name="ldo_supply",
            description="Replaced",
            nodes=[PatternNode("ldo", ["ic"], [])],
            edges=[],
        )
        engine.record_pattern(replacement)
        assert len(engine.list_patterns()) == original_count
        assert engine.pattern_stats()["ldo_supply"]["description"] == "Replaced"

    def test_record_new_pattern_appends(self):
        engine = CrossBoardEngine()
        original_count = len(engine.list_patterns())
        new_p = SubcircuitPattern(
            name="brand_new",
            description="New pattern",
            nodes=[PatternNode("x", ["ic"], [])],
            edges=[],
        )
        engine.record_pattern(new_p)
        assert len(engine.list_patterns()) == original_count + 1
        assert "brand_new" in engine.list_patterns()

    def test_deduplication_keeps_highest_score(self):
        """Two identical component assignments for the same pattern → one survives."""
        engine = CrossBoardEngine(match_threshold=0.3, proximity_px=200.0)
        # Two caps very close together: decoupling_pair will find both orderings
        comps = [
            BoardComponent("C1", "capacitor", ["1", "2"], (10.0, 10.0)),
            BoardComponent("C2", "capacitor", ["1", "2"], (20.0, 10.0)),
        ]
        result = engine.analyse(comps, [])
        # Even if both orderings are checked, duplicates are removed
        dedup_pairs = [m for m in result.matches if m.pattern_name == "decoupling_pair"]
        component_sets = [
            frozenset(m.component_roles.values()) for m in dedup_pairs
        ]
        assert len(component_sets) == len(set(component_sets))

    def test_proximity_adjacency_triggers_match(self):
        """Components within proximity_px should be treated as adjacent."""
        engine = CrossBoardEngine(match_threshold=0.5, proximity_px=100.0)
        comps = [
            BoardComponent("R1", "resistor", ["A", "B"], (0.0, 0.0)),
            BoardComponent("C1", "capacitor", ["1", "2"], (50.0, 0.0)),
        ]
        result = engine.analyse(comps, [])  # no explicit traces
        pattern_names = [m.pattern_name for m in result.matches]
        assert "rc_lowpass" in pattern_names

    def test_out_of_proximity_no_match(self):
        """Components far apart with no trace must not satisfy edge requirement."""
        engine = CrossBoardEngine(match_threshold=0.9, proximity_px=10.0)
        comps = [
            BoardComponent("R1", "resistor", ["A", "B"], (0.0, 0.0)),
            BoardComponent("C1", "capacitor", ["1", "2"], (5000.0, 5000.0)),
        ]
        result = engine.analyse(comps, [])
        rc_matches = [m for m in result.matches if m.pattern_name == "rc_lowpass"]
        assert rc_matches == []

    def test_zero_node_pattern_returns_no_matches(self):
        """A pattern with no nodes yields no matches (covers line 554)."""
        engine = CrossBoardEngine(match_threshold=0.0)
        empty_pattern = SubcircuitPattern(
            name="empty_pattern",
            description="Pattern with no nodes",
            nodes=[],
            edges=[],
        )
        engine.record_pattern(empty_pattern)
        comps = [BoardComponent("R1", "resistor", ["A", "B"], (0.0, 0.0))]
        result = engine.analyse(comps, [])
        empty_matches = [m for m in result.matches if m.pattern_name == "empty_pattern"]
        assert empty_matches == []

    def test_combinatorial_explosion_pruning(self):
        """More than 10,000 candidate combos triggers pruning to 4 per role (line 580)."""
        # The decoupling_pair pattern has 2 roles, each accepting 'capacitor'.
        # With 101+ capacitors per role, combos = 101*101 > 10,000 → pruning fires.
        engine = CrossBoardEngine(match_threshold=0.5, proximity_px=200.0)
        # Create 101 capacitors, all within proximity of each other
        comps = [
            BoardComponent(f"C{i}", "capacitor", ["1", "2"], (float(i * 5), 0.0))
            for i in range(101)
        ]
        # This must complete without error and return a BoardAnalysis
        result = engine.analyse(comps, [])
        assert isinstance(result, BoardAnalysis)
        # With pruning the engine limits candidates per role to 4, so at most
        # 4*4=16 combos are checked for any pattern — matches are still found
        decoupling_matches = [m for m in result.matches if m.pattern_name == "decoupling_pair"]
        assert len(decoupling_matches) >= 1
