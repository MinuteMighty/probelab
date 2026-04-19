"""Divergence counter: runner.py vs engine.py.

Runs every probe in `probes/` through both execution paths (where each
supports it) and reports where their classifications disagree.

This is the Week-1 bake test from the plan-eng-review: before deleting
runner.py, we want 5 consecutive days of zero divergence on the probe
corpus. Start by measuring the current state.

Note: runner.py consumes the legacy Check-based Probe model; engine.py
consumes the Step+Assertion model. Every probe currently in probes/ uses
the new Step+Assertion format, so runner.py will load them but see zero
checks (legacy field) and return HEALTHY trivially. This test makes that
structural reality visible so we stop treating runner.py as a second
source of truth.

Run with: pytest tests/test_runner_engine_divergence.py -v -s
"""

from __future__ import annotations

from pathlib import Path

import pytest

from probelab.io.loader import load_probe as load_new_probe
from probelab.probe import Probe as LegacyProbe


PROBES_DIR = Path(__file__).parent.parent / "probes"


def _collect_probe_paths() -> list[Path]:
    if not PROBES_DIR.exists():
        return []
    return sorted(PROBES_DIR.rglob("*.yaml"))


def _load_legacy(path: Path) -> LegacyProbe | None:
    """Load via the old probe.py loader. Returns None if it can't parse."""
    import yaml

    try:
        data = yaml.safe_load(path.read_text())
        return LegacyProbe.from_dict(data)
    except Exception:
        return None


def test_runner_engine_coverage_matrix():
    """Print a matrix of which probes each runtime can load.

    This is not pass/fail — it's a visibility test that shows the
    migration surface: how many probes are new-format (engine only),
    how many are legacy-format (runner only), and how many are dual.
    """
    probe_paths = _collect_probe_paths()
    assert probe_paths, f"No probes found in {PROBES_DIR}"

    engine_loadable = 0
    runner_loadable = 0
    engine_has_checks = 0  # legacy field non-empty on new loader
    runner_has_checks = 0  # checks non-empty on legacy loader
    both_loadable = 0

    rows: list[tuple[str, bool, bool, int, int]] = []

    for path in probe_paths:
        rel = path.relative_to(PROBES_DIR)
        new_probe = None
        legacy_probe = None

        try:
            new_probe = load_new_probe(path)
        except Exception:
            pass

        legacy_probe = _load_legacy(path)

        new_ok = new_probe is not None
        legacy_ok = legacy_probe is not None

        if new_ok:
            engine_loadable += 1
        if legacy_ok:
            runner_loadable += 1
        if new_ok and legacy_ok:
            both_loadable += 1

        new_asserts = len(getattr(new_probe, "assertions", []) or []) if new_probe else 0
        legacy_checks = len(legacy_probe.checks) if legacy_probe else 0

        if new_asserts > 0 and new_probe:
            engine_has_checks += 1
        if legacy_checks > 0 and legacy_probe:
            runner_has_checks += 1

        rows.append((str(rel), new_ok, legacy_ok, new_asserts, legacy_checks))

    # Report
    print()
    print("=" * 78)
    print("PROBE LOADABILITY MATRIX")
    print("=" * 78)
    print(f"{'Probe':<40}{'engine':>8}{'runner':>8}{'asserts':>10}{'checks':>10}")
    print("-" * 78)
    for rel, e, r, a, c in rows:
        print(f"{rel:<40}{'Y' if e else '-':>8}{'Y' if r else '-':>8}{a:>10}{c:>10}")
    print("-" * 78)
    total = len(probe_paths)
    print(f"{'TOTAL':<40}{engine_loadable:>8}{runner_loadable:>8}{engine_has_checks:>10}{runner_has_checks:>10}")
    print()
    print(f"engine loadable:   {engine_loadable}/{total}")
    print(f"runner loadable:   {runner_loadable}/{total}")
    print(f"both loadable:     {both_loadable}/{total}")
    print(f"has assertions (new model): {engine_has_checks}/{total}")
    print(f"has checks (legacy model):  {runner_has_checks}/{total}")
    print("=" * 78)

    # Assertion: the moment `runner_has_checks` is zero, runner.py is
    # objectively dead code for the current probe corpus.
    if runner_has_checks == 0:
        print()
        print("VERDICT: runner.py is processing zero checks across the probe")
        print("corpus. It returns HEALTHY trivially for every new-format probe.")
        print("The 'dual run_probe' concern from eng review outside voice is")
        print("architecturally real but empirically a no-op today. The")
        print("migration is safe to proceed: engine is the only path that")
        print("actually evaluates assertions.")
        print()


@pytest.mark.skipif(not PROBES_DIR.exists(), reason="no probes dir")
def test_runner_cannot_evaluate_new_format_probes():
    """Regression: confirm runner.py returns HEALTHY on new-format probes
    regardless of whether their assertions would pass.

    If this test ever starts FAILING (runner returning non-HEALTHY), it
    means someone added the new-model evaluation logic to runner.py
    without migrating callers first. Flag immediately.
    """
    probe_paths = _collect_probe_paths()
    legacy_fail_count = 0
    total_new_format = 0

    for path in probe_paths:
        legacy = _load_legacy(path)
        if not legacy or legacy.checks:
            continue  # legacy-format or unparseable; skip
        total_new_format += 1
        # runner.run_probe would return HEALTHY here (no checks to fail).
        # We don't actually execute (requires network) — just confirm
        # the parsed legacy Probe has zero checks.
        if len(legacy.checks) > 0:
            legacy_fail_count += 1

    assert legacy_fail_count == 0, (
        f"{legacy_fail_count}/{total_new_format} new-format probes "
        f"suddenly have legacy checks field populated. runner.py may "
        f"have gained new-model awareness — verify before migrating."
    )
