"""Tests for the Typer-based CLI."""

from typer.testing import CliRunner

from probelab.cli import app


runner = CliRunner()


def test_cli_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "probelab" in result.output.lower() or "browser" in result.output.lower()
    assert "check" in result.output
    assert "init" in result.output


def test_cli_help_shows_commands():
    result = runner.invoke(app, ["--help"])
    assert "show" in result.output
    assert "diff" in result.output
    assert "diagnose" in result.output
    assert "import-opencli" in result.output


def test_cli_init(tmp_path, monkeypatch):
    monkeypatch.setattr("probelab.cli.HOME", tmp_path)
    monkeypatch.setattr("probelab.cli.PROBES_DIR", tmp_path / "probes")

    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0
    assert "probelab initialized" in result.output.lower() or "Created" in result.output
    assert (tmp_path / "probes" / "hackernews.yaml").exists()


def test_cli_init_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr("probelab.cli.HOME", tmp_path)
    monkeypatch.setattr("probelab.cli.PROBES_DIR", tmp_path / "probes")

    runner.invoke(app, ["init"])
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0
    assert "Already exists" in result.output


def test_cli_check_no_probes_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("probelab.cli.HOME", tmp_path)
    monkeypatch.setattr("probelab.cli.PROBES_DIR", tmp_path / "probes")

    result = runner.invoke(app, ["check"])
    assert result.exit_code == 1
    assert "init" in result.output.lower()


def test_cli_check_nonexistent_probe():
    result = runner.invoke(app, ["check", "/nonexistent/probe.yaml"])
    assert result.exit_code == 1
    assert "not found" in result.output.lower()


def test_cli_show_no_runs(tmp_path, monkeypatch):
    monkeypatch.setattr("probelab.cli.HOME", tmp_path)

    result = runner.invoke(app, ["show", "nonexistent"])
    assert result.exit_code == 0
    assert "No runs" in result.output


def test_cli_diff_no_runs(tmp_path, monkeypatch):
    monkeypatch.setattr("probelab.cli.HOME", tmp_path)

    result = runner.invoke(app, ["diff", "nonexistent"])
    assert result.exit_code == 0
    assert "No runs" in result.output


def test_cli_diagnose_no_runs(tmp_path, monkeypatch):
    monkeypatch.setattr("probelab.cli.HOME", tmp_path)

    result = runner.invoke(app, ["diagnose", "nonexistent"])
    assert result.exit_code == 0
    assert "No runs" in result.output


def test_cli_import_opencli_nonexistent_path():
    result = runner.invoke(app, ["import-opencli", "/nonexistent/path"])
    assert result.exit_code == 1
    assert "not found" in result.output.lower()
