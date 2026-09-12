# Architecture — SEO/GEO Audit + Content-Generation Agentic Platform

This document is the foundation-level architecture. `BUILD-SPEC.md` is the contract
(what to build, in what order, with what acceptance tests); this file explains **why
the system is shaped the way it is** so that every later phase makes decisions
consistent with the foundation.

---

## 1. System overview

One platform, two LangGraph pipelines, one seam.

```
                 ┌────────────────────────────────────────────┐
                 │              SHARED INFRASTRUCTURE          │
                 │  state.py · ledger.py · guardrails.py      │
                 │  tools/ · prompts/loader · config.yaml     │
                 └────────────────────────────────────────────┘
                        ▲                          ▲
        ┌───────────────┴───────┐      ┌───────────┴──────────────┐
        │  PIPELINE A — AUDIT   │      │ PIPELINE B — CONTENT GEN │
        │  url (+ GSC export)   │      │ rebuild | net_new        │
        │        │              │      │        │                 │
        │  a0 intake            │      │  c0 intake router        │
        │  a1..a9 ∥ a10 ∥       │      │  L0 research  (∥)        │
        │  a11 synthesis        │      │  L1 strategy             │
        │        │              │      │  L2 outline              │
        │        ▼              │      │  L3 drafting  (fan-out)  │
        │  MasterReport +       │      │  L4 verification (∥)     │
        │  Diagnosis ───────────┼──────▶  L5 assembly             │
        └───────────────────────┘ seam │  L6 critics → gate       │
                                       │  L7 packager             │
                                       └──────────────────────────┘
```

**The single seam:** `Diagnosis` (Pipeline A output) is byte-for-byte the rebuild-mode
intake of Pipeline B. It is a typed contract (`state.Diagnosis`), serialized to
`runs/<ts>/diagnosis.json`, consumed with **no hand edits**. Nothing else crosses
between the pipelines. This is deliberate: it lets each pipeline evolve, be tested,
and be priced independently, and it makes "audit → rebuild" a reproducible artifact
chain rather than a conversation.

## 2. Where quality comes from (the quality spine)

Prompts are replaceable; the spine is not. Quality is enforced by five mechanisms,
all of which live in shared infrastructure and none of which involve a model call:

| # | Mechanism | Module | Enforced at |
|---|-----------|--------|-------------|
| 1 | Typed shared state (the Package), Pydantic-validated | `state.py` | after **every** node (`validate_state`) — fail loud via `StateValidationError` |
| 2 | Append-only Facts Ledger with provenance | `ledger.py` | seeded at L0 (c1), read by every writer, locked values can never be overwritten — only conflicted |
| 3 | Deterministic guardrails (`canonical_verify`, `grounding_check`, `flag_dont_fill`, `fact_diff`, `quantifier_check`, `source_precedence`) | `guardrails.py` | node exits + L6 gates; pure functions, unit-tested, zero LLM calls inside |
| 4 | Writer ≠ verifier separation | graph wiring | L3 drafts, L4 (c13 evidence) verifies; L6 critics judge; no node verifies its own output |
| 5 | Human checkpoints | `interrupt()` + `human_checkpoints` state field | facts no model can know: testimonials, author credentials, legal claims, publish decision |

**Failure philosophy:** a model that doesn't know writes `[VERIFY: …]`, never a
plausible value ("flag, don't fill"). A guardrail that finds a contradiction blocks
and routes back to the **owning node** (every defect names its owner). A conflict
between sources is **surfaced, never auto-resolved** (`source_precedence` returns a
recommendation; a human picks). Route-backs are capped per layer (`route_back_cap: 2`)
and then escalate to a human (`EscalateToHuman`) — no silent infinite loops, no
silently shipped fabrications.

## 3. Data flow and ownership

### 3.1 ContentState (the Package)
A single `TypedDict` flows through Pipeline B. Each node returns **only the keys it
owns** (LangGraph merges partial updates); concurrent branches own disjoint keys, so
parallelism is safe by construction. The 20-field Content Production Package is the
input half; working artifacts (outline, sections, draft, schema) accumulate; the
quality spine fields (`facts_ledger`, `verify_list`, `conflicts`, `route_back_count`,
`human_checkpoints`) are append-only and shared.

