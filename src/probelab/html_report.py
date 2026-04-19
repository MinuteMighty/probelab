"""Self-contained HTML report generator.

Renders probe results grouped by site/adapter — site overview table,
collapsible per-site detail cards with DOM diff, sparkline timeline,
drift alerts, and repair suggestions. Single HTML file, inline CSS,
no JavaScript frameworks.
"""

from __future__ import annotations

import html
import datetime
from pathlib import Path
from typing import Any

from probelab.probe import ProbeResult, Status

# ─────────────────────────────────────────────────────────────────────
# Color palette
# ─────────────────────────────────────────────────────────────────────

_COLORS = {
    "healthy": "#22c55e",
    "degraded": "#eab308",
    "broken": "#ef4444",
    "error": "#ef4444",
    "skipped": "#64748b",
    "bg": "#0f172a",
    "card": "#1e293b",
    "border": "#334155",
    "text": "#e2e8f0",
    "dim": "#94a3b8",
    "added": "#22c55e",
    "removed": "#ef4444",
    "modified": "#eab308",
    "code_bg": "#0d1117",
}

_STATUS_ICON = {
    Status.HEALTHY: "&#10003;",   # ✓
    Status.DEGRADED: "&#126;",    # ~
    Status.BROKEN: "&#10007;",    # ✗
    Status.ERROR: "&#33;",        # !
    Status.SKIPPED: "&#8211;",    # –
}

_STATUS_SEVERITY = {
    Status.SKIPPED: -1,
    Status.HEALTHY: 0,
    Status.DEGRADED: 1,
    Status.BROKEN: 2,
    Status.ERROR: 3,
}


# ─────────────────────────────────────────────────────────────────────
# Grouping helpers
# ─────────────────────────────────────────────────────────────────────

def _extract_site(result: ProbeResult) -> str:
    """Extract site name from a probe result."""
    tags = result.tags
    if len(tags) >= 2 and tags[0] == "opencli":
        return tags[1]
    if tags:
        return tags[0]
    if "-" in result.probe_name:
        return result.probe_name.split("-", 1)[0]
    return result.probe_name


def _group_by_site(results: list[ProbeResult]) -> dict[str, list[ProbeResult]]:
    """Group probe results by site."""
    groups: dict[str, list[ProbeResult]] = {}
    for r in results:
        site = _extract_site(r)
        groups.setdefault(site, []).append(r)
    return groups


def _site_status(results: list[ProbeResult]) -> Status:
    """Return the worst status among a list of probe results."""
    return max(results, key=lambda r: _STATUS_SEVERITY.get(r.status, 3)).status


# ─────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────

def generate_html_report(
    results: list[ProbeResult],
    history_map: dict[str, list[dict[str, Any]]] | None = None,
) -> str:
    """Generate a full HTML report string, grouped by site."""
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    site_groups = _group_by_site(results)

    total_probes = len(results)
    total_sites = len(site_groups)
    healthy_probes = sum(1 for r in results if r.status == Status.HEALTHY)
    broken_probes = sum(1 for r in results if r.status in (Status.BROKEN, Status.ERROR))
    degraded_probes = sum(1 for r in results if r.status == Status.DEGRADED)
    skipped_probes = sum(1 for r in results if r.status == Status.SKIPPED)
    tested_probes = total_probes - skipped_probes

    healthy_sites = sum(
        1 for probes in site_groups.values()
        if _site_status(probes) == Status.HEALTHY
    )
    skipped_sites = sum(
        1 for probes in site_groups.values()
        if all(p.status == Status.SKIPPED for p in probes)
    )
    broken_sites = total_sites - healthy_sites - skipped_sites

    sections: list[str] = []

    # 1. Summary bar (site-centric)
    sections.append(_render_site_summary(
        total_sites, healthy_sites, broken_sites, skipped_sites,
        total_probes, tested_probes, healthy_probes, skipped_probes, now,
    ))

    # 2. Site overview table
    sections.append(_render_site_overview_table(site_groups))

    # 3. Per-site detail cards (broken first)
    sorted_sites = sorted(
        site_groups.items(),
        key=lambda item: (_STATUS_SEVERITY.get(_site_status(item[1]), 3), item[0]),
        reverse=True,
    )
    for site_name, site_probes in sorted_sites:
        sections.append(_render_site_detail_card(
            site_name, site_probes, history_map or {},
        ))

    body = "\n".join(sections)
    return _wrap_page(body, total_probes, healthy_probes, broken_probes, degraded_probes,
                      total_sites, healthy_sites)


def write_html_report(
    path: str | Path,
    results: list[ProbeResult],
    history_map: dict[str, list[dict[str, Any]]] | None = None,
) -> Path:
    """Generate and write an HTML report to disk."""
    p = Path(path)
    p.write_text(generate_html_report(results, history_map))
    return p


# ─────────────────────────────────────────────────────────────────────
# Site summary bar
# ─────────────────────────────────────────────────────────────────────

def _render_site_summary(
    total_sites: int, healthy_sites: int, broken_sites: int, skipped_sites: int,
    total_probes: int, tested_probes: int, healthy_probes: int, skipped_probes: int,
    timestamp: str,
) -> str:
    return f"""
    <div class="summary">
      <div class="summary-stat">
        <span class="stat-number">{total_sites}</span>
        <span class="stat-label">Sites</span>
      </div>
      <div class="summary-stat">
        <span class="stat-number" style="color:{_COLORS['healthy']}">{healthy_sites}</span>
        <span class="stat-label">Healthy</span>
      </div>
      <div class="summary-stat">
        <span class="stat-number" style="color:{_COLORS['broken']}">{broken_sites}</span>
        <span class="stat-label">Broken</span>
      </div>
      <div class="summary-stat">
        <span class="stat-number" style="color:{_COLORS['skipped']}">{skipped_sites}</span>
        <span class="stat-label">Need Browser</span>
      </div>
      <div class="summary-divider"></div>
      <div class="summary-stat">
        <span class="stat-number" style="font-size:20px">{healthy_probes}/{tested_probes}</span>
        <span class="stat-label">Tested OK</span>
      </div>
      <div class="summary-stat">
        <span class="stat-number" style="font-size:20px;color:{_COLORS['skipped']}">{skipped_probes}</span>
        <span class="stat-label">Skipped</span>
      </div>
      <div class="summary-timestamp">{_e(timestamp)}</div>
    </div>"""


# ─────────────────────────────────────────────────────────────────────
# Site overview table
# ─────────────────────────────────────────────────────────────────────

def _render_site_overview_table(site_groups: dict[str, list[ProbeResult]]) -> str:
    rows: list[str] = []

    sorted_sites = sorted(
        site_groups.items(),
        key=lambda item: (_STATUS_SEVERITY.get(_site_status(item[1]), 3), item[0]),
        reverse=True,
    )

    for site_name, probes in sorted_sites:
        status = _site_status(probes)
        color = _COLORS.get(status.value, _COLORS["dim"])
        icon = _STATUS_ICON.get(status, "?")
        total = len(probes)
        healthy = sum(1 for p in probes if p.status == Status.HEALTHY)
        broken_names = [
            p.probe_name.split("-", 1)[1] if "-" in p.probe_name else p.probe_name
            for p in probes if p.status in (Status.BROKEN, Status.ERROR)
        ]
        broken_list = ", ".join(broken_names[:5])
        if len(broken_names) > 5:
            broken_list += f" +{len(broken_names) - 5} more"

        rows.append(f"""
        <tr>
          <td class="icon" style="color:{color}">{icon}</td>
          <td class="probe-name"><a href="#site-{_e(site_name)}">{_e(site_name)}</a></td>
          <td><span class="status-badge" style="background:{color}20;color:{color}">{_e(status.value)}</span></td>
          <td class="details">{healthy}/{total} probes OK</td>
          <td class="details dim">{_e(broken_list) if broken_list else '-'}</td>
        </tr>""")

    return f"""
    <div class="card">
      <h2>Site Overview</h2>
      <table class="results-table">
        <thead>
          <tr><th></th><th>Site</th><th>Status</th><th>Probes</th><th>Broken</th></tr>
        </thead>
        <tbody>{"".join(rows)}</tbody>
      </table>
    </div>"""


