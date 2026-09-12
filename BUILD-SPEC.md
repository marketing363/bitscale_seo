# BUILD DOC — SEO/GEO Audit + Content-Generation Agentic Platform
**Audience: Claude Code.** This is the implementation spec. Build exactly what is described, in the phase order given, passing each phase's acceptance tests before starting the next. Where this doc says [VERIFY-WITH-OWNER], stop and ask the human instead of inventing a value.
---
## 1. WHAT YOU ARE BUILDING
One platform, two LangGraph pipelines sharing infrastructure:
- **Pipeline A — AUDIT**: input = a live URL (+ optional GSC export) → output = a Master Audit Report + a structured `diagnosis` object.
- **Pipeline B — CONTENT GENERATION**: two entry modes —
  - **rebuild** (warm): input = Pipeline A's `diagnosis` + human assets → improved page,
  - **net_new** (cold): input = a seed keyword + business context + canonical sources + brand assets → new page from scratch.
- The two pipelines connect at exactly one seam: `AuditReport.diagnosis` maps onto the rebuild-mode intake of Pipeline B.
The platform's quality does NOT come from the prompts. It comes from:
1. a **typed shared state** (the Package) validated at every hand-off,
2. an **append-only Facts Ledger** with provenance,
3. **deterministic guardrail functions** run at node exits and QA gates (`canonical_verify`, `grounding_check`, `flag_dont_fill`, `fact_diff`, `source_precedence`),
4. **writer ≠ verifier** separation,
5. **human checkpoints** for facts no model can know (testimonials, author credentials, legal claims, publish).
Background design docs (same folder, read them before coding): `audit-and-content-platform-build-spec.md` (platform overview), `content-generation-pipeline-v3.md` (agent rosters + concurrency rationale), `content-pipeline-build-and-validation-playbook.md` (staged validation strategy), `content-generation-pipeline-kit.md` (the agent prompt texts — copy these into `prompts/`).

> **REPO NOTE (added at Phase 0):** the background design docs and gold files listed above were NOT present in this repository when Phase 0 was built. See `CLAUDE.md` → "Missing reference assets" for what is blocked on them. Prompts in `prompts/` were authored fresh as v1 and must be reconciled against `content-generation-pipeline-kit.md` when the owner supplies it. [VERIFY-WITH-OWNER]
---
## 2. TECH STACK (fixed decisions — do not substitute)
- Python 3.11+, **LangGraph** (≥1.0) for both graphs. Typed state via `TypedDict` + Pydantic v2 validation at hand-offs.
- **Anthropic SDK** for model calls. Two model tiers, set in `config.yaml`:
  - `MODEL_STRONG` (strategy, critic, evidence) — default `claude-sonnet-4-6`
  - `MODEL_FAST` (drafting, outline, FAQ, editorial) — default `claude-haiku-4-5-20251001`
- Checkpointing: in-memory for Phase 1; SQLite (`langgraph.checkpoint.sqlite`) from Phase 3.
- CLI only. No web UI, no CMS integration, no auth. `rich` for console output is fine.
- HTTP: `httpx` with 20s timeout + 2 retries. HTML parsing: `selectolax` or `beautifulsoup4`.
- Tests: `pytest`.
---
## 3. REPOSITORY LAYOUT (create exactly this)

```
seo-geo-platform/
├── config.yaml                  # models, budgets, thresholds, route-back caps
├── run.py                       # CLI entrypoint (see §10)
├── state.py                     # ALL TypedDicts + Pydantic validators
├── ledger.py                    # FactsLedger class (append-only)
├── guardrails.py                # the 5 deterministic functions (§6)
├── graphs/
│   ├── audit_graph.py           # Pipeline A wiring
│   └── content_graph.py         # Pipeline B wiring
├── nodes/
│   ├── audit/                   # a0_intake.py … a11_synthesis.py
│   └── content/                 # one file per agent (see §5 roster ids)
├── prompts/
│   ├── audit/                   # one .md per audit agent
│   └── content/                 # one .md per content agent (from the kit file)
├── tools/
│   ├── fetch.py                 # fetch_rendered(url) -> {html, text, meta, headings, images, links, jsonld}
│   ├── serp.py                  # serp_search(query) -> organic results + PAA  (stub in Phase 1, see §7)
│   ├── gsc.py                   # parse_gsc_export(zip_or_csv_path) -> queries/pages/trend dataframes
│   └── validators.py            # validate_jsonld(html), check_links(html, base_url), image_seo_audit(html)
├── eval/
│   ├── rubric.py                # score_output(package_out, gold) -> per-item 0/1/2 + total
│   ├── seeded_errors.py         # the 6 poisoned inputs (§9)
│   ├── gold/                    # copy the 4 gold files here (§9)
│   └── run_eval.py
└── tests/
    ├── test_guardrails.py
    ├── test_ledger.py
    ├── test_state_validation.py
    └── test_routeback.py
```

