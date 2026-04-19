"""Selector checking and schema validation logic."""

from __future__ import annotations

from typing import Any

import jsonschema
from selectolax.parser import HTMLParser

from probelab.probe import Check, CheckResult


def validate_checks(tree: HTMLParser, checks: list[Check]) -> list[CheckResult]:
    """Run all selector checks against a parsed HTML tree."""
    results = []
    for check in checks:
        try:
            nodes = tree.css(check.selector)
        except ValueError:
            # Invalid CSS selector — treat as zero matches
            results.append(
                CheckResult(
                    selector=check.selector,
                    match_count=0,
                    expected_min=check.expect_min,
                    expected_max=check.expect_max,
                    passed=False,
                    extracted=[],
                )
            )
            continue
        count = len(nodes)

        passed = count >= check.expect_min
        if check.expect_max is not None:
            passed = passed and count <= check.expect_max

        extracted = []
        for node in nodes[:10]:  # Limit extraction to first 10 for reporting
            if check.extract == "text":
                extracted.append(node.text(strip=True))
            elif check.extract == "html":
                extracted.append(node.html or "")
            elif check.extract.startswith("attr:"):
                attr_name = check.extract[5:]
                extracted.append(node.attributes.get(attr_name, ""))

        results.append(
            CheckResult(
                selector=check.selector,
                match_count=count,
                expected_min=check.expect_min,
                expected_max=check.expect_max,
                passed=passed,
                extracted=extracted,
            )
        )
    return results


def validate_schema(data: list[dict[str, Any]], schema: dict[str, Any]) -> list[str]:
    """Validate extracted data against a JSON Schema. Returns list of error messages."""
    errors = []

    # If schema expects an object, validate each item
    # If schema expects an array, validate the whole list
    if schema.get("type") == "array":
        try:
            jsonschema.validate(instance=data, schema=schema)
        except jsonschema.ValidationError as e:
            errors.append(f"Array validation: {e.message}")
    else:
        # Validate each extracted item against the schema
        for i, item in enumerate(data[:5]):  # Check first 5 items
            try:
                jsonschema.validate(instance=item, schema=schema)
            except jsonschema.ValidationError as e:
                errors.append(f"Item {i}: {e.message}")

    return errors
