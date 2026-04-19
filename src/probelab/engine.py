"""Probe execution engine — runs steps, evaluates assertions, collects artifacts.

Two execution paths:
1. HTTP mode (default): fetch HTML via httpx, run selector assertions. Fast, no browser.
2. Browser mode: use Playwright to execute interactive steps (goto, click, type, wait).
   Triggered when probe has interactive steps or browser=True.
"""

from __future__ import annotations

import re
import time
from typing import Any

import httpx
from selectolax.parser import HTMLParser

from probelab.models.probe import Probe, Step, Assertion
from probelab.models.result import (
    RunResult, StepResult, AssertionResult, FailureClassification, Status,
)


def run_probe(probe: Probe, cdp_url: str | None = None) -> RunResult:
    """Execute a single probe and return results."""
    from probelab.guardrails import build_guardrails

    started_at = RunResult.now_iso()
    start_time = time.monotonic()
    guardrails = build_guardrails(probe)

    if probe.browser or _needs_browser(probe):
        return _run_browser(probe, started_at, start_time, cdp_url, guardrails)
    else:
        return _run_http(probe, started_at, start_time, guardrails)


def run_all_probes(probes: list[Probe], cdp_url: str | None = None) -> list[RunResult]:
    """Execute all probes sequentially."""
    return [run_probe(p, cdp_url=cdp_url) for p in probes]


def _needs_browser(probe: Probe) -> bool:
    """Check if probe requires a browser (has interactive steps)."""
    interactive = {"click", "type", "wait_for_selector", "wait_for_text"}
    return any(s.action in interactive for s in probe.steps)


# ─── HTTP Mode ───────────────────────────────────────────────────────────


def _run_http(probe: Probe, started_at: str, start_time: float,
              guardrails=None) -> RunResult:
    """Fetch HTML via httpx and run assertions against it."""
    from probelab.guardrails import check_navigation, check_redirect, check_page_safety
    url = probe.target.url or (probe.steps[0].url if probe.steps else "")
    if not url:
        return _error_result(probe, started_at, "No URL specified in probe")

    step_results = []
    try:
        fetch_start = time.monotonic()
        with httpx.Client(
            timeout=probe.timeout,
            follow_redirects=True,
            headers={"User-Agent": "probelab/1.0.0"},
        ) as client:
            response = client.get(url)
            response.raise_for_status()
            html = response.text
            final_url = str(response.url)

        fetch_ms = int((time.monotonic() - fetch_start) * 1000)
        step_results.append(StepResult(
            step_index=0, action="goto", status="passed", duration_ms=fetch_ms,
        ))
    except httpx.HTTPStatusError as e:
        return _error_result(
            probe, started_at,
            f"HTTP {e.response.status_code}: {e.response.reason_phrase}",
            step_results=[StepResult(
                step_index=0, action="goto", status="failed",
                error=f"HTTP {e.response.status_code}",
            )],
        )
    except httpx.RequestError as e:
        return _error_result(
            probe, started_at, str(e),
            step_results=[StepResult(
                step_index=0, action="goto", status="failed", error=str(e),
            )],
        )

    # Security: check for redirect anomalies
    security_warnings = []
    if guardrails:
        redirect_violation = check_redirect(url, final_url, guardrails)
        if redirect_violation:
            security_warnings.append(redirect_violation.message)

        # Security: scan page content for prompt injection / suspicious elements
        page_violations = check_page_safety(html)
        for v in page_violations:
            security_warnings.append(v.message)

    # Run assertions against fetched HTML
    tree = HTMLParser(html)
    assertion_results = _evaluate_assertions(probe.assertions, tree, final_url)

    duration_ms = int((time.monotonic() - start_time) * 1000)
    status = _determine_status(assertion_results)

    result = RunResult(
        probe_name=probe.name,
        url=url,
        status=status,
        started_at=started_at,
        duration_ms=duration_ms,
        step_results=step_results,
        assertion_results=assertion_results,
        failure=_classify_failure(assertion_results, step_results, final_url, url, html) if status != Status.HEALTHY else None,
        tags=probe.tags,
    )

    if security_warnings:
        result.artifacts["security_warnings"] = "; ".join(security_warnings)

    return result


# ─── Browser Mode ────────────────────────────────────────────────────────