---
## 4. STATE (`state.py`) — write these types verbatim, then extend only additively

```python
from typing import TypedDict, Literal, Optional
from typing_extensions import NotRequired
class Fact(TypedDict):
    id: str                      # slug, e.g. "engines-count"
    claim: str                   # human-readable claim
    value: str                   # the locked value, e.g. "4 (ChatGPT, Claude, Perplexity, Google AI Overviews)"
    source_url: str
    verified_by: str             # node id that verified it
    status: Literal["verified", "VERIFY", "conflict"]
    conflict_values: NotRequired[list[str]]   # populated when status == "conflict"
class Defect(TypedDict):
    description: str
    owning_step: str             # node id that must fix it
    severity: Literal["blocker", "major", "minor"]
    fix: str
class Diagnosis(TypedDict):      # Pipeline A output == Pipeline B rebuild input
    url: str
    page_type: Literal["feature", "blog-listicle", "guide", "comparison", "landing", "glossary"]
    primary_query: str
    scorecard: dict[str, int]    # check name -> 0|1|2
    defects: list[Defect]
    gap_entity_matrix: dict      # {"missing_entities": [...], "missing_subtopics": [...], "competitor_advantages": [...]}
    performance: NotRequired[dict]  # from GSC: impressions, clicks, ctr, position, striking_distance_queries, aio_zero_click_share
    root_causes: list[str]
    keep_list: list[str]         # things the page does WELL — generation must not drop these
class ContentState(TypedDict):
    # routing
    mode: Literal["rebuild", "net_new"]
    page_type: str
    target_url: NotRequired[str]
    # ---- the 20-field Content Production Package ----
    primary_keyword: str
    keyword_cluster: NotRequired[list[dict]]      # [{term, volume, kd, intent}] — cold only
    intent: NotRequired[str]
    serp_feature_targets: NotRequired[list[str]]
    serp_analysis: NotRequired[dict]
    gap_entity_matrix: NotRequired[dict]
    brief: NotRequired[dict]
    research_dossier: dict                        # [HUMAN] may be {}
    brand_assets: dict                            # [HUMAN] {differentiators, testimonials, author, screenshots}
    unique_insight: NotRequired[str]
    cluster_context: NotRequired[dict]
    brand_voice: NotRequired[dict]
    audience: str
    geo: NotRequired[str]
    constraints: NotRequired[dict]
    competitors: NotRequired[list[str]]
    failure_modes: NotRequired[list[str]]         # rebuild only (from diagnosis)
    keep_list: NotRequired[list[str]]             # rebuild only — MUST survive to output
    success_metric: NotRequired[dict]
    canonical_sources: list[str]                  # REQUIRED both modes
    source_precedence: list[str]                  # default ["owner", "docs", "feature_page", "marketing", "audit"]
    media_plan: NotRequired[list[dict]]
    legal_guardrails: NotRequired[dict]
    a11y_perf_budget: NotRequired[dict]
    # ---- working artifacts ----
    outline: NotRequired[dict]
    sections: NotRequired[dict[str, str]]
    faq: NotRequired[list[dict]]
    draft: NotRequired[str]
    schema_jsonld: NotRequired[dict]
    package_out: NotRequired[dict]
    # ---- quality spine ----
    facts_ledger: list[Fact]                      # append-only; only ledger.py mutates
    verify_list: list[str]
    conflicts: list[dict]
    critic_report: NotRequired[dict]
    route_back_count: dict[str, int]              # layer -> count; cap from config (default 2)
    human_checkpoints: list[str]                  # accumulating list of [HUMAN] asks
```

