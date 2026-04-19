"""Load probe definitions from YAML (preferred) or TOML files."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

from probelab.models.probe import Probe

# Support TOML for backward compatibility with v0.2 probes
try:
    if sys.version_info >= (3, 11):
        import tomllib
    else:
        import tomli as tomllib
    _TOML_AVAILABLE = True
except ImportError:
    _TOML_AVAILABLE = False


def load_probe(path: Path) -> Probe:
    """Load a single probe from a YAML or TOML file."""
    suffix = path.suffix.lower()
    if suffix in (".yaml", ".yml"):
        return _load_yaml(path)
    elif suffix == ".toml" and _TOML_AVAILABLE:
        return _load_toml(path)
    elif suffix == ".toml":
        raise ImportError("TOML support requires tomli: pip install tomli")
    else:
        raise ValueError(f"Unsupported probe file format: {suffix}")


def _load_yaml(path: Path) -> Probe:
    """Load probe from YAML."""
    with open(path) as f:
        data = yaml.safe_load(f)
    return Probe.from_dict(data)


def _load_toml(path: Path) -> Probe:
    """Load probe from TOML (v0.2 backward compat).

    v0.2 TOML format uses [probe] section with checks[].
    This converts to the new step/assertion format.
    """
    with open(path, "rb") as f:
        raw = tomllib.load(f)

    probe_data = raw.get("probe", raw)

    # Convert v0.2 checks[] to v1 assertions[]
    assertions = []
    for check in probe_data.get("checks", []):
        assertions.append({
            "type": "selector_exists" if check.get("expect_min", 1) <= 1 else "selector_count",
            "selector": check["selector"],
            "min": check.get("expect_min", 1),
            "max": check.get("expect_max"),
            "extract": check.get("extract", "text"),
        })

    converted = {
        "name": probe_data["name"],
        "target": {"type": "web", "url": probe_data["url"]},
        "steps": [{"action": "goto", "url": probe_data["url"]}],
        "assertions": assertions,
        "tags": probe_data.get("tags", []),
        "timeout": probe_data.get("timeout", 30),
        "browser": probe_data.get("browser", False),
    }
    return Probe.from_dict(converted)


def load_all_probes(base: Path) -> list[Probe]:
    """Load all probe definitions from a directory.

    Supports both .yaml and .toml files.
    """
    if not base.exists():
        return []
    probes = []
    for pattern in ("*.yaml", "*.yml", "*.toml"):
        for path in sorted(base.glob(pattern)):
            try:
                probes.append(load_probe(path))
            except Exception as e:
                # Skip unparseable probes but warn
                import sys
                print(f"Warning: skipping {path.name}: {e}", file=sys.stderr)
    return probes


def save_probe_yaml(probe: Probe, path: Path) -> Path:
    """Save a probe definition as YAML."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.dump(probe.to_dict(), f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    return path
