"""Tests for baseline drift detection."""

import json
from pathlib import Path

from probelab.baseline import compute_baseline, detect_drift, suggest_expectations, BaselineStats


def _write_history(base: Path, probe_name: str, entries: list[dict]) -> None:
    """Write history entries for testing."""
    history_dir = base / ".probelab" / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    path = history_dir / f"{probe_name}.jsonl"
    with open(path, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


def _make_history_entry(match_count: int, selector: str = "li.item") -> dict:
    return {
        "name": "test",
        "status": "healthy",
        "checks": [
            {"selector": selector, "match_count": match_count, "passed": True}
        ],
        "timestamp": "2026-04-12T10:00:00",
    }


def test_compute_baseline_enough_samples(tmp_probelab, monkeypatch):
    monkeypatch.chdir(tmp_probelab)
    entries = [_make_history_entry(count) for count in [30, 28, 32, 29, 31, 30, 27, 33]]
    _write_history(tmp_probelab, "test", entries)

    baselines = compute_baseline("test")
    assert "li.item" in baselines
    stats = baselines["li.item"]
    assert stats.sample_count == 8
    assert 28 < stats.mean < 32  # Should be around 30
    assert stats.stddev > 0
    assert stats.min_seen == 27
    assert stats.max_seen == 33


def test_compute_baseline_not_enough_samples(tmp_probelab, monkeypatch):
    monkeypatch.chdir(tmp_probelab)
    entries = [_make_history_entry(30) for _ in range(3)]  # Only 3, need 5
    _write_history(tmp_probelab, "test", entries)

    baselines = compute_baseline("test")
    assert baselines == {}


def test_detect_drift_normal():
    """No alert when value is within normal range."""
    baselines = {
        "li.item": BaselineStats(
            selector="li.item", mean=30.0, stddev=2.0,
            sample_count=20, min_seen=26, max_seen=34,
        )
    }
    current = [{"selector": "li.item", "match_count": 29}]
    alerts = detect_drift(baselines, current)
    assert alerts == []


def test_detect_drift_warning():
    """Warning when value is 2+ sigma away."""
    baselines = {
        "li.item": BaselineStats(
            selector="li.item", mean=30.0, stddev=2.0,
            sample_count=20, min_seen=26, max_seen=34,
        )
    }
    current = [{"selector": "li.item", "match_count": 24}]  # 3 sigma drop
    alerts = detect_drift(baselines, current)
    assert len(alerts) == 1
    assert alerts[0].direction == "drop"
    assert alerts[0].severity == "critical"


def test_detect_drift_spike():
    """Alert on unusual spike."""
    baselines = {
        "li.item": BaselineStats(
            selector="li.item", mean=30.0, stddev=2.0,
            sample_count=20, min_seen=26, max_seen=34,
        )
    }
    current = [{"selector": "li.item", "match_count": 50}]  # 10 sigma spike
    alerts = detect_drift(baselines, current)
    assert len(alerts) >= 1
    assert alerts[0].direction == "spike"


def test_detect_drift_zero_matches():
    """Critical alert on zero matches when expecting 30."""
    baselines = {
        "li.item": BaselineStats(
            selector="li.item", mean=30.0, stddev=2.0,
            sample_count=20, min_seen=26, max_seen=34,
        )
    }
    current = [{"selector": "li.item", "match_count": 0}]
    alerts = detect_drift(baselines, current)
    assert len(alerts) == 1
    assert alerts[0].severity == "critical"
    assert alerts[0].deviation > 10


def test_detect_drift_zero_stddev():
    """Should still detect drift when all historical values were identical."""
    baselines = {
        "li.item": BaselineStats(
            selector="li.item", mean=30.0, stddev=0.0,
            sample_count=20, min_seen=30, max_seen=30,
        )
    }
    current = [{"selector": "li.item", "match_count": 25}]
    alerts = detect_drift(baselines, current)
    assert len(alerts) >= 1  # Should use floor stddev of 1.0


def test_suggest_expectations():
    baselines = {
        "li.item": BaselineStats(
            selector="li.item", mean=30.0, stddev=3.0,
            sample_count=20, min_seen=24, max_seen=36,
        )
    }
    suggestions = suggest_expectations(baselines)
    assert "li.item" in suggestions
    s = suggestions["li.item"]
    assert s["expect_min"] >= 22  # mean - 2*stddev, clamped
    assert s["expect_max"] <= 41  # mean + 2*stddev + 1, clamped
    assert s["based_on_samples"] == 20


def test_drift_alert_to_dict():
    baselines = {
        "li.item": BaselineStats(
            selector="li.item", mean=30.0, stddev=2.0,
            sample_count=20, min_seen=26, max_seen=34,
        )
    }
    current = [{"selector": "li.item", "match_count": 5}]
    alerts = detect_drift(baselines, current)
    assert len(alerts) > 0
    d = alerts[0].to_dict()
    assert "selector" in d
    assert "current" in d
    assert "deviation_sigma" in d
    assert "severity" in d