# ─────────────────────────────────────────────────────────────────────
# Per-site detail card (collapsible)
# ─────────────────────────────────────────────────────────────────────

def _render_site_detail_card(
    site_name: str,
    probes: list[ProbeResult],
    history_map: dict[str, list[dict[str, Any]]],
) -> str:
    status = _site_status(probes)
    color = _COLORS.get(status.value, _COLORS["dim"])
    healthy = sum(1 for p in probes if p.status == Status.HEALTHY)
    total = len(probes)
    icon = _STATUS_ICON.get(status, "?")

    # Probe table rows (broken first)
    sorted_probes = sorted(
        probes, key=lambda p: _STATUS_SEVERITY.get(p.status, 3), reverse=True,
    )
    probe_rows: list[str] = []
    for r in sorted_probes:
        r_color = _COLORS.get(r.status.value, _COLORS["dim"])
        r_icon = _STATUS_ICON.get(r.status, "?")
        # Show command name (strip site prefix)
        cmd = r.probe_name.split("-", 1)[1] if "-" in r.probe_name else r.probe_name
        details = _build_details_text(r)
        time_str = f"{r.response_time_ms}ms" if r.response_time_ms > 0 else "-"
        probe_rows.append(f"""
          <tr>
            <td class="icon" style="color:{r_color}">{r_icon}</td>
            <td class="probe-name">{_e(cmd)}</td>
            <td><span class="status-badge" style="background:{r_color}20;color:{r_color}">{_e(r.status.value)}</span></td>
            <td class="details">{_e(details)}</td>
            <td class="time">{_e(time_str)}</td>
          </tr>""")

    probe_table = f"""
      <table class="results-table">
        <thead>
          <tr><th></th><th>Command</th><th>Status</th><th>Details</th><th>Time</th></tr>
        </thead>
        <tbody>{"".join(probe_rows)}</tbody>
      </table>"""

    # Per-probe diagnostics (only for non-healthy)
    diagnostics: list[str] = []
    for r in sorted_probes:
        hist = history_map.get(r.probe_name, [])
        card_html = _render_probe_diagnostics(r, hist)
        if card_html:
            diagnostics.append(card_html)

    open_attr = " open" if status in (Status.BROKEN, Status.ERROR) else ""

    return f"""
    <div class="card site-card" id="site-{_e(site_name)}" style="border-left:3px solid {color}">
      <details{open_attr}>
        <summary class="site-header">
          <span class="icon" style="color:{color};font-size:16px">{icon}</span>
          <span class="site-name">{_e(site_name)}</span>
          <span class="status-badge" style="background:{color}20;color:{color}">{_e(status.value)}</span>
          <span class="site-probe-count">{healthy}/{total} probes OK</span>
        </summary>
        {probe_table}
        {"".join(diagnostics)}
      </details>
    </div>"""


# ─────────────────────────────────────────────────────────────────────
# Per-probe diagnostics (nested inside site card)
# ─────────────────────────────────────────────────────────────────────

def _render_probe_diagnostics(result: ProbeResult, history: list[dict[str, Any]]) -> str:
    """Render diagnostics for a single probe (timeline, diff, drift, repair)."""
    if result.status == Status.HEALTHY and not result.dom_diff and not result.drift_alerts:
        return ""

    color = _COLORS.get(result.status.value, _COLORS["dim"])
    cmd = result.probe_name.split("-", 1)[1] if "-" in result.probe_name else result.probe_name
    sections: list[str] = []

    if history:
        sections.append(_render_timeline_section(history))
    if result.dom_diff and result.dom_diff.get("changed"):
        sections.append(_render_dom_diff_section(result.dom_diff))
    if result.drift_alerts:
        sections.append(_render_drift_section(result.drift_alerts))
    if result.repair_suggestions:
        broken_sel = ""
        broken_count = 0
        for cr in result.check_results:
            if not cr.passed:
                broken_sel = cr.selector
                broken_count = cr.match_count
                break
        sections.append(_render_repair_section(broken_sel, broken_count, result.repair_suggestions))

    if not sections:
        return ""

    return f"""
      <div class="probe-detail" style="border-left:2px solid {color}">
        <h4 style="color:{color}">{_e(cmd)}</h4>
        {"".join(sections)}
      </div>"""


