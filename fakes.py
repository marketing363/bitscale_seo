"""Scripted LLM for offline runs and tests (Phase 1).

ScriptedLLM returns canned JSON per node id. A script value may be:
  - str: returned every call
  - list[str]: consumed in order (then last repeats)
  - callable(prompt, n): n = number of prior calls to that node id

make_rebuild_script() produces a coherent ChatGPT-visibility rebuild. With
poison_first_pass the section drafter emits "nine AI engines" on its first call
(caught by fact_diff at c19, routing back to L3) and the correct value after —
exercising the route-back loop. poison_always never corrects, forcing escalation.
"""
from __future__ import annotations

import json


class ScriptedLLM:
    def __init__(self, script: dict):
        self.script = script
        self.counts: dict[str, int] = {}

    def complete(self, prompt: str, tier: str, node_id: str | None = None) -> tuple[str, dict]:
        n = self.counts.get(node_id, 0)
        self.counts[node_id] = n + 1
        if node_id not in self.script:
            raise KeyError(f"ScriptedLLM has no response for node '{node_id}'")
        val = self.script[node_id]
        if callable(val):
            text = val(prompt, n)
        elif isinstance(val, list):
            text = val[min(n, len(val) - 1)]
        else:
            text = val
        return text, {"model": f"scripted-{tier}", "input_tokens": 0, "output_tokens": 0}


# \b anchor matters: without it "o(ften) AI engines" matches as "ten AI engines"
_ENGINES_PATTERN = (
    r"\b(\d+|zero|one|two|three|four|five|six|seven|eight|nine|ten)"
    r"\s+(?:major\s+)?AI engines"
)

_POISONED_BODY = (
    "## How Siftly tracks ChatGPT visibility\n\n"
    "Siftly monitors your brand across nine AI engines, then applies Sample "
    "Variance to separate signal from noise. By sampling many prompt phrasings, "
    "Siftly reports your AI Overview citation share across ChatGPT, Claude, "
    "Perplexity, and Google AI Overviews."
)
_CORRECT_BODY = (
    "## How Siftly tracks ChatGPT visibility\n\n"
    "Siftly monitors your brand across 4 AI engines (fact:engines-count), then "
    "applies Sample Variance to separate signal from noise. By sampling many "
    "prompt phrasings, Siftly reports your AI Overview citation share across "
    "ChatGPT, Claude, Perplexity, and Google AI Overviews."
)


