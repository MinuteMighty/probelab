"""Tests for compute_assertion_changes — baseline vs latest run comparison."""

from __future__ import annotations

from probelab.diff import compute_assertion_changes


def _result(status: str, assertions: list[dict]) -> dict:
    return {"status": status, "assertions": assertions}


def test_no_changes_when_identical():
    snap = _result("healthy", [
        {"assertion_index": 0, "type": "text_exists", "status": "passed",
         "actual": "Hacker News"},
        {"assertion_index": 1, "type": "selector_count", "status": "passed",
         "selector": "a.story", "match_count": 30},
    ])
    assert compute_assertion_changes(snap, snap) == []


def test_detects_regression_when_selector_shared_across_assertions():
    # Regression guard: selector_exists AND selector_count both target
    # the same selector. Keying by selector alone collapsed them and the
    # diff silently dropped one. Keying by assertion_index must not.
    shared = "span.titleline > a"
    baseline = _result("healthy", [
        {"assertion_index": 0, "type": "selector_exists", "status": "passed",
         "selector": shared, "actual": "found"},
        {"assertion_index": 1, "type": "selector_count", "status": "passed",
         "selector": shared, "match_count": 30},
    ])
    latest = _result("broken", [
        {"assertion_index": 0, "type": "selector_exists", "status": "failed",
         "selector": shared, "actual": "0 matches"},
        {"assertion_index": 1, "type": "selector_count", "status": "failed",
         "selector": shared, "match_count": 0},
    ])

    changes = compute_assertion_changes(baseline, latest)

    # Both assertions must surface as separate lines. Before the fix, keying
    # by selector collapsed them and only one appeared.
    assert len(changes) == 2
    assert all("was passing" in c and "now failing" in c for c in changes)
    # And both mention the shared selector.
    assert all(shared in c for c in changes)


def test_detects_count_delta_with_unique_selectors():
    baseline = _result("healthy", [
        {"assertion_index": 0, "type": "selector_count", "status": "passed",
         "selector": "article.Box-row", "match_count": 25},
        {"assertion_index": 1, "type": "selector_count", "status": "passed",
         "selector": "a.Link--primary", "match_count": 25},
    ])
    latest = _result("degraded", [
        {"assertion_index": 0, "type": "selector_count", "status": "passed",
         "selector": "article.Box-row", "match_count": 20},
        {"assertion_index": 1, "type": "selector_count", "status": "passed",
         "selector": "a.Link--primary", "match_count": 5},
    ])

    changes = compute_assertion_changes(baseline, latest)
    assert len(changes) == 2
    joined = "\n".join(changes)
    assert "article.Box-row: 25 -> 20" in joined
    assert "a.Link--primary: 25 -> 5" in joined


def test_count_increase_uses_yellow_count_decrease_uses_red():
    baseline = _result("healthy", [
        {"assertion_index": 0, "type": "selector_count", "status": "passed",
         "selector": "a.story", "match_count": 30},
    ])
    decreased = _result("degraded", [
        {"assertion_index": 0, "type": "selector_count", "status": "passed",
         "selector": "a.story", "match_count": 10},
    ])
    increased = _result("degraded", [
        {"assertion_index": 0, "type": "selector_count", "status": "passed",
         "selector": "a.story", "match_count": 50},
    ])
    assert "[red]" in compute_assertion_changes(baseline, decreased)[0]
    assert "[yellow]" in compute_assertion_changes(baseline, increased)[0]


def test_flags_removed_assertion_in_current_run():
    baseline = _result("healthy", [
        {"assertion_index": 0, "type": "text_exists", "status": "passed"},
        {"assertion_index": 1, "type": "selector_count", "status": "passed",
         "selector": "a.story", "match_count": 30},
    ])
    latest = _result("healthy", [
        {"assertion_index": 0, "type": "text_exists", "status": "passed"},
    ])
    changes = compute_assertion_changes(baseline, latest)
    assert len(changes) == 1
    assert "removed from current run" in changes[0]


def test_falls_back_to_positional_index_for_records_without_assertion_index():
    # Older records saved before AssertionResult carried assertion_index.
    baseline = _result("healthy", [
        {"type": "selector_count", "status": "passed",
         "selector": "a.story", "match_count": 30},
    ])
    latest = _result("broken", [
        {"type": "selector_count", "status": "failed",
         "selector": "a.story", "match_count": 0},
    ])
    changes = compute_assertion_changes(baseline, latest)
    assert len(changes) == 1
    assert "was passing" in changes[0]


def test_empty_baseline_or_latest_produces_no_changes():
    assert compute_assertion_changes({"assertions": []}, {"assertions": []}) == []
