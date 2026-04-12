"""Terminal visualizations — timeline, DOM tree diff, health dashboard, repair diff.

All rendering uses Rich. No browser, no HTML, no server.
"""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.tree import Tree
from rich.columns import Columns

# ─────────────────────────────────────────────────────────────────────
# 1. Match count timeline
# ─────────────────────────────────────────────────────────────────────

_SPARK_CHARS = " ▁▂▃▄▅▆▇█"


def _sparkline(values: list[int], width: int = 40) -> Text:
    """Render a list of ints as a colored sparkline."""
    if not values:
        return Text("(no data)")

    lo = min(values)
    hi = max(values)
    span = hi - lo if hi != lo else 1

    text = Text()
    for v in values[-width:]:
        idx = int((v - lo) / span * (len(_SPARK_CHARS) - 1))
        ch = _SPARK_CHARS[idx]
        # Color: green if in top 60%, yellow if mid, red if bottom 20%
        pct = (v - lo) / span
        if pct >= 0.6:
            text.append(ch, style="green")
        elif pct >= 0.2:
            text.append(ch, style="yellow")
        else:
            text.append(ch, style="red")
    return text


def render_timeline(
    probe_name: str,
    history: list[dict[str, Any]],
    console: Console | None = None,
) -> None:
    """Render match-count timeline for each selector in a probe's history."""
    if console is None:
        console = Console()

    if not history:
        console.print(f"[yellow]No history for '{probe_name}'.[/yellow]")
        return

    # Group match counts by selector across history
    selector_series: dict[str, list[int]] = {}
    timestamps: list[str] = []
    statuses: list[str] = []
    for entry in history:
        ts = entry.get("timestamp", "?")[:16]
        timestamps.append(ts)
        statuses.append(entry.get("status", "?"))
        for check in entry.get("checks", []):
            sel = check.get("selector", "?")
            count = check.get("match_count", 0)
            selector_series.setdefault(sel, []).append(count)

    console.print(f"\n[bold]Timeline: {probe_name}[/bold]  ({len(history)} runs)\n")

    # Status bar (recent run statuses)
    status_text = Text("  Status:  ")
    status_colors = {"healthy": "green", "degraded": "yellow", "broken": "red", "error": "red"}
    for s in statuses:
        color = status_colors.get(s, "dim")
        status_text.append("■", style=color)
    console.print(status_text)
    console.print()

    # Per-selector sparkline
    for selector, values in selector_series.items():
        current = values[-1] if values else 0
        peak = max(values) if values else 0
        spark = _sparkline(values)

        line = Text()
        line.append(f"  {selector[:50]:<50s}  ", style="bold")
        line.append_text(spark)
        line.append(f"  now={current}", style="bold" if current > 0 else "red bold")
        line.append(f"  peak={peak}", style="dim")
        console.print(line)

    # Time range
    if len(timestamps) >= 2:
        console.print(f"\n  [dim]{timestamps[0]}  ···  {timestamps[-1]}[/dim]")
    console.print()


# ─────────────────────────────────────────────────────────────────────
# 2. DOM diff tree view
# ─────────────────────────────────────────────────────────────────────

