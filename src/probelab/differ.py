"""DOM structural diff engine.

Captures a structural fingerprint of a page's DOM and detects changes between
runs. This turns "your selector broke" into "here's exactly what changed on
the page."

The fingerprint is a simplified tree: for each element we record the tag name,
id, classes, and child count. We then flatten the tree into a set of "paths"
(like CSS ancestor chains) and diff the sets between snapshots.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from selectolax.parser import HTMLParser, Node


@dataclass
class StructuralChange:
    """A single structural change detected between two snapshots."""

    change_type: str  # "added", "removed", "modified"
    path: str  # CSS-like path to the element
    details: str  # Human-readable description

    def to_dict(self) -> dict[str, str]:
        return {
            "type": self.change_type,
            "path": self.path,
            "details": self.details,
        }


@dataclass
class DiffResult:
    """Result of comparing two DOM snapshots."""

    changed: bool
    changes: list[StructuralChange] = field(default_factory=list)
    summary: str = ""
    old_hash: str = ""
    new_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "changed": self.changed,
            "summary": self.summary,
            "old_hash": self.old_hash,
            "new_hash": self.new_hash,
            "changes": [c.to_dict() for c in self.changes],
        }


def fingerprint_node(node: Node, max_depth: int = 6) -> dict[str, Any]:
    """Build a structural fingerprint for a DOM node.

    Captures tag name, id, classes, and child structure up to max_depth.
    Ignores text content — we care about structure, not data.
    """
    tag = node.tag
    if tag in ("script", "style", "noscript", "svg", "path"):
        return {"tag": tag, "skip": True}

    attrs: dict[str, Any] = {"tag": tag}

    node_id = node.attributes.get("id")
    if node_id:
        attrs["id"] = node_id

    classes = node.attributes.get("class", "").split()
    if classes:
        attrs["classes"] = sorted(classes)

    if max_depth > 0:
        children = []
        for child in node.iter():
            if child == node:
                continue
            # Only direct children — selectolax iter() is depth-first,
            # so we check parent
            if child.parent and child.parent == node:
                child_fp = fingerprint_node(child, max_depth - 1)
                if not child_fp.get("skip"):
                    children.append(child_fp)
        if children:
            attrs["children_count"] = len(children)
            # Keep first few children for structural comparison
            attrs["children"] = children[:20]

    return attrs


def extract_paths(fp: dict[str, Any], prefix: str = "", max_depth: int = 4) -> set[str]:
    """Flatten a fingerprint tree into a set of CSS-like paths.

    Example paths:
        "html > body > div#content"
        "html > body > div#content > ul.items"
        "html > body > div#content > ul.items > li.item"
    """
    tag = fp.get("tag", "?")
    node_id = fp.get("id")
    classes = fp.get("classes", [])

    # Build this node's selector
    selector = tag
    if node_id:
        selector += f"#{node_id}"
    if classes:
        selector += "." + ".".join(classes[:3])  # Limit class count

    current_path = f"{prefix} > {selector}" if prefix else selector
    paths = {current_path}

    if max_depth > 0:
        for child in fp.get("children", []):
            paths.update(extract_paths(child, current_path, max_depth - 1))

    return paths


def snapshot_page(html: str) -> dict[str, Any]:
    """Create a structural snapshot of an HTML page.

    Returns a dict with the fingerprint tree and a content hash.
    """
    tree = HTMLParser(html)
    body = tree.body
    if body is None:
        return {"hash": _hash(""), "fingerprint": {}, "paths": []}

    fp = fingerprint_node(body)
    paths = sorted(extract_paths(fp))
    content_hash = _hash(json.dumps(paths, sort_keys=True))

    return {
        "hash": content_hash,
        "fingerprint": fp,
        "paths": paths,
    }


def diff_snapshots(old: dict[str, Any], new: dict[str, Any]) -> DiffResult:
    """Compare two structural snapshots and report changes."""
    old_hash = old.get("hash", "")
    new_hash = new.get("hash", "")

    if old_hash == new_hash:
        return DiffResult(
            changed=False,
            summary="No structural changes detected.",
            old_hash=old_hash,
            new_hash=new_hash,
        )

    old_paths = set(old.get("paths", []))
    new_paths = set(new.get("paths", []))

    added = new_paths - old_paths
    removed = old_paths - new_paths

    changes: list[StructuralChange] = []

    for path in sorted(removed):
        changes.append(StructuralChange(
            change_type="removed",
            path=path,
            details=f"Element no longer present: {path.split(' > ')[-1]}",
        ))

    for path in sorted(added):
        changes.append(StructuralChange(
            change_type="added",
            path=path,
            details=f"New element appeared: {path.split(' > ')[-1]}",
        ))

    # Detect renames: an element removed at one path and added at a similar path
    # with different class/id but same parent structure
    rename_pairs = _detect_renames(removed, added)
    for old_path, new_path in rename_pairs:
        old_elem = old_path.split(" > ")[-1]
        new_elem = new_path.split(" > ")[-1]
        changes.append(StructuralChange(
            change_type="modified",
            path=old_path,
            details=f"Possible rename: {old_elem} -> {new_elem}",
        ))

    # Build summary
    parts = []
    if removed:
        parts.append(f"{len(removed)} element(s) removed")
    if added:
        parts.append(f"{len(added)} element(s) added")
    if rename_pairs:
        parts.append(f"{len(rename_pairs)} possible rename(s)")
    summary = "; ".join(parts) if parts else "Structure changed."

    return DiffResult(
        changed=True,
        changes=changes,
        summary=summary,
        old_hash=old_hash,
        new_hash=new_hash,
    )


def save_snapshot(probe_name: str, snapshot: dict[str, Any], base: Path = Path(".")) -> Path:
    """Save a DOM snapshot to disk."""
    from probelab.config import SNAPSHOTS_DIR, ensure_dirs
    ensure_dirs(base)
    path = base / SNAPSHOTS_DIR / f"{probe_name}.json"
    path.write_text(json.dumps(snapshot, indent=2))
    return path


def load_snapshot(probe_name: str, base: Path = Path(".")) -> dict[str, Any] | None:
    """Load a previously saved DOM snapshot."""
    from probelab.config import SNAPSHOTS_DIR
    path = base / SNAPSHOTS_DIR / f"{probe_name}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def _detect_renames(removed: set[str], added: set[str]) -> list[tuple[str, str]]:
    """Detect elements that were likely renamed (same parent path, different leaf)."""
    pairs = []
    used_added: set[str] = set()

    for r_path in removed:
        r_parts = r_path.split(" > ")
        if len(r_parts) < 2:
            continue
        r_parent = " > ".join(r_parts[:-1])
        r_tag = r_parts[-1].split(".")[0].split("#")[0]  # Just the tag name

        for a_path in added:
            if a_path in used_added:
                continue
            a_parts = a_path.split(" > ")
            if len(a_parts) < 2:
                continue
            a_parent = " > ".join(a_parts[:-1])
            a_tag = a_parts[-1].split(".")[0].split("#")[0]

            # Same parent, same tag, different classes/id
            if r_parent == a_parent and r_tag == a_tag and r_path != a_path:
                pairs.append((r_path, a_path))
                used_added.add(a_path)
                break

    return pairs


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()[:16]
