"""Run result models — what happened when a probe executed."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal


class Status(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    BROKEN = "broken"
    ERROR = "error"
    SKIPPED = "skipped"


@dataclass
class StepResult:
    """Result of executing a single step."""

    step_index: int
    action: str
    status: Literal["passed", "failed", "skipped"]
    duration_ms: int = 0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "step_index": self.step_index,
            "action": self.action,
            "status": self.status,
            "duration_ms": self.duration_ms,
        }
        if self.error:
            result["error"] = self.error
        return result


@dataclass
class AssertionResult:
    """Result of evaluating a single assertion."""

    assertion_index: int
    type: str
    status: Literal["passed", "failed"]
    expected: str | None = None
    actual: str | None = None
    detail: str | None = None
    selector: str | None = None
    match_count: int | None = None
    extracted: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "assertion_index": self.assertion_index,
            "type": self.type,
            "status": self.status,
        }
        if self.expected:
            result["expected"] = self.expected
        if self.actual:
            result["actual"] = self.actual
        if self.detail:
            result["detail"] = self.detail
        if self.selector:
            result["selector"] = self.selector
        if self.match_count is not None:
            result["match_count"] = self.match_count
        return result


FAILURE_CATEGORIES = [
    "navigation_error",
    "timeout",
    "selector_missing",
    "text_missing",
    "url_mismatch",
    "auth_expired",
    "captcha_detected",
    "page_changed",
    "unexpected_redirect",
    "unknown",
]


@dataclass
class FailureClassification:
    """Why a probe failed — not just 'it broke' but WHY."""

    category: str  # one of FAILURE_CATEGORIES
    message: str
    step_index: int | None = None
    assertion_index: int | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "category": self.category,
            "message": self.message,
        }
        if self.step_index is not None:
            result["step_index"] = self.step_index
        if self.assertion_index is not None:
            result["assertion_index"] = self.assertion_index
        return result


@dataclass
class RunResult:
    """Complete result of running a probe."""

    probe_name: str
    url: str
    status: Status
    started_at: str = ""
    duration_ms: int = 0
    step_results: list[StepResult] = field(default_factory=list)
    assertion_results: list[AssertionResult] = field(default_factory=list)
    failure: FailureClassification | None = None
    artifacts: dict[str, str] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    # Diagnostics (populated by post-processors)
    dom_diff: dict[str, Any] | None = None
    drift_alerts: list[dict[str, Any]] = field(default_factory=list)
    repair_suggestions: list[dict[str, Any]] = field(default_factory=list)

    @staticmethod
    def now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "probe_name": self.probe_name,
            "url": self.url,
            "status": self.status.value,
            "started_at": self.started_at,
            "duration_ms": self.duration_ms,
            "steps": [s.to_dict() for s in self.step_results],
            "assertions": [a.to_dict() for a in self.assertion_results],
        }
        if self.failure:
            result["failure"] = self.failure.to_dict()
        if self.artifacts:
            result["artifacts"] = self.artifacts
        if self.tags:
            result["tags"] = self.tags
        if self.dom_diff:
            result["dom_diff"] = self.dom_diff
        if self.drift_alerts:
            result["drift_alerts"] = self.drift_alerts
        if self.repair_suggestions:
            result["repair_suggestions"] = self.repair_suggestions
        return result
