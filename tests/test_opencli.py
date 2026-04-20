"""Tests for opencli adapter import."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from probelab.cli import app
from probelab.config import PROBES_DIR
from probelab.opencli import (
    ParsedAdapter,
    adapters_to_probes,
    import_opencli,
    parse_adapter,
    scan_opencli_dir,
    slugify,
)

# ---------------------------------------------------------------------------
# Sample adapter sources
# ---------------------------------------------------------------------------

SAMPLE_TS_ADAPTER = """\
import { cli, Strategy } from 'registry.js';

cli({
  site: 'hackernews',
  name: 'trending',
  description: 'Trending stories from HN',
  domain: 'news.ycombinator.com',
  strategy: Strategy.PUBLIC,
  browser: true,
  columns: ['rank', 'title', 'score', 'url'],
  func: async (page, kwargs) => {
    await page.goto('https://news.ycombinator.com');
    await page.waitForSelector('tr.athing');
    return await page.evaluate(() => {
      return Array.from(document.querySelectorAll('tr.athing')).map(row => ({
        title: row.querySelector('.titleline > a')?.textContent,
        score: row.querySelector('.score')?.textContent,
        url: row.querySelector('.titleline > a')?.href,
      }));
    });
  }
});
"""

SAMPLE_TS_PAGE_DOLLAR = """\
cli({
  site: 'reddit',
  name: 'hot',
  domain: 'www.reddit.com',
  browser: true,
  func: async (page, kwargs) => {
    await page.goto('https://www.reddit.com/r/all');
    const items = await page.$$('[data-testid="post-container"]');
    const title = await page.$('h3.post-title');
    return items;
  }
});
"""

SAMPLE_TS_NO_SELECTORS = """\
cli({
  site: 'weather',
  name: 'forecast',
  domain: 'api.weather.com',
  browser: false,
  func: async (page, kwargs) => {
    const data = await fetch('https://api.weather.com/v1/forecast');
    return data.json();
  }
});
"""

SAMPLE_TS_DYNAMIC_URL = """\
cli({
  site: 'github',
  name: 'repos',
  domain: 'github.com',
  browser: false,
  func: async (page, kwargs) => {
    await page.goto(`https://github.com/${kwargs.user}/repos`);
    await page.waitForSelector('div.repo-list-item');
    const items = await page.$$('div.repo-list-item h3 a');
    return items;
  }
});
"""

SAMPLE_TS_NO_DOMAIN = """\
cli({
  site: 'mystery',
  name: 'data',
  func: async (page, kwargs) => {
    await page.waitForSelector('.item');
    return [];
  }
});
"""

SAMPLE_TS_DUPLICATE_SELECTORS = """\
cli({
  site: 'example',
  name: 'dupes',
  domain: 'example.com',
  browser: false,
  func: async (page, kwargs) => {
    await page.goto('https://example.com');
    await page.waitForSelector('.item');
    const a = document.querySelectorAll('.item');
    const b = document.querySelector('.item');
    const c = document.querySelector('.other');
    return [];
  }
});
"""


# ---------------------------------------------------------------------------
# Helper: write a mock opencli directory
# ---------------------------------------------------------------------------


def _make_opencli_dir(tmp_path: Path, adapters: dict[str, dict[str, str]], subdir: str = "clis") -> Path:
    """Create a mock opencli directory.

    adapters is {site: {command: source_code}}.
    """
    root = tmp_path / "opencli"
    for site, commands in adapters.items():
        site_dir = root / subdir / site
        site_dir.mkdir(parents=True)
        for cmd_name, source in commands.items():
            (site_dir / f"{cmd_name}.js").write_text(source)
    return root


# ===========================================================================
# Tests: slugify
# ===========================================================================


class TestSlugify:
    def test_basic(self):
        assert slugify("HackerNews") == "hackernews"

    def test_spaces_and_special(self):
        assert slugify("my site/page") == "my-site-page"

    def test_consecutive_hyphens(self):
        assert slugify("a--b") == "a-b"

    def test_strip_edges(self):
        assert slugify("--hello--") == "hello"

    def test_already_clean(self):
        assert slugify("hackernews-trending") == "hackernews-trending"


# ===========================================================================
# Tests: parse_typescript_adapter
# ===========================================================================


class TestParseAdapter:
    def test_extracts_selectors(self, tmp_path):
        f = tmp_path / "trending.ts"
        f.write_text(SAMPLE_TS_ADAPTER)
        result = parse_adapter(f)
        assert result is not None
        assert "tr.athing" in result.selectors
        assert ".titleline > a" in result.selectors
        assert ".score" in result.selectors

    def test_extracts_url(self, tmp_path):
        f = tmp_path / "trending.ts"
        f.write_text(SAMPLE_TS_ADAPTER)
        result = parse_adapter(f)
        assert result is not None
        assert result.url == "https://news.ycombinator.com"

    def test_extracts_metadata(self, tmp_path):
        f = tmp_path / "trending.ts"
        f.write_text(SAMPLE_TS_ADAPTER)
        result = parse_adapter(f)
        assert result is not None
        assert result.site == "hackernews"
        assert result.command == "trending"
        assert result.domain == "news.ycombinator.com"
        assert result.browser is True

    def test_page_dollar_selectors(self, tmp_path):
        f = tmp_path / "hot.ts"
        f.write_text(SAMPLE_TS_PAGE_DOLLAR)
        result = parse_adapter(f)
        assert result is not None
        assert '[data-testid="post-container"]' in result.selectors
        assert "h3.post-title" in result.selectors

    def test_no_selectors_returns_none(self, tmp_path):
        f = tmp_path / "forecast.ts"
        f.write_text(SAMPLE_TS_NO_SELECTORS)
        result = parse_adapter(f)
        assert result is None

    def test_dynamic_url_falls_back_to_domain(self, tmp_path):
        f = tmp_path / "repos.ts"
        f.write_text(SAMPLE_TS_DYNAMIC_URL)
        result = parse_adapter(f)
        assert result is not None
        assert result.url == "https://github.com"

    def test_no_domain_no_url(self, tmp_path):
        f = tmp_path / "data.ts"
        f.write_text(SAMPLE_TS_NO_DOMAIN)
        result = parse_adapter(f)
        assert result is not None
        assert result.url is None
        assert len(result.selectors) == 1

    def test_deduplicates_selectors(self, tmp_path):
        f = tmp_path / "dupes.ts"
        f.write_text(SAMPLE_TS_DUPLICATE_SELECTORS)
        result = parse_adapter(f)
        assert result is not None
        assert result.selectors.count(".item") == 1
        assert ".other" in result.selectors

    def test_fallback_site_and_command_from_path(self, tmp_path):
        """When no site/name in source, use directory/filename."""
        source = """\
