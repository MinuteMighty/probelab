"""Probelab CLI v1 — Typer-based, step-oriented.

Commands:
    probelab init                  Create ~/.probelab/ + example probe
    probelab check <probe.yaml>    Run one probe
    probelab check-all             Run all probes in ~/.probelab/probes/
    probelab show <probe_name>     Show last run result
    probelab diff <probe_name>     Compare latest vs baseline
    probelab diagnose <probe_name> Show failure diagnosis + repair hints
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

app = typer.Typer(
    name="probelab",
    help="Browser automation health monitoring CLI.",
    no_args_is_help=True,
)
console = Console()

# Default paths
HOME = Path.home() / ".probelab"
PROBES_DIR = HOME / "probes"


@app.command()
def init():
    """Create ~/.probelab/ directory with an example probe."""
    from probelab.io.store import ensure_dirs
    from probelab.io.loader import save_probe_yaml
    from probelab.models.probe import Probe, Target, Step, Assertion, OutputSpec

    ensure_dirs(HOME)

    # Create example probe
    example = Probe(
        name="hackernews",
        description="Verify Hacker News loads and has stories",
        target=Target(type="web", url="https://news.ycombinator.com/"),
        steps=[
            Step(action="goto", url="https://news.ycombinator.com/"),
        ],
        assertions=[
            Assertion(type="text_exists", text="Hacker News"),
            Assertion(type="selector_exists", selector="span.titleline > a"),
            Assertion(type="selector_count", selector="span.titleline > a", min=10),
        ],
        outputs=[
            OutputSpec(type="screenshot"),
            OutputSpec(type="html"),
        ],
    )

    probe_path = PROBES_DIR / "hackernews.yaml"
    if not probe_path.exists():
        save_probe_yaml(example, probe_path)
        console.print(f"[green]Created[/] {probe_path}")
    else:
        console.print(f"[dim]Already exists:[/] {probe_path}")

    console.print(f"\n[bold]probelab initialized at {HOME}[/]")
    console.print(f"  Probes: {PROBES_DIR}")
    console.print(f"\nTry: [bold]probelab check {probe_path}[/]")


@app.command()
def check(
    probe_path: Optional[str] = typer.Argument(None, help="Path to probe YAML file"),
    cdp: Optional[str] = typer.Option(None, help="CDP endpoint (e.g., ws://localhost:9222)"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed results"),
):
    """Run one or all probes and show results."""
    from probelab.io.loader import load_probe, load_all_probes
    from probelab.io.store import append_history, save_baseline, save_run
    from probelab.engine import run_probe, run_all_probes
    from probelab.report.terminal import print_results, print_result_detail, print_json
    from probelab.models.result import Status

    if probe_path:
        # Run single probe
        path = Path(probe_path)
        if not path.exists():
            console.print(f"[red]Probe not found:[/] {path}")
            raise typer.Exit(1)
        probe = load_probe(path)
        results = [run_probe(probe, cdp_url=cdp)]
    else:
        # Run all probes
        if not PROBES_DIR.exists():
            console.print(f"[red]No probes directory.[/] Run [bold]probelab init[/] first.")
            raise typer.Exit(1)
        probes = load_all_probes(PROBES_DIR)
        if not probes:
            console.print(f"[dim]No probes found in {PROBES_DIR}[/]")
            raise typer.Exit(0)
        results = run_all_probes(probes, cdp_url=cdp)

    # Save results
    for result in results:
        result_dict = result.to_dict()
        append_history(result.probe_name, result_dict, HOME)
        save_run(result_dict, HOME)
        if result.status == Status.HEALTHY:
            save_baseline(result.probe_name, result_dict, HOME)

    # Output
    if json_output:
        print_json(results)
    elif verbose:
        for result in results:
            print_result_detail(result, console)
    else:
        print_results(results, console)

    # Exit code
    if any(r.status in (Status.BROKEN, Status.ERROR) for r in results):
        raise typer.Exit(1)


@app.command()
def show(
    probe_name: str = typer.Argument(..., help="Probe name"),
):
    """Show the last run result for a probe."""
    from probelab.io.store import load_last_run
    from probelab.models.result import RunResult, Status

    last = load_last_run(probe_name, HOME)
    if not last:
        console.print(f"[dim]No runs found for '{probe_name}'[/]")
        raise typer.Exit(0)

    # Reconstruct RunResult for display
    from probelab.report.terminal import print_result_detail

    result = RunResult(
        probe_name=last.get("probe_name", probe_name),
        url=last.get("url", ""),
        status=Status(last.get("status", "unknown")),
        started_at=last.get("started_at", ""),
        duration_ms=last.get("duration_ms", 0),
        tags=last.get("tags", []),
    )
    if last.get("failure"):
        from probelab.models.result import FailureClassification
        f = last["failure"]
        result.failure = FailureClassification(
            category=f.get("category", "unknown"),
            message=f.get("message", ""),
        )

    print_result_detail(result, console)


@app.command()
def diff(
    probe_name: str = typer.Argument(..., help="Probe name"),
):
    """Compare latest run vs baseline."""
    from probelab.io.store import load_last_run, load_baseline

    last = load_last_run(probe_name, HOME)
    baseline = load_baseline(probe_name, HOME)

    if not last:
        console.print(f"[dim]No runs found for '{probe_name}'[/]")
        raise typer.Exit(0)
    if not baseline:
        console.print(f"[dim]No baseline for '{probe_name}'. Run a successful check first.[/]")
        raise typer.Exit(0)

    console.print(f"\n[bold]{probe_name}[/]")
    console.print(f"  Baseline: {baseline.get('started_at', '?')} ([green]healthy[/])")
    console.print(f"  Current:  {last.get('started_at', '?')} ([{'green' if last.get('status') == 'healthy' else 'red'}]{last.get('status', '?')}[/])")

    from probelab.diff import compute_assertion_changes

    changes = compute_assertion_changes(baseline, last)

    if changes:
        console.print(f"\n  [bold]Changes:[/]")
        for change in changes:
            console.print(change)
    else:
        console.print(f"\n  [green]No changes from baseline.[/]")

    # Show failure classification if current is failed
    if last.get("failure"):
        f = last["failure"]
        console.print(f"\n  [bold]Classification:[/] [{STATUS_COLORS.get(f.get('category', ''), 'red')}]{f.get('category', '?')}[/]")
        console.print(f"  {f.get('message', '')}")

    console.print()


STATUS_COLORS = {
    "auth_expired": "yellow",
    "captcha_detected": "yellow",
    "selector_missing": "red",
    "timeout": "red",
    "navigation_error": "red",
    "unknown": "dim",
}


@app.command()
def diagnose(
    probe_name: str = typer.Argument(..., help="Probe name"),
):
    """Show failure diagnosis and repair suggestions."""
    from probelab.io.store import load_last_run

    last = load_last_run(probe_name, HOME)
    if not last:
        console.print(f"[dim]No runs found for '{probe_name}'[/]")
        raise typer.Exit(0)

    if last.get("status") == "healthy":
        console.print(f"[green]{probe_name} is healthy. Nothing to diagnose.[/]")
        raise typer.Exit(0)

    # Show failure
    failure = last.get("failure", {})
    console.print(f"\n[bold]{probe_name}[/] — [red]{last.get('status', '?')}[/]")
    console.print(f"  Category: [bold]{failure.get('category', 'unknown')}[/]")
    console.print(f"  Message: {failure.get('message', '')}")

    # For selector_missing, try to suggest repairs
    if failure.get("category") == "selector_missing":
        _suggest_repairs(probe_name, last, console)

    # For auth_expired, suggest re-login
    elif failure.get("category") == "auth_expired":
        console.print(f"\n  [bold]Action:[/] Re-login in Chrome, then re-run:")
        console.print(f"    probelab check --cdp ws://localhost:9222 ~/.probelab/probes/{probe_name}.yaml")

    # For captcha_detected, suggest manual visit
    elif failure.get("category") == "captcha_detected":
        url = last.get("url", "")
        console.print(f"\n  [bold]Action:[/] Open {url} manually, solve the CAPTCHA, then re-run.")

    console.print()


def _suggest_repairs(probe_name: str, last_run: dict, console: Console) -> None:
    """Use repair.py to suggest selector replacements."""
    try:
        from probelab.repair import suggest_repairs
    except ImportError:
        console.print(f"\n  [dim]Repair suggestions require the repair module.[/]")
        return

    # Find the broken selector from assertions
    broken_assertions = [
        a for a in last_run.get("assertions", [])
        if a.get("status") == "failed" and a.get("selector")
    ]

    if not broken_assertions:
        console.print(f"\n  [dim]No selector assertions to repair.[/]")
        return

    # We need the HTML to run repair suggestions
    # Check if we have an HTML artifact
    artifacts = last_run.get("artifacts", {})
    html_path = artifacts.get("html")
    if not html_path:
        console.print("\n  [dim]No HTML artifact saved. Add 'outputs: \\[type: html]' to the probe and re-run.[/]")
        return

    try:
        html = Path(html_path).read_text(encoding="utf-8")
    except FileNotFoundError:
        console.print(f"\n  [dim]HTML artifact not found at {html_path}[/]")
        return

    for broken in broken_assertions:
        selector = broken["selector"]
        console.print(f"\n  [bold]Selector:[/] {selector} -> {broken.get('actual', '0 matches')}")

        suggestions = suggest_repairs(
            html=html,
            broken_selector=selector,
            target_min=1,
            max_suggestions=3,
        )

        if suggestions:
            console.print(f"\n  [bold]Suggested replacements:[/]")
            for i, s in enumerate(suggestions, 1):
                conf = f"{s.confidence:.0%}"
                console.print(f"    {i}. [green]{s.selector}[/] -> {s.match_count} matches (confidence: {conf})")
                if s.reason:
                    console.print(f"       [dim]{s.reason}[/]")
        else:
            console.print(f"  [dim]No alternative selectors found.[/]")


def main():
    """Entry point."""
    app()


if __name__ == "__main__":
    main()