# ─────────────────────────────────────────────────────────────────────
# Timeline section (SVG sparkline)
# ─────────────────────────────────────────────────────────────────────

def _render_timeline_section(history: list[dict[str, Any]]) -> str:
    selector_series: dict[str, list[int]] = {}
    statuses: list[str] = []
    for entry in history:
        statuses.append(entry.get("status", "?"))
        for check in entry.get("checks", []):
            sel = check.get("selector", "?")
            count = check.get("match_count", 0)
            selector_series.setdefault(sel, []).append(count)

    parts: list[str] = []

    trail = "".join(
        f'<span class="trail-dot" style="background:{_COLORS.get(s, _COLORS["dim"])}" title="{s}"></span>'
        for s in statuses
    )
    parts.append(f'<div class="section-label">Status trail</div><div class="trail">{trail}</div>')

    for selector, values in selector_series.items():
        svg = _svg_sparkline(values, width=400, height=40)
        current = values[-1] if values else 0
        peak = max(values) if values else 0
        parts.append(
            f'<div class="section-label">{_e(selector)}</div>'
            f'<div class="sparkline-row">{svg}'
            f'<span class="spark-stat">now=<b>{current}</b> peak={peak}</span></div>'
        )

    return f'<div class="section timeline-section"><h3>Timeline</h3>{"".join(parts)}</div>'


def _svg_sparkline(values: list[int], width: int = 400, height: int = 40) -> str:
    if not values:
        return '<span class="dim">no data</span>'

    n = len(values)
    lo = min(values)
    hi = max(values)
    span = hi - lo if hi != lo else 1
    padding = 2

    points: list[str] = []
    for i, v in enumerate(values):
        x = padding + (i / max(n - 1, 1)) * (width - 2 * padding)
        y = height - padding - ((v - lo) / span) * (height - 2 * padding)
        points.append(f"{x:.1f},{y:.1f}")

    polyline = " ".join(points)
    first_x = padding
    last_x = padding + ((n - 1) / max(n - 1, 1)) * (width - 2 * padding)
    fill_points = f"{first_x},{height} {polyline} {last_x},{height}"

    last_pct = (values[-1] - lo) / span if span else 1
    if last_pct >= 0.6:
        color = _COLORS["healthy"]
    elif last_pct >= 0.2:
        color = _COLORS["degraded"]
    else:
        color = _COLORS["broken"]

    return (
        f'<svg class="sparkline-svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}">'
        f'<polygon points="{fill_points}" fill="{color}" opacity="0.15"/>'
        f'<polyline points="{polyline}" fill="none" stroke="{color}" stroke-width="2" stroke-linejoin="round"/>'
        f'<circle cx="{points[-1].split(",")[0]}" cy="{points[-1].split(",")[1]}" r="3" fill="{color}"/>'
        f'</svg>'
    )


# ─────────────────────────────────────────────────────────────────────
# DOM diff section
# ─────────────────────────────────────────────────────────────────────

def _render_dom_diff_section(dom_diff: dict[str, Any]) -> str:
    changes = dom_diff.get("changes", [])
    summary = dom_diff.get("summary", "Structure changed.")

    lines: list[str] = []
    for change in changes[:15]:
        ctype = change.get("type", "?")
        path = change.get("path", "?")
        color = _COLORS.get(ctype, _COLORS["dim"])
        icon_ch = {"added": "+", "removed": "&minus;", "modified": "~"}.get(ctype, "?")
        depth = path.count(" > ")
        indent = depth * 20

        lines.append(
            f'<div class="diff-line" style="padding-left:{indent}px">'
            f'<span class="diff-icon" style="color:{color}">{icon_ch}</span>'
            f'<span style="color:{color}">{_e(path.split(" > ")[-1])}</span>'
            f'</div>'
        )

    remaining = len(changes) - 15
    if remaining > 0:
        lines.append(f'<div class="dim" style="padding-left:20px">... and {remaining} more changes</div>')

    return (
        f'<div class="section diff-section"><h3>DOM Changes</h3>'
        f'<div class="diff-summary">{_e(summary)}</div>'
        f'<div class="diff-tree">{"".join(lines)}</div></div>'
    )


