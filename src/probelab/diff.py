"""Compare a probe's latest run against its saved baseline."""

from __future__ import annotations

from typing import Any


def _index_by_assertion_index(assertions: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    # Fall back to positional index if assertion_index is absent (older records).
    return {a.get("assertion_index", i): a for i, a in enumerate(assertions)}


def _display_key(a: dict[str, Any], idx: int) -> str:
    return a.get("selector") or a.get("type") or f"assertion[{idx}]"


def compute_assertion_changes(
    baseline: dict[str, Any], last: dict[str, Any]
) -> list[str]:
    """Return Rich-markup lines describing how last diverges from baseline.

    Assertions are matched by assertion_index so probes with repeated
    selectors (e.g. selector_exists + selector_count on the same selector)
    diff correctly — keying by selector alone collapses them.
    """
    base_by_idx = _index_by_assertion_index(baseline.get("assertions", []))
    curr_by_idx = _index_by_assertion_index(last.get("assertions", []))

    changes: list[str] = []
    for idx, base_a in base_by_idx.items():
        key = _display_key(base_a, idx)
        curr_a = curr_by_idx.get(idx)
        if curr_a is None:
            changes.append(f"  [red]-[/] {key}: [red]removed from current run[/]")
            continue
        if base_a.get("status") == "passed" and curr_a.get("status") == "failed":
            changes.append(
                f"  [red]-[/] {key}: was passing ({base_a.get('actual', '?')}), "
                f"now failing ({curr_a.get('actual', '?')})"
            )
            continue
        b_count = base_a.get("match_count")
        c_count = curr_a.get("match_count")
        if b_count is not None and c_count is not None and b_count != c_count:
            color = "red" if c_count < b_count else "yellow"
            changes.append(f"  [{color}]~[/] {key}: {b_count} -> {c_count} matches")
    return changes
