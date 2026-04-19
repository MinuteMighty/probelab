"""Tests for classify_failure — the core failure-categorization logic."""

from __future__ import annotations

from probelab.diagnosis.classify import classify_failure
from probelab.models.result import AssertionResult, StepResult


def _step(action: str, status: str, error: str | None = None, idx: int = 0) -> StepResult:
    return StepResult(step_index=idx, action=action, status=status, error=error)


def _assertion(type_: str, status: str, selector: str | None = None,
               actual: str | None = None, expected: str | None = None,
               idx: int = 0) -> AssertionResult:
    return AssertionResult(
        assertion_index=idx, type=type_, status=status,
        selector=selector, actual=actual, expected=expected,
    )


# ── Step-level failures (checked first) ─────────────────────────────────────

def test_timeout_from_step_error():
    fc = classify_failure(
        [], [_step("wait_for", "failed", error="Wait timeout after 5000ms")],
        "https://x.com/", "https://x.com/", "",
    )
    assert fc.category == "timeout"
    assert "wait_for" in fc.message
    assert fc.step_index == 0


def test_navigation_error_when_step_fails_without_timeout_keyword():
    fc = classify_failure(
        [], [_step("goto", "failed", error="net::ERR_NAME_NOT_RESOLVED")],
        "", "https://bogus.invalid/", "",
    )
    assert fc.category == "navigation_error"
    assert "ERR_NAME_NOT_RESOLVED" in fc.message


# ── Auth redirects ──────────────────────────────────────────────────────────

def test_auth_expired_from_login_url():
    fc = classify_failure(
        [], [], "https://zhihu.com/signin", "https://zhihu.com/", "<html></html>",
    )
    assert fc.category == "auth_expired"


def test_auth_expired_from_chinese_login_keyword_in_url():
    fc = classify_failure(
        [], [], "https://weibo.com/登录", "https://weibo.com/", "<html></html>",
    )
    assert fc.category == "auth_expired"


def test_auth_expired_from_page_content_when_all_selectors_fail():
    # Page didn't redirect but shows a login form AND every selector assertion failed.
    html = "<html><body><form>Sign in to continue</form></body></html>"
    fc = classify_failure(
        [_assertion("selector_exists", "failed", selector="a.story")],
        [], "https://x.com/feed", "https://x.com/feed", html,
    )
    assert fc.category == "auth_expired"


def test_login_text_in_content_without_selector_failures_is_not_auth():
    # A page that merely MENTIONS "login" (e.g. a nav link) shouldn't be flagged
    # as auth_expired if the assertions would otherwise have passed.
    html = "<html><body><a>login</a><h1>Home</h1></body></html>"
    fc = classify_failure(
        [_assertion("selector_exists", "passed", selector="h1")],
        [], "https://x.com/", "https://x.com/", html,
    )
    assert fc.category != "auth_expired"


# ── CAPTCHA ─────────────────────────────────────────────────────────────────

def test_captcha_detected_from_page_content():
    html = "<html><body>Please complete the reCAPTCHA below.</body></html>"
    fc = classify_failure(
        [_assertion("selector_exists", "failed", selector="a.story")],
        [], "https://x.com/", "https://x.com/", html,
    )
    assert fc.category == "captcha_detected"


def test_captcha_detected_from_cloudflare_challenge_url():
    fc = classify_failure(
        [], [], "https://x.com/cdn-cgi/challenge-platform",
        "https://x.com/", "<html></html>",
    )
    assert fc.category == "captcha_detected"


# ── Unexpected redirect ─────────────────────────────────────────────────────

def test_unexpected_redirect_when_domain_changes():
    fc = classify_failure(
        [], [], "https://evil.example/phish",
        "https://bank.example/", "<html></html>",
    )
    assert fc.category == "unexpected_redirect"
    assert "bank.example" in fc.message
    assert "evil.example" in fc.message


def test_same_domain_not_redirect_even_if_path_differs():
    # Same-domain path changes are normal; shouldn't trigger unexpected_redirect.
    # With one failing selector assertion, should fall through to selector_missing.
    fc = classify_failure(
        [_assertion("selector_exists", "failed", selector="a.story",
                    actual="0 matches")],
        [], "https://x.com/new-path", "https://x.com/old-path", "<html></html>",
    )
    assert fc.category == "selector_missing"


# ── Assertion-level failures ────────────────────────────────────────────────

def test_selector_missing_from_failed_selector_exists():
    fc = classify_failure(
        [_assertion("selector_exists", "failed", selector="a.story",
                    actual="0 matches")],
        [], "https://x.com/", "https://x.com/", "<html></html>",
    )
    assert fc.category == "selector_missing"
    assert "a.story" in fc.message
    assert fc.assertion_index == 0


def test_selector_missing_from_failed_selector_count():
    fc = classify_failure(
        [_assertion("selector_count", "failed", selector="a.story",
                    actual="3", expected="min 10", idx=2)],
        [], "https://x.com/", "https://x.com/", "<html></html>",
    )
    assert fc.category == "selector_missing"
    assert fc.assertion_index == 2


def test_text_missing_from_failed_text_exists():
    fc = classify_failure(
        [_assertion("text_exists", "failed", expected="Hacker News")],
        [], "https://news.ycombinator.com/", "https://news.ycombinator.com/",
        "<html><body>Home</body></html>",
    )
    assert fc.category == "text_missing"
    assert "Hacker News" in fc.message


def test_url_mismatch_from_failed_url_matches():
    fc = classify_failure(
        [_assertion("url_matches", "failed",
                    actual="https://x.com/feed", expected=r".*/home")],
        [], "https://x.com/feed", "https://x.com/feed", "<html></html>",
    )
    assert fc.category == "url_mismatch"


# ── Priority: step failures beat assertion failures ─────────────────────────

def test_step_failure_takes_priority_over_assertion_failure():
    fc = classify_failure(
        [_assertion("selector_exists", "failed", selector="a.story")],
        [_step("goto", "failed", error="timeout navigating to page")],
        "", "https://x.com/", "",
    )
    assert fc.category == "timeout"


# ── Fallback ────────────────────────────────────────────────────────────────

def test_unknown_when_no_step_or_assertion_failures_match():
    # No step failures, no assertion failures of recognized type, no auth/captcha hints.
    fc = classify_failure(
        [],  # empty assertions
        [],  # empty steps
        "https://x.com/", "https://x.com/", "<html><body>Hi</body></html>",
    )
    assert fc.category == "unknown"
