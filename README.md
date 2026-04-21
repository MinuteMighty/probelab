# probelab

**Find out what your code depends on. Know when it breaks.**

Your project depends on external web pages and APIs — for data, for links, for services. When they break, you find out from your users. probelab finds out first.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)

---

## Two commands

```bash
pip install probelab
probelab scan
```

```
  Scanning my-project/ ...

  Found 6 external dependencies:

  API Dependencies (2)
  Provider    Source               Env Key
  openai      src/ai.py:3         OPENAI_API_KEY
  stripe      src/billing.py:1    STRIPE_SECRET_KEY

  Web Dependencies (4)
  URL                             Source                    Selectors
  competitor.com/pricing          src/scraper.py:23         .price-card
  docs.stripe.com/api/charges     lib/api_check.py:8       -
  status.aws.com                  .github/workflows/ci.yml -
  myapp.com/health                scripts/deploy.sh:3      -

  6 probes ready to generate.
  Run: probelab scan --accept
```

probelab scans your code and finds every external thing it depends on — URLs in your Python, JavaScript, shell scripts, CI files, config, and docs. API SDKs like OpenAI, Stripe, Anthropic, Replicate, Gemini. CSS selectors in your scraping code. Health check URLs in your CI.

Then it generates monitoring probes for each one. Run `probelab check` daily, and you'll know something broke before your users do.

## The problem (you've had this)

- Your script pulls prices from a competitor's page. They redesigned. Your script returns empty data for three days before you notice.
- Your app uses the OpenAI API. They deprecate a model. Your calls start failing at 2am.
- Your README links to external docs. They restructured the site. Links are 404s. A user files an issue.
- Your CI health check curls an endpoint. The endpoint moves. Your deploy passes but the app is broken.

**In every case: nothing tells you. You find out from users, from blank data, from angry Slack messages.**

## Example: monitor your docs site

```yaml
name: my-docs
description: Make sure the install guide still exists

target:
  type: web
  url: https://docs.myproject.com/install

assertions:
  - type: text_exists
    text: "pip install"
  - type: selector_exists
    selector: "code"
  - type: selector_count
    selector: "h2"
    min: 3
```

This says: "The install page should contain 'pip install', should have `<code>` blocks, and should have at least 3 section headings."

Save it to `~/.probelab/probes/my-docs.yaml`. Run `probelab check`. Done.

## Example: monitor a competitor's pricing page

```yaml
name: competitor-pricing
description: Track if competitor changes pricing tiers

target:
  type: web
  url: https://competitor.com/pricing

assertions:
  - type: text_exists
    text: "Free"
  - type: text_exists
    text: "Enterprise"
  - type: selector_count
    selector: ".pricing-card"
    min: 3
```

If they drop the free tier or add a new plan, you'll know immediately.

## Example: monitor a job board

```yaml
name: company-jobs
description: Alert when new engineering roles posted

target:
  type: web
  url: https://dream-company.com/careers

assertions:
  - type: selector_exists
    selector: ".job-listing"
  - type: text_exists
    text: "Engineering"
```

## What happens when something breaks

probelab doesn't just say "it broke." It tells you _why_:

```
$ probelab check

  Probe               Status     Duration   Failure
  ──────────────────   ────────   ────────   ──────────────
  my-docs              healthy       312ms
  competitor-pricing   broken        891ms   selector_missing
  company-jobs         healthy       445ms

  2 healthy | 1 broken / 3 total
```

```
$ probelab check --verbose

  competitor-pricing broken
    URL: https://competitor.com/pricing
    Duration: 891ms

    Assertions
      ✓ text_exists "Free"
      ✓ text_exists "Enterprise"
      ✗ selector_count .pricing-card >= 3 → got 0

  ╭───────────────────── Failure ──────────────────────╮
  │ selector_missing                                   │
  │ Selector '.pricing-card' not found (0 matches).    │
  │ The page may have been redesigned.                 │
  │ Run: probelab diagnose competitor-pricing           │
  ╰────────────────────────────────────────────────────╯
```

### 9 failure categories

probelab classifies every failure so you know what action to take:

| You see | It means | Do this |
|---|---|---|
| `selector_missing` | A CSS element is gone | Run `probelab diagnose` for fix suggestions |
| `text_missing` | Expected text not on page | Check if the site changed its copy |
| `navigation_error` | DNS failure, HTTP error, site down | Wait and retry, or check the URL |
| `timeout` | Page too slow or element doesn't exist | Increase timeout or check element |
| `auth_expired` | Redirected to login page | Re-login in browser (see CDP mode below) |
| `captcha_detected` | Bot challenge detected | Open URL manually, solve it |
| `url_mismatch` | URL doesn't match expected pattern | Check for redirects |
| `page_changed` | DOM structure changed from baseline | Run `probelab diff` to see what changed |
| `unexpected_redirect` | Redirected to different domain | Check for CDN or config changes |

## Diagnose and fix

When a selector breaks, probelab analyzes the current page and suggests replacements:

```
$ probelab diagnose competitor-pricing

  competitor-pricing -- broken
    Category: selector_missing
    Message: Selector '.pricing-card' not found (0 matches).

  Suggested replacements:
    1. .plan-tier            -> 3 matches (confidence: 78%)
       Fuzzy class match: '.pricing-card' → '.plan-tier'
    2. [data-testid="plan"]  -> 3 matches (confidence: 62%)
       Semantic attribute selector
    3. article.plan          -> 3 matches (confidence: 41%)
       Structural match
```

