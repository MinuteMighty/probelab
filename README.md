# probelab

**Monitor web contracts. Detect drift. Diagnose and repair.**

Your automation depends on external web pages keeping their structure. When they don't, probelab tells you what changed and how to fix it.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)

---

## What is a web contract?

Every web scraper, CLI adapter, and browser automation script depends on an implicit **contract** with its target page: "element X exists at selector Y, returns at least N items, and conforms to schema Z."

When the page changes — a CSS class renamed, a `<ul>` replaced with `<div>`s, a field dropped from the response — the contract breaks. The page still returns HTTP 200. Your logs show no errors. But your data pipeline is silently producing garbage.

**probelab monitors these contracts.** It detects drift before your automation fails, diagnoses exactly what changed in the DOM, and suggests selector repairs.

## The full loop: detect, diagnose, repair

```
$ probelab check

 ✗  technews   broken   selector got 0 (expected >=5); DOM changed   1ms

╭─────────────────────── technews diagnostics ───────────────────────╮
│ DOM Changes:                                                       │
│   8 element(s) removed; 8 element(s) added; 1 possible rename     │
│   - Element no longer present: ul.story-list                       │
│   - Element no longer present: li.story-item                       │
│   - Element no longer present: a.story-link                        │
│   + New element appeared: div.feed                                 │
│   + New element appeared: article.feed-entry                       │
│                                                                    │
│ Drift Alerts:                                                      │
│   li.story-item a.story-link: got 0 matches, expected ~8.         │
│   Drop of 8.0 sigma.                                              │
│                                                                    │
│ Suggested Repairs:                                                 │
│   1. article.feed-entry > a  (8 matches, conf=36%)                │
│      Structural match: 8 sibling 'a' elements under 'article'     │
│      Preview: AI Agents Are Replacing Browser Extensions           │
╰────────────────────────────────────────────────────────────────────╯
```

One command told you:
- **What broke**: your selector matches 0 elements now
- **Why**: the site renamed `li.story-item` to `article.feed-entry`
- **How far off normal**: 8.0 standard deviations from baseline
- **How to fix it**: try `article.feed-entry > a` (8 matches, same content)

## Installation

```bash
pip install probelab
```

Requires Python 3.11+.

## Quick Start

```bash
# 1. Define a contract
probelab init hackernews \
  --url "https://news.ycombinator.com" \
  --select "tr.athing .titleline > a" \
  --expect-min 20

# 2. Monitor it
probelab check

# 3. When something breaks, probelab tells you what changed and how to fix it
```

## Try the demo

A self-contained demo that simulates a site redesign and walks through the full detect-diagnose-repair loop:

```bash
git clone https://github.com/MinuteMighty/probelab.git
cd probelab
pip install -e .
python demo.py
```

## How it works

### 1. Define contracts as probes

Probes are TOML files in `.probelab/probes/`:

```toml
[probe]
name = "technews"
url = "https://technews.example.com"
timeout = 10

[[probe.checks]]
selector = "li.story-item a.story-link"
expect_min = 5
extract = "text"

[probe.schema]
type = "object"
properties.text = { type = "string", minLength = 1 }
properties.href = { type = "string" }
required = ["text"]
```

A probe says: "This URL should have at least 5 elements matching this selector, and their content should conform to this schema."

### 2. Detect breakage

```bash
probelab check              # Run all probes
probelab check technews     # Run one probe
probelab check --format json --exit-code   # CI mode
```

| Status | Meaning |
|--------|---------|
| **healthy** | All selectors match, schema validates, no drift detected |
| **degraded** | Selectors match but schema fails, or DOM structure drifted, or baseline anomaly |
| **broken** | Selectors return fewer matches than expected |
| **error** | HTTP error, timeout, DNS failure |

### 3. Diagnose with DOM diff

probelab snapshots the page structure on every run. When it changes, you see exactly what was added, removed, or renamed:

```bash
probelab diff technews
```

### 4. Detect statistical drift

After 5+ runs, probelab learns what "normal" looks like for each selector. A drop from 30 to 5 matches triggers a **critical drift alert** — even if your hard-coded `expect_min=1` would pass.

```bash
probelab baseline technews
```

```
 Selector                    Mean  Stddev  Range   Suggested Min  Suggested Max
 tr.athing .titleline > a    30.2  1.4     28-33   27             34
```

### 5. Repair with selector suggestions

When a selector breaks, probelab analyzes the current DOM and suggests replacements using five strategies:

1. **Class relaxation** — drop one class at a time
2. **Fuzzy class matching** — catch renames like `story-link` → `storyLink`
3. **Parent simplification** — try the leaf selector alone
4. **Attribute-based selectors** — suggest `data-testid` or `role` alternatives
5. **Structural similarity** — find groups of sibling elements with the same tag

## Commands

| Command | Description |
|---------|-------------|
| `probelab init <name>` | Define a new contract |
| `probelab check [name]` | Monitor contracts (all or one) |
| `probelab list` | List all contracts |
| `probelab show <name>` | Show contract details |
| `probelab baseline <name>` | Show learned baseline statistics |
| `probelab diff <name>` | Show DOM structural snapshot |
| `probelab history <name>` | Show past results |
| `probelab remove <name>` | Delete a contract |

## CI/CD Integration

```bash
probelab check --exit-code --format json
# Exit 0 = all healthy
# Exit 1 = at least one broken
# Exit 2 = at least one degraded (with --strict)
```

```yaml
# .github/workflows/contracts.yml
name: Web Contracts
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
          python-version: '3.12'
      - run: pip install probelab
      - run: probelab check --exit-code --format json
```

## Use Cases

- **OpenCLI / CLI adapter monitoring** — detect when adapters break after site updates
- **Playwright / Puppeteer selector validation** — verify selectors before running full automation
- **Data pipeline contracts** — catch upstream changes before they corrupt your data
- **CI/CD gates** — fail builds when external dependencies change structure

## Comparison

| Tool | Monitors content? | Detects structure drift? | Suggests repairs? | CLI + CI? |
|------|:-:|:-:|:-:|:-:|
| **probelab** | Selectors + schema | DOM diff + baseline stats | 5 strategies | Yes |
| Uptime Kuma | HTTP status only | No | No | No |
| Sentry | Requires instrumentation | No | No | Partial |
| Playwright Test | Manual assertions | No | No | Yes |
| curl + jq scripts | Manual | Manual | No | Manual |

## Contributing

```bash
git clone https://github.com/MinuteMighty/probelab.git
cd probelab
pip install -e ".[dev]"
python -m pytest tests/ -v   # 76 tests
```

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT
