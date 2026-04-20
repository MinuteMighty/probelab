"""Tests for the codebase scanner and probe generator."""

from pathlib import Path

from probelab.scan.scanner import scan_directory, _clean_url, _should_skip_url
from probelab.scan.generate import dependencies_to_probes, write_probes, _slugify
from probelab.scan.patterns import Dependency


# ─────────────────────────────────────────────────────────────────────
# Helper: create mock project files
# ─────────────────────────────────────────────────────────────────────

def _make_project(tmp_path: Path, files: dict[str, str]) -> Path:
    """Create a mock project directory with the given files."""
    for rel_path, content in files.items():
        p = tmp_path / rel_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return tmp_path


# ===========================================================================
# Tests: URL helpers
# ===========================================================================


def test_clean_url_strips_trailing_punctuation():
    assert _clean_url("https://example.com/page,") == "https://example.com/page"
    assert _clean_url("https://example.com/page.") == "https://example.com/page"
    assert _clean_url("https://example.com/page)") == "https://example.com/page"


def test_clean_url_rejects_invalid():
    assert _clean_url("https://no-dot") is None
    assert _clean_url("not-a-url") is None


def test_should_skip_localhost():
    assert _should_skip_url("http://localhost:3000")
    assert _should_skip_url("http://127.0.0.1:8080")


def test_should_skip_assets():
    assert _should_skip_url("https://cdn.example.com/style.css")
    assert _should_skip_url("https://example.com/image.png")


def test_should_not_skip_real_urls():
    assert not _should_skip_url("https://api.stripe.com/v1/charges")
    assert not _should_skip_url("https://news.ycombinator.com")


def test_slugify():
    assert _slugify("example.com/pricing") == "example-com-pricing"
    assert _slugify("API.Stripe.com/V1") == "api-stripe-com-v1"


# ===========================================================================
# Tests: Python scanning
# ===========================================================================


def test_scan_finds_python_urls(tmp_path):
    project = _make_project(tmp_path, {
        "src/scraper.py": """
import requests
resp = requests.get("https://competitor.com/pricing")
""",
    })
    deps = scan_directory(project)
    urls = [d.url for d in deps if d.kind == "web"]
    assert "https://competitor.com/pricing" in urls


def test_scan_finds_python_selectors(tmp_path):
    project = _make_project(tmp_path, {
        "src/scraper.py": """
import requests
from bs4 import BeautifulSoup
resp = requests.get("https://competitor.com/pricing")
soup = BeautifulSoup(resp.text)
items = soup.select(".pricing-card")
title = soup.select_one("h1.title")
""",
    })
    deps = scan_directory(project)
    web = [d for d in deps if d.kind == "web"]
    assert len(web) >= 1
    selectors = web[0].selectors
    assert ".pricing-card" in selectors
    assert "h1.title" in selectors


def test_scan_finds_openai_import(tmp_path):
    project = _make_project(tmp_path, {
        "src/ai.py": """
import openai
client = openai.OpenAI()
response = client.chat.completions.create(model="gpt-4")
""",
    })
    deps = scan_directory(project)
    apis = [d for d in deps if d.kind == "api"]
    assert any(d.provider == "openai" for d in apis)


def test_scan_finds_anthropic_import(tmp_path):
    project = _make_project(tmp_path, {
        "src/ai.py": """
from anthropic import Anthropic
client = Anthropic()
""",
    })
    deps = scan_directory(project)
    apis = [d for d in deps if d.kind == "api"]
    assert any(d.provider == "anthropic" for d in apis)


def test_scan_finds_gemini_import(tmp_path):
    project = _make_project(tmp_path, {
        "src/ai.py": """
import google.generativeai as genai
genai.configure(api_key="xxx")
""",
    })
    deps = scan_directory(project)
    apis = [d for d in deps if d.kind == "api"]
    assert any(d.provider == "google-gemini" for d in apis)


def test_scan_finds_replicate_import(tmp_path):
    project = _make_project(tmp_path, {
        "src/ai.py": """
import replicate
output = replicate.run("stability-ai/sdxl")
""",
    })
    deps = scan_directory(project)
    apis = [d for d in deps if d.kind == "api"]
    assert any(d.provider == "replicate" for d in apis)


def test_scan_finds_stripe_import(tmp_path):
    project = _make_project(tmp_path, {
        "src/billing.py": """
import stripe
stripe.api_key = "sk_test_xxx"
""",
    })
    deps = scan_directory(project)
    apis = [d for d in deps if d.kind == "api"]
    assert any(d.provider == "stripe" for d in apis)


# ===========================================================================
# Tests: JavaScript scanning
# ===========================================================================


