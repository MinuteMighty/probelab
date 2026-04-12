"""Baseline drift detection.

Learns expected match counts from probe history using rolling statistics.
Instead of hard-coded expect_min=20, this module answers: "Is today's
match count within the normal range based on the last N runs?"

Uses a simple but effective approach:
- Rolling mean + standard deviation from recent history
- Configurable sensitivity (number of standard deviations)
- Minimum sample size before engaging (avoids false positives on sparse data)
- Directional awareness (drops are more suspicious than gains)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from probelab.config import load_history


@dataclass
class BaselineStats:
    """Statistical baseline for a single selector's match count."""

    selector: str
    mean: float
    stddev: float
    sample_count: int
    min_seen: int
    max_seen: int
    recent_values: list[int] = field(default_factory=list)


@dataclass
class DriftAlert:
    """A drift detection alert for a selector."""

    selector: str
    current_value: int
    expected_mean: float
    expected_stddev: float
    deviation: float  # How many stddevs away
    direction: str  # "drop" or "spike"
    severity: str  # "warning" (>2 sigma) or "critical" (>3 sigma)
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "selector": self.selector,
            "current": self.current_value,
            "expected_mean": round(self.expected_mean, 1),
            "expected_stddev": round(self.expected_stddev, 1),
            "deviation_sigma": round(self.deviation, 2),
            "direction": self.direction,
            "severity": self.severity,
            "message": self.message,
        }


def compute_baseline(
    probe_name: str,
    window: int = 20,
    min_samples: int = 5,
) -> dict[str, BaselineStats]:
    """Compute baseline statistics from probe history.

    Args:
        probe_name: Name of the probe to analyze.
        window: Number of recent runs to consider.
        min_samples: Minimum history entries before computing stats.

    Returns:
        Dict mapping selector -> BaselineStats.
    """
    history = load_history(probe_name, limit=window)
    if len(history) < min_samples:
        return {}

    # Collect match counts per selector across history
    selector_counts: dict[str, list[int]] = {}
    for entry in history:
        for check in entry.get("checks", []):
            sel = check.get("selector", "")
            count = check.get("match_count", 0)
            if sel:
                selector_counts.setdefault(sel, []).append(count)

    baselines: dict[str, BaselineStats] = {}
    for selector, counts in selector_counts.items():
        if len(counts) < min_samples:
            continue

        mean = sum(counts) / len(counts)
        variance = sum((x - mean) ** 2 for x in counts) / len(counts)
        stddev = math.sqrt(variance)

        baselines[selector] = BaselineStats(
            selector=selector,
            mean=mean,
            stddev=stddev,
            sample_count=len(counts),
            min_seen=min(counts),
            max_seen=max(counts),
            recent_values=counts[-10:],
        )

    return baselines


def detect_drift(
    baselines: dict[str, BaselineStats],
    current_checks: list[dict[str, Any]],
    warning_sigma: float = 2.0,
    critical_sigma: float = 3.0,
) -> list[DriftAlert]:
    """Detect anomalous deviations from baseline.

    Args:
        baselines: Baseline stats computed from history.
        current_checks: Check results from the current probe run.
        warning_sigma: Standard deviations for a warning (default 2.0).
        critical_sigma: Standard deviations for a critical alert (default 3.0).

    Returns:
        List of DriftAlert objects for any anomalous selectors.
    """
    alerts: list[DriftAlert] = []

    for check in current_checks:
        selector = check.get("selector", "")
        current = check.get("match_count", 0)

        baseline = baselines.get(selector)
        if baseline is None:
            continue

        # Guard: if stddev is 0 (all historical values identical), use a
        # minimum sensitivity floor so that ANY change is flagged
        effective_stddev = max(baseline.stddev, 1.0)

        deviation = abs(current - baseline.mean) / effective_stddev

        if deviation < warning_sigma:
            continue

        direction = "drop" if current < baseline.mean else "spike"

        # Drops are more suspicious than spikes for scraper health
        # (fewer matches usually means the page changed or selector broke)
        if direction == "drop":
            severity = "critical" if deviation >= critical_sigma else "warning"
        else:
            severity = "warning" if deviation >= critical_sigma else "info"
            if severity == "info":
                continue  # Don't alert on mild spikes

        message = (
            f"{selector}: got {current} matches, expected ~{baseline.mean:.0f} "
            f"(+/-{effective_stddev:.1f}). "
            f"{'Drop' if direction == 'drop' else 'Spike'} of {deviation:.1f} sigma."
        )

        alerts.append(DriftAlert(
            selector=selector,
            current_value=current,
            expected_mean=baseline.mean,
            expected_stddev=effective_stddev,
            deviation=deviation,
            direction=direction,
            severity=severity,
            message=message,
        ))

    return alerts


def suggest_expectations(baselines: dict[str, BaselineStats]) -> dict[str, dict[str, int]]:
    """Suggest expect_min/expect_max values based on historical data.

    Uses mean - 2*stddev for min and mean + 2*stddev for max,
    clamped to observed ranges.
    """
    suggestions: dict[str, dict[str, int]] = {}
    for selector, stats in baselines.items():
        suggested_min = max(1, int(stats.mean - 2 * stats.stddev))
        suggested_max = int(stats.mean + 2 * stats.stddev) + 1

        # Clamp to observed range with some margin
        suggested_min = max(suggested_min, max(1, stats.min_seen - 2))
        suggested_max = min(suggested_max, stats.max_seen + 5)

        suggestions[selector] = {
            "expect_min": suggested_min,
            "expect_max": suggested_max,
            "based_on_samples": stats.sample_count,
        }
    return suggestions
