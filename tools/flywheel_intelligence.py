#!/usr/bin/env python3
"""
flywheel_intelligence.py — Self-improving intelligence layer for retrace flywheels.

P0 (safety + fuel): Shadow Scoring, Active Learning Feedback
P1 (steering): Innovation Meta-Learning, Source Quality, Calibration, Confidence
P2 (optimization): Warm-Start cache, Trends/Observability (CUSUM + sparklines)

No external dependencies beyond Python stdlib + numpy (already a retrace dep).
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import statistics
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).parent.parent.resolve()
HISTORY_FILE = REPO_ROOT / ".flywheel_history.jsonl"
BRAIN_FILE = REPO_ROOT / ".flywheel_brain.json"

SPARK_BLOCKS = " ▁▂▃▄▅▆▇█"


# ═══════════════════════════════════════════════════════════════════════════
# P2: Time-Series Store (JSONL append-only)
# ═══════════════════════════════════════════════════════════════════════════


class TimeSeriesStore:
    """Append-only JSONL store for flywheel run history."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path if path is not None else HISTORY_FILE

    def append(self, record: dict[str, Any]) -> None:
        record.setdefault("ts", datetime.now(timezone.utc).isoformat())
        with open(self.path, "a") as f:
            f.write(json.dumps(record, default=str) + "\n")

    def read_all(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        records: list[dict[str, Any]] = []
        for line in self.path.read_text().splitlines():
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return records

    def read_last(self, n: int = 50) -> list[dict[str, Any]]:
        all_records = self.read_all()
        return all_records[-n:]

    def scores_for(self, flywheel: str, n: int = 50) -> list[float]:
        scores: list[float] = []
        for rec in self.read_all():
            fw_data = rec.get("flywheels", {}).get(flywheel, {})
            if "score" in fw_data:
                scores.append(fw_data["score"])
        return scores[-n:]


# ═══════════════════════════════════════════════════════════════════════════
# P2: Warm-Start Cache (git hash invalidation)
# ═══════════════════════════════════════════════════════════════════════════

FLYWHEEL_DEPS: dict[str, list[str]] = {
    "stats": ["tools/readme_stats.py", "README.md"],
    "lint": ["src/", "tests/"],
    "tests": ["src/", "tests/"],
    "demo": ["tools/generate_demo.py", "src/retrace/export/"],
    "coverage": ["src/", "tests/"],
    "gaps": ["src/", "tests/"],
    "regression": [],  # always runs (uses state)
    "component_db": ["src/retrace/identification/matcher.py"],
    "design_audit": ["README.md"],
    "svg_audit": ["src/retrace/export/svg.py", "src/retrace/export/pinout_diagram.py", "src/retrace/export/bom.py"],
    "readme_format": ["README.md"],
    "svg_render": ["docs/examples/"],
}


class WarmStartCache:
    """Skip unchanged flywheels using git tree hashes."""

    def __init__(self, brain: dict[str, Any]) -> None:
        self.cache: dict[str, str] = brain.get("warm_cache", {})
        self.hits = 0
        self.misses = 0

    def _compute_hash(self, globs: list[str]) -> str:
        if not globs:
            return "always-run"
        try:
            result = subprocess.run(
                ["git", "ls-files", "-s", "--"] + globs,
                capture_output=True, text=True, cwd=REPO_ROOT,
            )
            if result.returncode == 0 and result.stdout.strip():
                return hashlib.sha256(result.stdout.encode()).hexdigest()[:16]
        except Exception:
            pass
        combined = ""
        for g in globs:
            p = REPO_ROOT / g
            if p.is_file():
                combined += f"{p}:{p.stat().st_mtime_ns}\n"
            elif p.is_dir():
                for f in sorted(p.rglob("*.py")):
                    combined += f"{f}:{f.stat().st_mtime_ns}\n"
        return hashlib.sha256(combined.encode()).hexdigest()[:16]

    def is_cached(self, flywheel: str) -> bool:
        deps = FLYWHEEL_DEPS.get(flywheel, [])
        if not deps:
            return False
        current_hash = self._compute_hash(deps)
        cached_hash = self.cache.get(flywheel)
        if current_hash == cached_hash:
            self.hits += 1
            return True
        self.misses += 1
        return False

    def update(self, flywheel: str) -> None:
        deps = FLYWHEEL_DEPS.get(flywheel, [])
        if deps:
            self.cache[flywheel] = self._compute_hash(deps)

    def export(self) -> dict[str, str]:
        return dict(self.cache)


# ═══════════════════════════════════════════════════════════════════════════
# P0: Shadow Scoring
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class ShadowResult:
    flywheel: str
    production_score: float
    shadow_score: float
    algorithm: str
    delta: float = 0.0
    diverged: bool = False

    def __post_init__(self) -> None:
        self.delta = self.shadow_score - self.production_score
        self.diverged = abs(self.delta) > 15.0


class ShadowScorer:
    """Run experimental scoring alongside production. Champion/challenger pattern."""

    def __init__(self, brain: dict[str, Any]) -> None:
        self.results: list[ShadowResult] = []
        self.history: list[dict[str, Any]] = brain.get("shadow_history", [])
        self._challengers: dict[str, Any] = {}

    def register_challenger(self, flywheel: str, algorithm: str, scorer: Any) -> None:
        self._challengers[flywheel] = (algorithm, scorer)

    def run_shadow(self, flywheel: str, production_score: float, **kwargs: Any) -> ShadowResult | None:
        if flywheel not in self._challengers:
            return None
        algorithm, scorer = self._challengers[flywheel]
        try:
            shadow_score = scorer(**kwargs)
        except Exception:
            return None
        result = ShadowResult(
            flywheel=flywheel,
            production_score=production_score,
            shadow_score=shadow_score,
            algorithm=algorithm,
        )
        self.results.append(result)
        self.history.append(asdict(result))
        self.history = self.history[-200:]
        return result

    def agreement_rate(self, flywheel: str) -> float:
        relevant = [r for r in self.history if r["flywheel"] == flywheel]
        if len(relevant) < 5:
            return 1.0
        agreements = sum(1 for r in relevant if not r["diverged"])
        return agreements / len(relevant)

    def psi(self, flywheel: str) -> float:
        """Population Stability Index between production and shadow distributions."""
        relevant = [r for r in self.history if r["flywheel"] == flywheel]
        if len(relevant) < 10:
            return 0.0
        prod = [r["production_score"] for r in relevant[-50:]]
        shadow = [r["shadow_score"] for r in relevant[-50:]]
        return _compute_psi(prod, shadow)

    def promotion_eligible(self, flywheel: str) -> bool:
        return (
            self.agreement_rate(flywheel) > 0.95
            and self.psi(flywheel) < 0.1
            and len([r for r in self.history if r["flywheel"] == flywheel]) >= 50
        )

    def export(self) -> list[dict[str, Any]]:
        return self.history


def _compute_psi(expected: list[float], actual: list[float], bins: int = 10) -> float:
    if not expected or not actual:
        return 0.0
    lo = min(min(expected), min(actual))
    hi = max(max(expected), max(actual))
    if hi == lo:
        return 0.0
    bin_edges = [lo + i * (hi - lo) / bins for i in range(bins + 1)]
    eps = 1e-6

    def bin_pcts(values: list[float]) -> list[float]:
        counts = [0] * bins
        for v in values:
            idx = min(int((v - lo) / (hi - lo) * bins), bins - 1)
            counts[idx] += 1
        total = len(values)
        return [(c / total) + eps for c in counts]

    e_pcts = bin_pcts(expected)
    a_pcts = bin_pcts(actual)
    return sum((a - e) * math.log(a / e) for a, e in zip(a_pcts, e_pcts))


# ═══════════════════════════════════════════════════════════════════════════
# P0: Active Learning Feedback (Thompson Sampling)
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class BanditArm:
    flywheel: str
    alpha: float = 1.0
    beta: float = 1.0
    total_pulls: int = 0
    consecutive_runs: int = 0
    last_delta: float = 0.0

    def sample(self) -> float:
        return random.betavariate(self.alpha, self.beta)

    def update(self, improved: bool) -> None:
        self.total_pulls += 1
        if improved:
            self.alpha += 1.0
        else:
            self.beta += 0.5  # softer penalty — neutral ≠ bad

    @property
    def effectiveness(self) -> float:
        return self.alpha / (self.alpha + self.beta)


class ActiveLearner:
    """Thompson Sampling bandit over flywheels. Learns which produce most value."""

    COOLDOWN = 3
    EXPLORATION_FLOOR = 2

    def __init__(self, brain: dict[str, Any]) -> None:
        arms_data = brain.get("bandit_arms", {})
        self.arms: dict[str, BanditArm] = {}
        for fw, data in arms_data.items():
            self.arms[fw] = BanditArm(**data)

    def ensure_arm(self, flywheel: str) -> None:
        if flywheel not in self.arms:
            self.arms[flywheel] = BanditArm(flywheel=flywheel)

    def rank_flywheels(self, flywheels: list[str]) -> list[str]:
        for fw in flywheels:
            self.ensure_arm(fw)
        sampled = []
        forced_explore: list[str] = []
        cooled_down: list[str] = []
        for fw in flywheels:
            arm = self.arms[fw]
            if arm.consecutive_runs >= self.COOLDOWN:
                cooled_down.append(fw)
                continue
            sampled.append((arm.sample(), fw))
        sampled.sort(reverse=True)
        ranked = [fw for _, fw in sampled]
        by_pulls = sorted(flywheels, key=lambda fw: self.arms[fw].total_pulls)
        for fw in by_pulls[:self.EXPLORATION_FLOOR]:
            if fw not in ranked:
                ranked.append(fw)
        ranked.extend(cooled_down)
        return ranked

    def record_outcome(self, flywheel: str, score_before: float, score_after: float, had_changes: bool) -> None:
        self.ensure_arm(flywheel)
        arm = self.arms[flywheel]
        if not had_changes:
            return  # don't learn from no-ops
        delta = score_after - score_before
        arm.last_delta = delta
        improved = delta > 0
        arm.update(improved)
        arm.consecutive_runs += 1

    def reset_consecutive(self, flywheel: str) -> None:
        if flywheel in self.arms:
            self.arms[flywheel].consecutive_runs = 0

    def export(self) -> dict[str, dict[str, Any]]:
        return {fw: asdict(arm) for fw, arm in self.arms.items()}

    def top_performers(self, n: int = 5) -> list[tuple[str, float]]:
        ranked = sorted(self.arms.items(), key=lambda x: x[1].effectiveness, reverse=True)
        return [(fw, arm.effectiveness) for fw, arm in ranked[:n]]


# ═══════════════════════════════════════════════════════════════════════════
# P1: Innovation Meta-Learning
# ═══════════════════════════════════════════════════════════════════════════

INNOVATION_CATEGORIES = [
    "new_flywheel", "new_check", "expanded_db", "code_fix",
    "test_added", "config_tuned", "doc_improved",
]


@dataclass
class InnovationArm:
    category: str
    alpha: float = 1.0
    beta: float = 1.0
    total_pulls: int = 0
    cumulative_value: float = 0.0

    def sample(self) -> float:
        return random.betavariate(self.alpha, self.beta)

    @property
    def mean(self) -> float:
        return self.alpha / (self.alpha + self.beta)


class MetaLearner:
    """Thompson Sampling over innovation categories. Steers future work."""

    def __init__(self, brain: dict[str, Any]) -> None:
        data = brain.get("innovation_arms", {})
        self.arms: dict[str, InnovationArm] = {}
        for cat in INNOVATION_CATEGORIES:
            if cat in data:
                self.arms[cat] = InnovationArm(**data[cat])
            else:
                self.arms[cat] = InnovationArm(category=cat)

    def record_innovation(self, category: str, value_delta: float) -> None:
        if category not in self.arms:
            self.arms[category] = InnovationArm(category=category)
        arm = self.arms[category]
        arm.total_pulls += 1
        arm.cumulative_value += value_delta
        if value_delta > 0.5:
            arm.alpha += 1.0
        elif value_delta < -0.5:
            arm.beta += 1.0
        else:
            arm.beta += 0.3  # neutral is mildly negative

    def recommend_next(self, n: int = 3) -> list[str]:
        sampled = [(arm.sample(), cat) for cat, arm in self.arms.items()]
        sampled.sort(reverse=True)
        return [cat for _, cat in sampled[:n]]

    def export(self) -> dict[str, dict[str, Any]]:
        return {cat: asdict(arm) for cat, arm in self.arms.items()}

    def summary(self) -> list[tuple[str, float, int]]:
        return sorted(
            [(cat, arm.mean, arm.total_pulls) for cat, arm in self.arms.items()],
            key=lambda x: x[1], reverse=True,
        )


# ═══════════════════════════════════════════════════════════════════════════
# P1: Source Quality Tracker
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class SourceQuality:
    source_id: str
    ema_reliability: float = 1.0
    variance_window: list[float] = field(default_factory=list)
    failure_streak: int = 0

    EMA_ALPHA = 0.1
    WINDOW_SIZE = 20

    def record_success(self, score: float) -> None:
        self.ema_reliability = (1 - self.EMA_ALPHA) * self.ema_reliability + self.EMA_ALPHA * 1.0
        self.failure_streak = 0
        self.variance_window.append(score)
        self.variance_window = self.variance_window[-self.WINDOW_SIZE:]

    def record_failure(self) -> None:
        self.ema_reliability = (1 - self.EMA_ALPHA) * self.ema_reliability + self.EMA_ALPHA * 0.0
        self.failure_streak += 1

    @property
    def is_reliable(self) -> bool:
        return self.ema_reliability >= 0.7 and self.failure_streak < 3

    @property
    def variance(self) -> float:
        if len(self.variance_window) < 3:
            return 0.0
        return statistics.stdev(self.variance_window)


class SourceQualityTracker:
    """EMA-based reliability tracking per data source."""

    def __init__(self, brain: dict[str, Any]) -> None:
        data = brain.get("source_quality", {})
        self.sources: dict[str, SourceQuality] = {}
        for sid, sdata in data.items():
            self.sources[sid] = SourceQuality(**sdata)

    def get(self, source_id: str) -> SourceQuality:
        if source_id not in self.sources:
            self.sources[source_id] = SourceQuality(source_id=source_id)
        return self.sources[source_id]

    def record(self, source_id: str, success: bool, score: float = 0.0) -> None:
        sq = self.get(source_id)
        if success:
            sq.record_success(score)
        else:
            sq.record_failure()

    def unreliable_sources(self) -> list[str]:
        return [sid for sid, sq in self.sources.items() if not sq.is_reliable]

    def export(self) -> dict[str, dict[str, Any]]:
        return {sid: asdict(sq) for sid, sq in self.sources.items()}


# ═══════════════════════════════════════════════════════════════════════════
# P1: Calibration (drift detection + Platt scaling)
# ═══════════════════════════════════════════════════════════════════════════


class Calibrator:
    """Detect score inflation and apply calibration corrections."""

    def __init__(self, brain: dict[str, Any]) -> None:
        self.calibration: dict[str, dict[str, Any]] = brain.get("calibration", {})

    def record_score(self, flywheel: str, raw_score: float) -> None:
        if flywheel not in self.calibration:
            self.calibration[flywheel] = {
                "raw_history": [],
                "p90_baseline": None,
                "offset": 0.0,
                "anchors": [],
            }
        cal = self.calibration[flywheel]
        cal["raw_history"].append(raw_score)
        cal["raw_history"] = cal["raw_history"][-100:]

    def add_anchor(self, flywheel: str, raw_score: float, ground_truth: float) -> None:
        """Manual calibration point from human review."""
        if flywheel not in self.calibration:
            self.calibration[flywheel] = {"raw_history": [], "p90_baseline": None, "offset": 0.0, "anchors": []}
        self.calibration[flywheel]["anchors"].append({
            "raw": raw_score, "truth": ground_truth,
            "ts": datetime.now(timezone.utc).isoformat(),
        })
        self.calibration[flywheel]["anchors"] = self.calibration[flywheel]["anchors"][-50:]
        self._refit(flywheel)

    def _refit(self, flywheel: str) -> None:
        anchors = self.calibration[flywheel].get("anchors", [])
        if len(anchors) < 3:
            return
        raw_scores = [a["raw"] for a in anchors]
        truths = [a["truth"] for a in anchors]
        mean_raw = statistics.mean(raw_scores)
        mean_truth = statistics.mean(truths)
        self.calibration[flywheel]["offset"] = mean_truth - mean_raw

    def calibrated_score(self, flywheel: str, raw_score: float) -> float:
        if flywheel not in self.calibration:
            return raw_score
        offset = self.calibration[flywheel].get("offset", 0.0)
        return max(0.0, min(100.0, raw_score + offset))

    def detect_inflation(self, flywheel: str) -> str | None:
        """Check if 90th percentile drifted up >5pts without known improvement."""
        cal = self.calibration.get(flywheel, {})
        history = cal.get("raw_history", [])
        if len(history) < 20:
            return None
        recent_p90 = sorted(history[-10:])[-2] if len(history[-10:]) >= 2 else history[-1]
        baseline_p90 = cal.get("p90_baseline")
        if baseline_p90 is None:
            cal["p90_baseline"] = recent_p90
            return None
        if recent_p90 - baseline_p90 > 5.0:
            return f"{flywheel}: p90 drifted {baseline_p90:.0f}→{recent_p90:.0f} (+{recent_p90 - baseline_p90:.1f}pts)"
        cal["p90_baseline"] = recent_p90
        return None

    def export(self) -> dict[str, dict[str, Any]]:
        return dict(self.calibration)


# ═══════════════════════════════════════════════════════════════════════════
# P1: Confidence Estimation (Bootstrap CI)
# ═══════════════════════════════════════════════════════════════════════════


class ConfidenceEstimator:
    """Bootstrap confidence intervals for flywheel scores."""

    def __init__(self, store: TimeSeriesStore) -> None:
        self.store = store

    def compute_ci(self, flywheel: str, confidence: float = 0.95, n_boot: int = 500) -> tuple[float, float, float]:
        """Returns (mean, ci_low, ci_high)."""
        scores = self.store.scores_for(flywheel, n=50)
        if len(scores) < 5:
            if scores:
                m = statistics.mean(scores)
                return m, m, m
            return 0.0, 0.0, 0.0
        boot_means: list[float] = []
        for _ in range(n_boot):
            sample = random.choices(scores, k=len(scores))
            boot_means.append(statistics.mean(sample))
        boot_means.sort()
        alpha = (1 - confidence) / 2
        lo_idx = int(alpha * n_boot)
        hi_idx = int((1 - alpha) * n_boot) - 1
        mean = statistics.mean(scores)
        return mean, boot_means[lo_idx], boot_means[hi_idx]

    def ci_width(self, flywheel: str) -> float:
        _, lo, hi = self.compute_ci(flywheel)
        return hi - lo

    def is_stable(self, flywheel: str, threshold: float = 5.0) -> bool:
        return self.ci_width(flywheel) < threshold


# ═══════════════════════════════════════════════════════════════════════════
# P2: Trend Analyzer (CUSUM + sparklines)
# ═══════════════════════════════════════════════════════════════════════════


class TrendAnalyzer:
    """CUSUM changepoint detection + terminal sparklines."""

    def __init__(self, store: TimeSeriesStore) -> None:
        self.store = store

    @staticmethod
    def sparkline(values: list[float], width: int = 20) -> str:
        if not values:
            return ""
        if len(values) > width:
            step = len(values) / width
            sampled = [values[int(i * step)] for i in range(width)]
        else:
            sampled = values
        lo, hi = min(sampled), max(sampled)
        rng = hi - lo or 1.0
        return "".join(SPARK_BLOCKS[min(8, int((v - lo) / rng * 8))] for v in sampled)

    @staticmethod
    def cusum_detect(scores: list[float], k: float = 0.5, h: float = 4.0) -> str:
        """CUSUM changepoint detection. Returns 'regression', 'breakthrough', or 'stable'."""
        if len(scores) < 5:
            return "insufficient_data"
        mu = statistics.mean(scores[:5])
        sigma = max(1e-6, statistics.stdev(scores[:5]))
        s_pos, s_neg = 0.0, 0.0
        for s in scores[5:]:
            s_pos = max(0, s_pos + (s - mu) / sigma - k)
            s_neg = max(0, s_neg - (s - mu) / sigma - k)
            if s_pos > h:
                return "breakthrough"
            if s_neg > h:
                return "regression"
        if len(scores) >= 10:
            recent_var = statistics.variance(scores[-10:]) if len(scores[-10:]) >= 2 else 0
            if recent_var < 0.01:
                return "stalled"
        return "stable"

    def analyze_flywheel(self, flywheel: str) -> dict[str, Any]:
        scores = self.store.scores_for(flywheel, n=50)
        if not scores:
            return {"flywheel": flywheel, "status": "no_data", "sparkline": ""}
        trend = self.cusum_detect(scores)
        spark = self.sparkline(scores)
        result: dict[str, Any] = {
            "flywheel": flywheel,
            "status": trend,
            "sparkline": spark,
            "current": scores[-1],
            "runs": len(scores),
        }
        if len(scores) >= 2:
            result["delta"] = scores[-1] - scores[-2]
            result["mean"] = statistics.mean(scores)
            if len(scores) >= 3:
                result["stdev"] = statistics.stdev(scores)
        return result

    def analyze_all(self, flywheels: list[str]) -> list[dict[str, Any]]:
        return [self.analyze_flywheel(fw) for fw in flywheels]


# ═══════════════════════════════════════════════════════════════════════════
# Brain: unified persistence for all intelligence state
# ═══════════════════════════════════════════════════════════════════════════


class FlywheelBrain:
    """Unified intelligence state manager. Coordinates all P0/P1/P2 subsystems."""

    ALL_FLYWHEELS = [
        "stats", "lint", "tests", "demo", "coverage", "gaps",
        "regression", "component_db", "design_audit", "svg_audit",
        "readme_format", "svg_render",
    ]

    def __init__(self) -> None:
        self._brain = self._load()
        self.store = TimeSeriesStore(HISTORY_FILE)
        self.cache = WarmStartCache(self._brain)
        self.shadow = ShadowScorer(self._brain)
        self.learner = ActiveLearner(self._brain)
        self.meta = MetaLearner(self._brain)
        self.sources = SourceQualityTracker(self._brain)
        self.calibrator = Calibrator(self._brain)
        self.confidence = ConfidenceEstimator(self.store)
        self.trends = TrendAnalyzer(self.store)

    def _load(self) -> dict[str, Any]:
        if BRAIN_FILE.exists():
            try:
                return json.loads(BRAIN_FILE.read_text())
            except Exception:
                pass
        return {}

    def save(self) -> None:
        self._brain["warm_cache"] = self.cache.export()
        self._brain["shadow_history"] = self.shadow.export()
        self._brain["bandit_arms"] = self.learner.export()
        self._brain["innovation_arms"] = self.meta.export()
        self._brain["source_quality"] = self.sources.export()
        self._brain["calibration"] = self.calibrator.export()
        self._brain["last_save"] = datetime.now(timezone.utc).isoformat()
        self._brain["version"] = 1
        BRAIN_FILE.write_text(json.dumps(self._brain, indent=2, default=str))

    def record_run(self, flywheel_scores: dict[str, float], git_hash: str = "", mode: str = "full") -> None:
        record: dict[str, Any] = {
            "git_hash": git_hash,
            "mode": mode,
            "flywheels": {},
        }
        for fw, score in flywheel_scores.items():
            record["flywheels"][fw] = {"score": score}
            self.calibrator.record_score(fw, score)
            self.cache.update(fw)
        self.store.append(record)

    def get_trend_report(self) -> list[dict[str, Any]]:
        return self.trends.analyze_all(self.ALL_FLYWHEELS)

    def get_confidence_report(self) -> dict[str, tuple[float, float, float]]:
        report: dict[str, tuple[float, float, float]] = {}
        for fw in self.ALL_FLYWHEELS:
            report[fw] = self.confidence.compute_ci(fw)
        return report

    def get_inflation_warnings(self) -> list[str]:
        warnings: list[str] = []
        for fw in self.ALL_FLYWHEELS:
            w = self.calibrator.detect_inflation(fw)
            if w:
                warnings.append(w)
        return warnings

    def quality_gate(self, current_scores: dict[str, float]) -> tuple[bool, list[str]]:
        """Hold-the-line gate: fail if any flywheel score drops below its historical floor."""
        violations: list[str] = []
        floors = self._brain.get("quality_floors", {})
        for fw, score in current_scores.items():
            floor = floors.get(fw)
            if floor is not None and score < floor:
                violations.append(f"{fw}: {score:.0f} < floor {floor:.0f}")
            if floor is None or score > floor:
                floors[fw] = score
        self._brain["quality_floors"] = floors
        return len(violations) == 0, violations

    def explain_regression(self, flywheel: str) -> str | None:
        """Generate human-readable explanation when a score drops >5 points."""
        scores = self.store.scores_for(flywheel, n=10)
        if len(scores) < 2:
            return None
        delta = scores[-1] - scores[-2]
        if delta >= -5:
            return None
        records = self.store.read_last(2)
        if len(records) < 2:
            return None
        prev_hash = records[-2].get("git_hash", "")
        curr_hash = records[-1].get("git_hash", "")
        explanation = f"{flywheel} dropped {scores[-2]:.0f}→{scores[-1]:.0f} ({delta:+.0f}pts)"
        if prev_hash and curr_hash and prev_hash != curr_hash:
            try:
                result = subprocess.run(
                    ["git", "diff", "--stat", prev_hash, curr_hash],
                    capture_output=True, text=True, cwd=REPO_ROOT,
                )
                if result.returncode == 0:
                    changed_files = [
                        line.split("|")[0].strip()
                        for line in result.stdout.splitlines()
                        if "|" in line
                    ]
                    if changed_files:
                        explanation += f" after changes to: {', '.join(changed_files[:5])}"
                        if len(changed_files) > 5:
                            explanation += f" (+{len(changed_files) - 5} more)"
            except Exception:
                pass
        return explanation

    def get_regression_explanations(self) -> list[str]:
        explanations: list[str] = []
        for fw in self.ALL_FLYWHEELS:
            exp = self.explain_regression(fw)
            if exp:
                explanations.append(exp)
        return explanations

    def generate_heatmap_svg(self, output_path: "Path | None" = None) -> str:
        """Generate a GitHub-style 52-week x 7-day contribution heatmap SVG.

        Reads .flywheel_history.jsonl, aggregates daily flywheel score deltas,
        and renders a self-contained SVG using the retrace dark theme.

        Cell intensity encodes the aggregate flywheel score delta for that day:
        - Improvements: dark blue (#111827) through cyan (#22d3ee) to green (#22c55e)
        - Regressions: red (#ef4444)
        - No data: dark (#111827)

        Args:
            output_path: Where to write the SVG. Defaults to
                         docs/examples/flywheel_heatmap.svg.

        Returns:
            The SVG content as a string (also written to output_path).
        """
        from collections import defaultdict
        from datetime import date, timedelta

        if output_path is None:
            output_path = REPO_ROOT / "docs" / "examples" / "flywheel_heatmap.svg"

        # ── 1. Load history ──────────────────────────────────────────────────
        records = self.store.read_all()

        # Build dict: date_str → list of per-record mean flywheel scores
        daily_scores: dict[str, list[float]] = defaultdict(list)
        for rec in records:
            ts_raw = rec.get("ts", "")
            if not ts_raw:
                continue
            try:
                dt = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
            except ValueError:
                continue
            date_str = dt.date().isoformat()
            fw_data = rec.get("flywheels", {})
            scores_in_rec = [
                v["score"]
                for v in fw_data.values()
                if isinstance(v, dict) and "score" in v
            ]
            if scores_in_rec:
                daily_scores[date_str].append(sum(scores_in_rec) / len(scores_in_rec))

        # ── 2. Compute per-day deltas ─────────────────────────────────────────
        sorted_dates = sorted(daily_scores.keys())
        daily_avg: dict[str, float] = {
            d: sum(daily_scores[d]) / len(daily_scores[d]) for d in sorted_dates
        }
        daily_delta: dict[str, float] = {}
        prev_avg: float | None = None
        for d in sorted_dates:
            avg = daily_avg[d]
            daily_delta[d] = avg - prev_avg if prev_avg is not None else 0.0
            prev_avg = avg

        # ── 3. Build the 52-week calendar grid ──────────────────────────────
        today = datetime.now(timezone.utc).date()
        # Find the Sunday on or before today (isoweekday: Mon=1…Sun=7)
        dow = today.isoweekday() % 7   # Sun=0, Mon=1 … Sat=6
        grid_end = today - timedelta(days=dow)            # last Sunday <= today
        grid_start = grid_end - timedelta(weeks=52) + timedelta(days=1)

        # 52 columns × 7 rows — column-major order (week = column, day = row)
        grid: list[tuple[date, float]] = []
        for week in range(52):
            for dow_offset in range(7):
                d = grid_start + timedelta(weeks=week, days=dow_offset)
                delta = daily_delta.get(d.isoformat(), 0.0)
                grid.append((d, delta))

        # ── 4. Color helpers ─────────────────────────────────────────────────
        COLOR_EMPTY = "#111827"
        COLOR_IMPROVE_LO = "#22d3ee"   # cyan
        COLOR_IMPROVE_HI = "#22c55e"   # green
        COLOR_REGRESS_LO = "#7f1d1d"
        COLOR_REGRESS_HI = "#ef4444"   # red

        non_zero = [abs(dv) for _, dv in grid if dv != 0.0]
        max_abs = max(non_zero) if non_zero else 1.0

        def _lerp_hex(c1: str, c2: str, t: float) -> str:
            r1, g1, b1 = int(c1[1:3], 16), int(c1[3:5], 16), int(c1[5:7], 16)
            r2, g2, b2 = int(c2[1:3], 16), int(c2[3:5], 16), int(c2[5:7], 16)
            return (
                f"#{int(r1 + (r2 - r1) * t):02x}"
                f"{int(g1 + (g2 - g1) * t):02x}"
                f"{int(b1 + (b2 - b1) * t):02x}"
            )

        def _cell_color(delta: float) -> str:
            if delta == 0.0:
                return COLOR_EMPTY
            t = min(1.0, abs(delta) / max_abs)
            if delta > 0:
                return _lerp_hex(COLOR_IMPROVE_LO, COLOR_IMPROVE_HI, t)
            return _lerp_hex(COLOR_REGRESS_LO, COLOR_REGRESS_HI, t)

        # ── 5. SVG layout constants ───────────────────────────────────────────
        CELL = 11
        GAP = 2
        STEP = CELL + GAP
        MARGIN_LEFT = 32
        MARGIN_TOP = 28
        MARGIN_RIGHT = 12
        MARGIN_BOTTOM = 20

        SVG_W = MARGIN_LEFT + 52 * STEP + MARGIN_RIGHT
        SVG_H = MARGIN_TOP + 7 * STEP + MARGIN_BOTTOM

        BG = "#0a0e1a"
        TEXT_COLOR = "#94a3b8"
        FONT = "JetBrains Mono, monospace"

        # ── 6. Month label positions ──────────────────────────────────────────
        MONTH_ABBR = [
            "Jan", "Feb", "Mar", "Apr", "May", "Jun",
            "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
        ]
        month_labels: list[tuple[int, str]] = []
        prev_month: int | None = None
        for week in range(52):
            d = grid_start + timedelta(weeks=week)
            if d.month != prev_month:
                col_x = MARGIN_LEFT + week * STEP
                month_labels.append((col_x, MONTH_ABBR[d.month - 1]))
                prev_month = d.month

        # Visible day-of-week rows (Mon=1, Wed=3, Fri=5)
        DOW_VISIBLE = {1: "Mon", 3: "Wed", 5: "Fri"}

        # ── 7. Build SVG ──────────────────────────────────────────────────────
        parts: list[str] = []
        parts.append(
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'width="{SVG_W}" height="{SVG_H}" '
            f'viewBox="0 0 {SVG_W} {SVG_H}" '
            f'style="background:{BG};">'
        )
        parts.append(
            f'<rect width="{SVG_W}" height="{SVG_H}" fill="{BG}" rx="6"/>'
        )

        # Month labels along the top
        for col_x, label in month_labels:
            parts.append(
                f'<text x="{col_x}" y="{MARGIN_TOP - 6}" '
                f'font-size="9" fill="{TEXT_COLOR}" '
                f'font-family="{FONT}">{label}</text>'
            )

        # Day-of-week labels on the left
        for row, label in DOW_VISIBLE.items():
            cy = MARGIN_TOP + row * STEP + CELL // 2 + 3
            parts.append(
                f'<text x="{MARGIN_LEFT - 4}" y="{cy}" '
                f'font-size="8" fill="{TEXT_COLOR}" '
                f'text-anchor="end" font-family="{FONT}">{label}</text>'
            )

        # Cell grid
        for idx, (d, delta) in enumerate(grid):
            week = idx // 7
            row = idx % 7
            cx = MARGIN_LEFT + week * STEP
            cy = MARGIN_TOP + row * STEP
            color = _cell_color(delta)
            iso = d.isoformat()
            tip = f"{iso}: {delta:+.1f}" if delta != 0.0 else iso
            parts.append(
                f'<rect x="{cx}" y="{cy}" width="{CELL}" height="{CELL}" '
                f'rx="2" fill="{color}"><title>{tip}</title></rect>'
            )

        # Legend (bottom-right)
        legend_colors = [
            COLOR_EMPTY,
            _lerp_hex(COLOR_IMPROVE_LO, COLOR_IMPROVE_HI, 0.25),
            _lerp_hex(COLOR_IMPROVE_LO, COLOR_IMPROVE_HI, 0.5),
            _lerp_hex(COLOR_IMPROVE_LO, COLOR_IMPROVE_HI, 0.75),
            COLOR_IMPROVE_HI,
        ]
        LEGEND_X = SVG_W - MARGIN_RIGHT - len(legend_colors) * STEP - 44
        LEGEND_Y = SVG_H - MARGIN_BOTTOM + 4
        parts.append(
            f'<text x="{LEGEND_X - 4}" y="{LEGEND_Y + CELL - 2}" '
            f'font-size="8" fill="{TEXT_COLOR}" text-anchor="end" '
            f'font-family="{FONT}">less</text>'
        )
        for i, lc in enumerate(legend_colors):
            lx = LEGEND_X + i * STEP
            parts.append(
                f'<rect x="{lx}" y="{LEGEND_Y}" width="{CELL}" height="{CELL}" '
                f'rx="2" fill="{lc}"/>'
            )
        after_x = LEGEND_X + len(legend_colors) * STEP + 4
        parts.append(
            f'<text x="{after_x}" y="{LEGEND_Y + CELL - 2}" '
            f'font-size="8" fill="{TEXT_COLOR}" '
            f'font-family="{FONT}">more</text>'
        )

        parts.append("</svg>")
        svg_content = "\n".join(parts)

        # ── 8. Write to disk ──────────────────────────────────────────────────
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(svg_content, encoding="utf-8")
        return svg_content

    def format_brain_summary(self) -> str:
        lines: list[str] = []
        lines.append("═══ Flywheel Brain Summary ═══")
        lines.append("")

        # Active learning effectiveness
        lines.append("▸ Active Learning (Thompson Sampling)")
        top = self.learner.top_performers(5)
        if top:
            for fw, eff in top:
                arm = self.learner.arms[fw]
                lines.append(f"  {fw:20s}  eff={eff:.2f}  α={arm.alpha:.0f} β={arm.beta:.0f}  pulls={arm.total_pulls}")
        else:
            lines.append("  (no data yet — run flywheels to train)")

        # Innovation meta-learning
        lines.append("")
        lines.append("▸ Innovation Meta-Learning")
        for cat, mean, pulls in self.meta.summary():
            lines.append(f"  {cat:20s}  value={mean:.2f}  pulls={pulls}")
        recommended = self.meta.recommend_next(3)
        lines.append(f"  → Next recommended: {', '.join(recommended)}")

        # Source quality
        lines.append("")
        lines.append("▸ Source Quality")
        for sid, sq in self.sources.sources.items():
            status = "✓" if sq.is_reliable else "✗"
            lines.append(f"  {status} {sid:15s}  reliability={sq.ema_reliability:.2f}  var={sq.variance:.3f}")
        unreliable = self.sources.unreliable_sources()
        if unreliable:
            lines.append(f"  ⚠ Unreliable: {', '.join(unreliable)}")

        # Calibration warnings
        warnings = self.get_inflation_warnings()
        if warnings:
            lines.append("")
            lines.append("▸ Calibration Warnings")
            for w in warnings:
                lines.append(f"  ⚠ {w}")

        # Trends
        lines.append("")
        lines.append("▸ Trends (CUSUM)")
        trend_report = self.get_trend_report()
        for t in trend_report:
            if t["status"] == "no_data":
                continue
            spark = t.get("sparkline", "")
            current = t.get("current", "?")
            status_icon = {
                "stable": "→", "breakthrough": "↑", "regression": "↓",
                "stalled": "═", "insufficient_data": "?",
            }.get(t["status"], "?")
            lines.append(f"  {status_icon} {t['flywheel']:20s}  {spark}  {current}")

        # Confidence intervals
        lines.append("")
        lines.append("▸ Confidence (95% CI)")
        ci_report = self.get_confidence_report()
        for fw, (mean, lo, hi) in ci_report.items():
            if mean == 0 and lo == 0:
                continue
            width = hi - lo
            stability = "stable" if width < 5 else "variable" if width < 15 else "unstable"
            lines.append(f"  {fw:20s}  {mean:.1f}% [{lo:.1f}, {hi:.1f}]  ({stability})")

        # Cache stats
        lines.append("")
        lines.append("▸ Warm-Start Cache")
        lines.append(f"  Cached flywheels: {len(self.cache.cache)}")
        lines.append(f"  Session: {self.cache.hits} hits, {self.cache.misses} misses")

        return "\n".join(lines)
