"""CLI commands — the main user interface for probelab."""

from __future__ import annotations

import sys

import click
from rich.console import Console

from probelab import __version__
from probelab.config import (
    ensure_dirs,
    load_all_probes,
    load_history,
    load_probe,
    remove_probe,
    save_history,
    save_probe,
    PROBES_DIR,
)
from probelab.probe import Check, Probe
from probelab.reporter import print_json, print_table
from probelab.runner import run_all_probes, run_probe

console = Console()


@click.group()
@click.version_option(version=__version__, prog_name="probelab")
def main() -> None:
    """probelab — Monitor web contracts. Detect drift. Diagnose and repair."""


@main.command()
@click.argument("name")
@click.option("--url", required=True, help="Target URL to probe")
@click.option("--select", "selectors", multiple=True, help="CSS selector(s) to check")
@click.option("--expect-min", type=int, default=1, help="Minimum expected matches per selector")
@click.option("--expect-max", type=int, default=None, help="Maximum expected matches")
@click.option("--timeout", type=int, default=15, help="Request timeout in seconds")
@click.option("--tag", "tags", multiple=True, help="Tags for organizing probes")
def init(
    name: str,
    url: str,
    selectors: tuple[str, ...],
    expect_min: int,
    expect_max: int | None,
    timeout: int,
    tags: tuple[str, ...],
) -> None:
    """Create a new probe definition.

    Example:

        probelab init hackernews --url https://news.ycombinator.com \\
            --select "tr.athing .titleline > a" --expect-min 20
    """
    checks = [
        Check(selector=s, expect_min=expect_min, expect_max=expect_max)
        for s in selectors
    ]

    probe = Probe(
        name=name,
        url=url,
        checks=checks,
        timeout=timeout,
        tags=list(tags),
    )

    path = save_probe(probe)
    console.print(f"[green]Probe '{name}' created at {path}[/green]")


@main.command()
@click.argument("name", required=False)
@click.option("--format", "fmt", type=click.Choice(["table", "json"]), default="table", help="Output format")
@click.option("--html", "html_path", type=click.Path(), default=None, help="Write HTML report to this path")
@click.option("--strict", is_flag=True, help="Exit 2 on degraded probes (not just broken)")
@click.option("--exit-code", is_flag=True, help="Use exit codes for CI (0=healthy, 1=broken, 2=degraded)")
def check(name: str | None, fmt: str, html_path: str | None, strict: bool, exit_code: bool) -> None:
    """Run probes and report health status.

    Run all probes:     probelab check
    Run one probe:      probelab check hackernews
    CI mode:            probelab check --exit-code --format json
    HTML report:        probelab check --html report.html
    """
    if name:
        probe_path = PROBES_DIR / f"{name}.toml"
        if not probe_path.exists():
            console.print(f"[red]Probe '{name}' not found.[/red]")
            sys.exit(1)
        probes = [load_probe(probe_path)]
    else:
        probes = load_all_probes()
        if not probes:
            console.print("[yellow]No probes configured. Run 'probelab init' to create one.[/yellow]")
            return

    from probelab.runner import browser_available
    browser_probes = sum(1 for p in probes if p.browser)
    if browser_probes:
        if not browser_available():
            console.print(f"[dim]{browser_probes} probe(s) need browser — install with:[/dim] pip install probelab[browser]")
        else:
            from probelab.browser import check_cdp_available
            if check_cdp_available():
                console.print(f"[green]Chrome CDP detected[/green] — {browser_probes} browser probe(s) will use your real Chrome")
            else:
                console.print(f"[yellow]{browser_probes} browser probe(s) will use headless mode[/yellow]")
                console.print(f"[dim]For best results, start Chrome with: --remote-debugging-port=9222[/dim]")
    console.print(f"Running {len(probes)} probe(s)...\n")
    results = run_all_probes(probes)

    # Save results to history (skip probes that weren't actually tested)
    for result in results:
        if result.status.value != "skipped":
            save_history(result.probe_name, result.to_dict())

    if fmt == "json":
        print_json(results)
    else:
        print_table(results, console)

    # HTML report
    if html_path:
        from probelab.html_report import write_html_report
        history_map = {r.probe_name: load_history(r.probe_name, limit=30) for r in results}
        path = write_html_report(html_path, results, history_map)
        console.print(f"\n[green]HTML report written to {path}[/green]")

    if exit_code:
        has_broken = any(r.status.value in ("broken", "error") for r in results)
        has_degraded = any(r.status.value == "degraded" for r in results)
        if has_broken:
            sys.exit(1)
        if strict and has_degraded:
            sys.exit(2)