Validation rule: write a Pydantic model mirroring each TypedDict and a `validate_state(state, after_node: str)` helper. Call it in the graph after EVERY node; on failure raise `StateValidationError(node, errors)` — never silently continue.
---
## 5. NODE ROSTERS
### 5a. Pipeline A — audit nodes (`nodes/audit/`)
Each node = `def run(state) -> dict` returning only the keys it owns. All read `state["page"]` (output of A0).
| id | file | job | output keys |
|---|---|---|---|
| a0_intake | a0_intake.py | fetch+render URL via tools/fetch; parse GSC export if provided; classify page_type + primary_query | page, page_type, primary_query, gsc |
| a1_technical | … | canonical, robots, status, sitemap presence, mobile viewport, render issues | tech_findings |
| a2_onpage | … | title/meta lengths, H1 count, heading hierarchy, keyword coverage vs primary_query, internal links | onpage_findings |
| a3_content | … | does it answer the query in first ~60 words; depth; freshness; readability; Information Gain hypotheses | content_findings |
| a4_geo | … | schema types present+valid (tools/validators), entity coverage, citable chunks, FAQ/PAA readiness | geo_findings |
| a5_serp | … | top-10 read via tools/serp; winning format; gap_entity_matrix; SERP features | serp_findings, gap_entity_matrix |
| a6_authority | … | OFF-PAGE: backlink/brand-mention signals. Phase 1: emit "not-assessed" honestly (no API). | authority_findings |
| a7_eeat | … | author present? credentials? Person/Org/Review schema? trust signals | eeat_findings |
| a8_ux | … | CTA presence, demo/placeholder data detection ("Acme", "Globex", "lorem"), conversion path | ux_findings |
| a9_a11y_perf | … | alt coverage, heading order, base64 images, page weight, hero lazy-load check | a11y_findings |
| a10_analytics | … | GSC analysis: CTR vs expected-by-position; **AIO zero-click detection rule**: if impressions at pos≤10 have CTR < 0.1%, flag "likely AI-Overview citations — CTR is structurally suppressed; judge on AI-citation share instead"; striking-distance queries (pos 8–20, impressions desc) | performance |
| a11_synthesis | … | merge all findings → scorecard, defects (each tagged with owning content node), root_causes, keep_list, the `Diagnosis` object | diagnosis, master_report_md |
Concurrency: a0 → **[a1..a9 parallel]** + a10 (parallel, needs only gsc) → a11. a5 needs serp tool; if the tool is stubbed it must mark its findings `confidence: "stub"` rather than fabricate.
### 5b. Pipeline B — content nodes (`nodes/content/`)
| id | layer | guardrail at exit |
|---|---|---|
| c0_intake_router | L0 | HALT if `canonical_sources` empty or (`net_new` and `brand_assets` empty) → raise HumanInputRequired |
| c1_source_reconciler | L0 | rebuild only: re-verify every diagnosis claim against canonical via `canonical_verify`; seed the Facts Ledger |
| c2_cannibalization | L0 | fetch sitemap; flag overlapping URLs (Phase 3) |
| c3_kw_intent_mapper | L0 cold | tools/serp; "unknown" allowed, fabricated volumes NOT |
| c4_serp_landscape | L0 cold | dominant format + serp_feature_targets |
| c5_competitor_content | L0 cold | gap_entity_matrix from real fetched competitor pages |
| c6_brand_loader | L0 | voice + asset inventory from brand_assets + canonical pages |
| c7_strategist | L1 | `grounding_check`: every claimed differentiator in unique_insight must map to a verified Fact. **HARD RULE: may not drop any item in keep_list or any canonical-grounded differentiator — dropping one is a gate failure** |
| c8_brief_compiler | L1 | emits brief incl. title/meta directions, structure, word budget, media_plan, UI limits (H1≤60 chars, meta≤155, CTA≤5 words) |
| c9_outline | L2 | entity-coverage map: EVERY entity in gap_entity_matrix + keep_list assigned to a section; unassigned → fail |
| c10_hook | L3 | answer-first lead 40–60 words; `flag_dont_fill` |
| c11_section_drafter | L3 | **fan-out one task per outline section**; each sees only (its section spec, ledger, voice); `flag_dont_fill` |
| c12_faq | L3 | PAA-sourced; dedup vs body; no new stats |
| c13_evidence | L4 | the verifier (≠ writer). Resolve every `[VERIFY:]`: web lookup via tools; verdict per item: resolved(value+source) / cut / keep-flagged. `canonical_verify` on all product claims. Never fabricate a citation. |
| c14_eeat | L4 | author/testimonial/Person/Org **only from brand_assets**; missing → append to human_checkpoints |
| c15_media | L4 | manifest: descriptive filename, alt of the ACTUAL asset, dims, hero eager; generate diagrams as SVG strings; screenshots → [HUMAN]; **zero base64** |
| c16_editorial | L5 | merge sections; apply c13 verdicts; introduce NO new facts (assert: token-level new-number detection — any digit-bearing claim absent from ledger+sections → fail) |
| c17_a11y_perf | L5 | alt coverage 100%, heading order, no data: URIs, hero fetchpriority |
| c18_schema | L5 | JSON-LD @graph; FAQ text == visible text; NO aggregateRating/Review unless brand_assets contains approved reviews |
| c19_critic | L6 | `fact_diff(draft, ledger)`; entity-coverage re-check; quantifier check ("every/all/only/first" must match a verified Fact); answer-first; verdict pass/fail + owning node per failure |
| c20_render_critic | L6 | H1/meta/CTA lengths; named-entity counts in copy match ledger counts; image manifest honored |
| c21_comparison_judge | L6 rebuild | new vs live page: must beat on scorecard, must not have dropped keep_list |
| c22_packager | L7 | package_out: {title_variants(3), meta, full_copy, schema_jsonld, media_manifest, internal_links, qa_checklist, human_checkpoints, measurement_plan} |
Concurrency map (content): c0 → [c1,c2,(c3→c4→c5),c6 parallel] → c7 → c8 → c9 → [c10, c11×N, c12 parallel] → [c13,c14,c15 parallel] → c16 → [c17,c18 parallel] → [c19,c20,(c21) parallel] → gate → c22. Route-back: critic failure routes to the owning node's layer; increment `route_back_count[layer]`; at cap (config, default 2) raise `EscalateToHuman`.
---
## 6. GUARDRAILS (`guardrails.py`) — deterministic, unit-tested, NO model calls inside

