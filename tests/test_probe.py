"""Tests for the Probe data model."""

from probelab.probe import Check, Probe, ProbeResult, Status


def test_probe_from_dict():
    data = {
        "probe": {
            "name": "test",
            "url": "https://example.com",
            "method": "GET",
            "timeout": 10,
            "browser": False,
            "checks": [
                {"selector": "h1", "expect_min": 1, "extract": "text"},
                {"selector": ".item", "expect_min": 3, "expect_max": 10},
            ],
            "schema": {"type": "object", "properties": {"text": {"type": "string"}}},
        }
    }
    probe = Probe.from_dict(data)
    assert probe.name == "test"
    assert probe.url == "https://example.com"
    assert len(probe.checks) == 2
    assert probe.checks[0].selector == "h1"
    assert probe.checks[0].expect_min == 1
    assert probe.checks[1].expect_max == 10
    assert probe.schema is not None


def test_probe_to_dict_roundtrip():
    probe = Probe(
        name="roundtrip",
        url="https://example.com",
        checks=[Check(selector="div.item", expect_min=2, expect_max=5)],
        timeout=20,
        tags=["test"],
    )
    d = probe.to_dict()
    restored = Probe.from_dict(d)
    assert restored.name == probe.name
    assert restored.url == probe.url
    assert len(restored.checks) == 1
    assert restored.checks[0].selector == "div.item"
    assert restored.checks[0].expect_min == 2
    assert restored.checks[0].expect_max == 5
    assert restored.timeout == 20


def test_probe_result_to_dict():
    result = ProbeResult(
        probe_name="test",
        url="https://example.com",
        status=Status.HEALTHY,
        response_time_ms=142,
        timestamp="2026-04-12T10:00:00+00:00",
    )
    d = result.to_dict()
    assert d["name"] == "test"
    assert d["status"] == "healthy"
    assert d["response_time_ms"] == 142


def test_probe_defaults():
    probe = Probe(name="minimal", url="https://example.com")
    assert probe.method == "GET"
    assert probe.timeout == 15
    assert probe.browser is False
    assert probe.checks == []
    assert probe.headers == {}
    assert probe.tags == []