def test_scan_finds_js_fetch(tmp_path):
    project = _make_project(tmp_path, {
        "src/api.js": """
const resp = await fetch("https://api.example.com/data");
""",
    })
    deps = scan_directory(project)
    urls = [d.url for d in deps if d.kind == "web"]
    assert "https://api.example.com/data" in urls


def test_scan_finds_js_sdk(tmp_path):
    project = _make_project(tmp_path, {
        "src/ai.ts": """
import OpenAI from 'openai';
const client = new OpenAI();
""",
    })
    deps = scan_directory(project)
    apis = [d for d in deps if d.kind == "api"]
    assert any(d.provider == "openai" for d in apis)


def test_scan_finds_js_selectors(tmp_path):
    project = _make_project(tmp_path, {
        "src/scrape.js": """
const page = await browser.newPage();
await page.goto("https://shop.example.com/products");
const items = await page.$$(".product-card");
const title = await page.$("h1.page-title");
""",
    })
    deps = scan_directory(project)
    web = [d for d in deps if d.kind == "web"]
    assert len(web) >= 1
    all_selectors = []
    for d in web:
        all_selectors.extend(d.selectors)
    assert ".product-card" in all_selectors
    assert "h1.page-title" in all_selectors


# ===========================================================================
# Tests: Shell scanning
# ===========================================================================


def test_scan_finds_curl(tmp_path):
    project = _make_project(tmp_path, {
        "scripts/health.sh": """
#!/bin/bash
curl -s https://api.myservice.com/health | jq .status
""",
    })
    deps = scan_directory(project)
    urls = [d.url for d in deps if d.kind == "web"]
    assert "https://api.myservice.com/health" in urls


# ===========================================================================
# Tests: Config / env scanning
# ===========================================================================


def test_scan_finds_env_api_keys(tmp_path):
    project = _make_project(tmp_path, {
        ".env.example": """
OPENAI_API_KEY=sk-xxx
STRIPE_SECRET_KEY=sk_test_xxx
DATABASE_URL=postgres://localhost/mydb
""",
    })
    deps = scan_directory(project)
    apis = [d for d in deps if d.kind == "api"]
    providers = {d.provider for d in apis}
    assert "openai" in providers
    assert "stripe" in providers


def test_scan_finds_yaml_urls(tmp_path):
    project = _make_project(tmp_path, {
        "config/settings.yaml": """
services:
  payment: https://api.stripe.com/v1/charges
  docs: https://docs.myapp.com/api
""",
    })
    deps = scan_directory(project)
    urls = [d.url for d in deps if d.kind == "web"]
    assert any("stripe" in u for u in urls)
    assert any("docs.myapp.com" in u for u in urls)


def test_scan_finds_ci_urls(tmp_path):
    project = _make_project(tmp_path, {
        ".github/workflows/deploy.yml": """
jobs:
  health:
    steps:
      - run: curl https://myapp.com/health
""",
    })
    deps = scan_directory(project)
    web = [d for d in deps if d.kind == "web"]
    assert any("myapp.com" in (d.url or "") for d in web)


# ===========================================================================
# Tests: Markdown scanning
# ===========================================================================


def test_scan_finds_markdown_links(tmp_path):
    project = _make_project(tmp_path, {
        "README.md": """
# My Project
Check out the [API docs](https://docs.myapp.com/api).
See the [pricing page](https://competitor.com/pricing).
""",
    })
    deps = scan_directory(project)
    urls = [d.url for d in deps if d.kind == "web"]
    assert "https://docs.myapp.com/api" in urls
    assert "https://competitor.com/pricing" in urls


# ===========================================================================
# Tests: Skipping
# ===========================================================================


def test_scan_skips_node_modules(tmp_path):
    project = _make_project(tmp_path, {
        "node_modules/some-pkg/index.js": """
fetch("https://should-be-skipped.com")
""",
        "src/app.js": """
fetch("https://should-be-found.com/api")
""",
    })
    deps = scan_directory(project)
    urls = [d.url for d in deps if d.kind == "web"]
    assert not any("skipped" in u for u in urls)
    assert any("should-be-found" in u for u in urls)


def test_scan_skips_localhost(tmp_path):
    project = _make_project(tmp_path, {
        "src/app.py": """
requests.get("http://localhost:3000/api")
requests.get("https://real-api.com/data")
""",
    })
    deps = scan_directory(project)
    urls = [d.url for d in deps if d.kind == "web"]
    assert not any("localhost" in u for u in urls)
    assert any("real-api.com" in u for u in urls)


# ===========================================================================
# Tests: Deduplication
# ===========================================================================


def test_scan_deduplicates(tmp_path):
    project = _make_project(tmp_path, {
        "src/a.py": 'import openai\nrequests.get("https://api.example.com")',
        "src/b.py": 'import openai\nrequests.get("https://api.example.com")',
    })
    deps = scan_directory(project)
    openai_deps = [d for d in deps if d.provider == "openai"]
    assert len(openai_deps) == 1  # Deduplicated

    url_deps = [d for d in deps if d.url == "https://api.example.com"]
    assert len(url_deps) == 1