### 3.2 Facts Ledger lifecycle
1. **Seed** — c1 (rebuild) verifies every diagnosis claim against canonical sources via
   `canonical_verify` and writes `Fact`s; cold mode seeds from canonical pages in L0.
2. **Lock** — once a fact id has a `verified` value, `add()` with a different value
   does not overwrite: the fact flips to `status: "conflict"` with both values listed,
   which downstream gates treat as a blocker until a human resolves it.
3. **Cite** — writers reference facts inline as `(fact:engines-count)`; `grounding_check`
   and `quantifier_check` key off these refs.
4. **Diff** — `fact_diff` runs at L6 with per-fact `claim_pattern` matchers, so a draft
   saying "nine AI engines" against a locked `engines-count = 4` is a deterministic
   blocker, not a judgment call.

### 3.3 Run artifacts
Every run writes `runs/<ts>/`: per-node state snapshots, `ledger.json`,
`package_out.json|md`, `runlog.md` (inputs-summary / output-summary / guardrail
results per node, plus per-node cost & latency from Phase 5). The run directory is
the unit of reproducibility, resume (`--resume`), and eval.

## 4. Graph topology

### Pipeline A (audit)
`a0 → [a1 a2 a3 a4 a5 a6 a7 a8 a9 a10] (parallel) → a11`
- a10 depends only on the GSC export, so it joins the parallel fan-out.
- a5 (SERP) and a6 (authority) must degrade **honestly**: stubbed tool ⇒
  `confidence: "stub"`; no off-page API ⇒ `"not-assessed"`. Fabricated findings are
  a spec violation, not a fallback.
- a11 is the only synthesizer; every defect it emits names the content node that owns
  the fix — that is what makes the seam actionable.

### Pipeline B (content)
```
c0 → [ c1 · c2 · (c3→c4→c5) · c6 ]            L0 research (parallel)
   → c7 (strategist)                            L1
   → c8 (brief) → c9 (outline)                  L1/L2
   → [ c10 · c11×N (fan-out per section) · c12 ] L3 drafting (parallel)
   → [ c13 · c14 · c15 ]                        L4 verification (parallel)
   → c16 (editorial merge)                      L5
   → [ c17 · c18 ]                              L5 (parallel)
   → [ c19 · c20 · (c21 rebuild-only) ]         L6 critics (parallel)
   → gate → c22 (packager)                      L7
```
- **Fan-out (c11):** one drafting task per outline section; each sees only its section
  spec + ledger + voice. This bounds context, parallelizes the slowest stage, and
  prevents cross-section fact drift (the editorial merge at c16 may introduce **no**
  new facts — enforced by token-level new-number detection).
- **Route-back:** an L6 failure routes to the failing defect's owning layer,
  increments `route_back_count[layer]`, and escalates at the cap. Implemented in
  `graphs/content_graph.py:apply_route_back`.

## 5. Model tiering

Two tiers from `config.yaml`, never hard-coded in nodes:
- `strong` (`claude-sonnet-4-6`) — judgment-heavy: c7 strategist, c13 evidence,
  c19/c20/c21 critics, a11 synthesis.
- `fast` (`claude-haiku-4-5-20251001`) — volume work: outline, hook, section drafting,
  FAQ, editorial, most audit analyzers.

The critic being on the strong tier while drafters are on the fast tier is the
economic expression of writer ≠ verifier. Budgets (`max_cost_usd_per_page: 3.0`,
`max_minutes_per_page: 15`) are enforced per run and reported by the eval harness.

## 6. Module boundaries (who may do what)

| Module | May | May NOT |
|---|---|---|
| `guardrails.py` | regex/string/number analysis | call a model, mutate state, do I/O |
| `ledger.py` | append facts, mark conflicts | overwrite a value, delete a fact |
| `nodes/*` | call models via prompt loader, call tools, return owned keys | mutate `facts_ledger` directly, write keys they don't own |
| `tools/*` | network I/O with timeout+retry | call models |
| `graphs/*` | wiring, validation calls, route-back, interrupts | business logic |
| `eval/*` | run pipelines, score, seed errors | relax a guardrail to pass |

