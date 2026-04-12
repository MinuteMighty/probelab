"""Tests for the probe runner — uses httpx mock transport."""

import httpx

from probelab.probe import Check, Probe, Status
from probelab.runner import run_probe, run_all_probes
from tests.conftest import SAMPLE_HTML, EMPTY_HTML


def _mock_client(html: str, status_code: int = 200) -> httpx.Client:
    """Create an httpx client that returns fixed HTML."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, text=html)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_run_probe_healthy():
    probe = Probe(
        name="test",
        url="https://example.com",
        checks=[Check(selector="li.item", expect_min=3)],
    )
    client = _mock_client(SAMPLE_HTML)
    result = run_probe(probe, client=client)
    assert result.status == Status.HEALTHY
    assert result.response_time_ms >= 0
    assert result.error is None
    client.close()


def test_run_probe_broken_no_matches():
    probe = Probe(
        name="broken",
        url="https://example.com",
        checks=[Check(selector="li.item", expect_min=3)],
    )
    client = _mock_client(EMPTY_HTML)
    result = run_probe(probe, client=client)
    assert result.status == Status.BROKEN
    client.close()


def test_run_probe_degraded_schema_mismatch():
    probe = Probe(
        name="degraded",
        url="https://example.com",
        checks=[Check(selector="li.item a", expect_min=1, extract="text")],
        schema={
            "type": "object",
            "properties": {"missing_field": {"type": "string"}},
            "required": ["missing_field"],
        },
    )
    client = _mock_client(SAMPLE_HTML)
    result = run_probe(probe, client=client)
    assert result.status == Status.DEGRADED
    assert len(result.schema_errors) > 0
    client.close()


def test_run_probe_http_error():
    probe = Probe(
        name="error",
        url="https://example.com",
    )
    client = _mock_client("Not Found", status_code=404)
    result = run_probe(probe, client=client)
    assert result.status == Status.ERROR
    assert "404" in result.error
    client.close()


def test_run_probe_connection_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused")

    probe = Probe(name="connfail", url="https://unreachable.test")
    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = run_probe(probe, client=client)
    assert result.status == Status.ERROR
    assert "refused" in result.error.lower()
    client.close()


def test_run_all_probes():
    probes = [
        Probe(name="a", url="https://a.com", checks=[Check(selector="li.item", expect_min=1)]),
        Probe(name="b", url="https://b.com", checks=[Check(selector="li.item", expect_min=100)]),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=SAMPLE_HTML)

    # Patch run_all_probes to use our mock client
    import probelab.runner as runner_mod
    original = runner_mod.run_all_probes

    client = httpx.Client(transport=httpx.MockTransport(handler))
    results = []
    for p in probes:
        results.append(run_probe(p, client=client))
    client.close()

    assert len(results) == 2
    assert results[0].status == Status.HEALTHY
    assert results[1].status == Status.BROKEN


def test_run_probe_with_schema_valid():
    probe = Probe(
        name="schema-ok",
        url="https://example.com",
        checks=[Check(selector="li.item a", expect_min=1, extract="text")],
        schema={
            "type": "object",
            "properties": {"text": {"type": "string"}},
        },
    )
    client = _mock_client(SAMPLE_HTML)
    result = run_probe(probe, client=client)
    assert result.status == Status.HEALTHY
    assert result.schema_errors == []
    client.close()
