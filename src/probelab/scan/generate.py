"""Probe generator — converts discovered dependencies into probe YAML files.

Takes the output of scanner.scan_directory() and produces ready-to-use
probe definitions, choosing appropriate assertions based on the
dependency type and context.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from probelab.scan.patterns import Dependency, get_provider


def dependencies_to_probes(deps: list[Dependency]) -> list[dict[str, Any]]:
    """Convert dependencies to probe YAML dicts.

    Returns a list of dicts, each suitable for writing as a YAML probe file.
    """
    probes: list[dict[str, Any]] = []

    for dep in deps:
        if dep.kind == "api":
            probe = _make_api_probe(dep)
        else:
            probe = _make_web_probe(dep)

        if probe:
            probes.append(probe)

    return probes


def write_probes(
    probes: list[dict[str, Any]],
    output_dir: Path,
    overwrite: bool = False,
) -> list[Path]:
    """Write probe dicts as YAML files to output_dir.

    Returns list of paths written.
    """
    import yaml

    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for probe in probes:
        name = probe["name"]
        path = output_dir / f"{name}.yaml"

        if path.exists() and not overwrite:
            continue

        with open(path, "w") as f:
            yaml.dump(probe, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

        written.append(path)

    return written


# ─────────────────────────────────────────────────────────────────────
# Web probe generation
# ─────────────────────────────────────────────────────────────────────

def _make_web_probe(dep: Dependency) -> dict[str, Any] | None:
    """Generate a web probe from a dependency."""
    if not dep.url:
        return None

    parsed = urlparse(dep.url)
    slug = _slugify(parsed.netloc + parsed.path)
    name = slug[:50]

    probe: dict[str, Any] = {
        "name": name,
        "description": dep.description,
    }

    # Add source reference as a comment-friendly field
    probe["_discovered"] = {
        "file": dep.source_file,
        "line": dep.source_line,
        "confidence": round(dep.confidence, 2),
    }

    probe["target"] = {"type": "web", "url": dep.url}

    probe["steps"] = [{"action": "goto", "url": dep.url}]

    # Build assertions based on what we know
    assertions: list[dict[str, Any]] = []

    # If we found selectors, assert they exist
    for selector in dep.selectors[:5]:
        assertions.append({
            "type": "selector_exists",
            "selector": selector,
        })

    # If no selectors, at least check the page loads with expected content
    if not assertions:
        # Use the domain name as a text check (most sites show their name)
        domain_name = parsed.netloc.replace("www.", "").split(".")[0]
        if len(domain_name) >= 3:
            assertions.append({
                "type": "text_exists",
                "text": domain_name,
            })

    probe["assertions"] = assertions
    probe["outputs"] = [{"type": "html"}]

    return probe


# ─────────────────────────────────────────────────────────────────────
# API probe generation
# ─────────────────────────────────────────────────────────────────────

def _make_api_probe(dep: Dependency) -> dict[str, Any] | None:
    """Generate an API probe from a dependency."""
    provider = get_provider(dep.provider)
    if not provider:
        return None

    name = f"api-{dep.provider}"

    probe: dict[str, Any] = {
        "name": name,
        "description": dep.description,
    }

    probe["_discovered"] = {
        "file": dep.source_file,
        "line": dep.source_line,
        "confidence": round(dep.confidence, 2),
    }

    if provider.health_url:
        probe["target"] = {"type": "api", "url": provider.health_url}
    else:
        probe["target"] = {"type": "api", "url": ""}
        probe["_note"] = f"URL is project-specific. Set the {dep.provider} endpoint URL."

    # API assertions
    assertions: list[dict[str, Any]] = [
        {"type": "reachable", "description": f"{provider.name} API endpoint responds"},
    ]

    # If we know the env key, add an auth check
    env_key = dep.env_key
    if not env_key and provider.env_keys:
        env_key = provider.env_keys[0]

    if env_key:
        assertions.append({
            "type": "auth_valid",
            "env_key": env_key,
            "description": f"API key in ${env_key} is accepted",
        })

    probe["assertions"] = assertions

    return probe


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────

def _slugify(text: str) -> str:
    """Convert text to a URL-safe slug."""
    import re
    text = text.lower().strip("/")
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")