cli({
  domain: 'example.com',
  func: async (page, kwargs) => {
    await page.waitForSelector('.thing');
    return [];
  }
});
"""
        site_dir = tmp_path / "mysite"
        site_dir.mkdir()
        f = site_dir / "mycommand.ts"
        f.write_text(source)
        result = parse_adapter(f)
        assert result is not None
        assert result.site == "mysite"
        assert result.command == "mycommand"

    def test_unreadable_file_returns_none(self, tmp_path):
        f = tmp_path / "binary.ts"
        f.write_bytes(b"\x80\x81\x82\x83" * 100)
        result = parse_adapter(f)
        assert result is None


# ===========================================================================
# Tests: scan_opencli_dir
# ===========================================================================


class TestScanOpencliDir:
    def test_finds_ts_files(self, tmp_path):
        root = _make_opencli_dir(tmp_path, {
            "hackernews": {"trending": SAMPLE_TS_ADAPTER},
            "reddit": {"hot": SAMPLE_TS_PAGE_DOLLAR},
        })
        adapters = scan_opencli_dir(root)
        assert len(adapters) == 2
        sites = {a.site for a in adapters}
        assert sites == {"hackernews", "reddit"}

    def test_skips_no_selector_adapters(self, tmp_path):
        root = _make_opencli_dir(tmp_path, {
            "hackernews": {"trending": SAMPLE_TS_ADAPTER},
            "weather": {"forecast": SAMPLE_TS_NO_SELECTORS},
        })
        adapters = scan_opencli_dir(root)
        assert len(adapters) == 1
        assert adapters[0].site == "hackernews"

    def test_skips_index_and_test_files(self, tmp_path):
        root = _make_opencli_dir(tmp_path, {
            "hackernews": {"trending": SAMPLE_TS_ADAPTER},
        })
        # Add files that should be skipped
        site_dir = root / "clis" / "hackernews"
        (site_dir / "index.js").write_text("export * from './trending';")
        (site_dir / "trending.test.js").write_text("test('works', () => {});")
        (site_dir / "trending.spec.js").write_text("describe('trending', () => {});")
        (site_dir / "_internal.js").write_text("const x = 1;")
        (site_dir / "shared.js").write_text("export const HEADERS = {};")

        adapters = scan_opencli_dir(root)
        assert len(adapters) == 1

    def test_empty_dir(self, tmp_path):
        root = tmp_path / "empty-opencli"
        root.mkdir()
        adapters = scan_opencli_dir(root)
        assert adapters == []

    def test_fallback_without_clis_dir(self, tmp_path):
        """When clis/ doesn't exist, scan root for .js files."""
        root = tmp_path / "flat-opencli"
        root.mkdir()
        (root / "trending.js").write_text(SAMPLE_TS_ADAPTER)
        adapters = scan_opencli_dir(root)
        assert len(adapters) == 1


