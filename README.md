# probelab

**Browser automation health monitoring. Private-first. Self-diagnosing.**

Write a probe in YAML. probelab runs it, tells you if it passed or failed, and tells you _why_ it failed. Auth expired? Selector gone? CAPTCHA? DOM changed? You'll know in one command.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)

---

## Why

Every browser automation, web scraper, and CLI adapter depends on the target page staying the same. It never does.

- CSS classes get renamed. Selectors return 0 matches.
- Login sessions expire. The page silently redirects to `/signin`.
- Cloudflare throws a CAPTCHA. Your script sees an empty page.
- The site redesigns. Everything breaks at once.

We tested 5 OpenCLI adapters that were **less than one week old**. 67% of their selectors were already broken. ([Full audit](innoforge-projects/probelab/opencli-adapter-audit.md))

**probelab catches these failures, classifies them, and tells you exactly what to do.**

## Quick Start

```bash
pip install probelab
probelab init
probelab check
```

That's it. probelab creates an example probe and runs it:

```
  ✓  hackernews       healthy     279ms
```

## Write your own probe

Probes are YAML files. A probe says: go to this URL, check these conditions.

```yaml
name: hackernews
description: Verify HN front page loads and has stories

target:
  type: web
  url: https://news.ycombinator.com/

steps:
  - action: goto
    url: https://news.ycombinator.com/

assertions:
  - type: text_exists
    text: "Hacker News"
  - type: selector_exists
    selector: "span.titleline > a"
  - type: selector_count
    selector: "span.titleline > a"
    min: 10

outputs:
  - type: screenshot
  - type: html
```

Save it to `~/.probelab/probes/myprobe.yaml` and run `probelab check`.

## What failure classification looks like

probelab doesn't just say "it broke." It tells you _why_:

```
$ probelab check

  Probe             Status     Duration   Failure
  ────────────────   ────────   ────────   ──────────────
  hackernews         healthy       579ms
  github-trending    healthy      1374ms
  zhihu-cdp          broken       2692ms   auth_expired

  2 healthy | 1 broken / 3 total
```

```
$ probelab check probes/zhihu-cdp.yaml --verbose

  zhihu-cdp broken
    URL: https://www.zhihu.com/
    Duration: 4624ms

    Steps
      ✓ goto (2361ms)
      ✓ wait_for_text (10ms)

    Assertions
      ✗ selector_exists [itemprop='name'] = 0 matches
      ✗ selector_exists a[href*='/question/'] = 0 matches
      ✗ selector_exists .Post-Title = 0 matches

  ╭─────────────────────── Failure ────────────────────────╮
  │ auth_expired                                           │
  │ Redirected to login page:                              │
  │ https://www.zhihu.com/signin?next=%2F.                 │
  │ Re-login in Chrome.                                    │
  ╰────────────────────────────────────────────────────────╯
```

### 9 failure categories

| Category | What it means | What to do |
|---|---|---|
| `auth_expired` | Page redirected to login, or login form detected | Re-login in Chrome, re-run with `--cdp` |
| `captcha_detected` | CAPTCHA or bot challenge on page | Open the URL manually, solve it |
| `selector_missing` | CSS selector returns 0 matches | Run `probelab diagnose` for repair suggestions |
| `text_missing` | Expected text not found on page | Check if the site changed its copy |
| `url_mismatch` | URL doesn't match expected pattern | Check for redirects |
| `timeout` | Step or assertion timed out | Page may be slow or element may not exist |
| `navigation_error` | DNS failure, HTTP error, connection refused | Site may be down |
| `page_changed` | DOM structure changed from baseline | Run `probelab diff` to see what changed |
| `unexpected_redirect` | Redirected to a different domain | May be malicious or a CDN change |

## Authenticated sites (CDP mode)

probelab can connect to your running Chrome via CDP to use your real login sessions:

```bash
# 1. Launch Chrome with remote debugging
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222

# 2. Run probes with your login state
probelab check probes/zhihu-cdp.yaml --cdp ws://localhost:9222
```

This uses your real cookies, your real browser fingerprint. Sites can't tell it apart from you browsing manually.

## Diagnose and repair

When a selector breaks, probelab suggests replacements:

```
$ probelab diagnose zhihu-cdp

  zhihu-cdp -- broken
    Category: selector_missing
    Message: Selector '.Post-Title' not found (0 matches). DOM may have changed.

  Suggested replacements:
    1. [itemprop="name"]         -> 1 match  (confidence: 82%)
       Semantic attribute selector (survives redesigns)
    2. h1[class*="Title"]       -> 1 match  (confidence: 45%)
       Partial class match
    3. h1                        -> 3 matches (confidence: 12%)
       Tag-only fallback
```

Five repair strategies:
1. **Class relaxation** -- drop one class at a time
2. **Fuzzy class matching** -- catch renames (`story-link` -> `storyLink`)
3. **Parent simplification** -- try the leaf selector alone
4. **Attribute-based selectors** -- suggest `[data-testid]`, `[itemprop]`, `[role]`
5. **Structural similarity** -- find groups of sibling elements

## Baseline comparison

probelab saves successful runs as baselines. When things change:

