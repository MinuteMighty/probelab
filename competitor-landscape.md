# Competitive Landscape: Browser Agent CLIs + Self-Healing Scrapers

Generated: 2026-04-12
Context: Research for probelab / self-healing MCP server design

---

## Category 1: Browser Agent CLIs (AI agents controlling browsers)

| Product | Stars | Approach | CLI? | Self-healing? | Pricing | Key fact |
|---|---|---|---|---|---|---|
| [Browser Use](https://github.com/browser-use/browser-use) | 78K | Python, natural language goals, reasoning loop per action | Library | No | OSS (you pay LLM costs) | $17M raised, Paul Graham invested |
| [agent-browser](https://github.com/vercel-labs/agent-browser) (Vercel Labs) | 28.9K | Rust CLI, deterministic ref-based targeting (`click @e2`), accessibility tree snapshots | **Yes, CLI-first** | No | OSS | Semantic element selection, batch execution, 4x cheaper than MCP on tokens |
| [Playwright MCP](https://github.com/microsoft/playwright-mcp) | — | Microsoft official, exposes browser via MCP, accessibility tree | MCP server | Has "Healer" agent that auto-patches locators | OSS | Built into GitHub Copilot coding agent |
| [Playwright CLI](https://testcollab.com/blog/playwright-cli) | — | Microsoft, standalone `@playwright/cli` npm package, launched 2026 | **Yes, CLI** | No | OSS | 114K tokens (MCP) vs 27K tokens (CLI) for same task — 4x reduction |
| [Stagehand](https://www.browserbase.com) (Browserbase) | — | TypeScript, extends Playwright, deterministic-first, caches AI actions as replay | Library | Partial (caches working actions) | Token costs + Browserbase hosting | Optimizes for cost over time by converting AI actions to deterministic replay |
| [Skyvern](https://www.skyvern.com) | — | Computer vision + LLM, works on unseen websites, no per-site config | API/Cloud | Yes (vision-based, no selectors) | Transparent monthly pricing | 85.8% WebVoyager, built-in 2FA/CAPTCHA solving |
| [AgentQL](https://www.agentql.com) | — | Query language for the web, makes pages "AI-ready" | Library | Partial (semantic queries) | — | Query language approach, not selector-based |

---

## Category 2: Self-Healing Scraper Frameworks

| Product | Stars | How it heals | CLI? | Pricing | Status |
|---|---|---|---|---|---|
| [Kadoa](https://www.kadoa.com) | — (SaaS) | "Define what, not where" — AI agents maintain deterministic code, re-map extraction on layout change | No (web UI) | SaaS, enterprise | 98.4% accuracy across 3K pages (McGill study). Finance focus. |
| [scrapy-mcp-server](https://github.com/scrapoxy/scrapy-mcp-server) | **16** | MCP server for Scrapy spiders, AI debugs via MCP, generates fix PRs | MCP | OSS | **ARCHIVED Feb 2026**, 4 commits. Dead. |
| [Crawl4AI](https://github.com/unclecode/crawl4ai) | 58K | Pattern-learning algorithms adapt to DOM changes, finds new data locations without human intervention | Library | OSS (AGPL), sponsorship tiers | Hit #1 on GitHub trending. Active. |
| [Browse AI](https://www.browse.ai) | — (SaaS) | Visual point-and-click, AI-powered change detection, auto-adapts robots | No (web UI) | SaaS | Focus on lead gen / social selling |
| [Scrapling](https://cloudnews.tech/scrapling-bets-on-a-self-healing-python-scraping-adaptive-parser-spiders-and-a-unified-api/) | — | Adaptive parser, self-healing Python scraping, unified API | Library | OSS | Python-native |
| [Scrapy-Spider-Autorepair](https://github.com/ViralMehtaSWE/Scrapy-Spider-Autorepair) | — | LLM sidecar repairs broken selectors, tests candidates against live HTML | Library | OSS | Older project |

---

## Category 3: AI Extraction Platforms (scraping-as-a-service)

| Product | Approach | Self-healing? | Pricing |
|---|---|---|---|
| [Firecrawl](https://www.firecrawl.dev) | OSS crawler, outputs clean markdown, schema-based LLM extraction | Partial | $16/mo starter |
| [Diffbot](https://www.diffbot.com) | Computer vision + NLP, "sees" pages like a human, Knowledge Graph | Yes (visual, no selectors) | Enterprise |
| [Apify](https://apify.com) | Marketplace of 24K+ actors, cloud infrastructure | No (manual maintenance per actor) | Free/$39/$199/mo |
| [ScrapeOps](https://scrapeops.io) | Monitoring dashboard, alerts on failures, trend detection | No (monitor only, no repair) | — |
| [Oxylabs](https://oxylabs.io) | Website change monitoring + proxy infrastructure | No (detection only) | Enterprise |

---

## Key Takeaways

### The dead canary: scrapy-mcp-server

The closest thing to what probelab is building — an MCP server for self-healing spider repair. It had the right idea (MCP + AI repair + PR generation). It shipped in late 2025, got 16 stars, and was **archived in February 2026** after 4 commits. Why it died matters. Likely: too narrow (Scrapy-only), no community, no monitoring layer (just repair, not detection).

### The real threat: Kadoa

They've solved self-healing extraction at 98.4% accuracy by eliminating selectors entirely ("define what, not where"). But they're closed-source, enterprise-focused SaaS, not an OSS tool. If you're building for OSS maintainers and indie builders, Kadoa isn't your competition — it's your existence proof that the approach works.

### The interesting ally: agent-browser

Vercel's Rust CLI (28.9K stars) gives AI agents deterministic browser control at 4x lower token cost than MCP. This could be your browser-mode execution layer instead of raw Playwright. The ref-based system (`click @e2`) is more reliable than vision-based approaches.

### Playwright ecosystem convergence

Microsoft now ships three built-in test agents: Planner, Generator, and **Healer** (auto-patches broken locators). The Healer is doing self-healing for test suites — conceptually identical to what you'd do for scraper adapters. This validates the approach but also means Microsoft could expand Healer beyond tests.

### Crawl4AI (58K stars)

Has pattern-learning that auto-adapts to DOM changes. Open source, Python, actively maintained. If they add adapter-fleet management and monitoring, they're your biggest open-source competitor.

---

## Gap Map: Where probelab sits

```
                    Detection    Repair       Browser Mode    Fleet Mgmt
                    ---------    ------       ------------    ----------
probelab (you)         YES       Rule-based    Building...     YES
Kadoa                  YES       AI (98.4%)    Built-in        YES (SaaS)
scrapy-mcp-server      NO        AI+MCP        NO              NO (dead)
Crawl4AI               NO        Pattern-learn  Built-in       NO
agent-browser          NO        NO             YES (CLI)       NO
Playwright Healer      NO        AI             YES             NO (tests only)
ScrapeOps              YES       NO             NO              YES
Browse AI              YES       AI             YES             YES (SaaS)
```

**Probelab's unique position:** The only open-source tool that combines detection (health monitoring with sparklines/timelines) AND fleet management (51-site dashboard) AND is building toward browser-mode compatibility. No one else has the monitoring + repair + fleet view in one open-source package.

**The gap to fill:** Upgrade rule-based repair to LLM-powered, add browser-mode probing, and the product is differentiated.

---

## Sources

- [Kadoa: Self-Healing Web Scrapers](https://www.kadoa.com/blog/autogenerate-self-healing-web-scrapers)
- [Kadoa: How AI Is Changing Web Scraping 2026](https://www.kadoa.com/blog/how-ai-is-changing-web-scraping-2026)
- [scrapy-mcp-server (GitHub, archived)](https://github.com/scrapoxy/scrapy-mcp-server)
- [agent-browser (Vercel Labs)](https://github.com/vercel-labs/agent-browser)
- [Crawl4AI (GitHub)](https://github.com/unclecode/crawl4ai)
- [Building Self-Healing Scrapers with AI (DEV Community)](https://dev.to/viniciuspuerto/when-the-scraper-breaks-itself-building-a-self-healing-css-selector-repair-system-312d)
- [Playwright CLI: Token-Efficient Alternative](https://testcollab.com/blog/playwright-cli)
- [Playwright AI Ecosystem 2026](https://testdino.com/blog/playwright-ai-ecosystem/)
- [Browser Use vs Stagehand (Skyvern)](https://www.skyvern.com/blog/browser-use-vs-stagehand-which-is-better/)
- [Best AI Browser Agents 2026 (Firecrawl)](https://www.firecrawl.dev/blog/best-browser-agents)
- [ScrapeOps](https://scrapeops.io/)
- [Browse AI](https://www.browse.ai)
- [Apify Pricing](https://apify.com/pricing)
- [Crawl4AI vs Firecrawl Comparison](https://www.capsolver.com/blog/AI/crawl4ai-vs-firecrawl)
- [Best Web Extraction Tools for AI 2026 (Firecrawl)](https://www.firecrawl.dev/blog/best-web-extraction-tools)