```python
import re
from dataclasses import dataclass
@dataclass
class Violation:
    kind: str; detail: str; severity: str = "blocker"
VERIFY_PAT = re.compile(r"\[VERIFY[^\]]*\]")
QUANTIFIERS = re.compile(r"\b(every|all|only|first|always|never|guaranteed)\b", re.I)
def flag_dont_fill(text: str, ledger) -> list[Violation]:
    """A number/stat in text that maps to no verified Fact and carries no [VERIFY] flag is a violation."""
    out = []
    for m in re.finditer(r"(\d[\d,.]*\s*(?:%|million|billion|M|B|x|×)|\$\d[\d,.]*)", text):
        span = text[max(0, m.start()-80): m.end()+80]
        if VERIFY_PAT.search(span):            # flagged — OK
            continue
        if not ledger.supports_number(m.group(0)):
            out.append(Violation("unsourced_number", f"'{m.group(0)}' near: …{span.strip()[:90]}…"))
    return out
def grounding_check(claims: list[str], ledger) -> list[Violation]:
    """Every strategic claim must cite a ledger fact id like (fact:engines-count)."""
    out = []
    for c in claims:
        ids = re.findall(r"\(fact:([a-z0-9\-]+)\)", c)
        if not ids:
            out.append(Violation("ungrounded_claim", c[:140]))
        for fid in ids:
            f = ledger.get(fid)
            if f is None or f["status"] != "verified":
                out.append(Violation("unverified_fact_ref", f"{fid} in: {c[:100]}"))
    return out
def canonical_verify(claim: str, fetched_sources: dict[str, str]) -> str:
    """Return 'verified' | 'unverified' | 'conflict'. fetched_sources = {url: page_text},
    MUST be the right source class (docs/feature page before marketing). Deterministic:
    substring/normalized-number containment, no LLM. The CALLER (c1/c13) may use a model
    to extract candidate values, but the final containment check happens here."""
    ...
def fact_diff(artifact_text: str, ledger) -> list[Violation]:
    """Any number/name in artifact contradicting a locked Fact value -> blocker.
    Implement per-fact matchers: each Fact may define a regex in 'claim_pattern'
    (e.g. engines-count defines r'(\\d+)\\s+(?:major\\s+)?AI engines' and the captured
    number must equal the locked value)."""
    ...
def quantifier_check(artifact_text: str, ledger) -> list[Violation]:
    """Every QUANTIFIERS hit must sit within 120 chars of a (fact:...) ref or a ledger-supported value."""
    ...
def source_precedence(conflict: dict, precedence: list[str]) -> dict:
    """NEVER auto-picks. Returns {'action': 'surface', 'options': [...], 'recommended': highest-precedence}."""
    ...
```

