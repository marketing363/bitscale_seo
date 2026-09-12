"""Per-page-type structure contracts (the "shape" of each page type).

A comparison page must have a comparison table + verdict; a glossary must be
definition-first with examples; a feature page leads with the problem and proves
differentiators. These are CONTRACTS, not prompt suggestions: c8 seeds the brief
from the profile, c9 must cover every required block, c18 picks schema @types
from it, and c20 deterministically flags required blocks that never made it into
the draft.

Profiles are data. Word budgets defer to config.yaml where it defines them so the
two never diverge.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

_CFG = yaml.safe_load((Path(__file__).parent / "config.yaml").read_text())


@dataclass(frozen=True)
class Block:
    id: str
    label: str
    keywords: tuple[str, ...]          # heading/intent cues that count as "present"
    required: bool = True


@dataclass(frozen=True)
class PageProfile:
    page_type: str
    blocks: tuple[Block, ...]
    schema_types: tuple[str, ...]
    serp_targets: tuple[str, ...]
    default_word_budget: tuple[int, int]
    notes: str = ""

    @property
    def word_budget(self) -> list[int]:
        # config.yaml is the source of truth where it defines a budget
        return list(_CFG.get("word_budget", {}).get(self.page_type, self.default_word_budget))

    def required_blocks(self) -> list[Block]:
        return [b for b in self.blocks if b.required]

    def default_structure(self) -> list[dict]:
        """Deterministic fallback structure when a model under-specifies the brief."""
        return [{"id": b.id, "intent": b.label, "required": b.required} for b in self.blocks]

    def missing_blocks(self, draft: str, outline: dict | None = None) -> list[Block]:
        """Required blocks whose cues appear in neither the draft nor the outline."""
        hay = draft.lower()
        if outline:
            for s in outline.get("sections", []):
                hay += " " + str(s.get("h2", "")).lower() + " " + str(s.get("intent", "")).lower()
                for b in s.get("blocks", []) or []:
                    hay += " " + str(b).lower()
        missing = []
        for b in self.required_blocks():
            if not any(re.search(rf"\b{re.escape(k)}", hay) for k in b.keywords):
                missing.append(b)
        return missing


# --- the profiles -----------------------------------------------------------

_FAQ = Block("faq", "FAQ (PAA-sourced)", ("faq", "frequently asked", "questions"))
_CTA = Block("cta", "Call to action", ("get started", "start", "try", "demo", "sign up", "book"))

PROFILES: dict[str, PageProfile] = {
    "feature": PageProfile(
        "feature",
        blocks=(
            Block("answer_first", "Answer-first lead", ("",)),  # always present (the lead)
            Block("problem", "Problem this feature solves", ("problem", "challenge", "why", "struggle")),
            Block("how_it_works", "How it works", ("how it works", "how it", "works", "process")),
            Block("capabilities", "Key capabilities", ("capabilit", "feature", "what you can", "do")),
            Block("differentiators", "Differentiators (grounded)", ("unlike", "different", "only", "vs", "compared")),
            Block("proof", "Proof / evidence", ("proof", "result", "example", "case", "data")),
            _FAQ, _CTA,
        ),
        schema_types=("WebPage", "SoftwareApplication", "FAQPage"),
        serp_targets=("featured_snippet", "aio_citation"),
        default_word_budget=(1400, 1800),
        notes="Lead with the problem, prove the differentiators, end on a CTA.",
    ),
    "comparison": PageProfile(
        "comparison",
        blocks=(
            Block("verdict", "Answer-first verdict", ("verdict", "winner", "best for", "bottom line", "tl;dr", "short answer")),
            Block("at_a_glance", "At-a-glance comparison table", ("table", "at a glance", "side by side", "side-by-side", "comparison")),
            Block("criteria", "Comparison criteria", ("criteria", "how we compared", "factors", "what to look")),
            Block("head_to_head", "Head-to-head breakdown", ("head-to-head", "head to head", "vs", "versus")),
            Block("pros_cons", "Pros and cons", ("pros", "cons", "strengths", "weaknesses", "drawbacks")),
            Block("who_should", "Who should choose which", ("who should", "best for", "choose", "recommend")),
            _FAQ,
        ),
        schema_types=("WebPage", "FAQPage"),
        serp_targets=("featured_snippet", "aio_citation", "people_also_ask"),
        default_word_budget=(1500, 2200),
        notes="A comparison page without a comparison table is not a comparison page.",
    ),
    "guide": PageProfile(
        "guide",
        blocks=(
            Block("summary", "Answer-first summary", ("summary", "in short", "overview", "tl;dr")),
            Block("prerequisites", "Prerequisites / what you need", ("prerequisite", "before you", "what you need", "requirement")),
            Block("steps", "Step-by-step", ("step", "how to", "process", "walkthrough")),
            Block("examples", "Worked example", ("example", "for instance", "walkthrough", "sample")),
            Block("mistakes", "Common mistakes", ("mistake", "pitfall", "avoid", "common error")),
            _FAQ,
        ),
        schema_types=("WebPage", "HowTo", "FAQPage"),
        serp_targets=("featured_snippet", "aio_citation", "people_also_ask"),
        default_word_budget=(2000, 3200),
        notes="Steps must be ordered and self-contained enough to cite individually.",
    ),
    "blog-listicle": PageProfile(
        "blog-listicle",
        blocks=(
            Block("intro", "Answer-first intro", ("intro", "summary", "in short", "overview")),
            Block("criteria", "Selection criteria", ("criteria", "how we picked", "how we chose", "methodology")),
            Block("items", "Ranked items", ("1.", "#1", "best", "top", "option")),
            Block("summary_table", "Summary / quick-pick", ("summary", "quick pick", "table", "at a glance")),
            _FAQ,
        ),
        schema_types=("WebPage", "ItemList", "FAQPage"),
        serp_targets=("featured_snippet", "aio_citation", "people_also_ask"),
        default_word_budget=(1800, 2600),
        notes="State the selection criteria before the list — engines cite the 'why'.",
    ),
    "glossary": PageProfile(
        "glossary",
        blocks=(
            Block("definition", "Definition (answer-first, <=60 words)", ("is", "definition", "refers to", "means")),
            Block("attributes", "Key attributes", ("attribute", "characteristic", "key", "property")),
            Block("how_it_works", "How it works / context", ("how it works", "works", "context", "used")),
            Block("examples", "Examples", ("example", "for instance", "such as")),
            Block("related", "Related terms", ("related", "see also", "compare", "vs")),
            _FAQ,
        ),
        schema_types=("WebPage", "DefinedTerm", "FAQPage"),
        serp_targets=("featured_snippet", "aio_citation"),
        default_word_budget=(800, 1400),
        notes="Open with a clean <=60-word definition — the most citable chunk on the page.",
    ),
    "landing": PageProfile(
        "landing",
        blocks=(
            Block("value_prop", "Hero value proposition", ("",)),
            Block("benefits", "Key benefits", ("benefit", "why", "value", "outcome")),
            Block("social_proof", "Social proof", ("trusted", "customers", "proof", "testimonial", "logos")),
            Block("how_it_works", "How it works", ("how it works", "works", "get started", "steps")),
            _CTA,
        ),
        schema_types=("WebPage",),
        serp_targets=("aio_citation",),
        default_word_budget=(600, 1200),
        notes="Conversion-first; keep blocks tight and the CTA above the fold.",
    ),
}


def get_profile(page_type: str | None) -> PageProfile:
    """Profile for a page type; falls back to 'feature' for unknown types."""
    return PROFILES.get(page_type or "", PROFILES["feature"])
