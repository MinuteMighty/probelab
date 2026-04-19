"""Result storage — save runs, load history, manage baselines."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Default probelab home directory
DEFAULT_HOME = Path.home() / ".probelab"


def ensure_dirs(home: Path = DEFAULT_HOME) -> None:
    """Create probelab directory structure."""
    for d in ["probes", "runs", "baselines", "snapshots", "history"]:
        (home / d).mkdir(parents=True, exist_ok=True)


def save_run(result_dict: dict[str, Any], home: Path = DEFAULT_HOME) -> Path:
    """Save a run result as JSON.

    Saves to: ~/.probelab/runs/YYYY-MM-DD/probe-name/result.json
    """
    from datetime import datetime

    probe_name = result_dict.get("probe_name", "unknown")
    date_str = datetime.now().strftime("%Y-%m-%d")
    run_dir = home / "runs" / date_str / probe_name
    run_dir.mkdir(parents=True, exist_ok=True)

    result_path = run_dir / "result.json"
    with open(result_path, "w") as f:
        json.dump(result_dict, f, indent=2, ensure_ascii=False)

    return result_path


def save_artifact(probe_name: str, artifact_type: str, data: bytes | str,
                  home: Path = DEFAULT_HOME) -> Path:
    """Save an artifact (screenshot, HTML snapshot).

    Saves to: ~/.probelab/runs/YYYY-MM-DD/probe-name/artifact.ext
    """
    from datetime import datetime

    date_str = datetime.now().strftime("%Y-%m-%d")
    run_dir = home / "runs" / date_str / probe_name
    run_dir.mkdir(parents=True, exist_ok=True)

    ext = {"screenshot": "png", "html": "html"}.get(artifact_type, "dat")
    artifact_path = run_dir / f"{artifact_type}.{ext}"

    if isinstance(data, bytes):
        with open(artifact_path, "wb") as f:
            f.write(data)
    else:
        with open(artifact_path, "w", encoding="utf-8") as f:
            f.write(data)

    return artifact_path


def append_history(probe_name: str, result_dict: dict[str, Any],
                   home: Path = DEFAULT_HOME) -> None:
    """Append a result to the probe's history file (JSONL)."""
    history_dir = home / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    history_file = history_dir / f"{probe_name}.jsonl"
    with open(history_file, "a") as f:
        f.write(json.dumps(result_dict, ensure_ascii=False) + "\n")


def load_history(probe_name: str, home: Path = DEFAULT_HOME,
                 limit: int = 20) -> list[dict[str, Any]]:
    """Load recent run results from history."""
    history_file = home / "history" / f"{probe_name}.jsonl"
    if not history_file.exists():
        return []
    lines = history_file.read_text().strip().split("\n")
    results = [json.loads(line) for line in lines if line.strip()]
    return results[-limit:]


def load_last_run(probe_name: str, home: Path = DEFAULT_HOME) -> dict[str, Any] | None:
    """Load the most recent run result for a probe."""
    history = load_history(probe_name, home, limit=1)
    return history[-1] if history else None


def save_baseline(probe_name: str, result_dict: dict[str, Any],
                  home: Path = DEFAULT_HOME) -> Path:
    """Save a successful result as the baseline for future comparison."""
    baseline_dir = home / "baselines"
    baseline_dir.mkdir(parents=True, exist_ok=True)
    path = baseline_dir / f"{probe_name}.json"
    with open(path, "w") as f:
        json.dump(result_dict, f, indent=2, ensure_ascii=False)
    return path


def load_baseline(probe_name: str, home: Path = DEFAULT_HOME) -> dict[str, Any] | None:
    """Load the baseline for a probe."""
    path = home / "baselines" / f"{probe_name}.json"
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)