# ===========================================================================
# Tests: adapters_to_probes
# ===========================================================================


class TestAdaptersToProbes:
    def test_basic_conversion(self):
        adapter = ParsedAdapter(
            site="hackernews",
            command="trending",
            url="https://news.ycombinator.com",
            domain="news.ycombinator.com",
            selectors=["tr.athing", ".titleline > a"],
            browser=True,
            strategy="PUBLIC",
            source_path="/fake/path.ts",
        )
        probes, skipped = adapters_to_probes([adapter])
        assert len(probes) == 1
        assert len(skipped) == 0
        probe = probes[0]
        assert probe.name == "hackernews-trending"
        assert probe.url == "https://news.ycombinator.com"
        assert len(probe.checks) == 2
        assert probe.checks[0].selector == "tr.athing"
        assert probe.checks[0].expect_min == 1
        assert probe.browser is True

    def test_tags(self):
        adapter = ParsedAdapter(
            site="reddit",
            command="hot",
            url="https://www.reddit.com",
            domain="www.reddit.com",
            selectors=[".post"],
            browser=False,
            strategy="PUBLIC",
            source_path="/fake/path.ts",
        )
        probes, _ = adapters_to_probes([adapter])
        assert probes[0].tags == ["opencli", "reddit"]

    def test_cookie_strategy_sets_browser_true(self):
        adapter = ParsedAdapter(
            site="xhs",
            command="note",
            url="https://www.xiaohongshu.com",
            domain="www.xiaohongshu.com",
            selectors=[".title"],
            browser=False,
            strategy="COOKIE",
            source_path="/fake/path.ts",
        )
        probes, _ = adapters_to_probes([adapter])
        assert probes[0].browser is True  # COOKIE != PUBLIC → skip

    def test_public_strategy_keeps_browser_false(self):
        adapter = ParsedAdapter(
            site="hn",
            command="top",
            url="https://news.ycombinator.com",
            domain="news.ycombinator.com",
            selectors=[".item"],
            browser=False,
            strategy="PUBLIC",
            source_path="/fake/path.ts",
        )
        probes, _ = adapters_to_probes([adapter])
        assert probes[0].browser is False

    def test_skip_no_url(self):
        adapter = ParsedAdapter(
            site="mystery",
            command="data",
            url=None,
            domain=None,
            selectors=[".item"],
            browser=False,
            strategy="PUBLIC",
            source_path="/fake/path.ts",
        )
        probes, skipped = adapters_to_probes([adapter])
        assert len(probes) == 0
        assert len(skipped) == 1
        assert "no URL" in skipped[0][1]

    def test_skip_duplicate_names(self):
        adapter1 = ParsedAdapter(
            site="site", command="cmd", url="https://a.com",
            domain="a.com", selectors=[".a"], browser=False, strategy="PUBLIC", source_path="1",
        )
        adapter2 = ParsedAdapter(
            site="site", command="cmd", url="https://b.com",
            domain="b.com", selectors=[".b"], browser=False, strategy="PUBLIC", source_path="2",
        )
        probes, skipped = adapters_to_probes([adapter1, adapter2])
        assert len(probes) == 1
        assert len(skipped) == 1
        assert "duplicate" in skipped[0][1]


