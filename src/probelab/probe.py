"""Probe data model — defines what to check and how."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Status(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    BROKEN = "broken"
    ERROR = "error"


@dataclass
class Check:
    """A single selector check within a probe."""

    selector: str
    expect_min: int = 1
    expect_max: int | None = None
    extract: str = "text"  # "text", "html", "attr:href", etc.


@dataclass
class Probe:
    """A probe definition — what URL to hit and what to validate."""

    name: str
    url: str
    checks: list[Check] = field(default_factory=list)
    schema: dict[str, Any] | None = None
    method: str = "GET"
    headers: dict[str, str] = field(default_factory=dict)
    timeout: int = 15
    browser: bool = False
    tags: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Probe:
        """Create a Probe from a parsed TOML dict."""
        probe_data = data.get("probe", data)
        checks = [
            Check(
                selector=c["selector"],
                expect_min=c.get("expect_min", 1),
                expect_max=c.get("expect_max"),
                extract=c.get("extract", "text"),
            )
            for c in probe_data.get("checks", [])
        ]
        return cls(
            name=probe_data["name"],
            url=probe_data["url"],
            checks=checks,
            schema=probe_data.get("schema"),
            method=probe_data.get("method", "GET"),
            headers=probe_data.get("headers", {}),
            timeout=probe_data.get("timeout", 15),
            browser=probe_data.get("browser", False),
            tags=probe_data.get("tags", []),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a TOML-friendly dict."""
        result: dict[str, Any] = {
            "probe": {
                "name": self.name,
                "url": self.url,
                "method": self.method,
                "timeout": self.timeout,
                "browser": self.browser,
            }
        }
        if self.headers:
            result["probe"]["headers"] = self.headers
        if self.tags:
            result["probe"]["tags"] = self.tags
        if self.checks:
            result["probe"]["checks"] = [
                {
                    "selector": c.selector,
                    "expect_min": c.expect_min,
                    **({"expect_max": c.expect_max} if c.expect_max is not None else {}),
                    "extract": c.extract,
                }
                for c in self.checks
            ]
        if self.schema:
            result["probe"]["schema"] = self.schema
        return result


@dataclass
class CheckResult:
    """Result of running a single selector check."""

    selector: str
    match_count: int
    expected_min: int
    expected_max: int | None
    passed: bool
    extracted: list[str] = field(default_factory=list)


@dataclass
class ProbeResult:
    """Result of running a full probe."""

    probe_name: str
    url: str
    status: Status
    check_results: list[CheckResult] = field(default_factory=list)
    schema_errors: list[str] = field(default_factory=list)
    response_time_ms: int = 0
    error: str | None = None
    timestamp: str = ""
    # New v0.2 fields
    dom_diff: dict[str, Any] | None = None
    drift_alerts: list[dict[str, Any]] = field(default_factory=list)
    repair_suggestions: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize for JSON output."""
        result: dict[str, Any] = {
            "name": self.probe_name,
            "url": self.url,
            "status": self.status.value,
            "response_time_ms": self.response_time_ms,
            "checks": [
                {
                    "selector": cr.selector,
                    "match_count": cr.match_count,
                    "expected_min": cr.expected_min,
                    "expected_max": cr.expected_max,
                    "passed": cr.passed,
                }
                for cr in self.check_results
            ],
            "schema_errors": self.schema_errors,
            "error": self.error,
            "timestamp": self.timestamp,
        }
        if self.dom_diff:
            result["dom_diff"] = self.dom_diff
        if self.drift_alerts:
            result["drift_alerts"] = self.drift_alerts
        if self.repair_suggestions:
            result["repair_suggestions"] = self.repair_suggestions
        return result
