"""Minimal security guardrails for probe execution.

Not a full security product. Just enough to prevent the most common dangers:
1. Domain allowlist — probes can't navigate to undeclared domains
2. Action restrictions — dangerous actions require explicit opt-in
3. Redirect anomaly detection — flag unexpected domain changes mid-execution
4. Output validation — don't trust page content as probe conclusions

This runs DURING execution, not after. The classifier (diagnosis/classify.py)
handles post-execution failure analysis. Guardrails prevent the probe from
doing something dangerous in the first place.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from probelab.models.probe import Probe, Step


@dataclass
class GuardrailConfig:
    """Security configuration for a probe execution."""

    # Domains the probe is allowed to visit (derived from target + steps)
    allowed_domains: set[str] = field(default_factory=set)

    # Actions that require explicit opt-in in the probe YAML
    # Default: only read-only actions are allowed
    dangerous_actions: set[str] = field(default_factory=lambda: {
        "submit_form", "download", "upload", "delete",
        "send_message", "change_settings",
    })

    # Maximum number of navigations per probe run (prevents infinite redirect loops)
    max_navigations: int = 10

    # Whether to block execution on domain violations (True) or just warn (False)
    strict: bool = True


@dataclass
class GuardrailViolation:
    """A security violation detected during execution."""

    type: str  # "domain_violation", "action_blocked", "redirect_anomaly", "navigation_limit"
    message: str
    step_index: int | None = None
    blocked: bool = True  # whether execution was stopped


def build_guardrails(probe: Probe) -> GuardrailConfig:
    """Build guardrail config from a probe definition.

    Extracts allowed domains from target URL and step URLs.
    """
    allowed = set()

    # Target domain
    if probe.target.url:
        domain = _extract_domain(probe.target.url)
        if domain:
            allowed.add(domain)

    # Step domains
    for step in probe.steps:
        if step.url:
            domain = _extract_domain(step.url)
            if domain:
                allowed.add(domain)

    return GuardrailConfig(allowed_domains=allowed)


def check_navigation(url: str, config: GuardrailConfig,
                     step_index: int | None = None) -> GuardrailViolation | None:
    """Check if a navigation target is allowed."""
    domain = _extract_domain(url)
    if not domain:
        return None  # Can't parse, let it through

    if domain not in config.allowed_domains:
        return GuardrailViolation(
            type="domain_violation",
            message=f"Navigation to '{domain}' blocked. "
                    f"Allowed domains: {', '.join(sorted(config.allowed_domains))}. "
                    f"Add this domain to the probe's steps to allow it.",
            step_index=step_index,
            blocked=config.strict,
        )
    return None


def check_redirect(original_url: str, final_url: str,
                   config: GuardrailConfig) -> GuardrailViolation | None:
    """Check if a page redirect went to an unexpected domain."""
    orig_domain = _extract_domain(original_url)
    final_domain = _extract_domain(final_url)

    if not orig_domain or not final_domain:
        return None

    if final_domain != orig_domain and final_domain not in config.allowed_domains:
        return GuardrailViolation(
            type="redirect_anomaly",
            message=f"Page redirected from '{orig_domain}' to '{final_domain}' "
                    f"(not in allowed domains). This may indicate auth redirect, "
                    f"CAPTCHA, or malicious page behavior.",
            blocked=False,  # Don't block, but flag for classification
        )
    return None


def check_page_safety(html: str, url: str = "") -> list[GuardrailViolation]:
    """Quick safety scan of page content.

    Checks for common prompt injection patterns and suspicious content
    that could mislead an AI agent. These patterns are checked BEFORE
    any LLM processing of the page (relevant for future heal/diagnose
    features that use LLM).
    """
    violations = []
    page_text = _extract_visible_text(html)

    # Check for common prompt injection patterns
    injection_patterns = [
        (r"ignore\s+(previous|all|above)\s+(instructions|prompts|rules)",
         "Possible prompt injection: 'ignore previous instructions' pattern"),
        (r"you\s+are\s+now\s+(a|an)\s+",
         "Possible prompt injection: role reassignment pattern"),
        (r"system\s*:\s*you\s+(must|should|are)",
         "Possible prompt injection: fake system prompt"),
        (r"<\s*/?(?:system|instruction|prompt)\s*>",
         "Possible prompt injection: fake XML instruction tags"),
    ]

    for pattern, message in injection_patterns:
        if re.search(pattern, page_text, re.IGNORECASE):
            violations.append(GuardrailViolation(
                type="prompt_injection_detected",
                message=message,
                blocked=False,  # Flag, don't block (monitoring should still report)
            ))
            break  # One injection warning is enough

    # Check for suspicious download/action triggers in hidden elements
    hidden_action_patterns = [
        (r'style\s*=\s*"[^"]*display\s*:\s*none[^"]*"[^>]*(?:href|action|onclick)',
         "Hidden element with action/link detected"),
        (r'<iframe[^>]*(?:width\s*=\s*["\']?0|height\s*=\s*["\']?0|style\s*=\s*["\']?[^"\']*display\s*:\s*none)',
         "Hidden iframe detected (potential tracking/exploit)"),
    ]

    for pattern, message in hidden_action_patterns:
        if re.search(pattern, html, re.IGNORECASE):
            violations.append(GuardrailViolation(
                type="suspicious_content",
                message=message,
                blocked=False,
            ))

    return violations


def _extract_domain(url: str) -> str | None:
    """Extract domain from URL."""
    try:
        parsed = urlparse(url)
        return parsed.netloc.lower() if parsed.netloc else None
    except Exception:
        return None


def _extract_visible_text(html: str) -> str:
    """Extract visible text from HTML for safety scanning."""
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()[:5000]  # First 5K chars
