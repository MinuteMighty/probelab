"""Self-contained HTML report generator.

Renders all probe results — status table, DOM diff tree, sparkline timeline,
drift alerts, and repair suggestions — as a single HTML file with inline CSS.
No JavaScript frameworks, no external dependencies. One file you can open in
any browser or attach to a CI artifact.
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
}


# ─────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────

def generate_html_report(
    results: list[ProbeResult],
    history_map: dict[str, list[dict[str, Any]]] | None = None,
) -> str:
    """Generate a full HTML report string.

    Args:
        results: Current probe results.
        history_map: Optional {probe_name: [history_entries]} for timelines.

    Returns:
        Complete HTML document as a string.
    """
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    healthy = sum(1 for r in results if r.status == Status.HEALTHY)
    broken = sum(1 for r in results if r.status in (Status.BROKEN, Status.ERROR))
    degraded = sum(1 for r in results if r.status == Status.DEGRADED)
    total = len(results)

    sections: list[str] = []

    # Summary bar
    sections.append(_render_summary(total, healthy, degraded, broken, now))

    # Status table
    sections.append(_render_status_table(results))

    # Per-probe detail cards
    for result in results:
        hist = (history_map or {}).get(result.probe_name, [])
        sections.append(_render_probe_card(result, hist))

    body = "\n".join(sections)
    return _wrap_page(body, total, healthy, broken, degraded)


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
# Summary bar
# ─────────────────────────────────────────────────────────────────────

def _render_summary(total: int, healthy: int, degraded: int, broken: int, timestamp: str) -> str:
    return f"""
    <div class="summary">
      <div class="summary-stat">
        <span class="stat-number">{total}</span>
        <span class="stat-label">Total</span>
      </div>
      <div class="summary-stat">
        <span class="stat-number" style="color:{_COLORS['healthy']}">{healthy}</span>
        <span class="stat-label">Healthy</span>
      </div>
      <div class="summary-stat">
        <span class="stat-number" style="color:{_COLORS['degraded']}">{degraded}</span>
        <span class="stat-label">Degraded</span>
      </div>
      <div class="summary-stat">
        <span class="stat-number" style="color:{_COLORS['broken']}">{broken}</span>
        <span class="stat-label">Broken</span>
      </div>
      <div class="summary-timestamp">{_e(timestamp)}</div>
    </div>"""


# ─────────────────────────────────────────────────────────────────────
# Status table
# ─────────────────────────────────────────────────────────────────────

def _render_status_table(results: list[ProbeResult]) -> str:
    rows: list[str] = []
    for r in results:
        color = _COLORS.get(r.status.value, _COLORS["dim"])
        icon = _STATUS_ICON.get(r.status, "?")
        details = _build_details_text(r)
        time_str = f"{r.response_time_ms}ms" if r.response_time_ms > 0 else "-"
        rows.append(f"""
        <tr>
          <td class="icon" style="color:{color}">{icon}</td>
          <td class="probe-name">{_e(r.probe_name)}</td>
          <td><span class="status-badge" style="background:{color}20;color:{color}">{_e(r.status.value)}</span></td>
          <td class="details">{_e(details)}</td>
          <td class="time">{_e(time_str)}</td>
        </tr>""")

    return f"""
    <div class="card">
      <h2>Probe Results</h2>
      <table class="results-table">
        <thead>
          <tr><th></th><th>Probe</th><th>Status</th><th>Details</th><th>Time</th></tr>
        </thead>
        <tbody>{"".join(rows)}</tbody>
      </table>
    </div>"""


# ─────────────────────────────────────────────────────────────────────
# Per-probe detail card
# ─────────────────────────────────────────────────────────────────────

def _render_probe_card(result: ProbeResult, history: list[dict[str, Any]]) -> str:
    if result.status == Status.HEALTHY and not result.dom_diff and not result.drift_alerts:
        return ""  # Don't clutter with healthy cards

    color = _COLORS.get(result.status.value, _COLORS["dim"])
    sections: list[str] = []

    # Timeline sparkline
    if history:
        sections.append(_render_timeline_section(history))

    # DOM diff tree
    if result.dom_diff and result.dom_diff.get("changed"):
        sections.append(_render_dom_diff_section(result.dom_diff))

    # Drift alerts
    if result.drift_alerts:
        sections.append(_render_drift_section(result.drift_alerts))

    # Repair suggestions
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
    <div class="card probe-card" style="border-left:3px solid {color}">
      <h2>{_e(result.probe_name)} <span class="card-status" style="color:{color}">{_e(result.status.value)}</span></h2>
      {"".join(sections)}
    </div>"""


# ─────────────────────────────────────────────────────────────────────
# Timeline section (SVG sparkline)
# ─────────────────────────────────────────────────────────────────────

def _render_timeline_section(history: list[dict[str, Any]]) -> str:
    # Extract match counts per selector
    selector_series: dict[str, list[int]] = {}
    statuses: list[str] = []
    for entry in history:
        statuses.append(entry.get("status", "?"))
        for check in entry.get("checks", []):
            sel = check.get("selector", "?")
            count = check.get("match_count", 0)
            selector_series.setdefault(sel, []).append(count)

    parts: list[str] = []

    # Status trail
    trail = "".join(
        f'<span class="trail-dot" style="background:{_COLORS.get(s, _COLORS["dim"])}" title="{s}"></span>'
        for s in statuses
    )
    parts.append(f'<div class="section-label">Status trail</div><div class="trail">{trail}</div>')

    # SVG sparkline per selector
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

    # Fill area
    first_x = padding
    last_x = padding + ((n - 1) / max(n - 1, 1)) * (width - 2 * padding)
    fill_points = f"{first_x},{height} {polyline} {last_x},{height}"

    # Color: green if last value is high, red if low
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
        detail = change.get("details", "")
        color = _COLORS.get(ctype, _COLORS["dim"])
        icon = {"added": "+", "removed": "&minus;", "modified": "~"}.get(ctype, "?")

        # Indent based on path depth
        depth = path.count(" > ")
        indent = depth * 20

        lines.append(
            f'<div class="diff-line" style="padding-left:{indent}px">'
            f'<span class="diff-icon" style="color:{color}">{icon}</span>'
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
        sigma = alert.get("deviation_sigma", 0)

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

    # Side-by-side panels
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

    # Other candidates
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

def _wrap_page(body: str, total: int, healthy: int, broken: int, degraded: int) -> str:
    if broken > 0:
        favicon_color = "red"
    elif degraded > 0:
        favicon_color = "yellow"
    else:
        favicon_color = "green"

    title = f"probelab: {healthy}/{total} healthy"

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
  h1 {{
    font-size: 20px;
    font-weight: 600;
    margin-bottom: 4px;
  }}
  h1 span {{ font-weight: 400; color: {_COLORS['dim']}; font-size: 14px; }}
  h2 {{ font-size: 16px; font-weight: 600; margin-bottom: 12px; }}
  h3 {{ font-size: 13px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; color: {_COLORS['dim']}; margin-bottom: 8px; }}
  h4 {{ font-size: 13px; font-weight: 600; margin: 12px 0 6px; }}
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
  .summary-timestamp {{ margin-left: auto; font-size: 12px; color: {_COLORS['dim']}; }}

  /* Cards */
  .card {{
    background: {_COLORS['card']};
    border-radius: 8px;
    padding: 16px 20px;
    margin-bottom: 16px;
  }}
  .card-status {{ font-size: 13px; font-weight: 500; }}

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