def render_dom_diff_tree(
    old_snapshot: dict[str, Any],
    new_snapshot: dict[str, Any],
    console: Console | None = None,
) -> None:
    """Render a tree-style DOM diff showing structural changes."""
    if console is None:
        console = Console()

    old_paths = set(old_snapshot.get("paths", []))
    new_paths = set(new_snapshot.get("paths", []))

    if old_paths == new_paths:
        console.print("[green]No structural changes.[/green]")
        return

    # Build a merged tree with change annotations
    all_paths = old_paths | new_paths
    tree = Tree("[bold]DOM Structure Diff[/bold]")

    # Organize paths by depth for tree building
    nodes: dict[str, Any] = {}  # path -> tree node

    for path in sorted(all_paths, key=lambda p: (p.count(" > "), p)):
        parts = path.split(" > ")
        label = parts[-1]
        parent_path = " > ".join(parts[:-1]) if len(parts) > 1 else None

        in_old = path in old_paths
        in_new = path in new_paths

        if in_old and in_new:
            styled = Text(f"  {label}", style="dim")
        elif in_old and not in_new:
            styled = Text(f"- {label}", style="red")
        else:  # not in_old and in_new
            styled = Text(f"+ {label}", style="green")

        # Check for renames: same parent, same base tag, different classes
        if not in_new and in_old:
            # Look for a counterpart in new_paths with same parent
            _add_rename_hint(styled, path, old_paths, new_paths)

        parent_node = nodes.get(parent_path, tree) if parent_path else tree
        node = parent_node.add(styled)
        nodes[path] = node

    console.print()
    console.print(tree)
    console.print()

    # Summary counts
    removed = old_paths - new_paths
    added = new_paths - old_paths
    unchanged = old_paths & new_paths
    parts = []
    if removed:
        parts.append(f"[red]{len(removed)} removed[/red]")
    if added:
        parts.append(f"[green]{len(added)} added[/green]")
    parts.append(f"[dim]{len(unchanged)} unchanged[/dim]")
    console.print(f"  {', '.join(parts)}")
    console.print()


def _add_rename_hint(
    text: Text, old_path: str, old_paths: set[str], new_paths: set[str]
) -> None:
    """If a removed element has a likely renamed counterpart, annotate it."""
    parts = old_path.split(" > ")
    if len(parts) < 2:
        return
    parent = " > ".join(parts[:-1])
    old_leaf = parts[-1]
    old_tag = old_leaf.split(".")[0].split("#")[0]

    for new_path in new_paths:
        if new_path in old_paths:
            continue
        new_parts = new_path.split(" > ")
        if len(new_parts) < 2:
            continue
        new_parent = " > ".join(new_parts[:-1])
        new_leaf = new_parts[-1]
        new_tag = new_leaf.split(".")[0].split("#")[0]
        if new_parent == parent and new_tag == old_tag and new_leaf != old_leaf:
            text.append(f"  → {new_leaf}", style="yellow")
            break


# ─────────────────────────────────────────────────────────────────────
# 3. Health dashboard
# ─────────────────────────────────────────────────────────────────────

def render_health_dashboard(
    probes_history: dict[str, list[dict[str, Any]]],
    console: Console | None = None,
    trail_length: int = 30,
) -> None:
    """Render a one-screen health dashboard for all probes.

    Args:
        probes_history: {probe_name: [history_entries]}
        trail_length: Number of recent runs to show in the health trail.
    """
    if console is None:
        console = Console()

    if not probes_history:
        console.print("[yellow]No probes with history.[/yellow]")
        return

    console.print()
    console.print("[bold]Health Dashboard[/bold]")
    console.print()

    status_char = {"healthy": "■", "degraded": "■", "broken": "■", "error": "■"}
    status_color = {"healthy": "green", "degraded": "yellow", "broken": "red", "error": "red"}

    # Find the longest probe name for alignment
    max_name = max(len(name) for name in probes_history)

    for probe_name, history in sorted(probes_history.items()):
        # Current status
        current = history[-1].get("status", "?") if history else "?"
        current_color = status_color.get(current, "dim")

        # Build trail
        trail = Text()
        entries = history[-trail_length:]
        for entry in entries:
            s = entry.get("status", "?")
            ch = status_char.get(s, "·")
            c = status_color.get(s, "dim")
            trail.append(ch, style=c)

        # Pad if fewer than trail_length entries
        pad = trail_length - len(entries)
        if pad > 0:
            trail = Text("·" * pad, style="dim") + trail

        # Status summary
        if current == "healthy":
            since = _healthy_streak(history)
            summary = Text(f"healthy {since}", style="green")
        elif current == "broken":
            ago = _time_since_last_healthy(history)
            summary = Text(f"broken {ago}", style="red bold")
        elif current == "degraded":
            ago = _time_since_status_change(history, "degraded")
            summary = Text(f"degraded {ago}", style="yellow")
        else:
            summary = Text(current, style="red")

        line = Text()
        line.append(f"  {probe_name:<{max_name}s}  ", style="bold")
        line.append_text(trail)
        line.append("  ")
        line.append_text(summary)
        console.print(line)

    console.print()

    # Legend
    legend = Text("  ")
    legend.append("■", style="green")
    legend.append(" healthy  ")
    legend.append("■", style="yellow")
    legend.append(" degraded  ")
    legend.append("■", style="red")
    legend.append(" broken  ")
    legend.append("·", style="dim")
    legend.append(" no data")
    console.print(legend)
    console.print()