# ===========================================================================
# Tests: import_opencli (integration)
# ===========================================================================


class TestImportOpencli:
    def test_full_import(self, tmp_path):
        root = _make_opencli_dir(tmp_path, {
            "hackernews": {"trending": SAMPLE_TS_ADAPTER},
            "reddit": {"hot": SAMPLE_TS_PAGE_DOLLAR},
        })
        base = tmp_path / "project"
        base.mkdir()

        result = import_opencli(root, base=base)
        assert result.adapters_found == 2
        assert result.probes_created == 2
        assert len(result.skipped) == 0
        assert (base / PROBES_DIR / "hackernews-trending.toml").exists()
        assert (base / PROBES_DIR / "reddit-hot.toml").exists()

    def test_skip_existing_without_force(self, tmp_path):
        root = _make_opencli_dir(tmp_path, {
            "hackernews": {"trending": SAMPLE_TS_ADAPTER},
        })
        base = tmp_path / "project"
        base.mkdir()

        # First import
        import_opencli(root, base=base)
        # Second import — should skip
        result = import_opencli(root, base=base, force=False)
        assert result.probes_created == 0
        assert len(result.skipped) == 1
        assert "already exists" in result.skipped[0][1]

    def test_force_overwrites(self, tmp_path):
        root = _make_opencli_dir(tmp_path, {
            "hackernews": {"trending": SAMPLE_TS_ADAPTER},
        })
        base = tmp_path / "project"
        base.mkdir()

        import_opencli(root, base=base)
        result = import_opencli(root, base=base, force=True)
        assert result.probes_created == 1
        assert len(result.skipped) == 0

    def test_extra_tags(self, tmp_path):
        root = _make_opencli_dir(tmp_path, {
            "hackernews": {"trending": SAMPLE_TS_ADAPTER},
        })
        base = tmp_path / "project"
        base.mkdir()

        result = import_opencli(root, base=base, extra_tags=["ci", "nightly"])
        assert result.probes_created == 1

        # Verify the saved probe has extra tags
        from probelab.config import load_probe
        probe = load_probe(base / PROBES_DIR / "hackernews-trending.toml")
        assert "ci" in probe.tags
        assert "nightly" in probe.tags
        assert "opencli" in probe.tags


# ===========================================================================
# Tests: CLI command
# ===========================================================================


class TestCliImportOpencli:
    def test_dry_run(self, tmp_path):
        root = _make_opencli_dir(tmp_path, {
            "hackernews": {"trending": SAMPLE_TS_ADAPTER},
        })
        runner = CliRunner()
        result = runner.invoke(app, ["import-opencli", str(root), "--dry-run"])
        assert result.exit_code == 0
        assert "hackernews-tren" in result.output  # Rich may truncate in narrow terminal
        assert "Dry Run" in result.output

    def test_import_creates_probes(self, tmp_path, monkeypatch):
        root = _make_opencli_dir(tmp_path, {
            "hackernews": {"trending": SAMPLE_TS_ADAPTER},
        })
        work_dir = tmp_path / "workdir"
        work_dir.mkdir()
        monkeypatch.chdir(work_dir)
        runner = CliRunner()
        result = runner.invoke(app, ["import-opencli", str(root)])
        assert result.exit_code == 0
        assert "Probes created" in result.output
        assert (work_dir / PROBES_DIR / "hackernews-trending.toml").exists()

    def test_empty_dir_message(self, tmp_path):
        root = tmp_path / "empty"
        root.mkdir()
        runner = CliRunner()
        result = runner.invoke(app, ["import-opencli", str(root), "--dry-run"])
        assert result.exit_code == 0
        assert "No adapters" in result.output

    def test_with_extra_tags(self, tmp_path, monkeypatch):
        root = _make_opencli_dir(tmp_path, {
            "hackernews": {"trending": SAMPLE_TS_ADAPTER},
        })
        work_dir = tmp_path / "workdir"
        work_dir.mkdir()
        monkeypatch.chdir(work_dir)
        runner = CliRunner()
        result = runner.invoke(app, [
            "import-opencli", str(root), "--tag", "ci", "--tag", "nightly",
        ])
        assert result.exit_code == 0
        assert "Probes created" in result.output
