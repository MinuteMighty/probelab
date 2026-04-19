"""OpenCLI adapter import — scan opencli repos and generate probelab probes."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from probelab.config import save_probe, PROBES_DIR
from probelab.probe import Check, Probe

# ---------------------------------------------------------------------------
# Regex patterns for adapter parsing (JS and TS)
# ---------------------------------------------------------------------------

SELECTOR_PATTERNS = [
    re.compile(r"""querySelector(?:All)?\(\s*['"](.+?)['"]\s*\)"""),
    re.compile(r"""waitForSelector\(\s*['"](.+?)['"]\s*\)"""),
    re.compile(r"""page\.\$\$?\(\s*['"](.+?)['"]\s*\)"""),
]

URL_STATIC_PATTERNS = [
    re.compile(r"""page\.goto\(\s*['"](.+?)['"]\s*\)"""),
    re.compile(r"""navigate:\s*['"](.+?)['"]"""),
    re.compile(r"""fetch\(\s*['"](.+?)['"]\s*\)"""),
]

URL_DYNAMIC_PATTERN = re.compile(r"""page\.goto\(\s*`(.+?)`\s*\)""")

META_PATTERNS = {
    "site": re.compile(r"""site:\s*['"](.+?)['"]"""),
    "name": re.compile(r"""name:\s*['"](.+?)['"]"""),
    "domain": re.compile(r"""domain:\s*['"](.+?)['"]"""),
    "browser": re.compile(r"""browser:\s*(true|false)"""),
    "strategy": re.compile(r"""strategy:\s*(?:Strategy\.)?(\w+)"""),
}


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class ParsedAdapter:
    """An opencli adapter parsed from source."""

    site: str
    command: str
    url: str | None
    domain: str | None
    selectors: list[str]
    browser: bool
    strategy: str  # "PUBLIC", "COOKIE", "INTERCEPT", etc.
    source_path: str


@dataclass
class ImportResult:
    """Summary of an import-opencli run."""

    adapters_found: int = 0
    probes_created: int = 0
    skipped: list[tuple[str, str]] = field(default_factory=list)  # (name, reason)
    created_paths: list[Path] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def slugify(name: str) -> str:
    """Convert a name to a filesystem-safe slug."""
    s = name.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-+", "-", s)
    return s.strip("-")