def _healthy_streak(history: list[dict[str, Any]]) -> str:
    """Count consecutive healthy runs from the end."""
    count = 0
    for entry in reversed(history):
        if entry.get("status") == "healthy":
            count += 1
        else:
            break
    if count >= 30:
        return f"({count} runs)"
    return f"({count} run{'s' if count != 1 else ''})"


def _time_since_last_healthy(history: list[dict[str, Any]]) -> str:
    """How many runs ago was the last healthy status."""
    for i, entry in enumerate(reversed(history)):
        if entry.get("status") == "healthy":
            if i == 0:
                return "(just now)"
            return f"({i} run{'s' if i != 1 else ''} ago)"
    return "(never healthy)"


def _time_since_status_change(history: list[dict[str, Any]], status: str) -> str:
    """How many consecutive runs have been in this status."""
    count = 0
    for entry in reversed(history):
        if entry.get("status") == status:
            count += 1
        else:
            break
    return f"({count} run{'s' if count != 1 else ''})"


# ─────────────────────────────────────────────────────────────────────
# 4. Repair suggestion visual diff
# ─────────────────────────────────────────────────────────────────────

def render_repair_diff(
    broken_selector: str,
    broken_count: int,
    suggestions: list[dict[str, Any]],
    console: Console | None = None,
) -> None:
    """Render a side-by-side diff of broken selector vs suggested repairs."""
    if console is None:
        console = Console()

    if not suggestions:
        console.print("[dim]No repair suggestions available.[/dim]")
        return

    # Left panel: broken selector
    left_lines: list[str] = []
    left_lines.append(f"[red bold]{broken_selector}[/red bold]")
    left_lines.append("")
    left_lines.append(f"[red]{broken_count} matches[/red]")
    left_lines.append("")
    left_lines.append("[dim](no content extracted)[/dim]")

    left_panel = Panel(
        "\n".join(left_lines),
        title="[red]BROKEN[/red]",
        border_style="red",
        width=38,
    )

    # Right panel: best suggestion
    best = suggestions[0]
    right_lines: list[str] = []
    right_lines.append(f"[green bold]{best['selector']}[/green bold]")
    right_lines.append("")
    conf = best.get("confidence", 0)
    right_lines.append(f"[green]{best['match_count']} matches[/green]  conf={conf:.0%}")
    right_lines.append("")
    for sample in best.get("sample_texts", [])[:3]:
        right_lines.append(f"[green]✓[/green] {sample[:34]}")
    if not best.get("sample_texts"):
        right_lines.append("[dim](run check to see content)[/dim]")

    right_panel = Panel(
        "\n".join(right_lines),
        title="[green]SUGGESTED[/green]",
        border_style="green",
        width=38,
    )

    console.print()
    console.print(Columns([left_panel, right_panel], padding=(0, 2)))

    # Additional suggestions
    if len(suggestions) > 1:
        console.print()
        console.print("  [bold]Other candidates:[/bold]")
        for i, s in enumerate(suggestions[1:5], 2):
            conf = s.get("confidence", 0)
            console.print(
                f"    {i}. [cyan]{s['selector']}[/cyan]  "
                f"({s['match_count']} matches, conf={conf:.0%})  "
                f"[dim]{s.get('reason', '')}[/dim]"
            )
    console.print()
