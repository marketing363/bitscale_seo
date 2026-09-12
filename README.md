# SEO/GEO Audit + Content-Generation Agentic Platform

Two LangGraph pipelines sharing one quality spine:

- **Pipeline A — Audit**: live URL (+ optional GSC export) → Master Audit Report + typed `Diagnosis`.
- **Pipeline B — Content**: `rebuild` (from a Diagnosis) or `net_new` (from a seed keyword) → a fully
  packaged page (copy, schema, media manifest, QA checklist) with every fact provenance-tracked.

Quality comes from infrastructure, not prompts: typed state validated at every hand-off, an
append-only Facts Ledger, deterministic guardrails (`fact_diff`, `flag_dont_fill`,
`grounding_check`, `canonical_verify`, `quantifier_check`, `source_precedence`),
writer ≠ verifier separation, and human checkpoints for facts no model can know.

📐 Start here: [`ARCHITECTURE.md`](ARCHITECTURE.md) · contract: [`BUILD-SPEC.md`](BUILD-SPEC.md) · build status: [`CLAUDE.md`](CLAUDE.md)

## Setup

```bash
pip install -r requirements.txt
pytest          # 90+ tests pin the guardrail/ledger/state contracts
```

### Model provider

`config.yaml → provider` selects who serves the models (offline `--fake` runs need neither):

| provider | env vars | tiers |
|---|---|---|
| `claude_code` | none — uses your local `claude` CLI login (`CLAUDE_CODE_BIN` to override path) | `models:` strong/fast → `--model` |
| `anthropic` | `ANTHROPIC_API_KEY` | `models:` strong=Sonnet, fast=Haiku |
| `azure_openai` | `AZURE_OPENAI_ENDPOINT` (full Responses-API URL incl. `?api-version=`), `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_DEPLOYMENT` (or per-tier names in `azure_openai.deployments`) | deployments play the strong/fast roles |

`claude_code` is the default: every model step (strategist, drafters, critics) shells out to
`claude -p --output-format json` with tools disabled — no API key, your Claude Code subscription.

Keys never go in committed files. With `azure_openai`, update `pricing:` to your Azure rates or runlog cost figures will be wrong.

## The three commands

```bash
# 1. Audit a live URL (Phase 3)
python run.py audit --url https://example.com/page [--gsc export.zip] [--keyword "…"]

# 2. Rebuild a page from its audit diagnosis (Phase 1)
python run.py content --mode rebuild --diagnosis runs/<ts>/diagnosis.json --inputs inputs.json

# 3. Create a new page cold from a keyword (Phase 4)
python run.py content --mode net_new --inputs inputs.json

# GO/KILL gate (Phase 2): rubric ≥85% vs gold AND all 6 seeded poisons caught
python run.py eval
```

Every run writes `runs/<ts>/` with per-node state snapshots, `ledger.json`,
`package_out.json/md`, and a `runlog.md` carrying per-node latency, token usage,
and cost (model pricing lives in `config.yaml`) with budget warnings.

Interrupted runs resume from their SQLite checkpoint — completed nodes are never
re-executed and the resulting package is byte-identical:

```bash
python run.py content --resume runs/<ts>
```

## Multi-domain accounts

Each domain gets its own isolated workspace (config, brand assets, GSC exports, runs) —
adding one is configuration, like adding a property in Google Search Console:

```bash
python run.py account add example.com      # scaffold workspaces/example.com/
# fill in account.yaml + brand_assets.json, drop GSC export ZIPs into gsc/
python run.py audit   --account example.com --url https://example.com/page
python run.py content --account example.com --mode rebuild --diagnosis …
```

Runs land in `workspaces/example.com/runs/<ts>/`. Accounts are fully isolated;
explicit CLI flags always override account config. GSC connects via export files
today; the schema reserves `gsc.mode: api` for a per-domain OAuth upgrade.

## Status

Phase 0 (skeleton & contracts) is complete; Phases 1–5 are tracked in `CLAUDE.md`,
which also lists the owner-supplied reference assets (gold files, prompt kit) that
gate Phase 2.
