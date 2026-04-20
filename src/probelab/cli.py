"""Probelab CLI — browser automation health monitoring.

Commands:
    probelab init                       Create ~/.probelab/ + example probe
    probelab check [probe.yaml]         Run one or all probes
    probelab show <name>                Show last run result
    probelab diff <name>                Compare latest vs baseline
    probelab diagnose <name>            Failure analysis + repair suggestions
    probelab import-opencli <path>      Import probes from opencli adapters
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

import httpx
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
def login(
    url: str = typer.Argument(..., help="URL to open for login (e.g., https://www.zhihu.com)"),
):
    """Open Chrome and wait for you to log in.

    Launches Chrome with your real profile and CDP enabled,
    navigates to the URL, then waits for you to log in manually
    (scan QR code, enter credentials, etc.).

    After you're done, press Enter and Chrome stays running.
    Subsequent 'probelab check' commands will use your session.

    Example:

        probelab login https://www.zhihu.com
        # ... log in in the browser ...
        # press Enter
        probelab check probes/zhihu-cdp.yaml
    """
    from probelab.browser import check_cdp_available, ensure_chrome_cdp, DEFAULT_CDP_URL

    console.print(f"\n[bold]probelab login[/]\n")

    # Step 1: ensure Chrome is running with CDP
    endpoint = DEFAULT_CDP_URL
    if not check_cdp_available(endpoint):
        console.print("  Launching Chrome with your profile...")
        if not ensure_chrome_cdp(endpoint):
            console.print("[red]  Could not launch Chrome.[/]")
            console.print("  Try manually: /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome --remote-debugging-port=9222 --user-data-dir=/tmp/probelab-chrome")
            raise typer.Exit(1)
        console.print("  [green]Chrome launched.[/]\n")
    else:
        console.print("  [green]Chrome already running with CDP.[/]\n")

    # Step 2: open the URL in a new tab
    try:
        from playwright.sync_api import sync_playwright

        console.print(f"  Opening {url} ...")

        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(endpoint)
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded")
            page.bring_to_front()

            console.print(f"  [green]Page opened.[/]\n")
            console.print("  [bold]Log in now.[/] Scan QR code, enter credentials, whatever you need.")
            console.print("  When you're done, come back here and press Enter.\n")

            # Wait for user
            input("  Press Enter when logged in → ")

            # Verify we're no longer on a login page
            current_url = page.url
            console.print(f"\n  Current URL: {current_url}")

            if any(kw in current_url.lower() for kw in ("login", "signin", "sign-in", "auth", "sso")):
                console.print("  [yellow]Still looks like a login page. You may need to try again.[/]")
            else:
                console.print("  [green]Looks good! Session should be active.[/]")

            console.print(f"\n  Chrome stays running. Now run:")
            console.print(f"  [bold]probelab check <your-probe.yaml>[/]\n")

            # Disconnect without closing Chrome
            browser.close()

    except ImportError:
        console.print("[red]  Playwright not installed. Run: pip install probelab[browser][/]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]  Error: {e}[/]")
        raise typer.Exit(1)


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
        probes = [probe]
    else:
        # Run all probes
        if not PROBES_DIR.exists():
            console.print(f"[red]No probes directory.[/] Run [bold]probelab init[/] first.")
            raise typer.Exit(1)
        probes = load_all_probes(PROBES_DIR)
        if not probes:
            console.print(f"[dim]No probes found in {PROBES_DIR}[/]")
            raise typer.Exit(0)

    # Auto-launch Chrome if any probe needs a browser and CDP isn't running
    needs_browser = any(
        p.browser or any(s.action in ("click", "type", "wait_for_selector") for s in p.steps)
        for p in probes
    )
    if needs_browser or cdp:
        from probelab.browser import check_cdp_available, ensure_chrome_cdp, DEFAULT_CDP_URL
        endpoint = cdp or DEFAULT_CDP_URL
        if not check_cdp_available(endpoint):
            console.print("[dim]Chrome CDP not running. Launching Chrome...[/]")
            if ensure_chrome_cdp(endpoint):
                console.print("[green]Chrome launched with debugging enabled.[/]")
            else:
                console.print("[yellow]Could not launch Chrome. Browser probes may use headless mode.[/]")

    results = run_all_probes(probes, cdp_url=cdp)

    # === Interactive auth retry ===
    # If any probe failed due to auth and we're in a terminal (not CI),
    # offer to open the browser for login and retry automatically.
    if not json_output and _is_interactive():
        auth_failures = [
            (i, r) for i, r in enumerate(results)
            if r.failure and r.failure.category == "auth_expired"
        ]
        if auth_failures:
            retried = _handle_auth_retry(auth_failures, probes, cdp, console)
            if retried:
                # Replace failed results with retry results
                for idx, new_result in retried:
                    results[idx] = new_result

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


@app.command("import-opencli")
def import_opencli_cmd(
    path: str = typer.Argument(..., help="Path to opencli repository"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be imported without saving"),
    force: bool = typer.Option(False, "--force", help="Overwrite existing probes with the same name"),
    extra_tags: Optional[list[str]] = typer.Option(None, "--tag", help="Additional tags for imported probes"),
):
    """Import probe definitions from an opencli repository."""
    from probelab.opencli import import_opencli, scan_opencli_dir, adapters_to_probes

    opencli_path = Path(path)
    if not opencli_path.exists():
        console.print(f"[red]Path not found:[/] {path}")
        raise typer.Exit(1)

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


@app.command()
def scan(
    path: str = typer.Argument(".", help="Project directory to scan (defaults to current dir)"),
    accept: bool = typer.Option(False, "--accept", "-y", help="Accept all and write probe files immediately"),
    min_confidence: float = typer.Option(0.5, "--min-confidence", help="Minimum confidence threshold (0.0-1.0)"),
    output_dir: Optional[str] = typer.Option(None, "--output", "-o", help="Output directory for probe files"),
):
    """Scan your project for external web and API dependencies.

    Finds URLs, API SDKs, selectors, and env vars in your code,
    then generates probe YAML files for monitoring each one.

    Examples:

        probelab scan                  # scan current directory
        probelab scan ~/my-project     # scan a specific project
        probelab scan --accept         # scan and write probes immediately
    """
    from rich.table import Table

    from probelab.scan.scanner import scan_directory
    from probelab.scan.generate import dependencies_to_probes, write_probes

    scan_path = Path(path).resolve()
    if not scan_path.is_dir():
        console.print(f"[red]Not a directory:[/] {path}")
        raise typer.Exit(1)

    console.print(f"\n[bold]Scanning {scan_path.name}/[/] ...\n")

    deps = scan_directory(scan_path)

    # Filter by confidence
    deps = [d for d in deps if d.confidence >= min_confidence]

    if not deps:
        console.print("[dim]No external dependencies found.[/]")
        console.print("[dim]Try lowering --min-confidence, or check that the directory has source files.[/]")
        raise typer.Exit(0)

    # Separate web and API deps
    web_deps = [d for d in deps if d.kind == "web"]
    api_deps = [d for d in deps if d.kind == "api"]

    console.print(f"  Found [bold]{len(deps)}[/] external dependencies:\n")

    # Display results
    if api_deps:
        api_table = Table(title=f"API Dependencies ({len(api_deps)})", show_lines=False)
        api_table.add_column("Provider", style="bold cyan")
        api_table.add_column("Source")
        api_table.add_column("Env Key", style="dim")
        api_table.add_column("Confidence", justify="right")

        for dep in api_deps:
            api_table.add_row(
                dep.provider,
                f"{dep.source_file}:{dep.source_line}",
                dep.env_key or "-",
                f"{dep.confidence:.0%}",
            )
        console.print(api_table)
        console.print()

    if web_deps:
        web_table = Table(title=f"Web Dependencies ({len(web_deps)})", show_lines=False)
        web_table.add_column("URL", style="bold")
        web_table.add_column("Source")
        web_table.add_column("Selectors")
        web_table.add_column("Confidence", justify="right")

        for dep in web_deps:
            sel_str = ", ".join(dep.selectors[:2])
            if len(dep.selectors) > 2:
                sel_str += f" +{len(dep.selectors) - 2}"
            web_table.add_row(
                (dep.url or "")[:60],
                f"{dep.source_file}:{dep.source_line}",
                sel_str or "-",
                f"{dep.confidence:.0%}",
            )
        console.print(web_table)
        console.print()

    # Generate probes
    probes = dependencies_to_probes(deps)

    if not probes:
        console.print("[dim]No probes could be generated from these dependencies.[/]")
        raise typer.Exit(0)

    console.print(f"  [bold]{len(probes)} probe(s)[/] ready to generate.\n")

    if accept:
        out = Path(output_dir) if output_dir else PROBES_DIR
        from probelab.io.store import ensure_dirs
        ensure_dirs(HOME)
        written = write_probes(probes, out)
        console.print(f"  [green]Wrote {len(written)} probe file(s) to {out}/[/]")
        if written:
            console.print(f"\n  Run [bold]probelab check[/] to test them.")
    else:
        # Preview mode
        console.print("  [dim]Probes not written yet. Run with [bold]--accept[/bold] to save them.[/]")
        console.print(f"  [dim]Or: probelab scan {path} --accept[/]")
        console.print()

        # Show a preview of each probe
        for probe in probes[:10]:
            kind_color = "cyan" if probe.get("target", {}).get("type") == "api" else "green"
            assertions = probe.get("assertions", [])
            assert_summary = ", ".join(a.get("type", "?") for a in assertions[:3])
            console.print(
                f"    [{kind_color}]{probe.get('target', {}).get('type', '?')}[/{kind_color}]  "
                f"[bold]{probe['name']}[/]  "
                f"[dim]{assert_summary}[/]"
            )

        remaining = len(probes) - 10
        if remaining > 0:
            console.print(f"    [dim]... and {remaining} more[/]")
        console.print()


@app.command()
def doctor(
    path: str = typer.Argument(".", help="Project directory to scan"),
    min_confidence: float = typer.Option(0.8, "--min-confidence", help="Minimum confidence threshold"),
    timeout: int = typer.Option(15, "--timeout", help="Request timeout in seconds"),
    verify_keys: bool = typer.Option(False, "--verify-keys", help="Actually send API keys to verify they work (opt-in)"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """Scan your project and check all external dependencies RIGHT NOW.

    Combines scan + check in one step: discovers your web and API
    dependencies, then immediately tests each one and reports status.

    SAFE BY DEFAULT: API keys are never sent anywhere. probelab only
    checks if the env var is set and the service endpoint is reachable.
    Use --verify-keys to opt in to actual key validation.

    Examples:

        probelab doctor                      # scan + check (safe mode)
        probelab doctor ~/my-project         # scan a specific project
        probelab doctor --verify-keys        # actually validate API keys
    """
    import json
    from rich.table import Table

    from probelab.scan.scanner import scan_directory
    from probelab.scan.api_check import check_api, ApiCheckResult

    scan_path = Path(path).resolve()
    if not scan_path.is_dir():
        console.print(f"[red]Not a directory:[/] {path}")
        raise typer.Exit(1)

    console.print(f"\n[bold]probelab doctor[/] — scanning {scan_path.name}/ ...\n")

    deps = scan_directory(scan_path)
    deps = [d for d in deps if d.confidence >= min_confidence]

    if not deps:
        console.print("[green]No external dependencies found. Nothing to check.[/]")
        raise typer.Exit(0)

    api_deps = [d for d in deps if d.kind == "api"]
    web_deps = [d for d in deps if d.kind == "web"]

    all_results: list[dict] = []
    has_failures = False

    # === Check API dependencies ===
    if api_deps:
        console.print(f"  Checking {len(api_deps)} API dependencies...\n")

        api_table = Table(show_lines=False)
        api_table.add_column("", width=2)
        api_table.add_column("Provider", style="bold")
        api_table.add_column("Status")
        api_table.add_column("Message")
        api_table.add_column("Time", justify="right")

        if not verify_keys:
            console.print(f"  [dim]Safe mode: keys are NOT sent. Use --verify-keys to validate them.[/]\n")

        for dep in api_deps:
            result = check_api(dep.provider, env_key=dep.env_key or None, timeout=timeout, verify_key=verify_keys)

            icon, color = _status_display(result.status)
            time_str = f"{result.response_time_ms}ms" if result.response_time_ms else "-"

            api_table.add_row(
                icon,
                result.provider,
                f"[{color}]{result.status}[/{color}]",
                result.message[:60],
                time_str,
            )

            if result.status not in ("healthy",):
                has_failures = True

            all_results.append({"kind": "api", **result.to_dict()})

        console.print(api_table)
        console.print()

    # === Check web dependencies (basic reachability) ===
    if web_deps:
        console.print(f"  Checking {len(web_deps)} web dependencies...\n")

        web_table = Table(show_lines=False)
        web_table.add_column("", width=2)
        web_table.add_column("URL", style="bold")
        web_table.add_column("Status")
        web_table.add_column("Details")
        web_table.add_column("Time", justify="right")

        with httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "probelab/1.0"},
        ) as client:
            for dep in web_deps:
                if not dep.url:
                    continue
                web_result = _check_web_dep(client, dep.url)
                icon, color = _status_display(web_result["status"])
                time_str = f"{web_result.get('response_time_ms', 0)}ms"

                web_table.add_row(
                    icon,
                    (dep.url or "")[:55],
                    f"[{color}]{web_result['status']}[/{color}]",
                    web_result.get("message", "")[:50],
                    time_str,
                )

                if web_result["status"] != "healthy":
                    has_failures = True

                all_results.append({"kind": "web", "url": dep.url, **web_result})

        console.print(web_table)
        console.print()

    # === Summary ===
    total = len(all_results)
    healthy = sum(1 for r in all_results if r.get("status") == "healthy")
    no_key = sum(1 for r in all_results if r.get("status") == "no_key")
    broken = total - healthy - no_key

    if json_output:
        print(json.dumps({"results": all_results, "summary": {"total": total, "healthy": healthy, "broken": broken, "no_key": no_key}}, indent=2))
    else:
        parts = []
        if broken:
            parts.append(f"[red]{broken} broken[/]")
        if no_key:
            parts.append(f"[yellow]{no_key} no key[/]")
        parts.append(f"[green]{healthy} healthy[/]")
        console.print(f"  {total} dependencies: {', '.join(parts)}")
        console.print()

    if has_failures:
        raise typer.Exit(1)


def _check_web_dep(client: httpx.Client, url: str) -> dict:
    """Quick health check on a web URL."""
    try:
        start = time.monotonic()
        response = client.get(url)
        elapsed_ms = int((time.monotonic() - start) * 1000)

        if response.status_code == 200:
            return {"status": "healthy", "message": f"HTTP {response.status_code}", "response_time_ms": elapsed_ms}
        elif response.status_code in (301, 302, 307, 308):
            return {"status": "healthy", "message": f"Redirect -> {response.headers.get('location', '?')[:40]}", "response_time_ms": elapsed_ms}
        elif response.status_code == 403:
            return {"status": "healthy", "message": "HTTP 403 (blocked but reachable)", "response_time_ms": elapsed_ms}
        elif response.status_code == 404:
            return {"status": "broken", "message": "HTTP 404 — page not found", "response_time_ms": elapsed_ms}
        elif response.status_code >= 500:
            return {"status": "broken", "message": f"HTTP {response.status_code} — server error", "response_time_ms": elapsed_ms}
        else:
            return {"status": "healthy", "message": f"HTTP {response.status_code}", "response_time_ms": elapsed_ms}
    except httpx.ConnectError:
        return {"status": "broken", "message": "Connection failed — DNS or network error"}
    except httpx.TimeoutException:
        return {"status": "broken", "message": "Timed out"}
    except httpx.RequestError as e:
        return {"status": "broken", "message": str(e)[:60]}


def _status_display(status: str) -> tuple[str, str]:
    """Return (icon, color) for a status string."""
    if status == "healthy":
        return ("[green]\u2713[/]", "green")
    elif status == "no_key":
        return ("[yellow]?[/]", "yellow")
    elif status in ("auth_expired", "auth_invalid"):
        return ("[red]\u2717[/]", "red")
    elif status in ("broken", "service_down", "unreachable"):
        return ("[red]![/]", "red")
    else:
        return ("[dim]-[/]", "dim")


def _is_interactive() -> bool:
    """Check if we're in an interactive terminal (not piped/CI)."""
    import sys
    return sys.stdin.isatty() and sys.stdout.isatty()


