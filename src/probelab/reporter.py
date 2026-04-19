"""Output formatting — table, JSON, and summary reporters.

Enhanced with DOM diff, drift alerts, and repair suggestion display.
"""

from __future__ import annotations

import json
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from probelab.probe import ProbeResult, Status

STATUS_ICONS = {
    Status.HEALTHY: "[green]\u2713[/green]",
    Status.DEGRADED: "[yellow]~[/yellow]",
    Status.BROKEN: "[red]\u2717[/red]",
    Status.ERROR: "[red]![/red]",
    Status.SKIPPED: "[dim]\u2013[/dim]",
}

STATUS_COLORS = {
    Status.HEALTHY: "green",
    Status.DEGRADED: "yellow",
    Status.BROKEN: "red",
    Status.ERROR: "red",
    Status.SKIPPED: "dim",
}


def print_table(results: list[ProbeResult], console: Console | None = None) -> None:
    """Print probe results as a rich table with diagnostic details."""
    if console is None:
        console = Console()

    table = Table(title="Probe Results", show_lines=False)
    table.add_column("", width=2)
    table.add_column("Probe", style="bold")
    table.add_column("Status")
    table.add_column("Details")
    table.add_column("Time", justify="right")

    for result in results:
        icon = STATUS_ICONS[result.status]
        status_text = f"[{STATUS_COLORS[result.status]}]{result.status.value}[/{STATUS_COLORS[result.status]}]"
        details = _build_details(result)
        time_str = f"{result.response_time_ms}ms" if result.response_time_ms > 0 else "-"

        table.add_row(icon, result.probe_name, status_text, details, time_str)

    console.print(table)
    console.print()

    # Summary line
    healthy = sum(1 for r in results if r.status == Status.HEALTHY)
    skipped = sum(1 for r in results if r.status == Status.SKIPPED)
    tested = len(results) - skipped
    total = len(results)
    if healthy == tested and tested > 0:
        console.print(f"[green]All {tested} tested probes healthy.[/green]")
    else:
        broken = sum(1 for r in results if r.status in (Status.BROKEN, Status.ERROR))
        degraded = sum(1 for r in results if r.status == Status.DEGRADED)
        parts = []
        if broken:
            parts.append(f"[red]{broken} broken[/red]")
        if degraded:
            parts.append(f"[yellow]{degraded} degraded[/yellow]")
        parts.append(f"[green]{healthy} healthy[/green]")
        console.print(f"{tested} tested: {', '.join(parts)}")
    if skipped:
        console.print(f"[dim]{skipped} skipped (need browser)[/dim]")

    # Print diagnostic panels for non-healthy probes
    for result in results:
        if result.status in (Status.HEALTHY, Status.SKIPPED):
            continue
        _print_diagnostics(result, console)


def print_json(results: list[ProbeResult]) -> None:
    """Print probe results as JSON."""
    output = {
        "results": [r.to_dict() for r in results],
        "summary": {
            "total": len(results),
            "healthy": sum(1 for r in results if r.status == Status.HEALTHY),
            "degraded": sum(1 for r in results if r.status == Status.DEGRADED),
            "broken": sum(1 for r in results if r.status == Status.BROKEN),
            "error": sum(1 for r in results if r.status == Status.ERROR),
            "skipped": sum(1 for r in results if r.status == Status.SKIPPED),
        },
    }
    print(json.dumps(output, indent=2))


def _print_diagnostics(result: ProbeResult, console: Console) -> None:
    """Print detailed diagnostic information for a non-healthy probe."""
    lines: list[str] = []

    # DOM diff section
    if result.dom_diff and result.dom_diff.get("changed"):
        lines.append("[bold]DOM Changes:[/bold]")
        lines.append(f"  {result.dom_diff.get('summary', 'Structure changed.')}")
        for change in result.dom_diff.get("changes", [])[:5]:
            ctype = change["type"]
            icon = {"added": "+", "removed": "-", "modified": "~"}.get(ctype, "?")
            lines.append(f"  [{_change_color(ctype)}]{icon} {change['details']}[/{_change_color(ctype)}]")
        total_changes = len(result.dom_diff.get("changes", []))
        if total_changes > 5:
            lines.append(f"  ... and {total_changes - 5} more changes")
        lines.append("")

    # Drift alerts section
    if result.drift_alerts:
        lines.append("[bold]Drift Alerts:[/bold]")
        for alert in result.drift_alerts:
            severity = alert.get("severity", "warning")
            color = "red" if severity == "critical" else "yellow"
            lines.append(f"  [{color}]{alert.get('message', '')}[/{color}]")
        lines.append("")

    if lines:
        panel_content = "\n".join(lines)
        color = STATUS_COLORS[result.status]
        console.print()
        console.print(Panel(
            panel_content,
            title=f"[bold]{result.probe_name}[/bold] diagnostics",
            border_style=color,
        ))

    # Repair visual diff (rendered outside the panel for better layout)
    if result.repair_suggestions:
        from probelab.viz import render_repair_diff
        broken_selector = ""
        broken_count = 0
        for cr in result.check_results:
            if not cr.passed:
                broken_selector = cr.selector
                broken_count = cr.match_count
                break
        render_repair_diff(broken_selector, broken_count, result.repair_suggestions, console)


def _build_details(result: ProbeResult) -> str:
    """Build a human-readable details string for a probe result."""
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
        critical = sum(1 for a in result.drift_alerts if a.get("severity") == "critical")
        if critical:
            parts.append(f"{critical} drift alert(s)")

    if result.dom_diff and result.dom_diff.get("changed"):
        parts.append("DOM changed")

    return "; ".join(parts) if parts else "-"


def _change_color(change_type: str) -> str:
    return {"added": "green", "removed": "red", "modified": "yellow"}.get(change_type, "white")


def _confidence_bar(confidence: float) -> str:
    """Render a confidence score as a compact visual."""
    if confidence >= 0.7:
        return f"[green]conf={confidence:.0%}[/green]"
    elif confidence >= 0.4:
        return f"[yellow]conf={confidence:.0%}[/yellow]"
    else:
        return f"[dim]conf={confidence:.0%}[/dim]"