Update your YAML with the new selector. Run `probelab check` again. Fixed.

## Compare against baseline

probelab saves every successful run. When a check fails, compare against the last good state:

```
$ probelab diff competitor-pricing

  Baseline: 2026-04-15 (healthy)
  Current:  2026-04-19 (broken)

  Changes:
    - .pricing-card: was 3 matches, now 0
    - New element appeared: .plan-tier
```

## Put it in CI

```yaml
# .github/workflows/web-contracts.yml
name: Web Contracts
on:
  schedule:
    - cron: '0 8 * * *'   # every morning
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: pip install probelab
      - run: probelab check --json
```

Commit your probe YAML files to the repo. CI runs them daily. If anything breaks, the job fails.

## Python API: preflight checks for browser agents

If you build with [browser-use](https://github.com/browser-use/browser-use), OpenClaw, or any browser agent, probelab saves you from wasting tokens on broken sites.

**The problem:** browser-use costs $0.02–4.00 per task. If the target site has a CAPTCHA, is down, or changed its selectors, the agent burns tokens failing. You find out after the money is spent.

**The fix:** a $0, 200ms pre-flight check before the agent runs.

```python
from probelab import preflight

# Check before spending tokens
status = preflight("https://www.linkedin.com/jobs", checks=[
    ("selector_exists", ".job-card"),
    ("no_captcha",),
    ("no_login_redirect",),
])

if status.healthy:
    # Site is ready — run the expensive agent
    from browser_use import Agent
    agent = Agent(task="Apply to Senior Engineer jobs", llm=llm)
    await agent.run()  # $0.30+
else:
    print(f"Skipping: {status.failure}")
    # "captcha_detected" or "auth_expired" or "selector_missing"
    # Saved $0.30
```

Works with any agent framework:

```python
from probelab import preflight

# browser-use
status = preflight("https://target.com")

# OpenClaw agent-browser
status = preflight("https://target.com")

# LangChain / CrewAI / AutoGen — same thing
status = preflight("https://target.com")
```

probelab doesn't care what browser tool you use. It answers one question before you start: **"Is this site ready for my agent, or will it waste money failing?"**

### Quick inline checks (no YAML needed)

```python
from probelab import check_url

# One-liner: is this page healthy?
result = check_url("https://news.ycombinator.com", selectors=["tr.athing"])
print(result.status)   # "healthy"
print(result.matches)  # {"tr.athing": 30}

# Check multiple things
result = check_url("https://competitor.com/pricing",
    selectors=[".pricing-card"],
    text=["Free", "Enterprise"],
)
if result.broken:
    print(result.failure)  # "selector_missing: .pricing-card not found"
```

### Diagnose agent failures after the fact

```python
from probelab import diagnose_url

# Agent failed — why?
diagnosis = diagnose_url("https://target.com",
    broken_selector=".old-button",
)
for suggestion in diagnosis.repairs:
    print(f"  Try: {suggestion.selector} ({suggestion.match_count} matches)")
```

## Pages that need login

probelab auto-launches Chrome when a probe needs authentication:

```bash
probelab check probes/zhihu.yaml

  zhihu: auth required — 1 probe(s) need login.

  Open Chrome to log in? [Y/n] → y

  Opening https://www.zhihu.com/ ...
  Log in now. Scan QR code, enter credentials, etc.

  Press Enter when done →

  Re-checking...
  ✓  zhihu   healthy   2481ms
```

One command. No manual Chrome flags.

## Import from OpenCLI

If you use [OpenCLI](https://github.com/jackwener/opencli), import its adapters as probes:

```bash
probelab import-opencli ~/code/opencli    # generates probes from 196 adapters
probelab check                            # test them all
```

## All commands

| Command | What it does |
|---|---|
| `probelab scan [path]` | **Scan your project for external dependencies** |
| `probelab scan --accept` | Scan and write probe files immediately |
| `probelab init` | Create example probe (manual setup) |
| `probelab check` | Run all probes |
| `probelab check myprobe.yaml` | Run one probe |
| `probelab check --verbose` | Show step-by-step details |
| `probelab check --json` | JSON output for CI |
| `probelab show <name>` | Show last result |
| `probelab diff <name>` | Compare against last healthy run |
| `probelab diagnose <name>` | Failure analysis + fix suggestions |
| `probelab login <url>` | Open Chrome, log in, keep session alive |
| `probelab doctor [path]` | Scan + check all dependencies in one step |
| `probelab import-opencli <path>` | Import OpenCLI adapters |

## Probe YAML reference

```yaml
name: my-probe                        # unique name
description: What this checks         # for humans

target:
  type: web
  url: https://example.com/page       # URL to check

steps:                                 # optional: browser actions
  - action: goto
    url: https://example.com/page
  - action: wait_for_text
    text: "Welcome"

assertions:                            # what must be true
  - type: text_exists
    text: "some text"
  - type: selector_exists
    selector: ".my-element"
  - type: selector_count
    selector: "li.item"
    min: 5
  - type: url_matches
    pattern: "example\\.com/page"

outputs:                               # optional: save artifacts
  - type: screenshot
  - type: html                         # needed for 'diagnose'
```

## Install

```bash
pip install probelab            # core (HTTP checks)
pip install probelab[browser]   # + browser for JS-rendered pages and CDP
```

Python 3.11+.

## Contributing

```bash
git clone https://github.com/MinuteMighty/probelab.git
cd probelab
pip install -e ".[dev]"
python -m pytest tests/ -v   # 231 tests
```

## License

MIT