def _run_browser(probe: Probe, started_at: str, start_time: float,
                 cdp_url: str | None = None, guardrails=None) -> RunResult:
    """Execute probe steps in a browser via Playwright."""
    from probelab.guardrails import check_navigation, check_redirect, check_page_safety

    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
    except ImportError:
        return _error_result(
            probe, started_at,
            "Browser mode requires playwright: pip install probelab[browser]",
        )

    from probelab.browser import check_cdp_available, DEFAULT_CDP_URL

    url = probe.target.url or ""
    step_results: list[StepResult] = []
    assertion_results: list[AssertionResult] = []
    final_url = url
    html = ""
    artifacts: dict[str, str] = {}

    endpoint = cdp_url or DEFAULT_CDP_URL
    use_cdp = check_cdp_available(endpoint)

    try:
        with sync_playwright() as p:
            if use_cdp:
                browser = p.chromium.connect_over_cdp(endpoint)
                context = browser.contexts[0] if browser.contexts else browser.new_context()
                page = context.new_page()
            else:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                               "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
                )
                page = context.new_page()

            try:
                # Execute steps
                for i, step in enumerate(probe.steps):
                    # Security: check domain allowlist before navigation
                    if guardrails and step.action == "goto" and step.url:
                        nav_violation = check_navigation(step.url, guardrails, step_index=i)
                        if nav_violation and nav_violation.blocked:
                            step_results.append(StepResult(
                                step_index=i, action=step.action,
                                status="failed", error=nav_violation.message,
                            ))
                            break

                    step_start = time.monotonic()
                    try:
                        _execute_step(page, step)
                        step_ms = int((time.monotonic() - step_start) * 1000)
                        step_results.append(StepResult(
                            step_index=i, action=step.action,
                            status="passed", duration_ms=step_ms,
                        ))
                    except PlaywrightTimeout:
                        step_ms = int((time.monotonic() - step_start) * 1000)
                        step_results.append(StepResult(
                            step_index=i, action=step.action,
                            status="failed", duration_ms=step_ms,
                            error=f"Timeout after {step.timeout_ms}ms",
                        ))
                        break
                    except Exception as e:
                        step_ms = int((time.monotonic() - step_start) * 1000)
                        step_results.append(StepResult(
                            step_index=i, action=step.action,
                            status="failed", duration_ms=step_ms, error=str(e),
                        ))
                        break

                # Collect page state for assertions
                final_url = page.url
                html = page.content()

                # Capture artifacts
                for output in probe.outputs:
                    if output.type == "screenshot":
                        from probelab.io.store import save_artifact, DEFAULT_HOME
                        screenshot_bytes = page.screenshot(full_page=True)
                        path = save_artifact(probe.name, "screenshot", screenshot_bytes)
                        artifacts["screenshot"] = str(path)
                    elif output.type == "html":
                        from probelab.io.store import save_artifact, DEFAULT_HOME
                        path = save_artifact(probe.name, "html", html)
                        artifacts["html"] = str(path)

            finally:
                if not use_cdp:
                    page.close()
                    browser.close()
                else:
                    page.close()
                    browser.close()

    except Exception as e:
        return _error_result(probe, started_at, f"Browser error: {e}")

    # Security checks on collected content
    security_warnings = []
    if guardrails and html:
        redirect_violation = check_redirect(url, final_url, guardrails)
        if redirect_violation:
            security_warnings.append(redirect_violation.message)
        page_violations = check_page_safety(html)
        for v in page_violations:
            security_warnings.append(v.message)

    # If any step failed, skip assertions
    all_steps_passed = all(s.status == "passed" for s in step_results)
    if all_steps_passed and html:
        tree = HTMLParser(html)
        assertion_results = _evaluate_assertions(probe.assertions, tree, final_url)

    duration_ms = int((time.monotonic() - start_time) * 1000)
    status = _determine_status(assertion_results, step_results)

    result = RunResult(
        probe_name=probe.name,
        url=url,
        status=status,
        started_at=started_at,
        duration_ms=duration_ms,
        step_results=step_results,
        assertion_results=assertion_results,
        failure=_classify_failure(assertion_results, step_results, final_url, url, html) if status != Status.HEALTHY else None,
        artifacts=artifacts,
        tags=probe.tags,
    )

    if security_warnings:
        result.artifacts["security_warnings"] = "; ".join(security_warnings)

    return result


def _execute_step(page: Any, step: Step) -> None:
    """Execute a single step on a Playwright page."""
    timeout = step.timeout_ms

    if step.action == "goto":
        page.goto(step.url, timeout=timeout, wait_until="domcontentloaded")
        page.wait_for_timeout(1000)  # Brief settle time

    elif step.action == "click":
        page.click(step.selector, timeout=timeout)

    elif step.action == "type":
        page.fill(step.selector, step.value or "", timeout=timeout)

    elif step.action == "wait_for_selector":
        page.wait_for_selector(step.selector, timeout=timeout)

    elif step.action == "wait_for_text":
        page.wait_for_function(
            f"() => document.body.innerText.includes({repr(step.text)})",
            timeout=timeout,
        )


