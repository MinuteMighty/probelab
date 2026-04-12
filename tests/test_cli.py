"""Tests for the CLI interface."""

from click.testing import CliRunner

from probelab.cli import main
from probelab.config import save_probe, PROBES_DIR
from probelab.probe import Check, Probe


def test_cli_version():
    runner = CliRunner()
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0
    assert "0.2.0" in result.output


def test_cli_help():
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "probelab" in result.output
    assert "check" in result.output
    assert "init" in result.output


def test_cli_init():
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(main, [
            "init", "my-probe",
            "--url", "https://example.com",
            "--select", "h1",
            "--expect-min", "1",
        ])
        assert result.exit_code == 0
        assert "my-probe" in result.output
        assert (PROBES_DIR / "my-probe.toml").exists()


def test_cli_list_empty():
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(main, ["list"])
        assert result.exit_code == 0
        assert "No probes" in result.output


def test_cli_list_with_probes():
    runner = CliRunner()
    with runner.isolated_filesystem():
        runner.invoke(main, [
            "init", "probe-a", "--url", "https://a.com", "--select", "h1",
        ])
        runner.invoke(main, [
            "init", "probe-b", "--url", "https://b.com", "--select", "div",
        ])
        result = runner.invoke(main, ["list"])
        assert result.exit_code == 0
        assert "probe-a" in result.output
        assert "probe-b" in result.output


def test_cli_show():
    runner = CliRunner()
    with runner.isolated_filesystem():
        runner.invoke(main, [
            "init", "my-probe",
            "--url", "https://example.com",
            "--select", "h1",
            "--tag", "test",
        ])
        result = runner.invoke(main, ["show", "my-probe"])
        assert result.exit_code == 0
        assert "my-probe" in result.output
        assert "https://example.com" in result.output
        assert "h1" in result.output


def test_cli_show_nonexistent():
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(main, ["show", "nonexistent"])
        assert result.exit_code == 1
        assert "not found" in result.output.lower()


def test_cli_remove():
    runner = CliRunner()
    with runner.isolated_filesystem():
        runner.invoke(main, [
            "init", "to-remove", "--url", "https://example.com",
        ])
        result = runner.invoke(main, ["remove", "to-remove"], input="y\n")
        assert result.exit_code == 0
        assert "removed" in result.output.lower()


def test_cli_check_no_probes():
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(main, ["check"])
        assert result.exit_code == 0
        assert "No probes" in result.output


def test_cli_check_nonexistent_probe():
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(main, ["check", "nonexistent"])
        assert result.exit_code == 1


def test_cli_history_empty():
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(main, ["history", "nonexistent"])
        assert result.exit_code == 0
        assert "No history" in result.output


def test_cli_status_empty():
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(main, ["status"])
        assert result.exit_code == 0
        assert "No probes" in result.output


def test_cli_status_with_probes():
    runner = CliRunner()
    with runner.isolated_filesystem():
        runner.invoke(main, [
            "init", "probe-a", "--url", "https://a.com", "--select", "h1",
        ])
        result = runner.invoke(main, ["status"])
        assert result.exit_code == 0
        assert "Health Dashboard" in result.output
        assert "probe-a" in result.output


def test_cli_help_shows_status():
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert "status" in result.output
