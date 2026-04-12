"""Probe execution engine — fetches pages and runs checks.

Integrates DOM diff, baseline drift detection, and selector auto-repair.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

import httpx
from selectolax.parser import HTMLParser

from probelab.checker import validate_checks, validate_schema
from probelab.probe import Probe, ProbeResult, Status


def run_probe(
    probe: Probe,
    client: httpx.Client | None = None,
    enable_diff: bool = True,
    enable_drift: bool = True,
    enable_repair: bool = True,
) -> ProbeResult:
    """Execute a single probe and return results.

    Args:
        probe: The probe to execute.
        client: Optional shared httpx client.
        enable_diff: Run DOM structural diff against previous snapshot.
        enable_drift: Run baseline drift detection from history.
        enable_repair: Suggest selector repairs on broken probes.
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    own_client = client is None

    if own_client:
        client = httpx.Client(
            timeout=probe.timeout,
            follow_redirects=True,
            headers={"User-Agent": "probelab/0.1.0"},
        )

    try:
        start = time.monotonic()
        response = client.request(
            method=probe.method,
            url=probe.url,
            headers=probe.headers,
        )
        elapsed_ms = int((time.monotonic() - start) * 1000)

        response.raise_for_status()

        html = response.text
        tree = HTMLParser(html)

        # Run selector checks
        check_results = validate_checks(tree, probe.checks)

        # Run schema validation if defined
        schema_errors: list[str] = []
        if probe.schema and check_results:
            extracted_data = _extract_data(tree, probe.checks)
            schema_errors = validate_schema(extracted_data, probe.schema)

        # Determine base status
        all_checks_passed = all(cr.passed for cr in check_results)
        has_schema_errors = len(schema_errors) > 0

        if not all_checks_passed:
            status = Status.BROKEN
        elif has_schema_errors:
            status = Status.DEGRADED
        else:
            status = Status.HEALTHY

        result = ProbeResult(
            probe_name=probe.name,
            url=probe.url,
            status=status,
            check_results=check_results,
            schema_errors=schema_errors,
            response_time_ms=elapsed_ms,
            timestamp=timestamp,
        )

        # === DOM Diff ===
        if enable_diff:
            try:
                from probelab.differ import snapshot_page, diff_snapshots, load_snapshot, save_snapshot
                new_snapshot = snapshot_page(html)
                old_snapshot = load_snapshot(probe.name)
                if old_snapshot:
                    diff_result = diff_snapshots(old_snapshot, new_snapshot)
                    result.dom_diff = diff_result.to_dict()
                    # Upgrade status if structure changed but checks pass
                    if diff_result.changed and status == Status.HEALTHY:
                        result.status = Status.DEGRADED
                save_snapshot(probe.name, new_snapshot)
            except Exception:
                pass  # Don't fail the probe if diff fails

        # === Baseline Drift Detection ===
        if enable_drift and check_results:
            try:
                from probelab.baseline import compute_baseline, detect_drift
                baselines = compute_baseline(probe.name)
                if baselines:
                    check_dicts = [
                        {"selector": cr.selector, "match_count": cr.match_count}
                        for cr in check_results
                    ]
                    alerts = detect_drift(baselines, check_dicts)
                    if alerts:
                        result.drift_alerts = [a.to_dict() for a in alerts]
                        # Critical drift on a "healthy" probe -> degraded
                        if any(a.severity == "critical" for a in alerts) and result.status == Status.HEALTHY:
                            result.status = Status.DEGRADED
            except Exception:
                pass  # Don't fail the probe if drift detection fails

        # === Selector Auto-Repair ===
        if enable_repair and status == Status.BROKEN:
            try:
                from probelab.repair import suggest_repairs
                for cr in check_results:
                    if not cr.passed:
                        suggestions = suggest_repairs(
                            html=html,
                            broken_selector=cr.selector,
                            target_min=cr.expected_min,
                            target_max=cr.expected_max,
                        )
                        if suggestions:
                            result.repair_suggestions.extend(
                                s.to_dict() for s in suggestions
                            )
            except Exception:
                pass  # Don't fail the probe if repair fails

        return result

    except httpx.HTTPStatusError as e:
        return ProbeResult(
            probe_name=probe.name,
            url=probe.url,
            status=Status.ERROR,
            error=f"HTTP {e.response.status_code}: {e.response.reason_phrase}",
            response_time_ms=0,
            timestamp=timestamp,
        )
    except httpx.RequestError as e:
        return ProbeResult(
            probe_name=probe.name,
            url=probe.url,
            status=Status.ERROR,
            error=str(e),
            response_time_ms=0,
            timestamp=timestamp,
        )
    finally:
        if own_client:
            client.close()


def run_all_probes(
    probes: list[Probe],
    enable_diff: bool = True,
    enable_drift: bool = True,
    enable_repair: bool = True,
) -> list[ProbeResult]:
    """Execute all probes sequentially using a shared client."""
    results = []
    with httpx.Client(
        follow_redirects=True,
        headers={"User-Agent": "probelab/0.1.0"},
    ) as client:
        for probe in probes:
            result = run_probe(
                probe, client=client,
                enable_diff=enable_diff,
                enable_drift=enable_drift,
                enable_repair=enable_repair,
            )
            results.append(result)
    return results


def _extract_data(tree: HTMLParser, checks: list) -> list[dict[str, str]]:
    """Extract data from matched elements for schema validation."""
    items: list[dict[str, str]] = []
    if not checks:
        return items

    primary = checks[0]
    nodes = tree.css(primary.selector)

    for node in nodes:
        item: dict[str, str] = {}
        if primary.extract == "text":
            item["text"] = node.text(strip=True)
        elif primary.extract == "html":
            item["html"] = node.html or ""
        elif primary.extract.startswith("attr:"):
            attr_name = primary.extract[5:]
            item[attr_name] = node.attributes.get(attr_name, "")

        href = node.attributes.get("href")
        if href:
            item["href"] = href

        if item:
            items.append(item)

    return items