**Never build:** auto-publish, CMS write access, fabricated reviews/aggregateRating,
auto-resolution of source conflicts.

## 7. Evaluation as a gate, not a report

Phase 2 is a GO/KILL gate: the rubric (10 deterministic checks, 0/1/2 each) must reach
≥85% of the gold package's score, and **all 6 seeded poisons must be caught** — each
seed is a real failure mode observed in manual runs (fabricated engine counts, unsourced
stats, unpermissioned testimonials, dropped keep-list items, conflicting canonicals,
sibling-product scope creep). The rule of repair is fixed: rubric shortfall ⇒ fix
prompts; a seed shipping silently ⇒ stop everything and fix guardrails.

## 8. Decision log

| Decision | Rationale |
|---|---|
| TypedDict + Pydantic mirror (not Pydantic-only state) | LangGraph merges plain dicts cheaply; validation is explicit at hand-offs where it matters |
| Guardrails are pure functions | unit-testable in ms, no flakiness, no cost; "the functions are the product" |
| Ledger conflicts instead of overwrites | provenance survives; a second source disagreeing is information, not noise |
| `(fact:id)` inline citation convention | makes grounding machine-checkable with a regex instead of an LLM judge |
| Stub tools return `{"stub": true}` and nodes propagate `confidence: "stub"` | honest degradation beats fabricated SERP data |
| CLI + run directories, no UI/CMS | reproducibility first; publishing stays a human act |
| SQLite checkpointer from Phase 3 | resume + audit-trail without infra; in-memory is enough to prove the walking skeleton |

## 8b. Site-level intent boundary (L−1: link, don't host)

Single-page completeness is a trap: optimizing each page to be "maximally
complete" makes siblings cannibalize each other. The fix is one site-level input
and one deterministic gate.

- **Input:** a `cluster_map` (`cluster_map.py`) — the site's pillar/spoke
  topology, each entry declaring an intent and the one URL that owns it. Supplied
  per account (`account.yaml → cluster_map`) or per run (`inputs.json`); absent ⇒
  **single-page mode** (no constraints — every existing run is unaffected).
- **Resolution (c2, L0):** the upgraded Cannibalization & Intent Guard resolves
  this page's `page_intent` from the map, and for each planned subtopic emits a
  host-vs-link verdict, accumulating sibling-owned intents into `delegate_list`.
- **Enforcement:** `intent_boundary_check(outline, cluster_map, page_intent,
  current_url)` is the **cluster-level sibling of `fact_diff`** — where `fact_diff`
  stops a page contradicting the facts, this stops it *trespassing* on a sibling's
  intent. It runs at **c9** (outline gate, inverse coverage check) and is
  re-checked at **c19** (blocker → route back to c9 → convert the section to an
  internal link). Pure, no model calls, unit-tested.

A section is allowed when it covers the page's own intent or an intent this URL
owns; a section whose intent another URL owns is a blocker to delegate. Novel,
unowned intents are free to host — the gate constrains trespassing, not coverage.

## 8c. Intent governance (v2: every page has an intent contract)

The deepest quality lever is whether a page even *matches the intent* its buyers
have — a commercial feature page that explains a concept ranks but never converts,
and stuffing sibling intents cannibalizes the cluster. v2 governs this with one
shared object and deterministic gates on both pipelines.

- **`intent_contract`** (`intent.py`): page_type → primary_intent_type +
  job_statement, owned vs delegated query classes (from the cluster_map), and the
  page's own **GSC head queries** bucketed by `classify_intent`. Built by c2 in
  content mode; **emitted onto the Diagnosis by audit a11** so the content pipeline
  inherits it across the seam. `governed` is True only when a cluster_map and/or
  GSC data is present — without them the page runs single-page and the intent
  gates are no-ops (every legacy run is unchanged).
- **New deterministic guardrails:** `classify_intent(query)` (commercial /
  informational / transactional / navigational — lexical, the load-bearing
  function), `mirror_score(copy, head_queries)` (fraction of commercial head
  queries the copy mirrors), and `intent_fit_check(draft, contract, h1)` (delivered
  intent must sell not explain · H1 carries the commercial keyword · mirror ≥ 60% ·
  every delegated class is linked out).
