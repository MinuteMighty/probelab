"""Tests for the HTML report generator."""

from pathlib import Path

from probelab.html_report import (
    generate_html_report,
    write_html_report,
    _group_by_site,
    _extract_site,
    _site_status,
)
from probelab.probe import CheckResult, ProbeResult, Status


def _healthy_result() -> ProbeResult:
    return ProbeResult(
        probe_name="hackernews-top",
        url="https://news.ycombinator.com",
        status=Status.HEALTHY,
        check_results=[
            CheckResult(selector="tr.athing a", match_count=30, expected_min=20, expected_max=None, passed=True)
        ],
        response_time_ms=132,
        timestamp="2026-04-12T10:00:00+00:00",
        tags=["opencli", "hackernews"],
    )


def _broken_result() -> ProbeResult:
    return ProbeResult(
        probe_name="reddit-hot",
        url="https://reddit.com",
        status=Status.BROKEN,
        check_results=[
            CheckResult(selector="div.post", match_count=0, expected_min=5, expected_max=None, passed=False)
        ],
        response_time_ms=891,
        timestamp="2026-04-12T10:00:00+00:00",
        tags=["opencli", "reddit"],
        dom_diff={
            "changed": True,
            "summary": "3 element(s) removed; 2 element(s) added",
            "changes": [
                {"type": "removed", "path": "body > div.post-list", "details": "Element removed: div.post-list"},
                {"type": "added", "path": "body > main.feed", "details": "New element: main.feed"},
                {"type": "modified", "path": "body > nav.old", "details": "Possible rename: nav.old -> nav.new"},
            ],
        },
        drift_alerts=[
            {
                "selector": "div.post",
                "current": 0,
                "expected_mean": 25.0,
                "expected_stddev": 2.0,
                "deviation_sigma": 12.5,
                "direction": "drop",
                "severity": "critical",
                "message": "div.post: got 0 matches, expected ~25. Drop of 12.5 sigma.",
            }
        ],
        repair_suggestions=[
            {
                "selector": "main.feed > article",
                "match_count": 20,
                "confidence": 0.65,
                "reason": "Structural match: 20 sibling 'article' elements under 'main'",
                "sample_texts": ["First Post Title", "Second Post Title", "Third Post"],
            },
            {
                "selector": "article.feed-item",
                "match_count": 20,
                "confidence": 0.52,
                "reason": "Fuzzy class match: '.post' -> '.feed-item'",
                "sample_texts": ["A Post"],
            },
        ],
    )


def _degraded_result() -> ProbeResult:
    return ProbeResult(
        probe_name="twitter-feed",
        url="https://twitter.com",
        status=Status.DEGRADED,
        check_results=[
            CheckResult(selector="div.tweet", match_count=10, expected_min=5, expected_max=None, passed=True)
        ],
        schema_errors=["Item 0: 'author' is a required property"],
        response_time_ms=445,
        timestamp="2026-04-12T10:00:00+00:00",
        tags=["opencli", "twitter"],
    )


# ── Grouping helpers ──

def test_extract_site_from_tags():
    r = ProbeResult(probe_name="twitter-trending", url="", status=Status.HEALTHY, tags=["opencli", "twitter"])
    assert _extract_site(r) == "twitter"


def test_extract_site_fallback_to_name():
    r = ProbeResult(probe_name="twitter-trending", url="", status=Status.HEALTHY, tags=[])
    assert _extract_site(r) == "twitter"


def test_extract_site_no_hyphen():
    r = ProbeResult(probe_name="hackernews", url="", status=Status.HEALTHY, tags=[])
    assert _extract_site(r) == "hackernews"


def test_group_by_site():
    results = [
        ProbeResult(probe_name="twitter-trending", url="", status=Status.HEALTHY, tags=["opencli", "twitter"]),
        ProbeResult(probe_name="twitter-search", url="", status=Status.BROKEN, tags=["opencli", "twitter"]),
        ProbeResult(probe_name="reddit-hot", url="", status=Status.HEALTHY, tags=["opencli", "reddit"]),
    ]
    groups = _group_by_site(results)
    assert len(groups) == 2
    assert len(groups["twitter"]) == 2
    assert len(groups["reddit"]) == 1


def test_site_status_worst_wins():
    results = [
        ProbeResult(probe_name="a", url="", status=Status.HEALTHY),
        ProbeResult(probe_name="b", url="", status=Status.BROKEN),
    ]
    assert _site_status(results) == Status.BROKEN


def test_site_status_all_healthy():
    results = [
        ProbeResult(probe_name="a", url="", status=Status.HEALTHY),
        ProbeResult(probe_name="b", url="", status=Status.HEALTHY),
    ]
    assert _site_status(results) == Status.HEALTHY


# ── Basic generation ──

def test_generate_html_report_returns_html():
    html = generate_html_report([_healthy_result()])
    assert html.startswith("<!DOCTYPE html>")
    assert "</html>" in html


