"""Terminal output using Rich — tables, colors, failure details."""

from __future__ import annotations

import json

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

from probelab.models.result import RunResult, Status

STATUS_ICONS = {
    Status.HEALTHY: "[green]✓[/]",
    Status.DEGRADED: "[yellow]~[/]",
    Status.BROKEN: "[red]✗[/]",
    Status.ERROR: "[red]![/]",
    Status.SKIPPED: "[dim]—[/]",
}

STATUS_COLORS = {
    Status.HEALTHY: "green",
    Status.DEGRADED: "yellow",
    Status.BROKEN: "red",
    Status.ERROR: "red",
    Status.SKIPPED: "dim",
}


def print_results(results: list[RunResult], console: Console | None = None) -> None:
    """Print a summary table of probe results."""
    console = console or Console()

    table = Table(show_header=True, header_style="bold", show_lines=False, padding=(0, 1))
    table.add_column("", width=2)
    table.add_column("Probe", style="bold")
    table.add_column("Status", width=10)
    table.add_column("Duration", justify="right", width=10)
    table.add_column("Failure", style="dim")

    for result in results:
        icon = STATUS_ICONS.get(result.status, "?")
        color = STATUS_COLORS.get(result.status, "white")
        status_text = f"[{color}]{result.status.value}[/]"
        duration = f"{result.duration_ms}ms" if result.duration_ms else "—"
        failure = ""
        if result.failure:
            failure = f"[{color}]{result.failure.category}[/]"

        table.add_row(icon, result.probe_name, status_text, duration, failure)

    console.print()
    console.print(table)

    # Summary line
    healthy = sum(1 for r in results if r.status == Status.HEALTHY)
    broken = sum(1 for r in results if r.status == Status.BROKEN)
    error = sum(1 for r in results if r.status == Status.ERROR)
    total = len(results)

    parts = [f"[green]{healthy}[/] healthy"]
    if broken:
        parts.append(f"[red]{broken}[/] broken")
    if error:
        parts.append(f"[red]{error}[/] error")

    console.print(f"\n  {' | '.join(parts)} / {total} total\n")


def print_result_detail(result: RunResult, console: Console | None = None) -> None:
    """Print detailed results for a single probe."""
    console = console or Console()
    color = STATUS_COLORS.get(result.status, "white")

    console.print(f"\n[bold]{result.probe_name}[/] [{color}]{result.status.value}[/]")
    console.print(f"  URL: {result.url}")
    console.print(f"  Duration: {result.duration_ms}ms")
    console.print(f"  Time: {result.started_at}")

    # Steps
    if result.step_results:
        console.print(f"\n  [bold]Steps[/]")
        for step in result.step_results:
            icon = "[green]✓[/]" if step.status == "passed" else "[red]✗[/]"
            line = f"    {icon} {step.action}"
            if step.duration_ms:
                line += f" ({step.duration_ms}ms)"
            if step.error:
                line += f" [red]{step.error}[/]"
            console.print(line)

    # Assertions
    if result.assertion_results:
        console.print(f"\n  [bold]Assertions[/]")
        for a in result.assertion_results:
            icon = "[green]✓[/]" if a.status == "passed" else "[red]✗[/]"
            line = f"    {icon} {a.type}"
            if a.selector:
                line += f" [dim]{a.selector}[/]"
            if a.actual:
                line += f" = {a.actual}"
            console.print(line)

    # Failure classification
    if result.failure:
        console.print(Panel(
            f"[bold]{result.failure.category}[/]\n{result.failure.message}",
            title="Failure",
            border_style=color,
            padding=(0, 1),
        ))

    # Artifacts
    if result.artifacts:
        console.print(f"\n  [bold]Artifacts[/]")
        for atype, path in result.artifacts.items():
            console.print(f"    {atype}: {path}")

    console.print()


def print_json(results: list[RunResult]) -> None:
    """Print results as JSON."""
    data = {
        "results": [r.to_dict() for r in results],
        "summary": {
            "total": len(results),
            "healthy": sum(1 for r in results if r.status == Status.HEALTHY),
            "broken": sum(1 for r in results if r.status == Status.BROKEN),
            "error": sum(1 for r in results if r.status == Status.ERROR),
        },
    }
    print(json.dumps(data, indent=2, ensure_ascii=False))