@main.command("list")
@click.option("--tag", help="Filter by tag")
def list_probes(tag: str | None) -> None:
    """List all configured probes."""
    probes = load_all_probes()
    if not probes:
        console.print("[yellow]No probes configured. Run 'probelab init' to create one.[/yellow]")
        return

    if tag:
        probes = [p for p in probes if tag in p.tags]

    from rich.table import Table

    table = Table(title="Configured Probes")
    table.add_column("Name", style="bold")
    table.add_column("URL")
    table.add_column("Checks", justify="right")
    table.add_column("Tags")

    for probe in probes:
        table.add_row(
            probe.name,
            probe.url,
            str(len(probe.checks)),
            ", ".join(probe.tags) if probe.tags else "-",
        )

    console.print(table)


@main.command()
@click.argument("name")
def show(name: str) -> None:
    """Show details of a specific probe."""
    probe_path = PROBES_DIR / f"{name}.toml"
    if not probe_path.exists():
        console.print(f"[red]Probe '{name}' not found.[/red]")
        sys.exit(1)

    probe = load_probe(probe_path)
    console.print(f"[bold]Probe: {probe.name}[/bold]")
    console.print(f"  URL:     {probe.url}")
    console.print(f"  Method:  {probe.method}")
    console.print(f"  Timeout: {probe.timeout}s")
    console.print(f"  Browser: {probe.browser}")
    if probe.tags:
        console.print(f"  Tags:    {', '.join(probe.tags)}")
    console.print()

    if probe.checks:
        console.print("[bold]Checks:[/bold]")
        for i, check in enumerate(probe.checks, 1):
            bounds = f">={check.expect_min}"
            if check.expect_max is not None:
                bounds += f", <={check.expect_max}"
            console.print(f"  {i}. {check.selector}  ({bounds}, extract={check.extract})")
    else:
        console.print("[yellow]  No checks defined.[/yellow]")

    if probe.schema:
        import json

        console.print()
        console.print("[bold]Schema:[/bold]")
        console.print(f"  {json.dumps(probe.schema, indent=2)}")


@main.command()
@click.argument("name")
@click.confirmation_option(prompt="Are you sure you want to remove this probe?")
def remove(name: str) -> None:
    """Remove a probe definition."""
    if remove_probe(name):
        console.print(f"[green]Probe '{name}' removed.[/green]")
    else:
        console.print(f"[red]Probe '{name}' not found.[/red]")
        sys.exit(1)


@main.command()
@click.argument("name")
@click.option("--limit", type=int, default=30, help="Number of recent results to show")
def history(name: str, limit: int) -> None:
    """Show match-count timeline and run history for a probe."""
    from probelab.viz import render_timeline

    results = load_history(name, limit=limit)
    if not results:
        console.print(f"[yellow]No history for probe '{name}'.[/yellow]")
        return

    render_timeline(name, results, console)


@main.command()
def status() -> None:
    """Health dashboard — one-screen overview of all probes."""
    from probelab.viz import render_health_dashboard

    probes = load_all_probes()
    if not probes:
        console.print("[yellow]No probes configured.[/yellow]")
        return

    probes_history: dict[str, list] = {}
    for probe in probes:
        hist = load_history(probe.name, limit=30)
        probes_history[probe.name] = hist

    render_health_dashboard(probes_history, console)


@main.command()
@click.argument("name")
def baseline(name: str) -> None:
    """Show learned baseline statistics and suggested thresholds for a probe.

    Requires at least 5 history entries. Run 'probelab check' several times first.
    """
    from probelab.baseline import compute_baseline, suggest_expectations
    from rich.table import Table

    baselines = compute_baseline(name)
    if not baselines:
        console.print(f"[yellow]Not enough history for probe '{name}' (need 5+ runs).[/yellow]")
        return

    table = Table(title=f"Baseline: {name}")
    table.add_column("Selector")
    table.add_column("Mean", justify="right")
    table.add_column("Stddev", justify="right")
    table.add_column("Range", justify="right")
    table.add_column("Suggested Min", justify="right")
    table.add_column("Suggested Max", justify="right")
    table.add_column("Samples", justify="right")

    suggestions = suggest_expectations(baselines)

    for selector, stats in baselines.items():
        sugg = suggestions.get(selector, {})
        table.add_row(
            selector[:50],
            f"{stats.mean:.1f}",
            f"{stats.stddev:.1f}",
            f"{stats.min_seen}-{stats.max_seen}",
            str(sugg.get("expect_min", "?")),
            str(sugg.get("expect_max", "?")),
            str(stats.sample_count),
        )

    console.print(table)


