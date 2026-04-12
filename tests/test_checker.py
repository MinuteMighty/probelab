"""Tests for the checker module — selector validation and schema checking."""

from selectolax.parser import HTMLParser

from probelab.checker import validate_checks, validate_schema
from probelab.probe import Check
from tests.conftest import SAMPLE_HTML, EMPTY_HTML, MALFORMED_HTML


def test_validate_checks_passing():
    tree = HTMLParser(SAMPLE_HTML)
    checks = [Check(selector="li.item", expect_min=3)]
    results = validate_checks(tree, checks)
    assert len(results) == 1
    assert results[0].passed is True
    assert results[0].match_count == 5


def test_validate_checks_exact_bounds():
    tree = HTMLParser(SAMPLE_HTML)
    checks = [Check(selector="li.item", expect_min=5, expect_max=5)]
    results = validate_checks(tree, checks)
    assert results[0].passed is True


def test_validate_checks_failing_min():
    tree = HTMLParser(SAMPLE_HTML)
    checks = [Check(selector="li.item", expect_min=10)]
    results = validate_checks(tree, checks)
    assert results[0].passed is False
    assert results[0].match_count == 5


def test_validate_checks_failing_max():
    tree = HTMLParser(SAMPLE_HTML)
    checks = [Check(selector="li.item", expect_min=1, expect_max=3)]
    results = validate_checks(tree, checks)
    assert results[0].passed is False


def test_validate_checks_no_matches():
    tree = HTMLParser(SAMPLE_HTML)
    checks = [Check(selector="div.nonexistent", expect_min=1)]
    results = validate_checks(tree, checks)
    assert results[0].passed is False
    assert results[0].match_count == 0


def test_validate_checks_empty_page():
    tree = HTMLParser(EMPTY_HTML)
    checks = [Check(selector="li.item", expect_min=1)]
    results = validate_checks(tree, checks)
    assert results[0].passed is False
    assert results[0].match_count == 0


def test_validate_checks_malformed_html():
    tree = HTMLParser(MALFORMED_HTML)
    checks = [Check(selector="div.item", expect_min=1)]
    results = validate_checks(tree, checks)
    assert results[0].passed is True
    assert results[0].match_count == 2


def test_validate_checks_extracts_text():
    tree = HTMLParser(SAMPLE_HTML)
    checks = [Check(selector="li.item a", expect_min=1, extract="text")]
    results = validate_checks(tree, checks)
    assert "Item One" in results[0].extracted
    assert "Item Two" in results[0].extracted


def test_validate_checks_extracts_attr():
    tree = HTMLParser(SAMPLE_HTML)
    checks = [Check(selector="li.item a", expect_min=1, extract="attr:href")]
    results = validate_checks(tree, checks)
    assert "/item/1" in results[0].extracted


def test_validate_checks_multiple():
    tree = HTMLParser(SAMPLE_HTML)
    checks = [
        Check(selector="h1", expect_min=1),
        Check(selector="li.item", expect_min=5),
        Check(selector="footer", expect_min=1),
    ]
    results = validate_checks(tree, checks)
    assert all(r.passed for r in results)


def test_validate_schema_passing():
    data = [
        {"text": "Item One", "href": "/item/1"},
        {"text": "Item Two", "href": "/item/2"},
    ]
    schema = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "minLength": 1},
            "href": {"type": "string"},
        },
        "required": ["text"],
    }
    errors = validate_schema(data, schema)
    assert errors == []


def test_validate_schema_failing():
    data = [
        {"text": "OK"},
        {"value": 42},  # missing "text"
    ]
    schema = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    }
    errors = validate_schema(data, schema)
    assert len(errors) > 0
    assert "text" in errors[0].lower() or "required" in errors[0].lower()


def test_validate_schema_array_mode():
    data = [{"a": 1}, {"a": 2}]
    schema = {
        "type": "array",
        "items": {"type": "object", "properties": {"a": {"type": "integer"}}},
    }
    errors = validate_schema(data, schema)
    assert errors == []
