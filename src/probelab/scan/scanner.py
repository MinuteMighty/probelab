"""Codebase scanner — discovers external web and API dependencies.

Walks a project directory, reads source files, and finds:
1. URLs being fetched (requests, httpx, fetch, curl, etc.)
2. CSS selectors being used (BeautifulSoup, querySelector, etc.)
3. API SDK imports (openai, anthropic, stripe, etc.)
4. Environment variables that look like API keys
5. External links in docs and config files

Returns a list of Dependency objects that can be converted to probe YAML.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from probelab.scan.patterns import (
    KNOWN_PROVIDERS,
    MARKDOWN_LINK,
    PY_SELECTOR_PATTERNS,
    JS_SELECTOR_PATTERNS,
    SCAN_EXTENSIONS,
    SKIP_DIRS,
    SKIP_FILES,
    SKIP_URL_PATTERNS,
    URL_PATTERN,
    ENV_KEY_PATTERN,
    Dependency,
    get_provider,
)


def scan_directory(path: Path, max_files: int = 5000) -> list[Dependency]:
    """Scan a project directory for external dependencies.

    Args:
        path: Root directory to scan.
        max_files: Stop after this many files to avoid scanning huge repos.

    Returns:
        Deduplicated list of Dependency objects.
    """
    deps: list[Dependency] = []
    files_scanned = 0

    for root, dirs, files in os.walk(path):
        # Skip ignored directories
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.endswith(".egg-info")]

        for filename in files:
            if files_scanned >= max_files:
                break

            # Skip lock files and generated files
            if filename in SKIP_FILES:
                continue

            filepath = Path(root) / filename
            ext = filepath.suffix.lower()

            # .env files have no extension but match by name
            if filepath.name.startswith(".env"):
                ext = ".env"

            if ext not in SCAN_EXTENSIONS:
                continue

            files_scanned += 1

            try:
                content = filepath.read_text(encoding="utf-8", errors="ignore")
            except (OSError, UnicodeDecodeError):
                continue

            rel_path = str(filepath.relative_to(path))

            if ext in (".py",):
                deps.extend(_scan_python(content, rel_path))
            elif ext in (".js", ".ts", ".jsx", ".tsx"):
                deps.extend(_scan_javascript(content, rel_path))
            elif ext in (".sh", ".bash", ".zsh"):
                deps.extend(_scan_shell(content, rel_path))
            elif ext in (".yaml", ".yml"):
                deps.extend(_scan_yaml(content, rel_path))
            elif ext in (".json",):
                deps.extend(_scan_json(content, rel_path))
            elif ext in (".env",):
                deps.extend(_scan_env(content, rel_path))
            elif ext in (".md", ".mdx", ".rst"):
                deps.extend(_scan_markdown(content, rel_path))
            elif ext in (".toml",):
                deps.extend(_scan_config(content, rel_path))

    return _deduplicate(deps)


# ─────────────────────────────────────────────────────────────────────
# Per-language scanners
# ─────────────────────────────────────────────────────────────────────

def _scan_python(content: str, rel_path: str) -> list[Dependency]:
    deps: list[Dependency] = []

    lines = content.split("\n")
    for lineno, line in enumerate(lines, 1):
        # API SDK imports
        for provider in KNOWN_PROVIDERS:
            for pattern in provider.import_patterns:
                if pattern in line:
                    deps.append(Dependency(
                        kind="api",
                        url=provider.health_url or None,
                        source_file=rel_path,
                        source_line=lineno,
                        provider=provider.name,
                        description=f"Uses {provider.description}",
                        confidence=0.95,
                    ))

        # URLs in code
        for m in URL_PATTERN.finditer(line):
            url = _clean_url(m.group(1))
            if url and not _should_skip_url(url):
                selectors = _extract_nearby_selectors(lines, lineno - 1, PY_SELECTOR_PATTERNS)
                deps.append(Dependency(
                    kind="web",
                    url=url,
                    source_file=rel_path,
                    source_line=lineno,
                    selectors=selectors,
                    description=f"HTTP request to {urlparse(url).netloc}",
                    confidence=0.8,
                ))

    return deps


def _scan_javascript(content: str, rel_path: str) -> list[Dependency]:
    deps: list[Dependency] = []

    lines = content.split("\n")
    for lineno, line in enumerate(lines, 1):
        # API SDK imports
        for provider in KNOWN_PROVIDERS:
            for pattern in provider.js_import_patterns:
                if pattern in line:
                    deps.append(Dependency(
                        kind="api",
                        url=provider.health_url or None,
                        source_file=rel_path,
                        source_line=lineno,
                        provider=provider.name,
                        description=f"Uses {provider.description}",
                        confidence=0.95,
                    ))

        # URLs
        for m in URL_PATTERN.finditer(line):
            url = _clean_url(m.group(1))
            if url and not _should_skip_url(url):
                selectors = _extract_nearby_selectors(lines, lineno - 1, JS_SELECTOR_PATTERNS)
                deps.append(Dependency(
                    kind="web",
                    url=url,
                    source_file=rel_path,
                    source_line=lineno,
                    selectors=selectors,
                    description=f"Fetches {urlparse(url).netloc}",
                    confidence=0.8,
                ))

    return deps


def _scan_shell(content: str, rel_path: str) -> list[Dependency]:
    deps: list[Dependency] = []

    for lineno, line in enumerate(content.split("\n"), 1):
        # curl/wget commands
        if re.search(r"\b(curl|wget)\b", line):
            for m in URL_PATTERN.finditer(line):
                url = _clean_url(m.group(1))
                if url and not _should_skip_url(url):
                    deps.append(Dependency(
                        kind="web",
                        url=url,
                        source_file=rel_path,
                        source_line=lineno,
                        description=f"Shell request to {urlparse(url).netloc}",
                        confidence=0.9,
                    ))

    return deps


def _scan_yaml(content: str, rel_path: str) -> list[Dependency]:
    deps: list[Dependency] = []

    for lineno, line in enumerate(content.split("\n"), 1):
        for m in URL_PATTERN.finditer(line):
            url = _clean_url(m.group(1))
            if url and not _should_skip_url(url):
                # CI health checks get higher confidence
                is_ci = "workflows" in rel_path or "ci" in rel_path.lower()
                deps.append(Dependency(
                    kind="web",
                    url=url,
                    source_file=rel_path,
                    source_line=lineno,
                    description=f"{'CI dependency' if is_ci else 'Config URL'}: {urlparse(url).netloc}",
                    confidence=0.85 if is_ci else 0.6,
                ))

    return deps


def _scan_json(content: str, rel_path: str) -> list[Dependency]:
    deps: list[Dependency] = []

    for lineno, line in enumerate(content.split("\n"), 1):
        for m in URL_PATTERN.finditer(line):
            url = _clean_url(m.group(1))
            if url and not _should_skip_url(url):
                deps.append(Dependency(
                    kind="web",
                    url=url,
                    source_file=rel_path,
                    source_line=lineno,
                    description=f"Config URL: {urlparse(url).netloc}",
                    confidence=0.5,
                ))

    return deps


def _scan_env(content: str, rel_path: str) -> list[Dependency]:
    deps: list[Dependency] = []

    for lineno, line in enumerate(content.split("\n"), 1):
        # Find API key env vars
        for m in ENV_KEY_PATTERN.finditer(line):
            key = m.group(1)
            # Match to known provider
            for provider in KNOWN_PROVIDERS:
                if key in provider.env_keys:
                    deps.append(Dependency(
                        kind="api",
                        url=provider.health_url or None,
                        source_file=rel_path,
                        source_line=lineno,
                        provider=provider.name,
                        env_key=key,
                        description=f"API key for {provider.description}",
                        confidence=0.9,
                    ))
                    break

        # Also check for URLs in env files
        for m in URL_PATTERN.finditer(line):
            url = _clean_url(m.group(1))
            if url and not _should_skip_url(url):
                deps.append(Dependency(
                    kind="web",
                    url=url,
                    source_file=rel_path,
                    source_line=lineno,
                    description=f"Environment URL: {urlparse(url).netloc}",
                    confidence=0.7,
                ))

    return deps


def _scan_markdown(content: str, rel_path: str) -> list[Dependency]:
    deps: list[Dependency] = []

    for lineno, line in enumerate(content.split("\n"), 1):
        for m in MARKDOWN_LINK.finditer(line):
            url = _clean_url(m.group(2))
            if url and not _should_skip_url(url):
                link_text = m.group(1)
                deps.append(Dependency(
                    kind="web",
                    url=url,
                    source_file=rel_path,
                    source_line=lineno,
                    description=f"Doc link: {link_text or urlparse(url).netloc}",
                    confidence=0.4,
                ))

    return deps


def _scan_config(content: str, rel_path: str) -> list[Dependency]:
    """Scan TOML and other config files for URLs."""
    deps: list[Dependency] = []

    for lineno, line in enumerate(content.split("\n"), 1):
        for m in URL_PATTERN.finditer(line):
            url = _clean_url(m.group(1))
            if url and not _should_skip_url(url):
                deps.append(Dependency(
                    kind="web",
                    url=url,
                    source_file=rel_path,
                    source_line=lineno,
                    description=f"Config URL: {urlparse(url).netloc}",
                    confidence=0.5,
                ))

    return deps


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────

def _clean_url(url: str) -> str | None:
    """Clean and validate a URL string."""
    # Strip trailing punctuation that got captured
    url = url.rstrip(".,;:)>]}'\"")
    # Must have a valid netloc
    parsed = urlparse(url)
    if not parsed.netloc or "." not in parsed.netloc:
        return None
    return url


def _should_skip_url(url: str) -> bool:
    """Return True if this URL should be ignored."""
    return bool(SKIP_URL_PATTERNS.match(url))


def _extract_nearby_selectors(
    lines: list[str], current_idx: int, patterns: list[re.Pattern]
) -> list[str]:
    """Look for CSS selectors within a few lines of a URL reference."""
    selectors: list[str] = []
    start = max(0, current_idx - 3)
    end = min(len(lines), current_idx + 15)

    for line in lines[start:end]:
        for pattern in patterns:
            for m in pattern.finditer(line):
                sel = m.group(1).strip()
                if sel and sel not in selectors:
                    selectors.append(sel)

    return selectors


def _deduplicate(deps: list[Dependency]) -> list[Dependency]:
    """Remove duplicate dependencies, keeping highest confidence."""
    seen: dict[str, Dependency] = {}

    for dep in deps:
        # Key: combination of kind + url/provider
        if dep.kind == "api":
            key = f"api:{dep.provider}"
        else:
            key = f"web:{dep.url}"

        existing = seen.get(key)
        if existing is None or dep.confidence > existing.confidence:
            # Merge selectors from duplicates
            if existing and dep.kind == "web":
                merged_selectors = list(existing.selectors)
                for s in dep.selectors:
                    if s not in merged_selectors:
                        merged_selectors.append(s)
                dep.selectors = merged_selectors
            seen[key] = dep

    return list(seen.values())
