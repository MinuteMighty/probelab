"""probelab Python API — programmatic health checks for browser agents.

Use this when you want to check a URL from Python code without writing
YAML or running CLI commands. Designed for agent frameworks (browser-use,
LangChain, CrewAI, etc.) that need a fast pre-flight check before spending
tokens on browser automation.

    from probelab import preflight, check_url

    # Pre-flight: should I run my agent on this site?
    status = preflight("https://target.com", checks=[
        ("selector_exists", ".job-card"),
        ("no_captcha",),
    ])
    if status.healthy:
        agent.run(...)

    # Quick check with selectors and text
    result = check_url("https://news.ycombinator.com", selectors=["tr.athing"])
    print(result.status)   # "healthy"
    print(result.matches)  # {"tr.athing": 30}
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
from selectolax.parser import HTMLParser


# ─────────────────────────────────────────────────────────────────────
# Result types
# ─────────────────────────────────────────────────────────────────────

@dataclass
class CheckResult:
    """Result of a URL health check."""

    url: str
    status: str  # "healthy", "broken", "error"
    failure: str | None = None  # failure category if broken
    message: str = ""
    response_code: int = 0
    response_time_ms: int = 0
    matches: dict[str, int] = field(default_factory=dict)  # selector -> count
    text_found: dict[str, bool] = field(default_factory=dict)  # text -> found?
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def healthy(self) -> bool:
        return self.status == "healthy"

    @property
    def broken(self) -> bool:
        return self.status in ("broken", "error")

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "status": self.status,
            "failure": self.failure,
            "message": self.message,
            "response_code": self.response_code,
            "response_time_ms": self.response_time_ms,
            "matches": self.matches,
            "text_found": self.text_found,
        }


@dataclass
class RepairSuggestion:
    """A suggested replacement selector."""

    selector: str
    match_count: int
    confidence: float
    reason: str


@dataclass
class DiagnoseResult:
    """Result of diagnosing a broken URL."""

    url: str
    failure: str
    message: str
    repairs: list[RepairSuggestion] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────
# Auth / captcha detection patterns (shared with diagnosis/classify.py)
# ─────────────────────────────────────────────────────────────────────

_AUTH_PATTERNS = re.compile(
    r"(login|sign[\s\-_]?in|auth|sso|oauth|cas/login|passport|"
    r"accounts\.google|accounts\.apple|登录|登陆|注册)",
    re.IGNORECASE,
)

_CAPTCHA_PATTERNS = re.compile(
    r"(captcha|recaptcha|hcaptcha|challenge|verify.you.are.human|"
    r"bot.detection|cloudflare|turnstile|just.a.moment|"
    r"验证|人机验证|安全验证)",
    re.IGNORECASE,
)


# ─────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────

def check_url(
    url: str,
    selectors: list[str] | None = None,
    text: list[str] | None = None,
    timeout: int = 15,
) -> CheckResult:
    """Check if a URL is healthy — selectors match, text exists.

    Args:
        url: The URL to check.
        selectors: CSS selectors that should exist on the page.
        text: Text strings that should appear on the page.
        timeout: Request timeout in seconds.

    Returns:
        CheckResult with status, matches, and failure info.

    Example:
        result = check_url(
            "https://news.ycombinator.com",
            selectors=["tr.athing"],
            text=["Hacker News"],
        )
        print(result.status)   # "healthy"
        print(result.matches)  # {"tr.athing": 30}
    """
    try:
        start = time.monotonic()
        with httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "probelab/1.0"},
        ) as client:
            response = client.get(url)
        elapsed_ms = int((time.monotonic() - start) * 1000)
    except httpx.ConnectError:
        return CheckResult(
            url=url, status="error",
            failure="navigation_error",
            message="Connection failed — DNS or network error",
        )
    except httpx.TimeoutException:
        return CheckResult(
            url=url, status="error",
            failure="timeout",
            message=f"Timed out after {timeout}s",
        )
    except httpx.RequestError as e:
        return CheckResult(
            url=url, status="error",
            failure="navigation_error",
            message=str(e),
        )

    html = response.text
    final_url = str(response.url)
    code = response.status_code

    if code >= 500:
        return CheckResult(
            url=url, status="broken",
            failure="navigation_error",
            message=f"Server error: HTTP {code}",
            response_code=code,
            response_time_ms=elapsed_ms,
        )

    if code == 404:
        return CheckResult(
            url=url, status="broken",
            failure="navigation_error",
            message="Page not found: HTTP 404",
            response_code=code,
            response_time_ms=elapsed_ms,
        )

    # Check for auth redirect
    if _AUTH_PATTERNS.search(final_url) and final_url != url:
        return CheckResult(
            url=url, status="broken",
            failure="auth_expired",
            message=f"Redirected to login: {final_url}",
            response_code=code,
            response_time_ms=elapsed_ms,
        )

    # Check for CAPTCHA
    if _CAPTCHA_PATTERNS.search(html[:5000]):
        return CheckResult(
            url=url, status="broken",
            failure="captcha_detected",
            message="CAPTCHA or bot challenge detected on page",
            response_code=code,
            response_time_ms=elapsed_ms,
        )

    tree = HTMLParser(html)
    matches: dict[str, int] = {}
    text_found: dict[str, bool] = {}
    failures: list[str] = []

    # Check selectors
    if selectors:
        for sel in selectors:
            try:
                count = len(tree.css(sel))
            except ValueError:
                count = 0
            matches[sel] = count
            if count == 0:
                failures.append(f"selector_missing: '{sel}' not found")

    # Check text
    if text:
        for t in text:
            found = t in html
            text_found[t] = found
            if not found:
                failures.append(f"text_missing: '{t}' not on page")

    if failures:
        return CheckResult(
            url=url, status="broken",
            failure=failures[0].split(":")[0],
            message="; ".join(failures),
            response_code=code,
            response_time_ms=elapsed_ms,
            matches=matches,
            text_found=text_found,
        )

    return CheckResult(
        url=url, status="healthy",
        message="All checks passed",
        response_code=code,
        response_time_ms=elapsed_ms,
        matches=matches,
        text_found=text_found,
    )


def preflight(
    url: str,
    checks: list[str | tuple] | None = None,
    timeout: int = 10,
) -> CheckResult:
    """Pre-flight check for browser agents. Fast, $0, no YAML.

    Designed to run before an expensive browser-use/agent task.
    Returns quickly with a health status so you can decide whether
    to proceed or skip.

    Args:
        url: Target URL the agent will visit.
        checks: List of checks to run. Each is either:
            - A string: "no_captcha", "no_login_redirect"
            - A tuple: ("selector_exists", ".job-card")
            - A tuple: ("text_exists", "Sign Up")
        timeout: Request timeout in seconds (default 10 for speed).

    Returns:
        CheckResult — check result.healthy or result.broken.

    Example:
        status = preflight("https://linkedin.com/jobs", checks=[
            ("selector_exists", ".job-card"),
            ("no_captcha",),
            ("no_login_redirect",),
        ])
        if status.healthy:
            agent.run(...)
    """
    selectors: list[str] = []
    text_checks: list[str] = []
    check_captcha = False
    check_auth = False

    if checks:
        for check in checks:
            if isinstance(check, str):
                name = check
                args = ()
            else:
                name = check[0]
                args = check[1:]

            if name == "selector_exists" and args:
                selectors.append(args[0])
            elif name == "text_exists" and args:
                text_checks.append(args[0])
            elif name == "no_captcha":
                check_captcha = True
            elif name == "no_login_redirect":
                check_auth = True

    # Fetch the page
    try:
        start = time.monotonic()
        with httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "probelab/1.0"},
        ) as client:
            response = client.get(url)
        elapsed_ms = int((time.monotonic() - start) * 1000)
    except httpx.ConnectError:
        return CheckResult(
            url=url, status="error",
            failure="navigation_error",
            message="Connection failed",
        )
    except httpx.TimeoutException:
        return CheckResult(
            url=url, status="error",
            failure="timeout",
            message=f"Timed out after {timeout}s",
        )
    except httpx.RequestError as e:
        return CheckResult(
            url=url, status="error",
            failure="navigation_error",
            message=str(e),
        )

    html = response.text
    final_url = str(response.url)
    code = response.status_code
    failures: list[str] = []

    if code >= 500:
        return CheckResult(
            url=url, status="broken",
            failure="navigation_error",
            message=f"HTTP {code}",
            response_code=code,
            response_time_ms=elapsed_ms,
        )

    # Auth redirect check
    if check_auth and _AUTH_PATTERNS.search(final_url) and final_url != url:
        failures.append(f"auth_expired: redirected to {final_url}")

    # CAPTCHA check
    if check_captcha and _CAPTCHA_PATTERNS.search(html[:5000]):
        failures.append("captcha_detected: bot challenge on page")

    tree = HTMLParser(html)
    matches: dict[str, int] = {}
    text_found: dict[str, bool] = {}

    # Selector checks
    for sel in selectors:
        try:
            count = len(tree.css(sel))
        except ValueError:
            count = 0
        matches[sel] = count
        if count == 0:
            failures.append(f"selector_missing: '{sel}' not found")

    # Text checks
    for t in text_checks:
        found = t in html
        text_found[t] = found
        if not found:
            failures.append(f"text_missing: '{t}' not on page")

    if failures:
        first_category = failures[0].split(":")[0]
        return CheckResult(
            url=url, status="broken",
            failure=first_category,
            message="; ".join(failures),
            response_code=code,
            response_time_ms=elapsed_ms,
            matches=matches,
            text_found=text_found,
        )

    return CheckResult(
        url=url, status="healthy",
        message="All preflight checks passed",
        response_code=code,
        response_time_ms=elapsed_ms,
        matches=matches,
        text_found=text_found,
    )


def diagnose_url(
    url: str,
    broken_selector: str,
    timeout: int = 15,
    max_suggestions: int = 5,
) -> DiagnoseResult:
    """Diagnose a broken selector and suggest repairs.

    Fetches the page, runs the repair engine, and returns
    alternative selectors that might work.

    Args:
        url: The URL to diagnose.
        broken_selector: The CSS selector that no longer works.
        timeout: Request timeout.
        max_suggestions: Max repair suggestions to return.

    Example:
        result = diagnose_url(
            "https://competitor.com/pricing",
            broken_selector=".pricing-card",
        )
        for r in result.repairs:
            print(f"  {r.selector} ({r.match_count} matches, {r.confidence:.0%})")
    """
    try:
        with httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "probelab/1.0"},
        ) as client:
            response = client.get(url)
        html = response.text
    except httpx.RequestError as e:
        return DiagnoseResult(
            url=url,
            failure="navigation_error",
            message=str(e),
        )

    # Check if selector actually works (maybe it's fine)
    tree = HTMLParser(html)
    try:
        count = len(tree.css(broken_selector))
    except ValueError:
        count = 0

    if count > 0:
        return DiagnoseResult(
            url=url,
            failure="none",
            message=f"Selector '{broken_selector}' matches {count} elements — not broken.",
        )

    # Run repair engine
    from probelab.repair import suggest_repairs

    suggestions = suggest_repairs(
        html=html,
        broken_selector=broken_selector,
        target_min=3,
        max_suggestions=max_suggestions,
    )

    repairs = [
        RepairSuggestion(
            selector=s.selector,
            match_count=s.match_count,
            confidence=s.confidence,
            reason=s.reason,
        )
        for s in suggestions
    ]

    return DiagnoseResult(
        url=url,
        failure="selector_missing",
        message=f"Selector '{broken_selector}' not found (0 matches).",
        repairs=repairs,
    )