@main.command()
@click.argument("name")
def diff(name: str) -> None:
    """Show DOM structural diff as a tree view.

    Compares the current snapshot against the previous one, showing
    added, removed, and renamed elements in a tree hierarchy.
    """
    from probelab.differ import load_snapshot
    from probelab.viz import render_dom_diff_tree

    snapshot = load_snapshot(name)
    if not snapshot:
        console.print(f"[yellow]No snapshot for '{name}'. Run 'probelab check' first.[/yellow]")
        return

    # Check if we have a previous snapshot stored in history
    hist = load_history(name, limit=10)
    old_snapshot = None
    for entry in reversed(hist):
        dd = entry.get("dom_diff")
        if dd and dd.get("old_hash") and dd["old_hash"] != snapshot.get("hash"):
            # We need the actual old snapshot, not just the diff.
            # Build a synthetic "old" snapshot from the diff info.
            # The real old snapshot is gone, but we can reconstruct
            # paths from the current snapshot + the diff changes.
            break

    # For now, show the current snapshot as a tree.
    # If the last check recorded a diff, show it.
    last_diff = None
    if hist:
        last_entry = hist[-1]
        last_diff = last_entry.get("dom_diff")

    if last_diff and last_diff.get("changed"):
        # Reconstruct old paths from current paths + diff changes
        current_paths = set(snapshot.get("paths", []))
        changes = last_diff.get("changes", [])
        removed_paths = {c["path"] for c in changes if c["type"] == "removed"}
        added_paths = {c["path"] for c in changes if c["type"] == "added"}
        old_paths = (current_paths | removed_paths) - added_paths

        old_synthetic = {"paths": sorted(old_paths), "hash": last_diff.get("old_hash", "?")}
        new_synthetic = {"paths": snapshot.get("paths", []), "hash": snapshot.get("hash", "?")}
        render_dom_diff_tree(old_synthetic, new_synthetic, console)
    else:
        console.print(f"[bold]Current snapshot for {name}[/bold]")
        console.print(f"  Hash: {snapshot.get('hash', '?')}")
        console.print(f"  No previous diff available — run 'probelab check' after a site change.")


@main.command("import-opencli")
@click.argument("path", type=click.Path(exists=True, file_okay=False))
@click.option("--dry-run", is_flag=True, help="Show what would be imported without saving")
@click.option("--force", is_flag=True, help="Overwrite existing probes with the same name")
@click.option("--tag", "extra_tags", multiple=True, help="Additional tags for imported probes")
def import_opencli_cmd(path: str, dry_run: bool, force: bool, extra_tags: tuple[str, ...]) -> None:
    """Import probe definitions from an opencli repository.

    Scans the given PATH for opencli adapter files, extracts CSS
    selectors and URLs, and generates probelab probes.

    Example:

        probelab import-opencli ~/code/opencli
        probelab import-opencli ./opencli --dry-run
    """
    from pathlib import Path as P

    from probelab.opencli import import_opencli, scan_opencli_dir, adapters_to_probes

    opencli_path = P(path)

    if dry_run:
        adapters = scan_opencli_dir(opencli_path)
        if not adapters:
            console.print("[yellow]No adapters found in this directory.[/yellow]")
            return

        probes, skipped = adapters_to_probes(adapters)

        from rich.table import Table

        table = Table(title=f"Dry Run: {len(probes)} probe(s) from {len(adapters)} adapter(s)")
        table.add_column("Probe Name", style="bold")
        table.add_column("URL")
        table.add_column("Selectors", justify="right")
        table.add_column("Browser")
        table.add_column("Tags")

        for probe in probes:
            table.add_row(
                probe.name,
                probe.url[:60] + "..." if len(probe.url) > 60 else probe.url,
                str(len(probe.checks)),
                "yes" if probe.browser else "no",
                ", ".join(probe.tags),
            )

        console.print(table)

        if skipped:
            console.print(f"\n[yellow]Skipped {len(skipped)}:[/yellow]")
            for name, reason in skipped:
                console.print(f"  {name}: {reason}")
        return

    result = import_opencli(
        opencli_path,
        force=force,
        extra_tags=list(extra_tags) if extra_tags else None,
    )

    console.print(f"\n[bold]Import complete[/bold]")
    console.print(f"  Adapters found:  {result.adapters_found}")
    console.print(f"  Probes created:  [green]{result.probes_created}[/green]")

    if result.skipped:
        console.print(f"  Skipped:         [yellow]{len(result.skipped)}[/yellow]")
        for name, reason in result.skipped:
            console.print(f"    {name}: {reason}")

    if result.created_paths:
        console.print(f"\n[green]Probes saved to .probelab/probes/[/green]")
        console.print(f"Run 'probelab check' to test them.")


if __name__ == "__main__":
    main()
