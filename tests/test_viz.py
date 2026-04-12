"""Tests for terminal visualizations."""

from io import StringIO

from rich.console import Console

from probelab.viz import (
    render_timeline,
    render_dom_diff_tree,
    render_health_dashboard,
    render_repair_diff,
    _sparkline,
)


def _console() -> tuple[Console, StringIO]:
    buf = StringIO()
    c = Console(file=buf, force_terminal=True, width=80)
    return c, buf


def _make_history(statuses: list[str], match_count: int = 30) -> list[dict]:
    return [
        {
            "name": "test",
            "status": s,
            "timestamp": f"2026-04-{10+i:02d}T10:00:00",
            "checks": [{"selector": "li.item", "match_count": match_count if s == "healthy" else 0}],
            "response_time_ms": 100,
        }
        for i, s in enumerate(statuses)
    ]


# ── Sparkline ──

def test_sparkline_empty():
    result = _sparkline([])
    assert "no data" in result.plain


def test_sparkline_flat():
    result = _sparkline([10, 10, 10, 10])
    # All same value → all max height
    assert len(result.plain) == 4


def test_sparkline_cliff():
    result = _sparkline([30, 30, 30, 30, 0])
    assert len(result.plain) == 5
    # Last char should be lowest (space or block 1)


def test_sparkline_respects_width():
    result = _sparkline(list(range(100)), width=20)
    assert len(result.plain) == 20


# ── Timeline ──

def test_render_timeline_basic():
    c, buf = _console()
    history = _make_history(["healthy"] * 5)
    render_timeline("test", history, c)
    output = buf.getvalue()
    assert "Timeline: test" in output
    assert "li.item" in output
    assert "now=" in output


def test_render_timeline_empty():
    c, buf = _console()
    render_timeline("test", [], c)
    output = buf.getvalue()
    assert "No history" in output


def test_render_timeline_with_breakage():
    c, buf = _console()
    history = _make_history(["healthy", "healthy", "healthy", "broken"])
    history[-1]["checks"][0]["match_count"] = 0
    render_timeline("test", history, c)
    output = buf.getvalue()
    assert "now=0" in output


# ── DOM diff tree ──

def test_render_dom_diff_tree_no_changes():
    c, buf = _console()
    snap = {"paths": ["body", "body > div#content"], "hash": "abc"}
    render_dom_diff_tree(snap, snap, c)
    output = buf.getvalue()
    assert "No structural changes" in output


def test_render_dom_diff_tree_with_changes():
    c, buf = _console()
    old = {"paths": ["body", "body > ul.items", "body > ul.items > li.item"], "hash": "old"}
    new = {"paths": ["body", "body > div.feed", "body > div.feed > article.entry"], "hash": "new"}
    render_dom_diff_tree(old, new, c)
    output = buf.getvalue()
    assert "DOM Structure Diff" in output
    assert "removed" in output or "li.item" in output
    assert "added" in output or "article.entry" in output


def test_render_dom_diff_tree_shows_rename_hint():
    c, buf = _console()
    old = {"paths": ["body", "body > div.old-name"], "hash": "old"}
    new = {"paths": ["body", "body > div.new-name"], "hash": "new"}
    render_dom_diff_tree(old, new, c)
    output = buf.getvalue()
    # Should show the rename arrow
    assert "new-name" in output


# ── Health dashboard ──

def test_render_dashboard_empty():
    c, buf = _console()
    render_health_dashboard({}, c)
    output = buf.getvalue()
    assert "No probes" in output


def test_render_dashboard_single_probe():
    c, buf = _console()
    history = _make_history(["healthy"] * 10)
    render_health_dashboard({"my-probe": history}, c)
    output = buf.getvalue()
    assert "Health Dashboard" in output
    assert "my-probe" in output
    assert "healthy" in output


def test_render_dashboard_multiple_probes():
    c, buf = _console()
    probes = {
        "probe-a": _make_history(["healthy"] * 5),
        "probe-b": _make_history(["healthy", "healthy", "broken"]),
        "probe-c": _make_history(["degraded"] * 3),
    }
    render_health_dashboard(probes, c)
    output = buf.getvalue()
    assert "probe-a" in output
    assert "probe-b" in output
    assert "probe-c" in output
    assert "broken" in output
    assert "degraded" in output


def test_render_dashboard_legend():
    c, buf = _console()
    render_health_dashboard({"x": _make_history(["healthy"])}, c)
    output = buf.getvalue()
    assert "healthy" in output
    assert "degraded" in output
    assert "broken" in output


# ── Repair diff ──

def test_render_repair_diff_no_suggestions():
    c, buf = _console()
    render_repair_diff("li.item", 0, [], c)
    output = buf.getvalue()
    assert "No repair suggestions" in output


def test_render_repair_diff_with_suggestion():
    c, buf = _console()
    suggestions = [
        {
            "selector": "li.entry",
            "match_count": 5,
            "confidence": 0.72,
            "reason": "Fuzzy class match",
            "sample_texts": ["First Entry", "Second Entry"],
        }
    ]
    render_repair_diff("li.item", 0, suggestions, c)
    output = buf.getvalue()
    assert "BROKEN" in output
    assert "SUGGESTED" in output
    assert "li.item" in output
    assert "li.entry" in output
    assert "5 matches" in output
    assert "First Entry" in output


def test_render_repair_diff_multiple_suggestions():
    c, buf = _console()
    suggestions = [
        {"selector": "li.entry", "match_count": 5, "confidence": 0.72,
         "reason": "Fuzzy class", "sample_texts": ["A"]},
        {"selector": "#list > li", "match_count": 5, "confidence": 0.45,
         "reason": "Structural", "sample_texts": ["B"]},
        {"selector": "li[data-id]", "match_count": 3, "confidence": 0.30,
         "reason": "Attribute", "sample_texts": []},
    ]
    render_repair_diff("li.item", 0, suggestions, c)
    output = buf.getvalue()
    assert "Other candidates" in output
    assert "#list > li" in output