def test_generate_html_report_contains_probe_names():
    html = generate_html_report([_healthy_result(), _broken_result()])
    assert "hackernews" in html
    assert "reddit" in html


def test_generate_html_report_contains_status():
    html = generate_html_report([_healthy_result(), _broken_result(), _degraded_result()])
    assert "healthy" in html
    assert "broken" in html
    assert "degraded" in html


def test_generate_html_report_has_site_overview():
    html = generate_html_report([_healthy_result(), _broken_result(), _degraded_result()])
    assert "Site Overview" in html


def test_generate_html_report_title():
    html = generate_html_report([_healthy_result()])
    assert "1/1 sites healthy" in html
    assert "1/1 probes" in html


# ── Site grouping in report ──

def test_report_groups_by_site():
    twitter1 = ProbeResult(probe_name="twitter-trending", url="", status=Status.HEALTHY, tags=["opencli", "twitter"])
    twitter2 = ProbeResult(probe_name="twitter-search", url="", status=Status.BROKEN, tags=["opencli", "twitter"])
    reddit = ProbeResult(probe_name="reddit-hot", url="", status=Status.HEALTHY, tags=["opencli", "reddit"])
    html = generate_html_report([twitter1, twitter2, reddit])
    # Should have site-level anchors
    assert 'id="site-twitter"' in html
    assert 'id="site-reddit"' in html


def test_broken_site_open_by_default():
    html = generate_html_report([_broken_result()])
    assert "<details open>" in html


def test_healthy_site_collapsed():
    html = generate_html_report([_healthy_result()])
    # Should NOT have <details open>
    assert "<details open>" not in html
    assert "<details>" in html


def test_site_overview_shows_probe_counts():
    twitter1 = ProbeResult(probe_name="twitter-trending", url="", status=Status.HEALTHY, tags=["opencli", "twitter"])
    twitter2 = ProbeResult(probe_name="twitter-search", url="", status=Status.BROKEN, tags=["opencli", "twitter"])
    html = generate_html_report([twitter1, twitter2])
    assert "1/2 probes OK" in html


# ── DOM diff rendering ──

def test_html_contains_dom_diff():
    html = generate_html_report([_broken_result()])
    assert "DOM Changes" in html
    assert "3 element(s) removed" in html
    assert "div.post-list" in html
    assert "main.feed" in html


# ── Drift alerts ──

def test_html_contains_drift_alerts():
    html = generate_html_report([_broken_result()])
    assert "Drift Alerts" in html
    assert "12.5 sigma" in html
    assert "critical" in html


# ── Repair suggestions ──

def test_html_contains_repair_suggestions():
    html = generate_html_report([_broken_result()])
    assert "Repair Suggestions" in html
    assert "BROKEN" in html
    assert "SUGGESTED" in html
    assert "main.feed &gt; article" in html
    assert "20 matches" in html
    assert "First Post Title" in html


def test_html_contains_other_candidates():
    html = generate_html_report([_broken_result()])
    assert "Other candidates" in html
    assert "article.feed-item" in html


# ── Timeline with history ──

def test_html_contains_timeline_with_history():
    history = [
        {
            "status": "healthy",
            "timestamp": f"2026-04-{d:02d}T10:00:00",
            "checks": [{"selector": "div.post", "match_count": 30}],
        }
        for d in range(1, 6)
    ]
    html = generate_html_report(
        [_broken_result()],
        history_map={"reddit-hot": history},
    )
    assert "Timeline" in html
    assert "<svg" in html


def test_html_no_timeline_without_history():
    html = generate_html_report([_broken_result()], history_map={})
    assert "DOM Changes" in html


# ── SVG sparkline ──

def test_html_sparkline_has_svg_elements():
    history = [
        {"status": "healthy", "timestamp": "2026-04-01", "checks": [{"selector": "a", "match_count": v}]}
        for v in [30, 28, 32, 25, 5, 0]
    ]
    html = generate_html_report([_broken_result()], history_map={"reddit-hot": history})
    assert "<polyline" in html
    assert "<circle" in html
    assert "<polygon" in html


# ── Write to file ──

def test_write_html_report(tmp_path):
    path = write_html_report(tmp_path / "report.html", [_healthy_result(), _broken_result()])
    assert path.exists()
    content = path.read_text()
    assert "<!DOCTYPE html>" in content
    assert "hackernews" in content
    assert "reddit" in content


# ── Healthy-only report (no detail cards) ──

def test_healthy_only_report_is_clean():
    html = generate_html_report([_healthy_result()])
    assert "hackernews" in html
    assert "DOM Changes" not in html
    assert "Repair Suggestions" not in html


# ── HTML escaping ──

def test_html_escapes_special_chars():
    result = ProbeResult(
        probe_name='<script>alert("xss")</script>',
        url="https://example.com",
        status=Status.HEALTHY,
        response_time_ms=100,
        timestamp="2026-04-12T10:00:00",
    )
    html = generate_html_report([result])
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
