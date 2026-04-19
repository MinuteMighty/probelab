"""Failure classification — not just 'it broke' but WHY.

This is probelab's core product differentiator. Every failure gets a specific
category + actionable message. Users don't see 'AssertionError' — they see
'auth_expired: Page redirected to login. Re-login to zhihu.com in Chrome.'
"""

from __future__ import annotations

import re

from probelab.models.result import (
    AssertionResult, StepResult, FailureClassification,
)

# Patterns that indicate auth/login redirect
AUTH_PATTERNS = re.compile(
    r"(login|sign[\s\-_]?in|auth|sso|oauth|cas/login|passport|"
    r"accounts\.google|accounts\.apple|登录|登陆|注册)",
    re.IGNORECASE,
)

# Patterns that indicate CAPTCHA/bot challenge
CAPTCHA_PATTERNS = re.compile(
    r"(captcha|recaptcha|hcaptcha|challenge|verify.you.are.human|"
    r"bot.detection|cloudflare|turnstile|just.a.moment|"
    r"验证|人机验证|安全验证)",
    re.IGNORECASE,
)

# Patterns that indicate maintenance/downtime
MAINTENANCE_PATTERNS = re.compile(
    r"(maintenance|under.construction|temporarily.unavailable|"
    r"维护中|升级中|暂时无法访问|系统维护)",
    re.IGNORECASE,
)


def classify_failure(
    assertion_results: list[AssertionResult],
    step_results: list[StepResult],
    final_url: str,
    expected_url: str,
    html: str,
) -> FailureClassification:
    """Classify the root cause of a probe failure.

    Checks in priority order (most specific first):
    1. Step-level failures (timeout, navigation error)
    2. Auth redirect (URL or page content matches login patterns)
    3. CAPTCHA/bot detection
    4. Maintenance page
    5. Unexpected redirect (URL changed but not to login)
    6. Selector missing (assertion failure)
    7. Text missing
    8. URL mismatch
    9. Unknown
    """

    # ── Step failures ──
    for step in step_results:
        if step.status != "failed":
            continue
        if step.error and "timeout" in step.error.lower():
            return FailureClassification(
                category="timeout",
                message=f"Step '{step.action}' timed out. Page may be slow or element missing.",
                step_index=step.step_index,
            )
        return FailureClassification(
            category="navigation_error",
            message=step.error or f"Step '{step.action}' failed.",
            step_index=step.step_index,
        )

    # ── Auth redirect ──
    if AUTH_PATTERNS.search(final_url):
        return FailureClassification(
            category="auth_expired",
            message=f"Redirected to login page: {final_url}. Re-login in Chrome.",
        )

    # Check page content for login prompts (some sites don't redirect)
    page_text = _extract_text(html)[:2000]  # First 2K chars
    if AUTH_PATTERNS.search(page_text) and _no_selectors_found(assertion_results):
        return FailureClassification(
            category="auth_expired",
            message="Page appears to show a login form. Session may have expired.",
        )

    # ── CAPTCHA / bot detection ──
    if CAPTCHA_PATTERNS.search(page_text):
        return FailureClassification(
            category="captcha_detected",
            message="CAPTCHA or bot challenge detected on page.",
        )

    if CAPTCHA_PATTERNS.search(final_url):
        return FailureClassification(
            category="captcha_detected",
            message=f"Redirected to challenge page: {final_url}",
        )

    # ── Maintenance ──
    if MAINTENANCE_PATTERNS.search(page_text):
        return FailureClassification(
            category="page_changed",
            message="Site appears to be under maintenance.",
        )

    # ── Unexpected redirect ──
    if expected_url and final_url:
        from urllib.parse import urlparse
        expected_domain = urlparse(expected_url).netloc
        actual_domain = urlparse(final_url).netloc
        if expected_domain and actual_domain and expected_domain != actual_domain:
            return FailureClassification(
                category="unexpected_redirect",
                message=f"Redirected from {expected_domain} to {actual_domain}.",
            )

    # ── Assertion-level failures ──
    for a in assertion_results:
        if a.status != "failed":
            continue

        if a.type == "selector_exists":
            return FailureClassification(
                category="selector_missing",
                message=f"Selector '{a.selector}' not found ({a.actual}). DOM may have changed.",
                assertion_index=a.assertion_index,
            )

        if a.type == "selector_count":
            return FailureClassification(
                category="selector_missing",
                message=f"Selector '{a.selector}' count {a.actual}, expected {a.expected}.",
                assertion_index=a.assertion_index,
            )

        if a.type == "text_exists":
            return FailureClassification(
                category="text_missing",
                message=f"Expected text '{a.expected}' not found on page.",
                assertion_index=a.assertion_index,
            )

        if a.type == "url_matches":
            return FailureClassification(
                category="url_mismatch",
                message=f"URL '{a.actual}' doesn't match pattern '{a.expected}'.",
                assertion_index=a.assertion_index,
            )

    return FailureClassification(
        category="unknown",
        message="Probe failed for unknown reason. Check artifacts.",
    )


def _extract_text(html: str) -> str:
    """Quick text extraction without full parse."""
    # Strip tags for pattern matching (good enough for classification)
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _no_selectors_found(assertion_results: list[AssertionResult]) -> bool:
    """Check if ALL selector assertions failed (strong signal for auth issue)."""
    selector_assertions = [a for a in assertion_results if a.type in ("selector_exists", "selector_count")]
    if not selector_assertions:
        return False
    return all(a.status == "failed" for a in selector_assertions)
