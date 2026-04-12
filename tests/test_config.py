"""Tests for config loading and saving."""

from probelab.config import save_probe, load_probe, load_all_probes, remove_probe, save_history, load_history
from probelab.probe import Check, Probe


def test_save_and_load_probe(tmp_probelab):
    probe = Probe(
        name="test-save",
        url="https://example.com",
        checks=[Check(selector="h1", expect_min=1)],
        tags=["test"],
    )
    path = save_probe(probe, base=tmp_probelab)
    assert path.exists()

    loaded = load_probe(path)
    assert loaded.name == "test-save"
    assert loaded.url == "https://example.com"
    assert len(loaded.checks) == 1
    assert loaded.checks[0].selector == "h1"
    assert loaded.tags == ["test"]


def test_load_all_probes(tmp_probelab):
    for i in range(3):
        save_probe(
            Probe(name=f"probe-{i}", url=f"https://example{i}.com"),
            base=tmp_probelab,
        )
    probes = load_all_probes(base=tmp_probelab)
    assert len(probes) == 3
    names = [p.name for p in probes]
    assert "probe-0" in names
    assert "probe-2" in names


def test_load_all_probes_empty(tmp_path):
    probes = load_all_probes(base=tmp_path)
    assert probes == []


def test_remove_probe(tmp_probelab):
    save_probe(Probe(name="to-remove", url="https://example.com"), base=tmp_probelab)
    assert remove_probe("to-remove", base=tmp_probelab) is True
    assert remove_probe("to-remove", base=tmp_probelab) is False


def test_save_and_load_history(tmp_probelab):
    save_history("test", {"status": "healthy", "time": 100}, base=tmp_probelab)
    save_history("test", {"status": "broken", "time": 200}, base=tmp_probelab)

    history = load_history("test", base=tmp_probelab)
    assert len(history) == 2
    assert history[0]["status"] == "healthy"
    assert history[1]["status"] == "broken"


def test_load_history_nonexistent(tmp_probelab):
    history = load_history("nonexistent", base=tmp_probelab)
    assert history == []


def test_load_history_with_limit(tmp_probelab):
    for i in range(10):
        save_history("test", {"i": i}, base=tmp_probelab)
    history = load_history("test", base=tmp_probelab, limit=3)
    assert len(history) == 3
    assert history[0]["i"] == 7  # last 3 of 0-9
