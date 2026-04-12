"""Selector auto-repair suggestion engine.

When a CSS selector breaks (returns 0 or too few matches), this module
analyzes the current DOM and suggests alternative selectors that might
capture the intended content.

Strategy:
1. Parse the broken selector into components (tag, classes, id, combinators)
2. Generate candidate selectors by relaxing constraints:
   - Drop one class at a time
   - Try parent selectors
   - Try sibling selectors with same tag
   - Try selectors with partial class matches (fuzzy)
   - Try attribute selectors
3. Score candidates by:
   - Match count (should be close to original expect_min)
   - Structural similarity to the original selector
   - Specificity (more specific = better)
4. Return top N suggestions with match counts and confidence scores
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from selectolax.parser import HTMLParser, Node


@dataclass
class SelectorSuggestion:
    """A suggested replacement selector."""

    selector: str
    match_count: int
    confidence: float  # 0.0 to 1.0
    reason: str  # Why this was suggested
    sample_texts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "selector": self.selector,
            "match_count": self.match_count,
            "confidence": round(self.confidence, 2),
            "reason": self.reason,
            "sample_texts": self.sample_texts[:3],
        }


@dataclass
class SelectorParts:
    """Parsed components of a CSS selector."""

    tag: str
    id: str | None
    classes: list[str]
    attrs: list[tuple[str, str]]  # (attr_name, attr_value)
    combinator: str  # " ", ">", "+", "~"
    parent: SelectorParts | None = None


def suggest_repairs(
    html: str,
    broken_selector: str,
    target_min: int = 1,
    target_max: int | None = None,
    max_suggestions: int = 5,
) -> list[SelectorSuggestion]:
    """Suggest alternative selectors when the original one breaks.

    Args:
        html: The current page HTML.
        broken_selector: The CSS selector that's no longer matching.
        target_min: Expected minimum matches (from probe config).
        target_max: Expected maximum matches.
        max_suggestions: Maximum number of suggestions to return.

    Returns:
        List of SelectorSuggestion, sorted by confidence descending.
    """
    tree = HTMLParser(html)
    candidates: list[SelectorSuggestion] = []
    seen: set[str] = {broken_selector}

    parts = _parse_selector(broken_selector)
    target = target_min if target_max is None else (target_min + target_max) // 2

    # Strategy 1: Drop one class at a time
    candidates.extend(_try_class_relaxation(tree, parts, target, seen))

    # Strategy 2: Try just the tag name with partial class matches
    candidates.extend(_try_fuzzy_classes(tree, parts, target, seen))

    # Strategy 3: Try parent context variations
    candidates.extend(_try_parent_variations(tree, broken_selector, target, seen))

    # Strategy 4: Try data-attribute and role-based selectors
    candidates.extend(_try_attribute_selectors(tree, parts, target, seen))

    # Strategy 5: Try similar structures (same tag, similar depth)
    candidates.extend(_try_structural_similarity(tree, parts, target, seen))

    # Score and sort
    for c in candidates:
        c.confidence = _score_candidate(c, target, broken_selector)

    candidates.sort(key=lambda c: c.confidence, reverse=True)
    return candidates[:max_suggestions]


def _parse_selector(selector: str) -> SelectorParts:
    """Parse a simple CSS selector into components.

    Handles: tag, .class, #id, [attr=val], and direct child (>).
    Does NOT handle pseudo-classes, :nth-child, etc.
    """
    # Split on combinators, take the last segment
    # e.g., "div.container > ul.items > li.item" -> analyze "li.item"
    parts_list = re.split(r'\s*([>+~])\s*|\s+', selector.strip())
    parts_list = [p for p in parts_list if p]

    # Take the last meaningful segment
    segment = parts_list[-1] if parts_list else selector

    tag = ""
    sel_id = None
    classes: list[str] = []
    attrs: list[tuple[str, str]] = []

    # Extract tag
    tag_match = re.match(r'^([a-zA-Z][a-zA-Z0-9-]*)', segment)
    if tag_match:
        tag = tag_match.group(1)

    # Extract id
    id_match = re.search(r'#([a-zA-Z][a-zA-Z0-9_-]*)', segment)
    if id_match:
        sel_id = id_match.group(1)

    # Extract classes
    classes = re.findall(r'\.([a-zA-Z][a-zA-Z0-9_-]*)', segment)

    # Extract attribute selectors
    attr_matches = re.findall(r'\[([a-zA-Z-]+)(?:="([^"]*)")?\]', segment)
    attrs = [(a, v) for a, v in attr_matches]

    # Determine combinator and parent
    parent = None
    combinator = " "
    if len(parts_list) > 1:
        # Reconstruct parent selector
        parent_parts = parts_list[:-1]
        if parent_parts and parent_parts[-1] in (">", "+", "~"):
            combinator = parent_parts[-1]
            parent_parts = parent_parts[:-1]
        if parent_parts:
            parent_selector = " ".join(parent_parts)
            parent = _parse_selector(parent_selector)

    return SelectorParts(
        tag=tag,
        id=sel_id,
        classes=classes,
        attrs=attrs,
        combinator=combinator,
        parent=parent,
    )


def _try_class_relaxation(
    tree: HTMLParser,
    parts: SelectorParts,
    target: int,
    seen: set[str],
) -> list[SelectorSuggestion]:
    """Try removing one class at a time from the selector."""
    results: list[SelectorSuggestion] = []
    if len(parts.classes) < 2:
        return results

    for i, cls in enumerate(parts.classes):
        remaining = [c for j, c in enumerate(parts.classes) if j != i]
        tag = parts.tag or "*"
        new_sel = tag + "".join(f".{c}" for c in remaining)

        if new_sel in seen:
            continue
        seen.add(new_sel)

        count, samples = _test_selector(tree, new_sel)
        if count > 0:
            results.append(SelectorSuggestion(
                selector=new_sel,
                match_count=count,
                confidence=0.0,
                reason=f"Dropped class '.{cls}' from selector",
                sample_texts=samples,
            ))

    return results


def _try_fuzzy_classes(
    tree: HTMLParser,
    parts: SelectorParts,
    target: int,
    seen: set[str],
) -> list[SelectorSuggestion]:
    """Try selectors using partial class name matches.

    Sites often rename classes from 'item-title' to 'itemTitle' or
    'story-link' to 'storylink'. This finds elements whose classes
    contain substrings of the original.
    """
    results: list[SelectorSuggestion] = []
    if not parts.classes or not parts.tag:
        return results

    body = tree.body
    if body is None:
        return results

    # For each original class, find elements with similar class names
    for original_class in parts.classes:
        # Generate search fragments: split on -, _, camelCase boundaries
        fragments = _class_fragments(original_class)
        if not fragments:
            continue

        # Find all elements with matching tag that have classes containing fragments
        for node in body.css(parts.tag):
            node_classes = node.attributes.get("class", "").split()
            for nc in node_classes:
                if nc == original_class:
                    continue  # Skip exact match (that's the broken one)
                nc_lower = nc.lower()
                # Check if any fragment appears in this class name
                if any(f in nc_lower for f in fragments if len(f) >= 3):
                    new_sel = f"{parts.tag}.{nc}"
                    if new_sel in seen:
                        continue
                    seen.add(new_sel)

                    count, samples = _test_selector(tree, new_sel)
                    if count > 0:
                        results.append(SelectorSuggestion(
                            selector=new_sel,
                            match_count=count,
                            confidence=0.0,
                            reason=f"Fuzzy class match: '.{original_class}' -> '.{nc}'",
                            sample_texts=samples,
                        ))
                    break  # One suggestion per node class

    return results


def _try_parent_variations(
    tree: HTMLParser,
    original: str,
    target: int,
    seen: set[str],
) -> list[SelectorSuggestion]:
    """Try simplifying the parent context of the selector."""
    results: list[SelectorSuggestion] = []

    # Split selector on spaces and >
    parts = re.split(r'\s*>\s*|\s+', original.strip())
    if len(parts) < 2:
        return results

    leaf = parts[-1]

    # Try just the leaf selector
    if leaf not in seen:
        seen.add(leaf)
        count, samples = _test_selector(tree, leaf)
        if count > 0:
            results.append(SelectorSuggestion(
                selector=leaf,
                match_count=count,
                confidence=0.0,
                reason="Using only the leaf selector (removed parent context)",
                sample_texts=samples,
            ))

    # Try with just the immediate parent
    if len(parts) >= 2:
        short = f"{parts[-2]} {leaf}"
        if short not in seen:
            seen.add(short)
            count, samples = _test_selector(tree, short)
            if count > 0:
                results.append(SelectorSuggestion(
                    selector=short,
                    match_count=count,
                    confidence=0.0,
                    reason=f"Simplified parent context to '{parts[-2]}'",
                    sample_texts=samples,
                ))

    return results


def _try_attribute_selectors(
    tree: HTMLParser,
    parts: SelectorParts,
    target: int,
    seen: set[str],
) -> list[SelectorSuggestion]:
    """Try data-* attribute and role-based selectors."""
    results: list[SelectorSuggestion] = []
    if not parts.tag:
        return results

    body = tree.body
    if body is None:
        return results

    # Look for data-* attributes and role attributes on matching tags
    interesting_attrs = ("data-testid", "data-id", "data-type", "role", "aria-label", "data-component")
    attr_counts: dict[str, int] = {}

    for node in body.css(parts.tag):
        for attr in interesting_attrs:
            val = node.attributes.get(attr)
            if val:
                key = f"{parts.tag}[{attr}=\"{val}\"]"
                attr_counts[key] = attr_counts.get(key, 0) + 1

    for sel, count in sorted(attr_counts.items(), key=lambda x: -x[1]):
        if sel in seen:
            continue
        if count < 1:
            continue
        seen.add(sel)

        verified_count, samples = _test_selector(tree, sel)
        if verified_count > 0:
            results.append(SelectorSuggestion(
                selector=sel,
                match_count=verified_count,
                confidence=0.0,
                reason=f"Attribute-based selector (more resilient to class renames)",
                sample_texts=samples,
            ))
            if len(results) >= 3:
                break

    return results


def _try_structural_similarity(
    tree: HTMLParser,
    parts: SelectorParts,
    target: int,
    seen: set[str],
) -> list[SelectorSuggestion]:
    """Find elements with the same tag that appear in list-like structures.

    If we expected 20+ matches of 'li.item', look for any 'li' elements
    that appear 10+ times as siblings under the same parent.
    """
    results: list[SelectorSuggestion] = []
    if not parts.tag or target < 3:
        return results

    body = tree.body
    if body is None:
        return results

    # Find parents that have many children with the same tag.
    # Use a stable key (tag + id + first class) instead of id(parent)
    # because selectolax C-backed nodes can reuse Python object ids.
    parent_groups: dict[str, list[Node]] = {}
    parent_refs: dict[str, Node] = {}
    for node in body.css(parts.tag):
        parent = node.parent
        if parent is None:
            continue
        p_tag = parent.tag
        p_id = parent.attributes.get("id", "")
        p_cls = (parent.attributes.get("class", "").split() or [""])[0]
        pkey = f"{p_tag}#{p_id}.{p_cls}"
        parent_groups.setdefault(pkey, []).append(node)
        parent_refs[pkey] = parent

    for pkey, nodes in parent_groups.items():
        tag = parts.tag
        if len(nodes) < max(3, target // 2):
            continue

        # Build a selector using the parent's identity
        parent_node = parent_refs[pkey]

        parent_tag = parent_node.tag
        parent_classes = parent_node.attributes.get("class", "").split()
        parent_id = parent_node.attributes.get("id")

        if parent_id:
            sel = f"#{parent_id} > {tag}"
        elif parent_classes:
            sel = f"{parent_tag}.{parent_classes[0]} > {tag}"
        else:
            sel = f"{parent_tag} > {tag}"

        if sel in seen:
            continue
        seen.add(sel)

        count, samples = _test_selector(tree, sel)
        if count >= max(3, target // 2):
            results.append(SelectorSuggestion(
                selector=sel,
                match_count=count,
                confidence=0.0,
                reason=f"Structural match: {count} sibling '{tag}' elements under '{parent_tag}'",
                sample_texts=samples,
            ))

    return results


def _test_selector(tree: HTMLParser, selector: str) -> tuple[int, list[str]]:
    """Test a selector against the DOM. Returns (count, sample_texts)."""
    try:
        nodes = tree.css(selector)
    except Exception:
        return 0, []

    count = len(nodes)
    samples = [n.text(strip=True)[:80] for n in nodes[:3] if n.text(strip=True)]
    return count, samples


def _score_candidate(
    candidate: SelectorSuggestion,
    target: int,
    original: str,
) -> float:
    """Score a candidate selector from 0.0 to 1.0.

    Higher is better. Considers:
    - How close the match count is to the target
    - Selector specificity (more specific = more confident)
    - Textual similarity to the original
    """
    # Match count proximity (0.0 to 0.4)
    if target > 0:
        ratio = min(candidate.match_count, target) / max(candidate.match_count, target)
    else:
        ratio = 1.0 if candidate.match_count > 0 else 0.0
    count_score = ratio * 0.4

    # Specificity (0.0 to 0.3)
    sel = candidate.selector
    specificity = 0.0
    if "#" in sel:
        specificity += 0.15  # Has an ID
    specificity += min(0.1, sel.count(".") * 0.03)  # Has classes
    if "[" in sel:
        specificity += 0.05  # Has attribute selectors
    specificity_score = min(0.3, specificity)

    # Textual similarity to original (0.0 to 0.3)
    orig_parts = set(re.split(r'[.#\[\]>+~ ]+', original.lower()))
    cand_parts = set(re.split(r'[.#\[\]>+~ ]+', sel.lower()))
    orig_parts.discard("")
    cand_parts.discard("")
    if orig_parts:
        overlap = len(orig_parts & cand_parts) / len(orig_parts)
    else:
        overlap = 0.0
    similarity_score = overlap * 0.3

    return count_score + specificity_score + similarity_score


def _class_fragments(class_name: str) -> list[str]:
    """Split a class name into meaningful fragments for fuzzy matching.

    'story-link' -> ['story', 'link']
    'itemTitle' -> ['item', 'title']
    'post_content' -> ['post', 'content']
    """
    # Split on -, _, and camelCase boundaries
    parts = re.sub(r'([a-z])([A-Z])', r'\1_\2', class_name)
    fragments = re.split(r'[-_]', parts.lower())
    return [f for f in fragments if len(f) >= 2]