# ─── Assertions ──────────────────────────────────────────────────────────


def _evaluate_assertions(assertions: list[Assertion], tree: HTMLParser,
                         current_url: str) -> list[AssertionResult]:
    """Evaluate all assertions against page state."""
    results = []
    for i, assertion in enumerate(assertions):
        result = _evaluate_one(i, assertion, tree, current_url)
        results.append(result)
    return results


def _evaluate_one(index: int, assertion: Assertion, tree: HTMLParser,
                  current_url: str) -> AssertionResult:
    """Evaluate a single assertion."""

    if assertion.type == "selector_exists":
        try:
            nodes = tree.css(assertion.selector)
        except ValueError:
            nodes = []
        count = len(nodes)
        passed = count >= 1
        extracted = [n.text(strip=True) for n in nodes[:10]]
        return AssertionResult(
            assertion_index=index,
            type="selector_exists",
            status="passed" if passed else "failed",
            expected=f">= 1 match",
            actual=f"{count} matches",
            selector=assertion.selector,
            match_count=count,
            extracted=extracted,
        )

    elif assertion.type == "selector_count":
        try:
            nodes = tree.css(assertion.selector)
        except ValueError:
            nodes = []
        count = len(nodes)
        min_ok = count >= (assertion.min or 0)
        max_ok = count <= assertion.max if assertion.max is not None else True
        passed = min_ok and max_ok
        return AssertionResult(
            assertion_index=index,
            type="selector_count",
            status="passed" if passed else "failed",
            expected=f"{assertion.min or 0}-{assertion.max or '∞'}",
            actual=f"{count}",
            selector=assertion.selector,
            match_count=count,
        )

    elif assertion.type == "text_exists":
        page_text = tree.text() if tree.body else ""
        found = assertion.text in page_text if assertion.text else False
        return AssertionResult(
            assertion_index=index,
            type="text_exists",
            status="passed" if found else "failed",
            expected=assertion.text,
            actual="found" if found else "not found",
        )

    elif assertion.type == "url_matches":
        pattern = assertion.pattern or ""
        matched = bool(re.search(pattern, current_url))
        return AssertionResult(
            assertion_index=index,
            type="url_matches",
            status="passed" if matched else "failed",
            expected=pattern,
            actual=current_url,
        )

    else:
        return AssertionResult(
            assertion_index=index,
            type=assertion.type,
            status="failed",
            detail=f"Unknown assertion type: {assertion.type}",
        )


# ─── Status + Classification ─────────────────────────────────────────────


def _determine_status(assertion_results: list[AssertionResult],
                      step_results: list[StepResult] | None = None) -> Status:
    """Determine overall probe status from results."""
    if step_results and any(s.status == "failed" for s in step_results):
        return Status.BROKEN
    if any(a.status == "failed" for a in assertion_results):
        return Status.BROKEN
    return Status.HEALTHY


def _classify_failure(assertion_results: list[AssertionResult],
                      step_results: list[StepResult],
                      final_url: str, expected_url: str,
                      html: str) -> FailureClassification:
    """Classify why a probe failed. Imported from diagnosis module if available."""
    try:
        from probelab.diagnosis.classify import classify_failure
        return classify_failure(assertion_results, step_results, final_url, expected_url, html)
    except ImportError:
        # Fallback: basic classification
        for s in step_results:
            if s.status == "failed":
                if s.error and "timeout" in s.error.lower():
                    return FailureClassification("timeout", s.error, step_index=s.step_index)
                return FailureClassification("navigation_error", s.error or "Step failed", step_index=s.step_index)
        for a in assertion_results:
            if a.status == "failed" and a.type == "selector_exists":
                return FailureClassification("selector_missing", f"Selector '{a.selector}' not found", assertion_index=a.assertion_index)
        return FailureClassification("unknown", "Probe failed for unknown reason")


def _error_result(probe: Probe, started_at: str, error: str,
                  step_results: list[StepResult] | None = None) -> RunResult:
    """Create an ERROR result."""
    return RunResult(
        probe_name=probe.name,
        url=probe.target.url,
        status=Status.ERROR,
        started_at=started_at,
        failure=FailureClassification("navigation_error", error),
        step_results=step_results or [],
        tags=probe.tags,
    )