- **Audit (Pipeline A):** **a4b Intent-Match Auditor** classifies delivered intent
  and head-query coverage; **a10** buckets GSC queries by intent type and surfaces
  commercial striking-distance queries; **a11** adds Intent-Fit + head-query
  mirroring to the scorecard and tags each off-intent defect fix-here vs delegate.
- **Content (Pipeline B):** c7/c11 receive the contract + must-mirror buyer
  vocabulary; **c19** runs `intent_fit_check` + `intent_boundary_check` as blockers
  (route back to the owning layer); **c20** is the media gate — a visual page type
  with zero assets fails (G6).

This is the same philosophy as the rest of the spine: the model drafts, but
deterministic, model-free functions decide fit — `classify_intent` and
`mirror_score` are unit-tested and the gate produces its own pass/fail evidence.

## 8a. Page-type structure contracts

`page_type` is not just a label — each type carries a **structure contract**
(`page_profiles.py`) that flows through the pipeline:

| page_type | required blocks (abridged) | schema @types | budget |
|---|---|---|---|
| feature | problem · how-it-works · capabilities · differentiators · proof · FAQ · CTA | WebPage, SoftwareApplication, FAQPage | 1400–1800 |
| comparison | verdict · **at-a-glance table** · criteria · head-to-head · pros/cons · who-should · FAQ | WebPage, FAQPage | 1500–2200 |
| guide | summary · prerequisites · **step-by-step** · examples · mistakes · FAQ | WebPage, HowTo, FAQPage | 2000–3200 |
| blog-listicle | intro · selection criteria · ranked items · summary · FAQ | WebPage, ItemList, FAQPage | 1800–2600 |
| glossary | **definition (≤60w)** · attributes · how-it-works · examples · related · FAQ | WebPage, DefinedTerm, FAQPage | 800–1400 |
| landing | hero value prop · benefits · social proof · how-it-works · CTA | WebPage | 600–1200 |

Enforcement points (the contract, not a prompt suggestion):
- **c8** seeds `brief["structure"]` from the profile and re-merges any required
  block the model dropped — the brief can never lose a block.
- **c9** is told the required blocks and records which section covers each.
- **c18** picks JSON-LD @types from the profile (glossary→`DefinedTerm`,
  feature→`SoftwareApplication`, guide→`HowTo`, listicle→`ItemList`).
- **c20** deterministically flags required blocks absent from the draft
  (severity `major` — visible, tunable to blocker once prompts are tuned).

Word budgets defer to `config.yaml` where defined, so the two never diverge.

## 9. Multi-domain workspaces

The pipelines are account-agnostic by design — every run is driven entirely by its
inputs. The workspace layer (`workspaces.py`) makes those inputs durable per domain,
GSC-property style:

```
workspaces/<domain>/
├── account.yaml        # canonical sources, audience, precedence, sitemap, gsc mode
├── brand_assets.json   # differentiators, author, permissioned testimonials
├── gsc/                # this domain's GSC export files (mode: export)
└── runs/               # this account's audit + content runs
```

- `run.py account add|list|show <domain>` manages accounts; adding one is pure
  configuration, no code.
- `--account <domain>` on `audit`/`content` fills canonical sources, brand assets,
  audience, precedence, and the newest GSC export; explicit CLI flags override.
- Isolation is structural: each account has its own ledger, runs, assets, and
  budgets — facts from one domain can never leak into another's content
  (pinned by `tests/test_workspaces.py`).
- `gsc.mode: export` is live (drop export ZIPs in `gsc/`); `mode: api` is reserved
  in the schema for a per-domain OAuth upgrade and fails loudly until built.
- `SEO_WORKSPACES_DIR` relocates the whole tree (tests, deployments).
- `workspaces/` is gitignored — it is client data, not platform code.

## 10. Current status & known gaps

Phase status is tracked in `CLAUDE.md`. The reference assets named in BUILD-SPEC §1/§8/§9
(design docs, prompt kit, gold files, page-runs) were **not present in this repository**
at Phase 0; prompts in `prompts/` are authored v1 stand-ins and `eval/gold/` documents
exactly which files the owner must supply before the Phase 2 gate can run.