def _handle_auth_retry(
    auth_failures: list[tuple[int, Any]],
    probes: list,
    cdp: str | None,
    console: Console,
) -> list[tuple[int, Any]] | None:
    """Handle auth failures interactively: open browser, wait for login, retry.

    Returns list of (index, new_result) if retried, or None if user skipped.
    """
    from probelab.browser import check_cdp_available, ensure_chrome_cdp, DEFAULT_CDP_URL
    from probelab.engine import run_probe

    # Collect unique URLs that need auth
    urls = []
    for _, result in auth_failures:
        if result.url and result.url not in urls:
            urls.append(result.url)

    console.print()
    console.print(f"  [yellow]{len(auth_failures)} probe(s) need login.[/]")
    for url in urls[:3]:
        console.print(f"    • {url}")

    console.print()
    response = input("  Open Chrome to log in? [Y/n] → ").strip().lower()
    if response in ("n", "no"):
        return None

    # Ensure Chrome is running
    endpoint = cdp or DEFAULT_CDP_URL
    if not check_cdp_available(endpoint):
        console.print("\n  Launching Chrome...")
        if not ensure_chrome_cdp(endpoint):
            console.print("  [red]Could not launch Chrome.[/]")
            return None

    # Open each URL in Chrome for login
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(endpoint)
            context = browser.contexts[0] if browser.contexts else browser.new_context()

            for url in urls:
                console.print(f"\n  Opening {url} ...")
                page = context.new_page()
                page.goto(url, wait_until="domcontentloaded")
                page.bring_to_front()

            console.print()
            console.print("  [bold]Log in now.[/] Scan QR code, enter credentials, etc.")
            input("\n  Press Enter when done → ")

            browser.close()

    except ImportError:
        console.print("  [red]Playwright not installed: pip install probelab[browser][/]")
        return None
    except Exception as e:
        console.print(f"  [red]Error: {e}[/]")
        return None

    # Retry the failed probes
    console.print("\n  Re-checking...\n")
    retried: list[tuple[int, Any]] = []
    for idx, old_result in auth_failures:
        probe = probes[idx]
        new_result = run_probe(probe, cdp_url=cdp)
        retried.append((idx, new_result))

    return retried


def main():
    """Entry point."""
    app()


if __name__ == "__main__":
    main()
