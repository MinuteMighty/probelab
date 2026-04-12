"""Configuration and probe file management."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

import tomli_w

from probelab.probe import Probe

DEFAULT_DIR = Path(".probelab")
PROBES_DIR = DEFAULT_DIR / "probes"
SNAPSHOTS_DIR = DEFAULT_DIR / "snapshots"
HISTORY_DIR = DEFAULT_DIR / "history"


def ensure_dirs(base: Path = Path(".")) -> None:
    """Create .probelab directory structure if it doesn't exist."""
    for d in [PROBES_DIR, SNAPSHOTS_DIR, HISTORY_DIR]:
        (base / d).mkdir(parents=True, exist_ok=True)


def load_probe(path: Path) -> Probe:
    """Load a single probe from a TOML file."""
    with open(path, "rb") as f:
        data = tomllib.load(f)
    return Probe.from_dict(data)


def save_probe(probe: Probe, base: Path = Path(".")) -> Path:
    """Save a probe definition to a TOML file."""
    ensure_dirs(base)
    path = base / PROBES_DIR / f"{probe.name}.toml"
    with open(path, "wb") as f:
        tomli_w.dump(probe.to_dict(), f)
    return path


def load_all_probes(base: Path = Path(".")) -> list[Probe]:
    """Load all probe definitions from .probelab/probes/."""
    probes_dir = base / PROBES_DIR
    if not probes_dir.exists():
        return []
    probes = []
    for path in sorted(probes_dir.glob("*.toml")):
        probes.append(load_probe(path))
    return probes


def remove_probe(name: str, base: Path = Path(".")) -> bool:
    """Remove a probe definition file. Returns True if removed."""
    path = base / PROBES_DIR / f"{name}.toml"
    if path.exists():
        path.unlink()
        return True
    return False


def save_history(probe_name: str, result_dict: dict[str, Any], base: Path = Path(".")) -> None:
    """Append a probe result to the history file (JSON lines)."""
    import json

    ensure_dirs(base)
    history_file = base / HISTORY_DIR / f"{probe_name}.jsonl"
    with open(history_file, "a") as f:
        f.write(json.dumps(result_dict) + "\n")


def load_history(probe_name: str, base: Path = Path("."), limit: int = 20) -> list[dict[str, Any]]:
    """Load recent probe results from history."""
    import json

    history_file = base / HISTORY_DIR / f"{probe_name}.jsonl"
    if not history_file.exists():
        return []
    lines = history_file.read_text().strip().split("\n")
    results = [json.loads(line) for line in lines if line.strip()]
    return results[-limit:]