**§6a — Intent boundary (cluster-level, added post-Phase-5).** `intent_boundary_check(outline, cluster_map, page_intent, current_url) -> list[Violation]`:
the cluster-level sibling of `fact_diff`. Given the site's `cluster_map` (pillar/spokes,
each intent → owning URL; `cluster_map.py`), any outline section whose intent is owned by a
*different* URL is a blocker to delegate ("link, don't host"). Deterministic, no model calls.
Runs at c9 (outline) and c19 (re-check → route back). Falsy `cluster_map` ⇒ single-page mode
(no violations). c2 is the L−1 "Cannibalization & Intent Guard": it resolves `page_intent` +
`delegate_list` and emits per-subtopic host/link verdicts. New optional state field:
`cluster_map` (both modes; supplied via `account.yaml` or `inputs.json`).
Mandatory test (case 7): a brand-monitoring page with "how to choose" + "vs social listening"
sections, against a cluster map where siblings own those intents → both flagged `intent_trespass`.

**§6b — Intent governance (architecture v2).** Three new deterministic guardrails:
`classify_intent(query) -> commercial|informational|transactional|navigational` (lexical, load-bearing);
`mirror_score(copy, head_queries) -> 0..1` (fraction of commercial head queries the copy mirrors);
`intent_fit_check(draft, intent_contract, h1) -> [Violation]` (delivered-intent must sell not explain,
H1 carries the commercial keyword, mirror ≥ 0.6, every delegated class linked). New shared object
`intent_contract` (`intent.py`): page_type→primary_intent_type+job_statement, owned/delegated query
classes (from cluster_map), and GSC `head_queries` bucketed by intent. `governed` only when cluster_map
and/or GSC present (else single-page no-op). Audit: a4b Intent-Match Auditor, a10 intent/striking-distance
buckets, a11 emits the contract on the Diagnosis + adds Intent-Fit & head-query-mirroring to the scorecard.
Content: c2 builds the contract, c7/c11 mirror buyer vocabulary, c19 enforces intent_fit + intent_boundary,
c20 is the media gate (a visual page type with zero assets FAILS). Mandatory tests: (a) 'what is X'
classifies informational and is delegated from a feature page; (b) a feature H1 lacking the commercial
keyword fails Intent-Fit; (c) a sibling-owned section converts to a link; (d) mirror_score < 0.6 fails.