# ─────────────────────────────────────────────────────────────────────
# Drift alerts section
# ─────────────────────────────────────────────────────────────────────

def _render_drift_section(alerts: list[dict[str, Any]]) -> str:
    items: list[str] = []
    for alert in alerts:
        severity = alert.get("severity", "warning")
        color = _COLORS["broken"] if severity == "critical" else _COLORS["degraded"]
        msg = alert.get("message", "")

        items.append(
            f'<div class="alert" style="border-left:3px solid {color}">'
            f'<span class="alert-badge" style="background:{color}20;color:{color}">{severity}</span> '
            f'{_e(msg)}'
            f'</div>'
        )

    return f'<div class="section"><h3>Drift Alerts</h3>{"".join(items)}</div>'


# ─────────────────────────────────────────────────────────────────────
# Repair suggestions section
# ─────────────────────────────────────────────────────────────────────

def _render_repair_section(
    broken_sel: str, broken_count: int, suggestions: list[dict[str, Any]]
) -> str:
    if not suggestions:
        return ""

    best = suggestions[0]
    conf = best.get("confidence", 0)
    samples_html = "".join(
        f'<div class="sample">&#10003; {_e(s[:60])}</div>'
        for s in best.get("sample_texts", [])[:3]
    )
    if not samples_html:
        samples_html = '<div class="dim">(no preview available)</div>'

    left = (
        f'<div class="repair-panel broken-panel">'
        f'<div class="repair-label">BROKEN</div>'
        f'<code>{_e(broken_sel)}</code>'
        f'<div class="repair-count" style="color:{_COLORS["broken"]}">{broken_count} matches</div>'
        f'</div>'
    )
    right = (
        f'<div class="repair-panel suggested-panel">'
        f'<div class="repair-label" style="color:{_COLORS["healthy"]}">SUGGESTED</div>'
        f'<code>{_e(best["selector"])}</code>'
        f'<div class="repair-count" style="color:{_COLORS["healthy"]}">'
        f'{best["match_count"]} matches &middot; conf={conf:.0%}</div>'
        f'<div class="repair-reason">{_e(best.get("reason", ""))}</div>'
        f'{samples_html}'
        f'</div>'
    )

    others = ""
    if len(suggestions) > 1:
        other_rows: list[str] = []
        for i, s in enumerate(suggestions[1:5], 2):
            c = s.get("confidence", 0)
            other_rows.append(
                f'<tr><td>{i}.</td>'
                f'<td><code>{_e(s["selector"])}</code></td>'
                f'<td>{s["match_count"]}</td>'
                f'<td>{c:.0%}</td>'
                f'<td class="dim">{_e(s.get("reason", ""))}</td></tr>'
            )
        others = (
            f'<div class="other-candidates"><h4>Other candidates</h4>'
            f'<table class="candidates-table"><thead>'
            f'<tr><th></th><th>Selector</th><th>Matches</th><th>Conf</th><th>Reason</th></tr>'
            f'</thead><tbody>{"".join(other_rows)}</tbody></table></div>'
        )

    return (
        f'<div class="section"><h3>Repair Suggestions</h3>'
        f'<div class="repair-diff">{left}{right}</div>'
        f'{others}</div>'
    )


# ─────────────────────────────────────────────────────────────────────
# Page wrapper with inline CSS
# ─────────────────────────────────────────────────────────────────────

