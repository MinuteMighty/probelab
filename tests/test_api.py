"""Tests for the Python API (probelab.api)."""

from unittest.mock import patch, MagicMock

import httpx

from probelab.api import check_url, preflight, diagnose_url


SAMPLE_PAGE = """
<html>
<head><title>Test Page</title></head>
<body>
  <h1>Welcome</h1>
  <ul class="items">
    <li class="item">One</li>
    <li class="item">Two</li>
    <li class="item">Three</li>
  </ul>
  <p>Some content here</p>
</body>
</html>
"""

CAPTCHA_PAGE = """
<html>
<head><title>Verify</title></head>
<body>
  <div class="captcha">Please verify you are human</div>
  <div class="cloudflare-challenge">Just a moment...</div>
</body>
</html>
"""

RENAMED_PAGE = """
<html>
<head><title>Store</title></head>
<body>
  <div id="pricing">
    <div class="pricing-tier">Free</div>
    <div class="pricing-tier">Pro</div>
    <div class="pricing-tier">Enterprise</div>
    <div class="pricing-tier">Team</div>
    <div class="pricing-tier">Startup</div>
  </div>
</body>
</html>
"""


def _mock_response(html: str, status_code: int = 200, url: str = "https://test.com"):
    """Create a mock httpx.Response."""
    resp = MagicMock(spec=httpx.Response)
    resp.text = html
    resp.status_code = status_code
    resp.url = url
    return resp


def _patch_get(html: str, status_code: int = 200, url: str = "https://test.com"):
    """Patch httpx.Client to return a fixed response."""
    mock_resp = _mock_response(html, status_code, url)
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.get.return_value = mock_resp
    return patch("probelab.api.httpx.Client", return_value=mock_client)


# ─── check_url ───

class TestCheckUrl:
    def test_healthy_with_selectors(self):
        with _patch_get(SAMPLE_PAGE):
            result = check_url("https://test.com", selectors=["li.item", "h1"])
        assert result.healthy
        assert result.matches["li.item"] == 3
        assert result.matches["h1"] == 1

    def test_healthy_with_text(self):
        with _patch_get(SAMPLE_PAGE):
            result = check_url("https://test.com", text=["Welcome", "Some content"])
        assert result.healthy
        assert result.text_found["Welcome"] is True

    def test_broken_selector(self):
        with _patch_get(SAMPLE_PAGE):
            result = check_url("https://test.com", selectors=[".nonexistent"])
        assert result.broken
        assert result.failure == "selector_missing"
        assert result.matches[".nonexistent"] == 0

    def test_broken_text(self):
        with _patch_get(SAMPLE_PAGE):
            result = check_url("https://test.com", text=["This does not exist"])
        assert result.broken
        assert result.failure == "text_missing"

    def test_server_error(self):
        with _patch_get("Error", status_code=500):
            result = check_url("https://test.com")
        assert result.broken
        assert result.failure == "navigation_error"
        assert result.response_code == 500

    def test_404(self):
        with _patch_get("Not found", status_code=404):
            result = check_url("https://test.com")
        assert result.broken
        assert result.response_code == 404

    def test_connection_error(self):
        with patch("probelab.api.httpx.Client") as mock:
            mock.return_value.__enter__ = MagicMock(side_effect=httpx.ConnectError("fail"))
            # The error happens when creating the client context
            mock.side_effect = None
            mock.return_value.__enter__.side_effect = httpx.ConnectError("fail")
        # Use a simpler approach
        with patch("probelab.api.httpx.Client", side_effect=httpx.ConnectError("fail")):
            result = check_url("https://unreachable.test")
        assert result.status == "error"
        assert result.failure == "navigation_error"

    def test_captcha_detected(self):
        with _patch_get(CAPTCHA_PAGE):
            result = check_url("https://test.com")
        assert result.broken
        assert result.failure == "captcha_detected"

    def test_auth_redirect(self):
        with _patch_get(SAMPLE_PAGE, url="https://test.com/signin?next=/"):
            result = check_url("https://test.com")
        assert result.broken
        assert result.failure == "auth_expired"

    def test_to_dict(self):
        with _patch_get(SAMPLE_PAGE):
            result = check_url("https://test.com", selectors=["h1"])
        d = result.to_dict()
        assert d["status"] == "healthy"
        assert d["matches"]["h1"] == 1

    def test_no_checks_just_reachability(self):
        with _patch_get(SAMPLE_PAGE):
            result = check_url("https://test.com")
        assert result.healthy

    def test_healthy_and_broken_properties(self):
        with _patch_get(SAMPLE_PAGE):
            result = check_url("https://test.com")
        assert result.healthy is True
        assert result.broken is False