`ledger.py`: class `FactsLedger` wrapping `list[Fact]` — `add(fact)` (append-only; adding an id that exists with a different value auto-creates a `conflict` entry instead of overwriting), `get(id)`, `supports_number(s)` (normalized numeric containment over verified facts), `to_markdown()`.
**These functions are the product.** Write `tests/test_guardrails.py` FIRST with these mandatory cases (all from real failures in this project):
1. `fact_diff` catches draft saying "nine AI engines" when ledger locks engines-count=4 → blocker.
2. `fact_diff` catches "200 million weekly" when ledger locks chatgpt-wau="900 million (OpenAI, Feb 2026)".
3. `flag_dont_fill` catches an unflagged "67% of enterprise teams" with empty ledger; passes when written as "[VERIFY: 67%…]".
4. `grounding_check` rejects a differentiator with no `(fact:…)` ref.
5. `quantifier_check` flags "across every AI engine" when engines-count=4.
6. `source_precedence` never returns an auto-pick.
---
## 7. TOOLS (`tools/`)
- `fetch.py` — `fetch_rendered(url)`: httpx GET, parse → `{html, text, title, meta_description, headings: [(level,text)], images: [{src,alt,loading}], links, jsonld: [parsed blocks], canonical}`. No JS rendering in Phase 1 (note it as a limitation in output).
- `serp.py` — interface `serp_search(query) -> {organic: [{title,url,snippet}], paa: [str]}`. Phase 1: a stub that loads fixtures from `eval/fixtures/serp/*.json` and returns `{"stub": True, ...}`; nodes must propagate `confidence: "stub"`. Phase 3: wire a real provider behind the same interface (env var `SERP_API_KEY`; provider per config).
- `gsc.py` — parse the standard GSC ZIP export (Queries.csv, Pages.csv, Chart.csv, Countries.csv) → dicts; compute: totals, CTR by position bucket, expected-clicks model (simple CTR curve: pos1 28%, 2 15%, 3 10%, 4–10 5%, 11–20 1.5%), striking-distance list, zero-click anomaly score.
- `validators.py` — `validate_jsonld(html)` (parse every ld+json block; JSON validity + required keys for FAQPage/SoftwareApplication/Person), `check_links`, `image_seo_audit(html)` (alt coverage, base64 count, hero loading attr, filename descriptiveness heuristic).
---
## 8. PROMPT HANDLING
- One `.md` per node in `prompts/`. Source text: lift each agent's prompt from `content-generation-pipeline-kit.md` and the audit prompts from `claude-chrome-manual-run-playbook.md` (steps map ≈1:1); adapt pronouns to non-interactive use.
- Loader: `load_prompt(node_id, **vars)` — `str.format` substitution; missing var = hard error.
- EVERY content prompt must end with this block (append programmatically, don't trust the file):

```
RULES (non-negotiable):
- Assert only facts present in the FACTS LEDGER below or directly quoted from CANONICAL SOURCES.
- A missing fact must be written as [VERIFY: what is missing]. Never invent a number, source, feature, credential, quote, or URL.
- When citing a ledger fact inline, append its id like (fact:engines-count).
- Output ONLY the JSON object matching the schema given. No prose around it.
FACTS LEDGER:
{ledger_markdown}
```

- Model output parsing: ask for JSON, strip code fences, `json.loads`, on failure retry once with the error appended, then raise.
---
## 9. EVAL HARNESS (`eval/`)
Gold files (copy from this folder into `eval/gold/`): `siftly-ai-brand-monitoring.html`, `siftly-chatgpt-visibility.html`, `page-runs/chatgpt-visibility-content-package.md`, `page-runs/RUNLOG-chatgpt-visibility.md`.
`rubric.py` — score a `package_out` 0/1/2 each: answer-first lead ≤60 words; unique_insight present + grounded; entity coverage == gap matrix + keep_list; zero unresolved [VERIFY] in final copy; fact_diff clean; FAQ ≥5 + deduped; title ≤60 & meta ≤155; image manifest (descriptive names, alt, 0 base64, hero eager); schema valid + FAQ-text match; internal links ≥4 valid. **Pass bar: ≥85% of the gold package's score on the same rubric.**
`seeded_errors.py` — 6 poisoned runs; the suite PASSES only if every seed is flagged/blocked and FAILS if any ships silently:
1. research_dossier claims "9 AI engines" (canonical says 4) → must surface as conflict + fact_diff blocker.
2. dossier contains fabricated stat "73% of CMOs…" with no source → must become [VERIFY] or be cut.
3. brand_assets contains a testimonial marked `permission: false` → must NOT appear in copy or Review schema.
4. diagnosis keep_list contains "Sample Variance differentiator"; strategist prompt nudged to drop it → c9/c19 must fail the run.
5. canonical pages disagree (feature page "4 engines", marketing "6") → source_precedence surfaces, never auto-picks.
6. a sibling-product feature ("Citation Outreach") in the dossier scoped to another URL → must be linked-out, not claimed.
`run_eval.py` — runs rubric vs gold + the seeded suite + prints $/page (sum usage from SDK responses) and wall-clock. Exit code 0 only if rubric ≥85% AND seeds 6/6.
---
## 10. CLI (`run.py`)

```
python run.py audit  --url https://… [--gsc path.zip] [--keyword "…"] [--out runs/<ts>/]
python run.py content --mode rebuild --diagnosis runs/<ts>/diagnosis.json --inputs inputs.json
python run.py content --mode net_new --inputs inputs.json
python run.py eval
```

`inputs.json` (net_new minimum): `{"seed_keyword", "business_context", "page_type", "audience", "canonical_sources": [...], "brand_assets": {...}}` — validate on load; missing required → print exactly which field and exit 2.
Human checkpoints: implement with `langgraph` `interrupt()`; CLI renders the question, accepts typed input or `skip` (skip ⇒ the item stays on `human_checkpoints` and the Packager lists it as unresolved). Every run writes `runs/<ts>/`: state snapshots per node, ledger.json, package_out.json/md, runlog.md (one section per node: inputs-summary, output-summary, guardrail results — mirror the style of `page-runs/RUNLOG-chatgpt-visibility.md`).
---
## 11. BUILD PHASES + ACCEPTANCE TESTS (do them in order; stop at any red)
**Phase 0 — skeleton & contracts (no model calls).** repo tree, state.py, ledger.py, guardrails.py + ALL tests in §6 green, config, prompt loader.
✅ Accept: `pytest` green; `python -c "import graphs.content_graph"` ok.
**Phase 1 — content walking skeleton (rebuild mode, one page).** Nodes c0,c1,c7,c8,c9,c10,c11(fan-out),c12,c13,c16,c18,c19,c22 wired; route-back edge c19→owning layer with cap; in-memory checkpointer; runs against a hand-written `diagnosis.json` for the ChatGPT-visibility page (derive it from `page-runs/02-chatgpt-visibility.md`).
✅ Accept: end-to-end run completes; runlog written; deliberately poison the ledger (engines=4) + a draft saying "nine engines" → c19 blocks and routes back, second pass passes or escalates at cap (test_routeback.py covers this with a mocked LLM).
**Phase 2 — GO/KILL eval gate.** Copy gold files; implement rubric + seeded suite.
✅ Accept: `python run.py eval` → rubric ≥85% vs gold, seeds 6/6, prints cost+latency. **If rubric <85%: fix prompts, not guardrails. If any seed ships: STOP and fix guardrails before adding anything.**
**Phase 3 — audit pipeline + the seam.** a0–a11 (a1–a9+a10 parallel), gsc.py against the real export format, a10 zero-click rule, a11 emits `Diagnosis`; `run.py audit` then `run.py content --mode rebuild --diagnosis …` works with no hand edits. SQLite checkpointer.
✅ Accept: audit of a live URL produces a master report whose defects each name an owning content node; chained run completes; eval still green.
**Phase 4 — cold mode + remaining agents.** c2–c6 (serp behind interface; stub fixtures ok), c14, c15 (SVG generation), c17, c20, c21; net_new end-to-end from `inputs.json`.
✅ Accept: cold run on seed_keyword "ai citation tracking" with Siftly-style inputs completes; comparison_judge skipped in cold mode; eval green incl. seed 4 & 6 against the new nodes.
**Phase 5 — hardening.** Per-node cost/latency in runlog; retries/timeouts on all tools; `--resume runs/<ts>` from checkpoint; README with the three commands.
✅ Accept: kill a run mid-L3, resume, identical package_out hash on a fixed seed/mocked-LLM test.
**Never build:** auto-publish, CMS write access, fabricated reviews/aggregateRating, auto-resolution of source conflicts.
---
## 12. CONFIG DEFAULTS (`config.yaml`)

```yaml
models: {strong: claude-sonnet-4-6, fast: claude-haiku-4-5-20251001}
route_back_cap: 2
budgets: {max_cost_usd_per_page: 3.0, max_minutes_per_page: 15}
ui_limits: {h1_chars: 60, meta_chars: 155, cta_words: 5}
word_budget: {feature: [1400, 1800], blog-listicle: [1800, 2600], guide: [2000, 3200], comparison: [1500, 2200]}
rubric_pass_pct: 85
```

## 13. DEFINITION OF DONE
All five phases' acceptance tests green; `run.py eval` exit 0; a fresh clone + `pip install -r requirements.txt` + the three CLI commands reproduce: (1) an audit of a live URL, (2) a rebuild from its diagnosis, (3) a cold page from a keyword — each leaving a complete `runs/<ts>/` with runlog, ledger, and package.
