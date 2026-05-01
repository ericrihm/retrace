"""Smoke tests for the flywheel intelligence layer (P0/P1/P2)."""
from __future__ import annotations

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