def make_rebuild_script(poison_first_pass: bool = True, poison_always: bool = False) -> dict:
    c1 = json.dumps({
        "proposed_facts": [{
            "id": "engines-count",
            "claim": "Number of AI engines Siftly monitors",
            "value": "4 (ChatGPT, Claude, Perplexity, Google AI Overviews)",
            "source_url": "https://siftly.ai/features",
            "status": "verified",
            "claim_pattern": _ENGINES_PATTERN,
        }],
        "unresolved": [],
    })
    c7 = json.dumps({
        "unique_insight": "Siftly is the only platform that scores brand visibility across 4 AI engines with prompt-level Sample Variance analysis (fact:engines-count).",
        "strategy": {"reader": "B2B SEO leads", "promise": "Measure and improve ChatGPT visibility",
                     "proof_order": ["coverage", "variance", "citations"]},
        "keep_plan": [{"item": "Sample Variance differentiator", "placement": "s1"}],
        "link_outs": [],
        "claims": ["Siftly monitors 4 AI engines (fact:engines-count)."],
    })
    c8 = json.dumps({"brief": {
        "title_direction": "ChatGPT Visibility Tracking for Brands",
        "meta_direction": "See how your brand appears across ChatGPT and three other AI engines, and how to improve citation share with Siftly.",
        "structure": [{"id": "s1", "intent": "Explain multi-engine tracking and Sample Variance"}],
        "word_budgets": {"s1": 600},
        "media_plan": [],
        "cta": "Start free trial",
        "internal_link_targets": [
            "https://siftly.ai/features", "https://siftly.ai/pricing",
            "https://siftly.ai/docs", "https://siftly.ai/blog",
        ],
    }})
    c9 = json.dumps({"outline": {
        "sections": [{
            "id": "s1",
            "h2": "How Siftly tracks ChatGPT visibility",
            "intent": "multi-engine + variance",
            "word_budget": 600,
            "entities_assigned": ["ChatGPT", "Claude", "Perplexity", "Google AI Overviews", "AI Overview citation share"],
            "keep_items_assigned": ["Sample Variance differentiator"],
            "facts_needed": ["engines-count"],
        }],
        "coverage_map": {"AI Overview citation share": "s1", "Sample Variance differentiator": "s1"},
        "unassigned": [],
    }})
    c10 = json.dumps({
        "lead": ("Want to know how often ChatGPT recommends your brand? Siftly measures your "
                 "visibility across 4 AI engines (fact:engines-count) and turns prompt-level "
                 "Sample Variance into a clear citation-share score you can improve week over week."),
        "word_count": 48,
    })
    c12 = json.dumps({"faq": [
        {"q": "What is ChatGPT visibility?",
         "a": "It is how often ChatGPT surfaces or recommends your brand when users ask relevant questions, measured by sampling many prompts."},
        {"q": "How does Siftly measure it?",
         "a": "Siftly samples representative prompts, records when your brand is cited, and aggregates the results into a citation-share score."},
        {"q": "Which engines are covered?",
         "a": "Siftly covers ChatGPT, Claude, Perplexity, and Google AI Overviews (fact:engines-count)."},
        {"q": "What is Sample Variance?",
         "a": "Sample Variance captures how much citation results vary across prompt phrasings, so your score reflects reality rather than a single lucky query."},
        {"q": "How fast can I see results?",
         "a": "Most teams see a baseline within the first sampling cycle and track movement on a weekly cadence."},
    ], "dropped_as_duplicate": []})

    def c11(prompt: str, n: int) -> str:
        poisoned = poison_always or (poison_first_pass and n == 0)
        body = _POISONED_BODY if poisoned else _CORRECT_BODY
        return json.dumps({
            "section_id": "s1",
            "h2": "How Siftly tracks ChatGPT visibility",
            "body_md": body,
            "entities_covered": ["ChatGPT", "Claude", "Perplexity", "Google AI Overviews", "AI Overview citation share"],
            "verify_flags": [],
        })

    c6 = json.dumps({
        "brand_voice": {"tone": "direct, evidence-first", "person": "second",
                        "words_to_avoid": ["revolutionary", "game-changing"]},
        "human_checkpoints": [],
    })

    return {
        "c1_source_reconciler": c1,
        "c6_brand_loader": c6,
        "c7_strategist": c7,
        "c8_brief_compiler": c8,
        "c9_outline": c9,
        "c10_hook": c10,
        "c11_section_drafter": c11,
        "c12_faq": c12,
    }


def make_cold_script(keyword: str = "ai citation tracking") -> dict:
    """Coherent net_new run: same quality spine, no diagnosis/keep-list inputs.
    Cold-only research nodes (c2-c5) are deterministic and need no script."""
    script = make_rebuild_script(poison_first_pass=False)
    script["c7_strategist"] = json.dumps({
        "unique_insight": f"Siftly turns {keyword} into a weekly citation-share metric "
                          "across 4 AI engines with Sample Variance analysis (fact:engines-count).",
        "strategy": {"reader": "B2B SEO leads", "promise": f"Measure {keyword} properly",
                     "proof_order": ["coverage", "variance", "citations"]},
        "keep_plan": [],
        "link_outs": [],
        "claims": ["Siftly monitors 4 AI engines (fact:engines-count)."],
    })
    script["c10_hook"] = json.dumps({
        "lead": ("AI citation tracking measures how often AI engines cite your brand when "
                 "buyers ask questions. Siftly samples hundreds of prompt phrasings across "
                 "4 AI engines (fact:engines-count), applies Sample Variance analysis, and "
                 "reports a weekly citation-share score your team can actually improve."),
        "word_count": 47,
    })
    return script
