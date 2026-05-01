"""Smoke tests for the flywheel intelligence layer (P0/P1/P2)."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

from flywheel_intelligence import (
    INNOVATION_CATEGORIES,
    ActiveLearner,
    BanditArm,
    Calibrator,
    ConfidenceEstimator,
    FlywheelBrain,
    InnovationArm,
    MetaLearner,
    ShadowResult,
    ShadowScorer,
    SourceQuality,
    SourceQualityTracker,
    TimeSeriesStore,
    TrendAnalyzer,
    WarmStartCache,
    _compute_psi,
)

# ═══════════════════════════════════════════════════════════════════════════
# TimeSeriesStore
# ═══════════════════════════════════════════════════════════════════════════


class TestTimeSeriesStore:
    def test_append_and_read(self, tmp_path: Path) -> None:
        store = TimeSeriesStore(tmp_path / "history.jsonl")
        store.append({"flywheels": {"lint": {"score": 100}}})
        store.append({"flywheels": {"lint": {"score": 95}}})
        records = store.read_all()
        assert len(records) == 2
        assert records[0]["flywheels"]["lint"]["score"] == 100
        assert all("ts" in r for r in records)

    def test_read_empty(self, tmp_path: Path) -> None:
        store = TimeSeriesStore(tmp_path / "missing.jsonl")
        assert store.read_all() == []

    def test_read_last(self, tmp_path: Path) -> None:
        store = TimeSeriesStore(tmp_path / "h.jsonl")
        for i in range(20):
            store.append({"flywheels": {"x": {"score": i}}})
        last_5 = store.read_last(5)
        assert len(last_5) == 5
        assert last_5[0]["flywheels"]["x"]["score"] == 15

    def test_scores_for(self, tmp_path: Path) -> None:
        store = TimeSeriesStore(tmp_path / "h.jsonl")
        store.append({"flywheels": {"lint": {"score": 100}, "tests": {"score": 95}}})
        store.append({"flywheels": {"lint": {"score": 90}}})
        assert store.scores_for("lint") == [100, 90]
        assert store.scores_for("tests") == [95]
        assert store.scores_for("missing") == []

    def test_handles_corrupt_lines(self, tmp_path: Path) -> None:
        f = tmp_path / "h.jsonl"
        f.write_text('{"ok": true}\ngarbage\n{"also": "ok"}\n')
        store = TimeSeriesStore(f)
        assert len(store.read_all()) == 2


# ═══════════════════════════════════════════════════════════════════════════
# WarmStartCache
# ═══════════════════════════════════════════════════════════════════════════


class TestWarmStartCache:
    def test_empty_cache_is_miss(self) -> None:
        cache = WarmStartCache({})
        assert not cache.is_cached("lint")
        assert cache.misses == 1

    def test_always_run_flywheels(self) -> None:
        cache = WarmStartCache({"warm_cache": {"regression": "abc"}})
        assert not cache.is_cached("regression")

    def test_cache_hit_after_update(self) -> None:
        cache = WarmStartCache({})
        cache.is_cached("readme_format")
        cache.update("readme_format")
        exported = cache.export()
        assert "readme_format" in exported

    def test_export_round_trip(self) -> None:
        cache = WarmStartCache({})
        cache.cache["test_fw"] = "hash123"
        exported = cache.export()
        cache2 = WarmStartCache({"warm_cache": exported})
        assert cache2.cache["test_fw"] == "hash123"


# ═══════════════════════════════════════════════════════════════════════════
# ShadowScorer
# ═══════════════════════════════════════════════════════════════════════════


class TestShadowScorer:
    def test_no_challenger_returns_none(self) -> None:
        shadow = ShadowScorer({})
        assert shadow.run_shadow("lint", 100.0) is None

    def test_register_and_run(self) -> None:
        shadow = ShadowScorer({})
        shadow.register_challenger("lint", "v2_strict", lambda: 92.0)
        result = shadow.run_shadow("lint", 100.0)
        assert result is not None
        assert result.production_score == 100.0
        assert result.shadow_score == 92.0
        assert result.delta == -8.0
        assert not result.diverged

    def test_divergence_threshold(self) -> None:
        result = ShadowResult("fw", 100.0, 80.0, "v2")
        assert result.diverged  # delta = -20 > 15

    def test_agreement_rate(self) -> None:
        history = [
            {"flywheel": "lint", "diverged": False},
            {"flywheel": "lint", "diverged": False},
            {"flywheel": "lint", "diverged": True},
            {"flywheel": "lint", "diverged": False},
            {"flywheel": "lint", "diverged": False},
        ]
        shadow = ShadowScorer({"shadow_history": history})
        assert shadow.agreement_rate("lint") == 0.8

    def test_agreement_rate_insufficient_data(self) -> None:
        shadow = ShadowScorer({"shadow_history": [{"flywheel": "x", "diverged": False}]})
        assert shadow.agreement_rate("x") == 1.0

    def test_psi_identical_distributions(self) -> None:
        assert _compute_psi([50, 60, 70, 80, 90] * 10, [50, 60, 70, 80, 90] * 10) < 0.01

    def test_psi_different_distributions(self) -> None:
        assert _compute_psi([10, 20, 30] * 10, [70, 80, 90] * 10) > 0.1

    def test_psi_empty(self) -> None:
        assert _compute_psi([], [1, 2, 3]) == 0.0

    def test_promotion_not_eligible_few_runs(self) -> None:
        shadow = ShadowScorer({})
        assert not shadow.promotion_eligible("lint")

    def test_challenger_exception_returns_none(self) -> None:
        shadow = ShadowScorer({})
        shadow.register_challenger("lint", "broken", lambda: 1 / 0)
        assert shadow.run_shadow("lint", 100.0) is None


# ═══════════════════════════════════════════════════════════════════════════
# ActiveLearner (Thompson Sampling)
# ═══════════════════════════════════════════════════════════════════════════


class TestActiveLearner:
    def test_ensure_arm(self) -> None:
        learner = ActiveLearner({})
        learner.ensure_arm("lint")
        assert "lint" in learner.arms
        assert learner.arms["lint"].alpha == 1.0

    def test_rank_flywheels(self) -> None:
        learner = ActiveLearner({})
        ranked = learner.rank_flywheels(["a", "b", "c"])
        assert set(ranked) == {"a", "b", "c"}

    def test_record_outcome_improves_alpha(self) -> None:
        learner = ActiveLearner({})
        learner.ensure_arm("lint")
        initial_alpha = learner.arms["lint"].alpha
        learner.record_outcome("lint", 90.0, 95.0, had_changes=True)
        assert learner.arms["lint"].alpha > initial_alpha

    def test_record_outcome_no_changes_is_noop(self) -> None:
        learner = ActiveLearner({})
        learner.ensure_arm("lint")
        initial = learner.arms["lint"].total_pulls
        learner.record_outcome("lint", 90.0, 95.0, had_changes=False)
        assert learner.arms["lint"].total_pulls == initial

    def test_cooldown(self) -> None:
        learner = ActiveLearner({})
        learner.ensure_arm("hot")
        learner.arms["hot"].consecutive_runs = 5
        learner.arms["hot"].alpha = 100.0
        ranked = learner.rank_flywheels(["hot", "cold"])
        assert ranked[-1] == "hot"

    def test_top_performers(self) -> None:
        learner = ActiveLearner({})
        learner.ensure_arm("good")
        learner.arms["good"].alpha = 10.0
        learner.arms["good"].beta = 1.0
        learner.ensure_arm("bad")
        learner.arms["bad"].alpha = 1.0
        learner.arms["bad"].beta = 10.0
        top = learner.top_performers(2)
        assert top[0][0] == "good"
        assert top[0][1] > top[1][1]

    def test_export_round_trip(self) -> None:
        learner = ActiveLearner({})
        learner.ensure_arm("x")
        learner.arms["x"].alpha = 5.0
        exported = learner.export()
        learner2 = ActiveLearner({"bandit_arms": exported})
        assert learner2.arms["x"].alpha == 5.0

    def test_bandit_arm_sample_range(self) -> None:
        arm = BanditArm(flywheel="x", alpha=2.0, beta=2.0)
        samples = [arm.sample() for _ in range(100)]
        assert all(0 <= s <= 1 for s in samples)

    def test_bandit_arm_effectiveness(self) -> None:
        arm = BanditArm(flywheel="x", alpha=9.0, beta=1.0)
        assert arm.effectiveness == 0.9


# ═══════════════════════════════════════════════════════════════════════════
# MetaLearner (Innovation categories)
# ═══════════════════════════════════════════════════════════════════════════


class TestMetaLearner:
    def test_default_arms(self) -> None:
        meta = MetaLearner({})
        assert len(meta.arms) == len(INNOVATION_CATEGORIES)

    def test_record_positive_innovation(self) -> None:
        meta = MetaLearner({})
        meta.record_innovation("code_fix", 5.0)
        assert meta.arms["code_fix"].alpha > 1.0
        assert meta.arms["code_fix"].total_pulls == 1

    def test_record_negative_innovation(self) -> None:
        meta = MetaLearner({})
        meta.record_innovation("code_fix", -2.0)
        assert meta.arms["code_fix"].beta > 1.0

    def test_record_neutral_innovation(self) -> None:
        meta = MetaLearner({})
        meta.record_innovation("code_fix", 0.0)
        assert meta.arms["code_fix"].beta == 1.3

    def test_recommend_next(self) -> None:
        meta = MetaLearner({})
        recs = meta.recommend_next(3)
        assert len(recs) == 3
        assert all(r in INNOVATION_CATEGORIES for r in recs)

    def test_summary(self) -> None:
        meta = MetaLearner({})
        meta.record_innovation("new_flywheel", 10.0)
        summary = meta.summary()
        assert summary[0][0] == "new_flywheel"
        assert summary[0][2] == 1

    def test_unknown_category(self) -> None:
        meta = MetaLearner({})
        meta.record_innovation("custom_thing", 5.0)
        assert "custom_thing" in meta.arms

    def test_export_round_trip(self) -> None:
        meta = MetaLearner({})
        meta.record_innovation("code_fix", 3.0)
        exported = meta.export()
        meta2 = MetaLearner({"innovation_arms": exported})
        assert meta2.arms["code_fix"].total_pulls == 1


# ═══════════════════════════════════════════════════════════════════════════
# SourceQualityTracker
# ═══════════════════════════════════════════════════════════════════════════


class TestSourceQualityTracker:
    def test_initial_reliability(self) -> None:
        tracker = SourceQualityTracker({})
        sq = tracker.get("pytest")
        assert sq.ema_reliability == 1.0

    def test_record_success(self) -> None:
        tracker = SourceQualityTracker({})
        tracker.record("pytest", True, 98.0)
        assert tracker.get("pytest").is_reliable
        assert tracker.get("pytest").variance_window == [98.0]

    def test_record_failures_degrade_reliability(self) -> None:
        tracker = SourceQualityTracker({})
        for _ in range(20):
            tracker.record("broken_tool", False)
        assert not tracker.get("broken_tool").is_reliable

    def test_unreliable_sources(self) -> None:
        tracker = SourceQualityTracker({})
        for _ in range(20):
            tracker.record("bad", False)
        tracker.record("good", True, 100.0)
        assert "bad" in tracker.unreliable_sources()
        assert "good" not in tracker.unreliable_sources()

    def test_variance_window_capped(self) -> None:
        sq = SourceQuality(source_id="x")
        for i in range(30):
            sq.record_success(float(i))
        assert len(sq.variance_window) == 20

    def test_failure_streak(self) -> None:
        sq = SourceQuality(source_id="x")
        sq.record_failure()
        sq.record_failure()
        sq.record_failure()
        assert sq.failure_streak == 3
        assert not sq.is_reliable

    def test_success_resets_streak(self) -> None:
        sq = SourceQuality(source_id="x")
        sq.record_failure()
        sq.record_failure()
        sq.record_success(100.0)
        assert sq.failure_streak == 0

    def test_export_round_trip(self) -> None:
        tracker = SourceQualityTracker({})
        tracker.record("ruff", True, 100.0)
        exported = tracker.export()
        tracker2 = SourceQualityTracker({"source_quality": exported})
        assert tracker2.get("ruff").variance_window == [100.0]


# ═══════════════════════════════════════════════════════════════════════════
# Calibrator
# ═══════════════════════════════════════════════════════════════════════════


class TestCalibrator:
    def test_calibrated_score_no_anchors(self) -> None:
        cal = Calibrator({})
        assert cal.calibrated_score("design", 95.0) == 95.0

    def test_add_anchor_adjusts_offset(self) -> None:
        cal = Calibrator({})
        cal.add_anchor("design", 98.0, 90.0)
        cal.add_anchor("design", 95.0, 88.0)
        cal.add_anchor("design", 97.0, 89.0)
        calibrated = cal.calibrated_score("design", 98.0)
        assert calibrated < 98.0

    def test_calibrated_score_clamped(self) -> None:
        cal = Calibrator({})
        cal.calibration["x"] = {"raw_history": [], "p90_baseline": None, "offset": -200, "anchors": []}
        assert cal.calibrated_score("x", 50.0) == 0.0
        cal.calibration["y"] = {"raw_history": [], "p90_baseline": None, "offset": 200, "anchors": []}
        assert cal.calibrated_score("y", 50.0) == 100.0

    def test_record_score(self) -> None:
        cal = Calibrator({})
        cal.record_score("lint", 100.0)
        cal.record_score("lint", 95.0)
        assert cal.calibration["lint"]["raw_history"] == [100.0, 95.0]

    def test_detect_inflation_no_data(self) -> None:
        cal = Calibrator({})
        assert cal.detect_inflation("lint") is None

    def test_detect_inflation_triggers(self) -> None:
        cal = Calibrator({})
        cal.calibration["design"] = {
            "raw_history": [80.0] * 20 + [92.0] * 10,
            "p90_baseline": 80.0,
            "offset": 0.0,
            "anchors": [],
        }
        warning = cal.detect_inflation("design")
        assert warning is not None
        assert "drifted" in warning

    def test_history_capped(self) -> None:
        cal = Calibrator({})
        for i in range(150):
            cal.record_score("x", float(i))
        assert len(cal.calibration["x"]["raw_history"]) == 100

    def test_export_round_trip(self) -> None:
        cal = Calibrator({})
        cal.record_score("lint", 99.0)
        exported = cal.export()
        cal2 = Calibrator({"calibration": exported})
        assert cal2.calibration["lint"]["raw_history"] == [99.0]


# ═══════════════════════════════════════════════════════════════════════════
# ConfidenceEstimator
# ═══════════════════════════════════════════════════════════════════════════


class TestConfidenceEstimator:
    def test_no_data(self, tmp_path: Path) -> None:
        store = TimeSeriesStore(tmp_path / "h.jsonl")
        ce = ConfidenceEstimator(store)
        mean, lo, hi = ce.compute_ci("lint")
        assert mean == 0.0

    def test_single_score(self, tmp_path: Path) -> None:
        store = TimeSeriesStore(tmp_path / "h.jsonl")
        store.append({"flywheels": {"lint": {"score": 95.0}}})
        ce = ConfidenceEstimator(store)
        mean, lo, hi = ce.compute_ci("lint")
        assert mean == 95.0

    def test_stable_scores_narrow_ci(self, tmp_path: Path) -> None:
        store = TimeSeriesStore(tmp_path / "h.jsonl")
        for _ in range(20):
            store.append({"flywheels": {"lint": {"score": 100.0}}})
        ce = ConfidenceEstimator(store)
        mean, lo, hi = ce.compute_ci("lint")
        assert hi - lo < 1.0
        assert ce.is_stable("lint")

    def test_variable_scores_wide_ci(self, tmp_path: Path) -> None:
        store = TimeSeriesStore(tmp_path / "h.jsonl")
        import random
        random.seed(42)
        for _ in range(20):
            store.append({"flywheels": {"x": {"score": random.uniform(20, 100)}}})
        ce = ConfidenceEstimator(store)
        width = ce.ci_width("x")
        assert width > 5.0

    def test_ci_width(self, tmp_path: Path) -> None:
        store = TimeSeriesStore(tmp_path / "h.jsonl")
        for s in [90, 92, 91, 93, 90, 91, 92]:
            store.append({"flywheels": {"fw": {"score": s}}})
        ce = ConfidenceEstimator(store)
        width = ce.ci_width("fw")
        assert 0 < width < 10


# ═══════════════════════════════════════════════════════════════════════════
# TrendAnalyzer
# ═══════════════════════════════════════════════════════════════════════════


class TestTrendAnalyzer:
    def test_sparkline_empty(self) -> None:
        assert TrendAnalyzer.sparkline([]) == ""

    def test_sparkline_single(self) -> None:
        result = TrendAnalyzer.sparkline([50.0])
        assert len(result) == 1

    def test_sparkline_ascending(self) -> None:
        result = TrendAnalyzer.sparkline([0, 25, 50, 75, 100])
        assert result[0] < result[-1]

    def test_sparkline_width_limit(self) -> None:
        result = TrendAnalyzer.sparkline(list(range(100)), width=10)
        assert len(result) == 10

    def test_cusum_insufficient_data(self) -> None:
        assert TrendAnalyzer.cusum_detect([1, 2, 3]) == "insufficient_data"

    def test_cusum_stable(self) -> None:
        scores = [50.0, 51.0, 49.0, 50.0, 50.5, 49.5, 50.0, 51.0, 49.0, 50.0]
        assert TrendAnalyzer.cusum_detect(scores) == "stable"

    def test_cusum_regression(self) -> None:
        scores = [90.0, 91.0, 89.0, 90.0, 90.5] + [70.0, 65.0, 60.0, 55.0, 50.0]
        assert TrendAnalyzer.cusum_detect(scores) == "regression"

    def test_cusum_breakthrough(self) -> None:
        scores = [50.0, 51.0, 49.0, 50.0, 50.5] + [70.0, 75.0, 80.0, 85.0, 90.0]
        assert TrendAnalyzer.cusum_detect(scores) == "breakthrough"

    def test_cusum_stalled(self) -> None:
        scores = [50.0] * 20
        result = TrendAnalyzer.cusum_detect(scores)
        assert result == "stalled"

    def test_analyze_flywheel_no_data(self, tmp_path: Path) -> None:
        store = TimeSeriesStore(tmp_path / "h.jsonl")
        analyzer = TrendAnalyzer(store)
        result = analyzer.analyze_flywheel("lint")
        assert result["status"] == "no_data"

    def test_analyze_flywheel_with_data(self, tmp_path: Path) -> None:
        store = TimeSeriesStore(tmp_path / "h.jsonl")
        for s in [90, 92, 91, 93, 95, 94, 96, 95, 97, 98]:
            store.append({"flywheels": {"lint": {"score": s}}})
        analyzer = TrendAnalyzer(store)
        result = analyzer.analyze_flywheel("lint")
        assert result["status"] in ("stable", "breakthrough", "regression", "stalled")
        assert "sparkline" in result
        assert result["current"] == 98

    def test_analyze_all(self, tmp_path: Path) -> None:
        store = TimeSeriesStore(tmp_path / "h.jsonl")
        analyzer = TrendAnalyzer(store)
        results = analyzer.analyze_all(["lint", "tests"])
        assert len(results) == 2


# ═══════════════════════════════════════════════════════════════════════════
# FlywheelBrain (integration)
# ═══════════════════════════════════════════════════════════════════════════


class TestFlywheelBrain:
    def test_init_creates_subsystems(self) -> None:
        with patch("flywheel_intelligence.BRAIN_FILE", Path("/tmp/nonexistent_brain.json")):
            with patch("flywheel_intelligence.HISTORY_FILE", Path("/tmp/nonexistent_history.jsonl")):
                brain = FlywheelBrain()
                assert brain.store is not None
                assert brain.cache is not None
                assert brain.shadow is not None
                assert brain.learner is not None
                assert brain.meta is not None
                assert brain.sources is not None
                assert brain.calibrator is not None
                assert brain.confidence is not None
                assert brain.trends is not None

    def test_record_run(self, tmp_path: Path) -> None:
        with patch("flywheel_intelligence.BRAIN_FILE", tmp_path / "brain.json"):
            with patch("flywheel_intelligence.HISTORY_FILE", tmp_path / "history.jsonl"):
                brain = FlywheelBrain()
                brain.record_run({"lint": 100.0, "tests": 95.0}, git_hash="abc123")
                records = brain.store.read_all()
                assert len(records) == 1
                assert records[0]["git_hash"] == "abc123"

    def test_save_and_reload(self, tmp_path: Path) -> None:
        brain_file = tmp_path / "brain.json"
        history_file = tmp_path / "history.jsonl"
        with patch("flywheel_intelligence.BRAIN_FILE", brain_file):
            with patch("flywheel_intelligence.HISTORY_FILE", history_file):
                brain = FlywheelBrain()
                brain.learner.ensure_arm("lint")
                brain.learner.arms["lint"].alpha = 5.0
                brain.sources.record("ruff", True, 100.0)
                brain.save()
                assert brain_file.exists()
                brain2 = FlywheelBrain()
                assert brain2.learner.arms["lint"].alpha == 5.0
                assert brain2.sources.get("ruff").variance_window == [100.0]

    def test_format_brain_summary(self, tmp_path: Path) -> None:
        with patch("flywheel_intelligence.BRAIN_FILE", tmp_path / "brain.json"):
            with patch("flywheel_intelligence.HISTORY_FILE", tmp_path / "history.jsonl"):
                brain = FlywheelBrain()
                summary = brain.format_brain_summary()
                assert "Flywheel Brain Summary" in summary
                assert "Active Learning" in summary
                assert "Innovation Meta-Learning" in summary
                assert "Source Quality" in summary
                assert "Warm-Start Cache" in summary

    def test_get_trend_report(self, tmp_path: Path) -> None:
        with patch("flywheel_intelligence.BRAIN_FILE", tmp_path / "brain.json"):
            with patch("flywheel_intelligence.HISTORY_FILE", tmp_path / "history.jsonl"):
                brain = FlywheelBrain()
                report = brain.get_trend_report()
                assert len(report) == len(FlywheelBrain.ALL_FLYWHEELS)

    def test_get_inflation_warnings_empty(self, tmp_path: Path) -> None:
        with patch("flywheel_intelligence.BRAIN_FILE", tmp_path / "brain.json"):
            with patch("flywheel_intelligence.HISTORY_FILE", tmp_path / "history.jsonl"):
                brain = FlywheelBrain()
                assert brain.get_inflation_warnings() == []

    def test_all_flywheels_list(self) -> None:
        assert len(FlywheelBrain.ALL_FLYWHEELS) == 12
        assert "lint" in FlywheelBrain.ALL_FLYWHEELS
        assert "svg_render" in FlywheelBrain.ALL_FLYWHEELS

    def test_quality_gate_passes_on_improvement(self, tmp_path: Path) -> None:
        with patch("flywheel_intelligence.BRAIN_FILE", tmp_path / "brain.json"):
            with patch("flywheel_intelligence.HISTORY_FILE", tmp_path / "history.jsonl"):
                brain = FlywheelBrain()
                passed, violations = brain.quality_gate({"lint": 100.0, "tests": 95.0})
                assert passed
                assert violations == []

    def test_quality_gate_fails_on_regression(self, tmp_path: Path) -> None:
        with patch("flywheel_intelligence.BRAIN_FILE", tmp_path / "brain.json"):
            with patch("flywheel_intelligence.HISTORY_FILE", tmp_path / "history.jsonl"):
                brain = FlywheelBrain()
                brain.quality_gate({"lint": 100.0})
                passed, violations = brain.quality_gate({"lint": 80.0})
                assert not passed
                assert len(violations) == 1
                assert "lint" in violations[0]

    def test_quality_gate_updates_floor(self, tmp_path: Path) -> None:
        with patch("flywheel_intelligence.BRAIN_FILE", tmp_path / "brain.json"):
            with patch("flywheel_intelligence.HISTORY_FILE", tmp_path / "history.jsonl"):
                brain = FlywheelBrain()
                brain.quality_gate({"lint": 90.0})
                brain.quality_gate({"lint": 95.0})
                passed, violations = brain.quality_gate({"lint": 92.0})
                assert not passed  # dropped below new floor of 95

    def test_explain_regression_no_data(self, tmp_path: Path) -> None:
        with patch("flywheel_intelligence.BRAIN_FILE", tmp_path / "brain.json"):
            with patch("flywheel_intelligence.HISTORY_FILE", tmp_path / "history.jsonl"):
                brain = FlywheelBrain()
                assert brain.explain_regression("lint") is None

    def test_explain_regression_with_drop(self, tmp_path: Path) -> None:
        with patch("flywheel_intelligence.BRAIN_FILE", tmp_path / "brain.json"):
            with patch("flywheel_intelligence.HISTORY_FILE", tmp_path / "history.jsonl"):
                brain = FlywheelBrain()
                brain.store.append({"git_hash": "aaa", "flywheels": {"lint": {"score": 100}}})
                brain.store.append({"git_hash": "bbb", "flywheels": {"lint": {"score": 80}}})
                explanation = brain.explain_regression("lint")
                assert explanation is not None
                assert "dropped" in explanation
                assert "100" in explanation and "80" in explanation

    def test_explain_regression_small_delta_ignored(self, tmp_path: Path) -> None:
        with patch("flywheel_intelligence.BRAIN_FILE", tmp_path / "brain.json"):
            with patch("flywheel_intelligence.HISTORY_FILE", tmp_path / "history.jsonl"):
                brain = FlywheelBrain()
                brain.store.append({"git_hash": "a", "flywheels": {"lint": {"score": 100}}})
                brain.store.append({"git_hash": "b", "flywheels": {"lint": {"score": 97}}})
                assert brain.explain_regression("lint") is None

    def test_get_regression_explanations_empty(self, tmp_path: Path) -> None:
        with patch("flywheel_intelligence.BRAIN_FILE", tmp_path / "brain.json"):
            with patch("flywheel_intelligence.HISTORY_FILE", tmp_path / "history.jsonl"):
                brain = FlywheelBrain()
                assert brain.get_regression_explanations() == []


# ═══════════════════════════════════════════════════════════════════════════
# Edge cases and regression guards
# ═══════════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    def test_psi_same_value(self) -> None:
        assert _compute_psi([50.0] * 20, [50.0] * 20) == 0.0

    def test_innovation_arm_sample_range(self) -> None:
        arm = InnovationArm(category="x", alpha=2.0, beta=2.0)
        samples = [arm.sample() for _ in range(50)]
        assert all(0 <= s <= 1 for s in samples)

    def test_source_quality_variance_empty(self) -> None:
        sq = SourceQuality(source_id="x")
        assert sq.variance == 0.0

    def test_calibrator_unknown_flywheel_inflation(self) -> None:
        cal = Calibrator({})
        assert cal.detect_inflation("nonexistent") is None

    def test_active_learner_reset_consecutive(self) -> None:
        learner = ActiveLearner({})
        learner.ensure_arm("x")
        learner.arms["x"].consecutive_runs = 5
        learner.reset_consecutive("x")
        assert learner.arms["x"].consecutive_runs == 0

    def test_meta_learner_cumulative_value(self) -> None:
        meta = MetaLearner({})
        meta.record_innovation("code_fix", 3.0)
        meta.record_innovation("code_fix", 2.0)
        assert meta.arms["code_fix"].cumulative_value == 5.0

    def test_shadow_export_capped(self) -> None:
        shadow = ShadowScorer({})
        shadow.history = [{"flywheel": "x", "diverged": False}] * 300
        shadow.register_challenger("x", "v2", lambda: 50.0)
        shadow.run_shadow("x", 50.0)
        assert len(shadow.export()) <= 200


# ═══════════════════════════════════════════════════════════════════════════
# FlywheelBrain.generate_heatmap_svg
# ═══════════════════════════════════════════════════════════════════════════


class TestGenerateHeatmapSvg:
    """Tests for the GitHub-style contribution heatmap SVG generator."""

    # Helper: build a fake history file with N entries spread over multiple days.
    @staticmethod
    def _write_history(path: Path, entries: list[dict]) -> None:
        with open(path, "w") as f:
            for entry in entries:
                f.write(json.dumps(entry) + "\n")

    def _make_brain(self, tmp_path: Path) -> FlywheelBrain:
        with patch("flywheel_intelligence.BRAIN_FILE", tmp_path / "brain.json"):
            with patch("flywheel_intelligence.HISTORY_FILE", tmp_path / "history.jsonl"):
                return FlywheelBrain()

    # ── valid SVG structure ──────────────────────────────────────────────────

    def test_svg_starts_and_ends_correctly(self, tmp_path: Path) -> None:
        """SVG output must open with <svg and close with </svg>."""
        with patch("flywheel_intelligence.BRAIN_FILE", tmp_path / "brain.json"):
            with patch("flywheel_intelligence.HISTORY_FILE", tmp_path / "history.jsonl"):
                brain = FlywheelBrain()
                out = tmp_path / "heatmap.svg"
                svg = brain.generate_heatmap_svg(out)
        assert svg.strip().startswith("<svg"), "SVG must start with <svg"
        assert svg.strip().endswith("</svg>"), "SVG must end with </svg>"

    def test_svg_written_to_disk(self, tmp_path: Path) -> None:
        """generate_heatmap_svg must write the file to the given path."""
        with patch("flywheel_intelligence.BRAIN_FILE", tmp_path / "brain.json"):
            with patch("flywheel_intelligence.HISTORY_FILE", tmp_path / "history.jsonl"):
                brain = FlywheelBrain()
                out = tmp_path / "heatmap.svg"
                svg = brain.generate_heatmap_svg(out)
        assert out.exists(), "SVG file must be written to disk"
        assert out.read_text() == svg

    # ── empty history ────────────────────────────────────────────────────────

    def test_empty_history_produces_valid_svg(self, tmp_path: Path) -> None:
        """An empty .flywheel_history.jsonl must still produce a valid SVG."""
        with patch("flywheel_intelligence.BRAIN_FILE", tmp_path / "brain.json"):
            with patch("flywheel_intelligence.HISTORY_FILE", tmp_path / "history.jsonl"):
                brain = FlywheelBrain()
                out = tmp_path / "empty_heatmap.svg"
                svg = brain.generate_heatmap_svg(out)
        assert svg.strip().startswith("<svg")
        assert svg.strip().endswith("</svg>")
        # Grid should still be rendered — 52*7 = 364 cells
        assert svg.count("<rect") >= 364

    # ── mock data spanning multiple days ────────────────────────────────────

    def test_heatmap_with_multi_day_data(self, tmp_path: Path) -> None:
        """Heatmap with 10+ entries across multiple days must produce a non-trivial SVG."""
        from datetime import datetime, timedelta, timezone

        history_file = tmp_path / "history.jsonl"
        base = datetime.now(timezone.utc) - timedelta(days=30)
        entries = []
        for i in range(12):
            ts = (base + timedelta(days=i * 2)).isoformat()
            score = 70.0 + i * 2.0  # steadily improving
            entries.append({
                "ts": ts,
                "flywheels": {
                    "lint": {"score": score},
                    "tests": {"score": score + 5},
                    "coverage": {"score": score - 5},
                },
            })
        self._write_history(history_file, entries)

        with patch("flywheel_intelligence.BRAIN_FILE", tmp_path / "brain.json"):
            with patch("flywheel_intelligence.HISTORY_FILE", history_file):
                brain = FlywheelBrain()
                out = tmp_path / "heatmap.svg"
                svg = brain.generate_heatmap_svg(out)

        assert svg.strip().startswith("<svg")
        assert svg.strip().endswith("</svg>")
        # Should have improvement-colored cells (cyan/green range)
        assert "#22" in svg or "#1f" in svg, "Expected improvement colors in SVG"

    # ── month labels ─────────────────────────────────────────────────────────

    def test_month_labels_present(self, tmp_path: Path) -> None:
        """SVG must contain at least 2 distinct month abbreviations."""
        MONTH_ABBR = [
            "Jan", "Feb", "Mar", "Apr", "May", "Jun",
            "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
        ]
        with patch("flywheel_intelligence.BRAIN_FILE", tmp_path / "brain.json"):
            with patch("flywheel_intelligence.HISTORY_FILE", tmp_path / "history.jsonl"):
                brain = FlywheelBrain()
                out = tmp_path / "heatmap.svg"
                svg = brain.generate_heatmap_svg(out)
        found = [m for m in MONTH_ABBR if m in svg]
        assert len(found) >= 2, f"Expected >= 2 month labels, found: {found}"

    def test_day_of_week_labels_present(self, tmp_path: Path) -> None:
        """SVG must include Mon/Wed/Fri day-of-week labels."""
        with patch("flywheel_intelligence.BRAIN_FILE", tmp_path / "brain.json"):
            with patch("flywheel_intelligence.HISTORY_FILE", tmp_path / "history.jsonl"):
                brain = FlywheelBrain()
                out = tmp_path / "heatmap.svg"
                svg = brain.generate_heatmap_svg(out)
        assert "Mon" in svg
        assert "Wed" in svg
        assert "Fri" in svg

    # ── regression coloring ───────────────────────────────────────────────────

    def test_regression_coloring(self, tmp_path: Path) -> None:
        """A day with a large score drop should produce a red-hued cell."""
        from datetime import datetime, timedelta, timezone

        history_file = tmp_path / "history.jsonl"
        # Use dates guaranteed to be inside the 52-week grid window
        # (14 and 15 days ago are always before any recent Sunday boundary).
        day_a = (datetime.now(timezone.utc) - timedelta(days=15)).isoformat()
        day_b = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
        entries = [
            {"ts": day_a, "flywheels": {"lint": {"score": 95.0}}},
            {"ts": day_b, "flywheels": {"lint": {"score": 30.0}}},
        ]
        self._write_history(history_file, entries)

        with patch("flywheel_intelligence.BRAIN_FILE", tmp_path / "brain.json"):
            with patch("flywheel_intelligence.HISTORY_FILE", history_file):
                brain = FlywheelBrain()
                out = tmp_path / "heatmap.svg"
                svg = brain.generate_heatmap_svg(out)

        # Red palette used for regressions (the delta is -65, so a red cell must appear)
        assert "#ef4444" in svg or "#7f1d1d" in svg, (
            "Expected red regression color in SVG when score drops sharply"
        )

    # ── default output path ───────────────────────────────────────────────────

    def test_default_output_path(self, tmp_path: Path) -> None:
        """When output_path=None, the SVG is written to docs/examples/flywheel_heatmap.svg."""
        import flywheel_intelligence as fi_mod

        fake_root = tmp_path
        (fake_root / "docs" / "examples").mkdir(parents=True)

        with patch("flywheel_intelligence.BRAIN_FILE", tmp_path / "brain.json"):
            with patch("flywheel_intelligence.HISTORY_FILE", tmp_path / "history.jsonl"):
                with patch.object(fi_mod, "REPO_ROOT", fake_root):
                    brain = FlywheelBrain()
                    svg = brain.generate_heatmap_svg(None)

        expected = fake_root / "docs" / "examples" / "flywheel_heatmap.svg"
        assert expected.exists(), "Default path file must be created"
        assert expected.read_text() == svg

    # ── 52-week grid size ────────────────────────────────────────────────────

    def test_grid_contains_364_cells(self, tmp_path: Path) -> None:
        """The heatmap must have exactly 52 * 7 = 364 data cells."""
        with patch("flywheel_intelligence.BRAIN_FILE", tmp_path / "brain.json"):
            with patch("flywheel_intelligence.HISTORY_FILE", tmp_path / "history.jsonl"):
                brain = FlywheelBrain()
                out = tmp_path / "heatmap.svg"
                svg = brain.generate_heatmap_svg(out)
        # Count <rect elements that have a <title> child (data cells, not background/legend)
        import re
        cells_with_title = re.findall(r"<rect[^>]+><title>", svg)
        assert len(cells_with_title) == 364, (
            f"Expected 364 data cells, got {len(cells_with_title)}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# FlywheelBrain.export_prometheus
# ═══════════════════════════════════════════════════════════════════════════


class TestExportPrometheus:
    """Tests for the Prometheus text exposition format exporter."""

    def _make_brain(self, tmp_path: Path) -> FlywheelBrain:
        with patch("flywheel_intelligence.BRAIN_FILE", tmp_path / "brain.json"):
            with patch("flywheel_intelligence.HISTORY_FILE", tmp_path / "history.jsonl"):
                return FlywheelBrain()

    # ── output structure ────────────────────────────────────────────────────

    def test_returns_string(self, tmp_path: Path) -> None:
        brain = self._make_brain(tmp_path)
        result = brain.export_prometheus(tmp_path / "out.prom")
        assert isinstance(result, str)

    def test_written_to_disk(self, tmp_path: Path) -> None:
        brain = self._make_brain(tmp_path)
        out = tmp_path / "metrics.prom"
        text = brain.export_prometheus(out)
        assert out.exists()
        assert out.read_text(encoding="utf-8") == text

    def test_default_output_path(self, tmp_path: Path) -> None:
        """When output_path=None the file lands at REPO_ROOT/.flywheel_metrics.prom."""
        import flywheel_intelligence as fi_mod

        with patch("flywheel_intelligence.BRAIN_FILE", tmp_path / "brain.json"):
            with patch("flywheel_intelligence.HISTORY_FILE", tmp_path / "history.jsonl"):
                with patch.object(fi_mod, "REPO_ROOT", tmp_path):
                    brain = FlywheelBrain()
                    text = brain.export_prometheus(None)

        expected = tmp_path / ".flywheel_metrics.prom"
        assert expected.exists()
        assert expected.read_text(encoding="utf-8") == text

    # ── HELP / TYPE headers ─────────────────────────────────────────────────

    def test_has_flywheel_score_help_type(self, tmp_path: Path) -> None:
        brain = self._make_brain(tmp_path)
        text = brain.export_prometheus(tmp_path / "m.prom")
        assert "# HELP retrace_flywheel_score" in text
        assert "# TYPE retrace_flywheel_score gauge" in text

    def test_has_ci_width_help_type(self, tmp_path: Path) -> None:
        brain = self._make_brain(tmp_path)
        text = brain.export_prometheus(tmp_path / "m.prom")
        assert "# HELP retrace_flywheel_ci_width" in text
        assert "# TYPE retrace_flywheel_ci_width gauge" in text

    def test_has_source_reliability_help_type(self, tmp_path: Path) -> None:
        brain = self._make_brain(tmp_path)
        text = brain.export_prometheus(tmp_path / "m.prom")
        assert "# HELP retrace_source_reliability" in text
        assert "# TYPE retrace_source_reliability gauge" in text

    def test_has_bandit_effectiveness_help_type(self, tmp_path: Path) -> None:
        brain = self._make_brain(tmp_path)
        text = brain.export_prometheus(tmp_path / "m.prom")
        assert "# HELP retrace_bandit_effectiveness" in text
        assert "# TYPE retrace_bandit_effectiveness gauge" in text

    # ── all flywheels are present ───────────────────────────────────────────

    def test_all_flywheels_exported_score(self, tmp_path: Path) -> None:
        brain = self._make_brain(tmp_path)
        text = brain.export_prometheus(tmp_path / "m.prom")
        for fw in FlywheelBrain.ALL_FLYWHEELS:
            assert f'retrace_flywheel_score{{flywheel="{fw}"}}' in text

    def test_all_flywheels_exported_ci_width(self, tmp_path: Path) -> None:
        brain = self._make_brain(tmp_path)
        text = brain.export_prometheus(tmp_path / "m.prom")
        for fw in FlywheelBrain.ALL_FLYWHEELS:
            assert f'retrace_flywheel_ci_width{{flywheel="{fw}"}}' in text

    def test_all_flywheels_exported_bandit(self, tmp_path: Path) -> None:
        brain = self._make_brain(tmp_path)
        text = brain.export_prometheus(tmp_path / "m.prom")
        for fw in FlywheelBrain.ALL_FLYWHEELS:
            assert f'retrace_bandit_effectiveness{{flywheel="{fw}"}}' in text

    # ── label format (Prometheus spec: {key="value"}) ───────────────────────

    def test_label_format_uses_double_quotes(self, tmp_path: Path) -> None:
        brain = self._make_brain(tmp_path)
        text = brain.export_prometheus(tmp_path / "m.prom")
        # Every data line must use label format with double-quoted values
        data_lines = [
            line for line in text.splitlines()
            if line and not line.startswith("#")
        ]
        assert data_lines, "Expected at least one data line"
        for line in data_lines:
            assert '{' in line and '="' in line and '"}' in line, (
                f"Line does not match Prometheus label format: {line!r}"
            )

    # ── values match recorded scores ────────────────────────────────────────

    def test_score_value_reflects_last_calibration(self, tmp_path: Path) -> None:
        brain = self._make_brain(tmp_path)
        brain.calibrator.record_score("lint", 87.5)
        text = brain.export_prometheus(tmp_path / "m.prom")
        assert 'retrace_flywheel_score{flywheel="lint"} 87.5' in text

    def test_score_zero_when_no_history(self, tmp_path: Path) -> None:
        brain = self._make_brain(tmp_path)
        # Don't record any scores — all flywheels should default to 0.0
        text = brain.export_prometheus(tmp_path / "m.prom")
        assert 'retrace_flywheel_score{flywheel="lint"} 0.0' in text

    def test_source_reliability_appears_after_recording(self, tmp_path: Path) -> None:
        brain = self._make_brain(tmp_path)
        brain.sources.record("pytest", True, 100.0)
        text = brain.export_prometheus(tmp_path / "m.prom")
        assert 'retrace_source_reliability{source="pytest"}' in text

    def test_no_source_lines_when_no_sources_recorded(self, tmp_path: Path) -> None:
        brain = self._make_brain(tmp_path)
        text = brain.export_prometheus(tmp_path / "m.prom")
        data_lines = [l for l in text.splitlines() if l.startswith("retrace_source_reliability")]
        assert data_lines == [], (
            "Expected no source_reliability lines when no sources have been recorded"
        )

    def test_bandit_default_effectiveness_is_half(self, tmp_path: Path) -> None:
        """Arms with no data should report the uninformed prior of 0.5."""
        brain = self._make_brain(tmp_path)
        text = brain.export_prometheus(tmp_path / "m.prom")
        assert 'retrace_bandit_effectiveness{flywheel="lint"} 0.5' in text

    def test_bandit_effectiveness_updates_with_arm(self, tmp_path: Path) -> None:
        brain = self._make_brain(tmp_path)
        brain.learner.ensure_arm("lint")
        brain.learner.arms["lint"].alpha = 9.0
        brain.learner.arms["lint"].beta = 1.0
        text = brain.export_prometheus(tmp_path / "m.prom")
        # effectiveness = 9/(9+1) = 0.9
        assert 'retrace_bandit_effectiveness{flywheel="lint"} 0.9' in text

    # ── ends with newline ────────────────────────────────────────────────────

    def test_output_ends_with_newline(self, tmp_path: Path) -> None:
        brain = self._make_brain(tmp_path)
        text = brain.export_prometheus(tmp_path / "m.prom")
        assert text.endswith("\n")


# ═══════════════════════════════════════════════════════════════════════════
# FlywheelBrain.suggest_auto_fixes
# ═══════════════════════════════════════════════════════════════════════════


class TestSuggestAutoFixes:
    """Tests for the auto-fix suggestion engine."""

    def _make_brain(self, tmp_path: Path) -> FlywheelBrain:
        with patch("flywheel_intelligence.BRAIN_FILE", tmp_path / "brain.json"):
            with patch("flywheel_intelligence.HISTORY_FILE", tmp_path / "history.jsonl"):
                return FlywheelBrain()

    # ── empty / no-issue state ──────────────────────────────────────────────

    def test_empty_state_returns_list(self, tmp_path: Path) -> None:
        import flywheel_intelligence as fi_mod

        with patch("flywheel_intelligence.BRAIN_FILE", tmp_path / "brain.json"):
            with patch("flywheel_intelligence.HISTORY_FILE", tmp_path / "history.jsonl"):
                with patch.object(fi_mod, "REPO_ROOT", tmp_path):
                    brain = FlywheelBrain()
                    suggestions = brain.suggest_auto_fixes()
        assert isinstance(suggestions, list)

    def test_no_src_dir_returns_empty(self, tmp_path: Path) -> None:
        """When the src/retrace directory doesn't exist there are no gap suggestions."""
        import flywheel_intelligence as fi_mod

        with patch("flywheel_intelligence.BRAIN_FILE", tmp_path / "brain.json"):
            with patch("flywheel_intelligence.HISTORY_FILE", tmp_path / "history.jsonl"):
                with patch.object(fi_mod, "REPO_ROOT", tmp_path):
                    brain = FlywheelBrain()
                    suggestions = brain.suggest_auto_fixes()
        # No src/retrace, no matcher.py, no README.md, no docs/examples → no suggestions
        assert suggestions == []

    # ── gaps flywheel: untested source files ────────────────────────────────

    def test_gaps_untested_source_generates_suggestion(self, tmp_path: Path) -> None:
        import flywheel_intelligence as fi_mod

        # Create a source file with no corresponding test
        src_dir = tmp_path / "src" / "retrace"
        src_dir.mkdir(parents=True)
        (src_dir / "my_module.py").write_text("# placeholder\n")
        (tmp_path / "tests").mkdir()

        with patch("flywheel_intelligence.BRAIN_FILE", tmp_path / "brain.json"):
            with patch("flywheel_intelligence.HISTORY_FILE", tmp_path / "history.jsonl"):
                with patch.object(fi_mod, "REPO_ROOT", tmp_path):
                    brain = FlywheelBrain()
                    suggestions = brain.suggest_auto_fixes()

        gaps_suggestions = [s for s in suggestions if s["flywheel"] == "gaps"]
        assert len(gaps_suggestions) >= 1
        s = gaps_suggestions[0]
        assert s["severity"] == "high"
        assert s["auto_fixable"] is True
        assert "my_module.py" in s["description"] or "test_my_module.py" in s["description"]
        assert s["fix_template"] is not None
        assert "TestMyModule" in s["fix_template"] or "class Test" in s["fix_template"]

    def test_gaps_no_suggestion_when_test_exists(self, tmp_path: Path) -> None:
        import flywheel_intelligence as fi_mod

        src_dir = tmp_path / "src" / "retrace"
        src_dir.mkdir(parents=True)
        (src_dir / "my_module.py").write_text("# placeholder\n")
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_my_module.py").write_text("# tests\n")

        with patch("flywheel_intelligence.BRAIN_FILE", tmp_path / "brain.json"):
            with patch("flywheel_intelligence.HISTORY_FILE", tmp_path / "history.jsonl"):
                with patch.object(fi_mod, "REPO_ROOT", tmp_path):
                    brain = FlywheelBrain()
                    suggestions = brain.suggest_auto_fixes()

        gaps_suggestions = [s for s in suggestions if s["flywheel"] == "gaps"]
        assert gaps_suggestions == []

    def test_gaps_ignores_init_py(self, tmp_path: Path) -> None:
        import flywheel_intelligence as fi_mod

        src_dir = tmp_path / "src" / "retrace"
        src_dir.mkdir(parents=True)
        (src_dir / "__init__.py").write_text("")
        (tmp_path / "tests").mkdir()

        with patch("flywheel_intelligence.BRAIN_FILE", tmp_path / "brain.json"):
            with patch("flywheel_intelligence.HISTORY_FILE", tmp_path / "history.jsonl"):
                with patch.object(fi_mod, "REPO_ROOT", tmp_path):
                    brain = FlywheelBrain()
                    suggestions = brain.suggest_auto_fixes()

        gaps_suggestions = [s for s in suggestions if s["flywheel"] == "gaps"]
        assert gaps_suggestions == []

    # ── component_db flywheel: missing categories ───────────────────────────

    def test_component_db_missing_category_suggestion(self, tmp_path: Path) -> None:
        import flywheel_intelligence as fi_mod

        # Create matcher.py missing "fpga" category
        matcher_dir = tmp_path / "src" / "retrace" / "identification"
        matcher_dir.mkdir(parents=True)
        matcher_content = (
            '"category": "mcu"\n'
            '"category": "memory"\n'
            '"category": "regulator"\n'
        )
        (matcher_dir / "matcher.py").write_text(matcher_content)
        (tmp_path / "tests").mkdir()

        with patch("flywheel_intelligence.BRAIN_FILE", tmp_path / "brain.json"):
            with patch("flywheel_intelligence.HISTORY_FILE", tmp_path / "history.jsonl"):
                with patch.object(fi_mod, "REPO_ROOT", tmp_path):
                    brain = FlywheelBrain()
                    suggestions = brain.suggest_auto_fixes()

        db_suggestions = [s for s in suggestions if s["flywheel"] == "component_db"]
        assert len(db_suggestions) >= 1
        categories_mentioned = {s["description"].split("'")[1] for s in db_suggestions}
        # fpga, network, rf, secure_element, sensor, pmic, display, automotive should be missing
        assert "fpga" in categories_mentioned or "rf" in categories_mentioned
        for s in db_suggestions:
            assert s["severity"] == "medium"
            assert s["auto_fixable"] is True
            assert s["fix_template"] is not None
            assert '"category"' in s["fix_template"]

    def test_component_db_no_suggestion_when_all_present(self, tmp_path: Path) -> None:
        import flywheel_intelligence as fi_mod

        matcher_dir = tmp_path / "src" / "retrace" / "identification"
        matcher_dir.mkdir(parents=True)
        all_cats = (
            '"category": "mcu"\n'
            '"category": "memory"\n'
            '"category": "regulator"\n'
            '"category": "fpga"\n'
            '"category": "network"\n'
            '"category": "rf"\n'
            '"category": "secure_element"\n'
            '"category": "sensor"\n'
            '"category": "pmic"\n'
            '"category": "display"\n'
            '"category": "automotive"\n'
        )
        (matcher_dir / "matcher.py").write_text(all_cats)
        (tmp_path / "tests").mkdir()

        with patch("flywheel_intelligence.BRAIN_FILE", tmp_path / "brain.json"):
            with patch("flywheel_intelligence.HISTORY_FILE", tmp_path / "history.jsonl"):
                with patch.object(fi_mod, "REPO_ROOT", tmp_path):
                    brain = FlywheelBrain()
                    suggestions = brain.suggest_auto_fixes()

        db_suggestions = [s for s in suggestions if s["flywheel"] == "component_db"]
        assert db_suggestions == []

    # ── design_audit flywheel: LOW / MISS criteria ──────────────────────────

    def test_design_audit_missing_pip_install(self, tmp_path: Path) -> None:
        import flywheel_intelligence as fi_mod

        (tmp_path / "README.md").write_text(
            "# retrace\n\nA great tool with attack surface detection.\n"
        )
        (tmp_path / "tests").mkdir()

        with patch("flywheel_intelligence.BRAIN_FILE", tmp_path / "brain.json"):
            with patch("flywheel_intelligence.HISTORY_FILE", tmp_path / "history.jsonl"):
                with patch.object(fi_mod, "REPO_ROOT", tmp_path):
                    brain = FlywheelBrain()
                    suggestions = brain.suggest_auto_fixes()

        design_suggestions = [s for s in suggestions if s["flywheel"] == "design_audit"]
        # "pip install" is missing → should be suggested
        pip_sugg = [s for s in design_suggestions if "pip install" in s["description"]]
        assert len(pip_sugg) >= 1
        assert pip_sugg[0]["severity"] == "high"
        assert pip_sugg[0]["auto_fixable"] is True
        assert "pip install" in pip_sugg[0]["fix_template"]

    def test_design_audit_no_pip_suggestion_when_present(self, tmp_path: Path) -> None:
        import flywheel_intelligence as fi_mod

        (tmp_path / "README.md").write_text(
            "# retrace\n\n```bash\npip install retrace\n```\n\n"
            "attack surface detection.\n"
            "tests: 1320  loc: 8000\n"
        )
        (tmp_path / "tests").mkdir()

        with patch("flywheel_intelligence.BRAIN_FILE", tmp_path / "brain.json"):
            with patch("flywheel_intelligence.HISTORY_FILE", tmp_path / "history.jsonl"):
                with patch.object(fi_mod, "REPO_ROOT", tmp_path):
                    brain = FlywheelBrain()
                    suggestions = brain.suggest_auto_fixes()

        pip_sugg = [
            s for s in suggestions
            if s["flywheel"] == "design_audit" and "pip install" in s["description"]
        ]
        assert pip_sugg == []

    # ── svg_render flywheel ──────────────────────────────────────────────────

    def test_svg_render_missing_viewbox(self, tmp_path: Path) -> None:
        import flywheel_intelligence as fi_mod

        examples_dir = tmp_path / "docs" / "examples"
        examples_dir.mkdir(parents=True)
        # SVG without viewBox
        (examples_dir / "test_output.svg").write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="300">'
            "<rect/></svg>"
        )
        (tmp_path / "tests").mkdir()

        with patch("flywheel_intelligence.BRAIN_FILE", tmp_path / "brain.json"):
            with patch("flywheel_intelligence.HISTORY_FILE", tmp_path / "history.jsonl"):
                with patch.object(fi_mod, "REPO_ROOT", tmp_path):
                    brain = FlywheelBrain()
                    suggestions = brain.suggest_auto_fixes()

        render_sugg = [s for s in suggestions if s["flywheel"] == "svg_render"]
        viewbox_sugg = [s for s in render_sugg if "viewBox" in s["description"]]
        assert len(viewbox_sugg) >= 1
        assert viewbox_sugg[0]["severity"] == "medium"
        assert viewbox_sugg[0]["auto_fixable"] is True

    def test_svg_render_no_suggestion_for_valid_svg(self, tmp_path: Path) -> None:
        import flywheel_intelligence as fi_mod

        examples_dir = tmp_path / "docs" / "examples"
        examples_dir.mkdir(parents=True)
        (examples_dir / "good.svg").write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 300">'
            "<rect/></svg>"
        )
        (tmp_path / "tests").mkdir()

        with patch("flywheel_intelligence.BRAIN_FILE", tmp_path / "brain.json"):
            with patch("flywheel_intelligence.HISTORY_FILE", tmp_path / "history.jsonl"):
                with patch.object(fi_mod, "REPO_ROOT", tmp_path):
                    brain = FlywheelBrain()
                    suggestions = brain.suggest_auto_fixes()

        render_sugg = [s for s in suggestions if s["flywheel"] == "svg_render"]
        assert render_sugg == []

    # ── suggestion schema ────────────────────────────────────────────────────

    def test_all_suggestions_have_required_keys(self, tmp_path: Path) -> None:
        import flywheel_intelligence as fi_mod

        src_dir = tmp_path / "src" / "retrace"
        src_dir.mkdir(parents=True)
        (src_dir / "orphan.py").write_text("# orphan\n")
        (tmp_path / "tests").mkdir()

        with patch("flywheel_intelligence.BRAIN_FILE", tmp_path / "brain.json"):
            with patch("flywheel_intelligence.HISTORY_FILE", tmp_path / "history.jsonl"):
                with patch.object(fi_mod, "REPO_ROOT", tmp_path):
                    brain = FlywheelBrain()
                    suggestions = brain.suggest_auto_fixes()

        required_keys = {"flywheel", "severity", "description", "auto_fixable", "fix_template"}
        for s in suggestions:
            assert required_keys <= s.keys(), f"Missing keys in suggestion: {s}"

    def test_severity_values_are_valid(self, tmp_path: Path) -> None:
        import flywheel_intelligence as fi_mod

        src_dir = tmp_path / "src" / "retrace"
        src_dir.mkdir(parents=True)
        (src_dir / "orphan.py").write_text("# orphan\n")
        (tmp_path / "tests").mkdir()
        (tmp_path / "README.md").write_text("# retrace\n")

        with patch("flywheel_intelligence.BRAIN_FILE", tmp_path / "brain.json"):
            with patch("flywheel_intelligence.HISTORY_FILE", tmp_path / "history.jsonl"):
                with patch.object(fi_mod, "REPO_ROOT", tmp_path):
                    brain = FlywheelBrain()
                    suggestions = brain.suggest_auto_fixes()

        valid_severities = {"high", "medium", "low"}
        for s in suggestions:
            assert s["severity"] in valid_severities, (
                f"Invalid severity {s['severity']!r} in {s}"
            )
