# TODOS

Items deferred during planning and review. Each has enough context that
picking it up in 3 months won't require archaeology.

---

## 1. Grow heal eval harness from 5 → 20 fixtures

**What:** Expand `tests/healing/eval_cases/` from the 5 Day-0 smoke
fixtures to 20 real-world breakage cases.

**Why:** Blocks user-facing `probelab heal` release. n=5 is statistically
meaningless (one flaky fixture flips the 80% pass rate). The smoke bar
is fine for internal dogfood; the ship bar requires n=20 so the pass-rate
and median-cost numbers mean something.

**Pros:** Heal quality claims become defensible. Calibration data for
the semantic-similarity threshold gets richer. Catches edge cases (auth
redirect, CAPTCHA, DOM structural change) smoke set can't.

**Cons:** 15 more fixture captures. Each needs before.yaml + before.html +
after.html + expected.json. ~2-3 hours per fixture depending on how
much captured state needs sanitizing (PII, auth cookies).

**Context:** The Day-0 five come from the existing OpenCLI adapter audit
(`opencli-adapter-audit.md`) — those are known-broken adapters. For the
additional 15, pull from: (a) your own dogfood probes over a week;
(b) public site changes (GitHub UI refresh, Reddit redesign, etc.);
(c) breakage reports from early users if any.

**Depends on:** Week 1 migration + Week 2 heuristic+LLM heal shipping.
**Blocks:** Public announcement / release tagging past v1.0.0-alpha.N.

---

## 2. Async Anthropic client for parallel heal across probes

**What:** Currently heal is synchronous. When `probelab check --heal`
finds 5 broken probes, they heal serially. With async Anthropic client +
asyncio gather, they could heal in parallel.

**Why:** First user with 20+ probes and a big site redesign will watch
heal run for 10 minutes serially instead of 2 minutes parallel. Bad UX.

**Pros:** 5-10x wall-clock speedup when multiple probes break at once.

**Cons:** More code. Has to respect token budget GLOBALLY across parallel
heals (otherwise budget blown). Error handling more complex.

**Context:** Anthropic Python SDK already has `AsyncAnthropic`. Wrap
`llm_heal` in an async variant, use `asyncio.Semaphore` to cap
concurrency and global token budget. Start with `max_concurrent=3`.

**Depends on:** v1 heal ships and has real users who feel the pain.
**Blocks:** Nothing. Quality-of-life upgrade.

---

## 3. Multi-provider LLM support (OpenAI, Ollama, local models)

**What:** Heal's `llm.py` hardcodes Anthropic client. Abstract behind a
provider interface; add OpenAI and Ollama drivers.

**Why:** Privacy-first users may want Ollama (fully local). OpenAI users
exist. Vendor lock-in is a brand-risk given probelab's "private-first"
positioning.

**Pros:** Matches the private-first thesis more completely. Broader
adoption.

**Cons:** Each provider has different prompt-format quirks (OpenAI
strict JSON mode, Ollama model families with varying YAML-output
quality). Testing matrix grows.

**Context:** Design interface as `class LLMProvider(Protocol)` with
methods `heal(probe, context) -> HealCandidate`. Register via entry
points so third parties can add providers without modifying core.

**Depends on:** v1 heal ships with Anthropic-only and has usage data.
**Blocks:** Nothing.

---

## 4. DRY consolidation: "when selector is broken" logic

**What:** Three modules now have selector-broken logic: `repair.py`,
`diagnosis/classify.py`, `heal/candidates.py`. Consolidate into one
canonical place.

**Why:** Every time the selector-broken behavior needs to change
(new repair strategy, new classification nuance), it changes in three
places. Classic DRY violation.

**Pros:** Single source of truth. New strategies land in one module.
Tests consolidate.

**Cons:** Refactor touches three working files. Risk of regression in
existing `repair` and `classify` users. Needs full test run.

**Context:** Candidate target: `heal/candidates.py` owns candidate
generation; `repair.py::suggest_repairs` becomes a thin wrapper that
formats candidates as SelectorSuggestion for backwards-compat;
`diagnosis/classify.py` keeps classification but imports candidate
generator for its "what could fix this?" hints.

**Depends on:** Heal ships first (don't block the feature on a refactor).
**Blocks:** Nothing.