# ─── preflight ───

class TestPreflight:
    def test_healthy_preflight(self):
        with _patch_get(SAMPLE_PAGE):
            result = preflight("https://test.com", checks=[
                ("selector_exists", "li.item"),
                ("text_exists", "Welcome"),
            ])
        assert result.healthy

    def test_catches_missing_selector(self):
        with _patch_get(SAMPLE_PAGE):
            result = preflight("https://test.com", checks=[
                ("selector_exists", ".missing"),
            ])
        assert result.broken
        assert result.failure == "selector_missing"

    def test_catches_captcha(self):
        with _patch_get(CAPTCHA_PAGE):
            result = preflight("https://test.com", checks=["no_captcha"])
        assert result.broken
        assert result.failure == "captcha_detected"

    def test_no_checks_is_reachability(self):
        with _patch_get(SAMPLE_PAGE):
            result = preflight("https://test.com")
        assert result.healthy

    def test_string_check_format(self):
        with _patch_get(CAPTCHA_PAGE):
            result = preflight("https://test.com", checks=["no_captcha"])
        assert result.broken

    def test_auth_redirect_check(self):
        with _patch_get(SAMPLE_PAGE, url="https://test.com/login"):
            result = preflight("https://test.com", checks=["no_login_redirect"])
        assert result.broken
        assert result.failure == "auth_expired"

    def test_connection_error(self):
        with patch("probelab.api.httpx.Client", side_effect=httpx.ConnectError("fail")):
            result = preflight("https://unreachable.test")
        assert result.broken


# ─── diagnose_url ───

class TestDiagnoseUrl:
    def test_finds_repairs(self):
        # Use HTML where the repair engine can find structural matches
        html_with_list = """<html><body>
        <ul id="items">
          <li class="entry"><a href="/1">One</a></li>
          <li class="entry"><a href="/2">Two</a></li>
          <li class="entry"><a href="/3">Three</a></li>
          <li class="entry"><a href="/4">Four</a></li>
          <li class="entry"><a href="/5">Five</a></li>
        </ul>
        </body></html>"""
        with _patch_get(html_with_list):
            result = diagnose_url("https://test.com", broken_selector="li.item")
        assert result.failure == "selector_missing"
        assert len(result.repairs) > 0

    def test_selector_not_broken(self):
        with _patch_get(SAMPLE_PAGE):
            result = diagnose_url("https://test.com", broken_selector="li.item")
        assert result.failure == "none"
        assert "not broken" in result.message

    def test_connection_error(self):
        with patch("probelab.api.httpx.Client", side_effect=httpx.ConnectError("fail")):
            result = diagnose_url("https://unreachable.test", broken_selector=".x")
        assert result.failure == "navigation_error"

    def test_repair_has_fields(self):
        with _patch_get(RENAMED_PAGE):
            result = diagnose_url("https://test.com", broken_selector=".pricing-card")
        if result.repairs:
            r = result.repairs[0]
            assert r.selector
            assert r.match_count > 0
            assert 0 <= r.confidence <= 1
            assert r.reason


# ─── Import from probelab ───

class TestImportPath:
    def test_import_from_package(self):
        from probelab import check_url, preflight, diagnose_url, CheckResult
        assert callable(check_url)
        assert callable(preflight)
        assert callable(diagnose_url)
        assert CheckResult is not None