# ===========================================================================
# Tests: Probe generation
# ===========================================================================


def test_generate_web_probe():
    deps = [Dependency(
        kind="web",
        url="https://competitor.com/pricing",
        source_file="src/scraper.py",
        source_line=23,
        selectors=[".pricing-card", "h1.title"],
        description="HTTP request to competitor.com",
    )]
    probes = dependencies_to_probes(deps)
    assert len(probes) == 1

    probe = probes[0]
    assert probe["target"]["type"] == "web"
    assert probe["target"]["url"] == "https://competitor.com/pricing"
    assert any(a["type"] == "selector_exists" for a in probe["assertions"])
    assert any(a.get("selector") == ".pricing-card" for a in probe["assertions"])


def test_generate_api_probe():
    deps = [Dependency(
        kind="api",
        url="https://api.openai.com/v1/models",
        source_file="src/ai.py",
        source_line=1,
        provider="openai",
        env_key="OPENAI_API_KEY",
        description="Uses OpenAI API",
    )]
    probes = dependencies_to_probes(deps)
    assert len(probes) == 1

    probe = probes[0]
    assert probe["name"] == "api-openai"
    assert probe["target"]["type"] == "api"
    assert any(a["type"] == "reachable" for a in probe["assertions"])
    assert any(a["type"] == "auth_valid" for a in probe["assertions"])


def test_generate_web_probe_without_selectors():
    deps = [Dependency(
        kind="web",
        url="https://docs.example.com/install",
        source_file="README.md",
        source_line=15,
        description="Doc link",
    )]
    probes = dependencies_to_probes(deps)
    assert len(probes) == 1
    # Should have a text_exists assertion as fallback
    assertions = probes[0]["assertions"]
    assert any(a["type"] == "text_exists" for a in assertions)


def test_write_probes(tmp_path):
    probes = [
        {"name": "test-probe", "target": {"type": "web"}, "assertions": []},
    ]
    output_dir = tmp_path / "probes"
    written = write_probes(probes, output_dir)
    assert len(written) == 1
    assert written[0].exists()
    assert written[0].name == "test-probe.yaml"


def test_write_probes_no_overwrite(tmp_path):
    probes = [{"name": "test", "target": {"type": "web"}, "assertions": []}]
    output_dir = tmp_path / "probes"
    write_probes(probes, output_dir)
    written = write_probes(probes, output_dir, overwrite=False)
    assert len(written) == 0  # Should not overwrite


def test_write_probes_with_overwrite(tmp_path):
    probes = [{"name": "test", "target": {"type": "web"}, "assertions": []}]
    output_dir = tmp_path / "probes"
    write_probes(probes, output_dir)
    written = write_probes(probes, output_dir, overwrite=True)
    assert len(written) == 1


# ===========================================================================
# Tests: End-to-end scan + generate
# ===========================================================================


def test_scan_and_generate_full_project(tmp_path):
    """Scan a realistic project and verify probes are generated."""
    project = _make_project(tmp_path, {
        "src/main.py": """
import openai
import requests
from bs4 import BeautifulSoup

# Fetch competitor pricing
resp = requests.get("https://competitor.com/pricing")
soup = BeautifulSoup(resp.text)
prices = soup.select(".plan-card .price")
""",
        "src/notifications.py": """
import stripe
stripe.api_key = os.environ["STRIPE_SECRET_KEY"]
""",
        ".env.example": """
OPENAI_API_KEY=sk-xxx
REPLICATE_API_TOKEN=r8_xxx
""",
        "README.md": """
# My App
See the [user guide](https://docs.myapp.com/guide).
""",
        "scripts/deploy.sh": """
#!/bin/bash
curl -f https://myapp.com/health || exit 1
""",
    })

    deps = scan_directory(project)
    probes = dependencies_to_probes(deps)

    # Should find: openai, stripe, replicate (APIs) + competitor.com, docs, health (web)
    api_probes = [p for p in probes if p["target"]["type"] == "api"]
    web_probes = [p for p in probes if p["target"]["type"] == "web"]

    api_names = {p["name"] for p in api_probes}
    assert "api-openai" in api_names
    assert "api-stripe" in api_names
    assert "api-replicate" in api_names

    web_urls = {p["target"]["url"] for p in web_probes}
    assert "https://competitor.com/pricing" in web_urls
    assert any("myapp.com" in u for u in web_urls)

    # Competitor probe should have selectors
    competitor = [p for p in web_probes if "competitor" in p["target"]["url"]][0]
    selectors = [a.get("selector") for a in competitor["assertions"]]
    assert ".plan-card .price" in selectors
