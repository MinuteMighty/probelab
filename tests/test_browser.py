"""Tests for browser-based fetching."""

from unittest.mock import patch, MagicMock

from probelab.probe import Check, Probe, Status
from probelab.runner import run_probe, _analyze_html


SAMPLE_RENDERED_HTML = """
<!DOCTYPE html>
<html>
<body>
  <div data-testid="trend">
    <div>
      <div>1 · Trending</div>
      <div>Python</div>
      <div>10K posts</div>
    </div>
  </div>
  <div data-testid="trend">
    <div>
      <div>2 · Trending</div>
      <div>JavaScript</div>
    </div>
  </div>
</body>
</html>
"""


def _browser_probe() -> Probe:
    return Probe(
        name="twitter-trending",
        url="https://x.com/explore",
        checks=[
            Check(selector='[data-testid="trend"]', expect_min=1),
        ],
        browser=True,
        tags=["opencli", "twitter"],
    )


def _http_probe() -> Probe:
    return Probe(
        name="example",
        url="https://example.com",
        checks=[Check(selector="h1", expect_min=1)],
        browser=False,
    )


class TestBrowserProbeSkip:
    """When playwright is NOT installed, browser probes should be skipped."""

    def test_skip_when_playwright_missing(self):
        with patch("probelab.runner.browser_available", return_value=False):
            result = run_probe(_browser_probe())
            assert result.status == Status.SKIPPED
            assert "pip install probelab[browser]" in result.error

    def test_http_probe_unaffected(self):
        """HTTP probes should not be affected by playwright availability."""
        import httpx

        def handler(request):
            return httpx.Response(200, text="<html><body><h1>Hello</h1></body></html>")

        with patch("probelab.runner.browser_available", return_value=False):
            client = httpx.Client(transport=httpx.MockTransport(handler))
            result = run_probe(_http_probe(), client=client)
            assert result.status == Status.HEALTHY


class TestBrowserProbeFetch:
    """When playwright IS installed, browser probes should use it."""

    def test_browser_probe_uses_fetch_page(self):
        with patch("probelab.runner.browser_available", return_value=True), \
             patch("probelab.browser.fetch_page",
                   return_value=(SAMPLE_RENDERED_HTML, 1500)):
            result = run_probe(_browser_probe(),
                               enable_diff=False, enable_drift=False, enable_repair=False)
            assert result.status == Status.HEALTHY
            assert result.response_time_ms == 1500
            assert result.check_results[0].match_count == 2
            assert result.tags == ["opencli", "twitter"]

    def test_browser_error_returns_error_status(self):
        with patch("probelab.runner.browser_available", return_value=True), \
             patch("probelab.browser.fetch_page",
                   side_effect=Exception("Chromium not found")):
            result = run_probe(_browser_probe())
            assert result.status == Status.ERROR
            assert "Chromium not found" in result.error

    def test_cdp_preferred_over_headless(self):
        """fetch_page should try CDP first."""
        with patch("probelab.browser.check_cdp_available", return_value=True), \
             patch("probelab.browser.fetch_with_cdp",
                   return_value=(SAMPLE_RENDERED_HTML, 800)) as mock_cdp:
            from probelab.browser import fetch_page
            html, ms = fetch_page("https://example.com")
            mock_cdp.assert_called_once()
            assert ms == 800

    def test_fallback_to_headless_when_no_cdp(self):
        """fetch_page should fall back to headless when CDP not available."""
        with patch("probelab.browser.check_cdp_available", return_value=False), \
             patch("probelab.browser.fetch_with_browser",
                   return_value=(SAMPLE_RENDERED_HTML, 2000)) as mock_headless:
            from probelab.browser import fetch_page
            html, ms = fetch_page("https://example.com")
            mock_headless.assert_called_once()
            assert ms == 2000


class TestAnalyzeHtml:
    """_analyze_html should work the same regardless of fetch method."""

    def test_healthy_html(self):
        probe = _browser_probe()
        result = _analyze_html(
            probe, SAMPLE_RENDERED_HTML, 100, "2026-04-12T00:00:00",
            enable_diff=False, enable_drift=False, enable_repair=False,
        )
        assert result.status == Status.HEALTHY
        assert result.check_results[0].match_count == 2

    def test_broken_html(self):
        probe = _browser_probe()
        empty_html = "<html><body><p>Nothing here</p></body></html>"
        result = _analyze_html(
            probe, empty_html, 100, "2026-04-12T00:00:00",
            enable_diff=False, enable_drift=False, enable_repair=False,
        )
        assert result.status == Status.BROKEN
        assert result.check_results[0].match_count == 0