def _wrap_page(
    body: str, total: int, healthy: int, broken: int, degraded: int,
    total_sites: int = 0, healthy_sites: int = 0,
) -> str:
    if broken > 0:
        favicon_color = "red"
    elif degraded > 0:
        favicon_color = "yellow"
    else:
        favicon_color = "green"

    title = f"probelab: {healthy_sites}/{total_sites} sites healthy ({healthy}/{total} probes)"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_e(title)}</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
    background: {_COLORS['bg']};
    color: {_COLORS['text']};
    line-height: 1.6;
    padding: 24px;
    max-width: 960px;
    margin: 0 auto;
  }}
  a {{ color: {_COLORS['text']}; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  h1 {{ font-size: 20px; font-weight: 600; margin-bottom: 4px; }}
  h1 span {{ font-weight: 400; color: {_COLORS['dim']}; font-size: 14px; }}
  h2 {{ font-size: 16px; font-weight: 600; margin-bottom: 12px; }}
  h3 {{ font-size: 13px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; color: {_COLORS['dim']}; margin-bottom: 8px; }}
  h4 {{ font-size: 14px; font-weight: 600; margin: 0 0 8px; }}
  code {{
    font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
    font-size: 13px;
    background: {_COLORS['code_bg']};
    padding: 2px 6px;
    border-radius: 4px;
  }}
  .dim {{ color: {_COLORS['dim']}; }}

  /* Header */
  .header {{ margin-bottom: 24px; }}

  /* Summary bar */
  .summary {{
    display: flex;
    align-items: center;
    gap: 24px;
    padding: 16px 20px;
    background: {_COLORS['card']};
    border-radius: 8px;
    margin-bottom: 16px;
  }}
  .summary-stat {{ text-align: center; }}
  .stat-number {{ font-size: 28px; font-weight: 700; display: block; }}
  .stat-label {{ font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; color: {_COLORS['dim']}; }}
  .summary-divider {{ width: 1px; height: 40px; background: {_COLORS['border']}; }}
  .summary-timestamp {{ margin-left: auto; font-size: 12px; color: {_COLORS['dim']}; }}

  /* Cards */
  .card {{
    background: {_COLORS['card']};
    border-radius: 8px;
    padding: 16px 20px;
    margin-bottom: 16px;
  }}
  .card-status {{ font-size: 13px; font-weight: 500; }}

  /* Site cards */
  .site-card {{ padding: 0; overflow: hidden; }}
  .site-card details {{ }}
  .site-card details > *:not(summary) {{ padding: 0 20px; }}
  .site-card details > table {{ padding: 0 20px; margin-bottom: 12px; }}
  .site-header {{
    display: flex;
    align-items: center;
    gap: 12px;
    cursor: pointer;
    list-style: none;
    padding: 16px 20px;
  }}
  .site-header::-webkit-details-marker {{ display: none; }}
  .site-header::before {{
    content: "\\25B6";
    font-size: 10px;
    color: {_COLORS['dim']};
    transition: transform 0.2s;
  }}
  details[open] > .site-header::before {{ transform: rotate(90deg); }}
  .site-name {{ font-size: 16px; font-weight: 700; }}
  .site-probe-count {{ font-size: 13px; color: {_COLORS['dim']}; margin-left: auto; }}

  /* Probe detail (nested inside site card) */
  .probe-detail {{
    margin: 8px 20px 16px;
    padding: 12px 16px;
    border-radius: 6px;
    background: {_COLORS['bg']};
  }}

  /* Results table */
  .results-table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
  .results-table th {{
    text-align: left;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: {_COLORS['dim']};
    padding: 6px 8px;
    border-bottom: 1px solid {_COLORS['border']};
  }}
  .results-table td {{ padding: 10px 8px; border-bottom: 1px solid {_COLORS['border']}22; }}
  .results-table tr:last-child td {{ border-bottom: none; }}
  .icon {{ font-size: 16px; width: 24px; text-align: center; }}
  .probe-name {{ font-weight: 600; }}
  .status-badge {{
    padding: 2px 8px;
    border-radius: 12px;
    font-size: 12px;
    font-weight: 600;
  }}
  .details {{ color: {_COLORS['dim']}; font-size: 13px; }}
  .time {{ text-align: right; color: {_COLORS['dim']}; font-size: 13px; }}

  /* Sections inside cards */
  .section {{ margin-top: 16px; padding-top: 12px; border-top: 1px solid {_COLORS['border']}44; }}

  /* Timeline */
  .trail {{ display: flex; gap: 2px; margin-bottom: 8px; }}
  .trail-dot {{ width: 8px; height: 8px; border-radius: 2px; display: inline-block; }}
  .sparkline-row {{ display: flex; align-items: center; gap: 12px; margin-bottom: 4px; }}
  .sparkline-svg {{ display: block; }}
  .spark-stat {{ font-size: 12px; color: {_COLORS['dim']}; white-space: nowrap; }}
  .spark-stat b {{ color: {_COLORS['text']}; }}
  .section-label {{ font-size: 12px; color: {_COLORS['dim']}; margin: 6px 0 2px; font-family: 'SF Mono', monospace; }}

  /* DOM diff */
  .diff-summary {{ font-size: 13px; color: {_COLORS['dim']}; margin-bottom: 8px; }}
  .diff-tree {{ font-family: 'SF Mono', monospace; font-size: 13px; }}
  .diff-line {{ padding: 1px 0; }}
  .diff-icon {{ display: inline-block; width: 16px; text-align: center; font-weight: 700; }}

  /* Alerts */
  .alert {{
    padding: 8px 12px;
    margin-bottom: 6px;
    border-radius: 4px;
    background: {_COLORS['card']};
    font-size: 13px;
  }}
  .alert-badge {{
    padding: 1px 6px;
    border-radius: 8px;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
  }}

  /* Repair diff */
  .repair-diff {{ display: flex; gap: 12px; margin-bottom: 12px; }}
  .repair-panel {{
    flex: 1;
    padding: 12px 16px;
    border-radius: 8px;
    background: {_COLORS['code_bg']};
    border: 1px solid {_COLORS['border']};
  }}
  .broken-panel {{ border-color: {_COLORS['broken']}44; }}
  .suggested-panel {{ border-color: {_COLORS['healthy']}44; }}
  .repair-label {{
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: {_COLORS['broken']};
    margin-bottom: 8px;
  }}
  .repair-count {{ font-size: 13px; margin-top: 8px; }}
  .repair-reason {{ font-size: 12px; color: {_COLORS['dim']}; margin-top: 4px; }}
  .sample {{ font-size: 12px; color: {_COLORS['healthy']}; margin-top: 2px; }}

  /* Other candidates */
  .candidates-table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
  .candidates-table th {{
    text-align: left; font-size: 11px; text-transform: uppercase;
    color: {_COLORS['dim']}; padding: 4px 6px;
    border-bottom: 1px solid {_COLORS['border']};
  }}
  .candidates-table td {{ padding: 4px 6px; }}

  @media (max-width: 600px) {{
    body {{ padding: 12px; }}
    .summary {{ flex-wrap: wrap; gap: 12px; }}
    .repair-diff {{ flex-direction: column; }}
  }}
</style>
</head>
<body>
  <div class="header">
    <h1>probelab <span>web contract monitor</span></h1>
  </div>
  {body}
</body>
</html>"""


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────

def _e(text: str) -> str:
    """HTML-escape a string."""
    return html.escape(str(text))


def _build_details_text(result: ProbeResult) -> str:
    """Build a plain-text details string for the status table."""
    if result.error:
        return result.error

    parts = []
    for cr in result.check_results:
        if cr.passed:
            parts.append(f"{cr.match_count} matches")
        else:
            expected = f">={cr.expected_min}"
            if cr.expected_max is not None:
                expected += f", <={cr.expected_max}"
            parts.append(f"selector got {cr.match_count} (expected {expected})")

    if result.schema_errors:
        parts.append(f"{len(result.schema_errors)} schema error(s)")
    if result.drift_alerts:
        parts.append(f"{len(result.drift_alerts)} drift alert(s)")
    if result.dom_diff and result.dom_diff.get("changed"):
        parts.append("DOM changed")

    return "; ".join(parts) if parts else "-"