```
$ probelab diff hackernews

  Baseline: 2026-04-15 (healthy)
  Current:  2026-04-16 (broken)

  Changes:
    - span.titleline > a: was 30 matches, now 0
    - url redirected from / to /signin
  
  Classification: auth_expired
```

## Security guardrails

probelab includes safety checks that run _during_ execution, not after:

- **Domain allowlist** -- probes can only navigate to domains declared in target/steps
- **Redirect anomaly detection** -- flags unexpected domain changes mid-execution
- **Prompt injection scanning** -- detects "ignore previous instructions" patterns in page content
- **Hidden element detection** -- flags hidden iframes and invisible action elements

These protect you when probing untrusted pages, and prepare for future LLM-powered features (diagnose, heal) where page content could mislead an AI agent.

## Commands

| Command | Description |
|---|---|
| `probelab init` | Create `~/.probelab/` directory with example probe |
| `probelab check [probe.yaml]` | Run one probe, or all probes if no argument |
| `probelab check --json` | JSON output (for CI pipelines) |
| `probelab check --verbose` | Detailed step-by-step results |
| `probelab check --cdp ws://...` | Use Chrome CDP for authenticated sites |
| `probelab show <name>` | Show last run result |
| `probelab diff <name>` | Compare latest run vs last healthy baseline |
| `probelab diagnose <name>` | Failure analysis + selector repair suggestions |

## Probe YAML reference

### Actions (steps)

| Action | Parameters | Description |
|---|---|---|
| `goto` | `url` | Navigate to URL |
| `click` | `selector` | Click an element |
| `type` | `selector`, `value` | Type text into an input |
| `wait_for_selector` | `selector`, `timeout_ms` | Wait for element to appear |
| `wait_for_text` | `text`, `timeout_ms` | Wait for text on page |

### Assertions

| Type | Parameters | Description |
|---|---|---|
| `selector_exists` | `selector` | Element exists (>= 1 match) |
| `selector_count` | `selector`, `min`, `max` | Match count in range |
| `text_exists` | `text` | Text appears on page |
| `url_matches` | `pattern` | Current URL matches regex |

### Outputs

| Type | Description |
|---|---|
| `screenshot` | Full-page PNG screenshot |
| `html` | Page HTML snapshot |

## Data storage

Everything stays on your machine. No cloud. No telemetry.

```
~/.probelab/
  probes/              # your probe definitions (YAML)
  runs/                # execution results + artifacts
    2026-04-15/
      hackernews/
        result.json
        screenshot.png
        page.html
  baselines/           # last known good state per probe
  history/             # run history (JSONL, one file per probe)
```

## CI/CD

```bash
probelab check --json
# Exit 0 = all healthy
# Exit 1 = any broken or error
```

```yaml
# .github/workflows/probes.yml
name: Probe Health
on:
  schedule:
    - cron: '0 */6 * * *'
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.13'
      - run: pip install probelab
      - run: probelab check --json
```

## Import probes from OpenCLI

If you use [OpenCLI](https://github.com/jackwener/OpenCLI), probelab can import its adapters as probes:

```bash
probelab-legacy import-opencli ~/OpenCLI/clis/
probelab check
```

This scans OpenCLI's adapter directory, extracts CSS selectors and URLs, and generates probe YAML files. The core probelab system is adapter-format-agnostic -- it only reads its own Probe YAML.

## Use cases

- **Adapter fleet monitoring** -- detect when adapters break across any framework
- **Internal tool health** -- check if your admin dashboard still works after deploys
- **Scraper maintenance** -- catch selector breakage before your data pipeline produces garbage
- **CI/CD gates** -- fail builds when external page structure changes
- **Pre-deploy checks** -- verify staging has the expected elements before shipping

### Works with any adapter ecosystem

probelab monitors the PAGE, not the adapter code. Write a probe for any site your automation targets:

| Ecosystem | How to use probelab |
|---|---|
| [OpenCLI](https://github.com/jackwener/OpenCLI) | `probelab-legacy import-opencli` auto-generates probes from adapters |
| [agent-browser](https://github.com/vercel-labs/agent-browser) | Write probes for the sites your agent-browser scripts target |
| [Browser Use](https://github.com/browser-use/browser-use) / [Workflow Use](https://github.com/browser-use/workflow-use) | Write probes to monitor pages your cached workflows depend on |
| [bb-browser](https://github.com/epiral/bb-browser) | Write probes for the 36 platforms bb-browser supports |
| [Stagehand](https://github.com/browserbase/stagehand) | Write probes to validate selectors Stagehand caches |
| Playwright / Puppeteer scripts | Write probes for the selectors your scripts use |
| Custom scrapers | Write probes for any page with any selectors |

probelab doesn't read or parse adapter code. It checks whether the page still has the elements your automation expects. The probe YAML is the universal format.

## What's coming

```
v1.0  (current)  Health monitoring + failure classification + diagnose
v1.1             HTML report dashboard (sparklines, health trails)
v1.2             Statistical baseline drift detection (sigma-based alerts)
v1.3             CLI/API probe types (not just web)
v2.0             Team registry (sync probes via private Git repo)
```

## Contributing

```bash
git clone https://github.com/MinuteMighty/probelab.git
cd probelab
pip install -e ".[dev,browser]"
playwright install chromium
python -m pytest tests/ -v
```

## License

MIT