def parse_adapter(path: Path) -> ParsedAdapter | None:
    """Parse a JS/TS adapter file and extract selectors, URL, and metadata.

    Returns None if no CSS selectors are found.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None

    # Extract metadata
    site_m = META_PATTERNS["site"].search(text)
    name_m = META_PATTERNS["name"].search(text)
    domain_m = META_PATTERNS["domain"].search(text)
    browser_m = META_PATTERNS["browser"].search(text)
    strategy_m = META_PATTERNS["strategy"].search(text)

    site = site_m.group(1) if site_m else path.parent.name
    command = name_m.group(1) if name_m else path.stem
    domain = domain_m.group(1) if domain_m else None
    browser = browser_m.group(1) == "true" if browser_m else False
    strategy = strategy_m.group(1).upper() if strategy_m else "PUBLIC"

    # Extract CSS selectors (deduplicated, order-preserving)
    selectors: list[str] = []
    seen: set[str] = set()
    for pattern in SELECTOR_PATTERNS:
        for m in pattern.finditer(text):
            # Clean up JS escape sequences from extracted selectors
            sel = m.group(1).replace('\\"', '"').replace("\\'", "'")
            # Skip selectors that contain JS string concatenation fragments
            if "' +" in sel or "+ '" in sel:
                continue
            if sel not in seen:
                selectors.append(sel)
                seen.add(sel)

    if not selectors:
        return None

    # Extract URL: prefer static page.goto(), then fetch(), then dynamic, then domain
    url: str | None = None
    for pattern in URL_STATIC_PATTERNS:
        m = pattern.search(text)
        if m:
            url = m.group(1)
            break

    if url is None:
        m = URL_DYNAMIC_PATTERN.search(text)
        if m:
            # Dynamic URL with template interpolation — fall back to domain
            url = f"https://{domain}" if domain else None
        elif domain:
            url = f"https://{domain}"

    # Discard URLs that are just template variables (not real URLs)
    if url and not url.startswith(("http://", "https://")):
        url = f"https://{domain}" if domain else None

    return ParsedAdapter(
        site=site,
        command=command,
        url=url,
        domain=domain,
        selectors=selectors,
        browser=browser,
        strategy=strategy,
        source_path=str(path),
    )


def scan_opencli_dir(path: Path) -> list[ParsedAdapter]:
    """Scan an opencli repository for adapter files.

    Looks for JS/TS files in ``clis/<site>/<command>.js`` (the real opencli
    layout) or ``src/clis/``.  Falls back to scanning the entire directory
    if neither exists.
    """
    # Try the directories opencli actually uses, in priority order
    for subdir in ["clis", "src/clis"]:
        candidate = path / subdir
        if candidate.is_dir():
            clis_dir = candidate
            break
    else:
        clis_dir = path

    adapters: list[ParsedAdapter] = []
    for adapter_file in sorted(clis_dir.rglob("*.[jt]s")):
        # Skip test files, type definitions, index files, and shared utils
        if adapter_file.name.startswith("_") or adapter_file.name in ("index.ts", "index.js"):
            continue
        if ".test." in adapter_file.name or ".spec." in adapter_file.name:
            continue
        if adapter_file.name.endswith(".d.ts"):
            continue
        if adapter_file.name == "shared.js":
            continue
        # Skip _shared directory
        if "_shared" in adapter_file.parts:
            continue

        parsed = parse_adapter(adapter_file)
        if parsed is not None:
            adapters.append(parsed)

    return adapters


# ---------------------------------------------------------------------------
# Conversion
# ---------------------------------------------------------------------------


def adapters_to_probes(adapters: list[ParsedAdapter]) -> tuple[list[Probe], list[tuple[str, str]]]:
    """Convert parsed adapters to Probe objects.

    Returns (probes, skipped) where skipped is a list of (name, reason).
    """
    probes: list[Probe] = []
    skipped: list[tuple[str, str]] = []
    seen_names: set[str] = set()

    for adapter in adapters:
        name = slugify(f"{adapter.site}-{adapter.command}")

        if not adapter.url:
            skipped.append((name, "no URL or domain found"))
            continue

        if name in seen_names:
            skipped.append((name, "duplicate name"))
            continue
        seen_names.add(name)

        checks = [
            Check(selector=sel, expect_min=1, extract="text")
            for sel in adapter.selectors
        ]

        # Mark as browser=True if adapter needs JS rendering, auth cookies,
        # or store interception — probelab can't test these with plain HTTP
        needs_browser = adapter.browser or adapter.strategy != "PUBLIC"

        probe = Probe(
            name=name,
            url=adapter.url,
            checks=checks,
            browser=needs_browser,
            tags=["opencli", adapter.site],
        )
        probes.append(probe)

    return probes, skipped


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def import_opencli(
    path: Path,
    base: Path = Path("."),
    force: bool = False,
    extra_tags: list[str] | None = None,
) -> ImportResult:
    """Scan an opencli repo and generate probelab probes.

    Args:
        path: Path to the opencli repository root.
        base: Base directory for probelab config (where .probelab/ lives).
        force: Overwrite existing probes with the same name.
        extra_tags: Additional tags to apply to all imported probes.
    """
    adapters = scan_opencli_dir(path)
    probes, conversion_skipped = adapters_to_probes(adapters)

    result = ImportResult(adapters_found=len(adapters))
    result.skipped.extend(conversion_skipped)

    if extra_tags:
        for probe in probes:
            probe.tags.extend(extra_tags)

    for probe in probes:
        existing = base / PROBES_DIR / f"{probe.name}.toml"
        if existing.exists() and not force:
            result.skipped.append((probe.name, "probe already exists (use --force)"))
            continue

        saved_path = save_probe(probe, base=base)
        result.probes_created += 1
        result.created_paths.append(saved_path)

    return result
