"""Typed shared state (the Package) + Pydantic validation at hand-offs.

BUILD-SPEC §4: TypedDicts are written verbatim from the spec and extended only
additively. Every graph hand-off calls validate_state(); failure raises
StateValidationError — never silently continue.
"""
import operator
from typing import Annotated, Any, Literal, Optional, TypedDict

from pydantic import BaseModel, ConfigDict, ValidationError
from typing_extensions import NotRequired


# ---------------------------------------------------------------------------
# Exceptions (graph control flow + validation)
# ---------------------------------------------------------------------------

class StateValidationError(Exception):
    """Raised when state fails Pydantic validation after a node."""

    def __init__(self, node: str, errors: list[dict]):
        self.node = node
        self.errors = errors
        super().__init__(f"State validation failed after node '{node}': {errors}")


class HumanInputRequired(Exception):
    """Raised when a run cannot proceed without human-supplied input (c0 HALT)."""

    def __init__(self, missing: str, detail: str = ""):
        self.missing = missing
        self.detail = detail
        super().__init__(f"Human input required: {missing}. {detail}".strip())


class EscalateToHuman(Exception):
    """Raised when route_back_count for a layer exceeds the configured cap."""

    def __init__(self, layer: str, count: int, cap: int, failures: list | None = None):
        self.layer = layer
        self.count = count
        self.cap = cap
        self.failures = failures or []
        super().__init__(
            f"Route-back cap reached for layer '{layer}' ({count} > cap {cap}); escalating to human."
        )


# ---------------------------------------------------------------------------
# TypedDicts — BUILD-SPEC §4, verbatim (additive extensions marked)
# ---------------------------------------------------------------------------

class Fact(TypedDict):
    id: str                      # slug, e.g. "engines-count"
    claim: str                   # human-readable claim
    value: str                   # the locked value, e.g. "4 (ChatGPT, Claude, Perplexity, Google AI Overviews)"
    source_url: str
    verified_by: str             # node id that verified it
    status: Literal["verified", "VERIFY", "conflict"]
    conflict_values: NotRequired[list[str]]   # populated when status == "conflict"
    # additive (BUILD-SPEC §6 fact_diff): optional per-fact regex whose first
    # capture group must normalize to the locked value's number.
    claim_pattern: NotRequired[str]


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
    brand_profile: NotRequired[dict]              # rich selling brief (features, value props, ICP, objections…)
    unique_insight: NotRequired[str]
    cluster_context: NotRequired[dict]
    brand_voice: NotRequired[dict]
    audience: str
    geo: NotRequired[str]
    constraints: NotRequired[dict]
    competitors: NotRequired[list[str]]
    cluster_map: NotRequired[dict]                # site pillar/spoke topology (L−1 input)
    page_intent: NotRequired[str]                 # the single intent THIS page owns
    delegate_list: NotRequired[list[str]]         # sibling intents to link, not host
    intent_contract: NotRequired[dict]            # v2: governs the page (c2 builds it)
    head_queries: NotRequired[list[dict]]         # GSC head queries (term, intent_type, …)
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
    lead: NotRequired[str]                        # answer-first lead from c10
    strategy: NotRequired[dict]                   # from c7
    sections: NotRequired[dict[str, str]]
    faq: NotRequired[list[dict]]
    draft: NotRequired[str]
    schema_jsonld: NotRequired[dict]
    package_out: NotRequired[dict]
    canonical_source_texts: NotRequired[dict]     # url -> text, when provided/fetched
    sitemap: NotRequired[str]                     # account-configured sitemap URL (c2)
    media_manifest: NotRequired[list[dict]]       # from c15
    svg_assets: NotRequired[dict]                 # filename -> svg markup (c15)
    render_report: NotRequired[dict]              # from c20
    comparison_report: NotRequired[dict]          # from c21 (rebuild only)
    # ---- internal bookkeeping (graph channels; prefixed to stay out of package) ----
    _runlog: NotRequired[list]
    _guardrails: NotRequired[list]
    _c6: NotRequired[dict]
    _c7: NotRequired[dict]
    _c13_verdicts: NotRequired[list]
    _eeat: NotRequired[dict]
    _a11y_violations: NotRequired[list]
    # ---- quality spine ----
    facts_ledger: list[Fact]                      # append-only; only ledger.py mutates
    verify_list: list[str]
    conflicts: list[dict]
    critic_report: NotRequired[dict]
    route_back_count: dict[str, int]              # layer -> count; cap from config (default 2)
    human_checkpoints: list[str]                  # accumulating list of [HUMAN] asks


# additive: Pipeline A working state (BUILD-SPEC §5a node ownership)
class AuditState(TypedDict):
    url: str
    gsc_path: NotRequired[str]                    # CLI/account-supplied export path
    page: NotRequired[dict]                       # output of a0 (tools/fetch shape)
    page_type: NotRequired[str]
    primary_query: NotRequired[str]
    gsc: NotRequired[dict]
    tech_findings: NotRequired[dict]
    onpage_findings: NotRequired[dict]
    content_findings: NotRequired[dict]
    geo_findings: NotRequired[dict]
    serp_findings: NotRequired[dict]
    gap_entity_matrix: NotRequired[dict]
    authority_findings: NotRequired[dict]
    eeat_findings: NotRequired[dict]
    ux_findings: NotRequired[dict]
    a11y_findings: NotRequired[dict]
    performance: NotRequired[dict]
    intent_findings: NotRequired[dict]            # from a4b Intent-Match Auditor
    cluster_map: NotRequired[dict]                # optional site topology for the audit
    diagnosis: NotRequired[Diagnosis]
    master_report_md: NotRequired[str]
    # reducer channel: parallel analyzers each append their own runlog entry
    _runlog: NotRequired[Annotated[list, operator.add]]


# ---------------------------------------------------------------------------
# Pydantic mirrors — validated at every hand-off
# ---------------------------------------------------------------------------

_DEFAULT_SOURCE_PRECEDENCE = ["owner", "docs", "feature_page", "marketing", "audit"]


class FactModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    claim: str
    value: str
    source_url: str
    verified_by: str
    status: Literal["verified", "VERIFY", "conflict"]
    conflict_values: Optional[list[str]] = None
    claim_pattern: Optional[str] = None


class DefectModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: str
    owning_step: str
    severity: Literal["blocker", "major", "minor"]
    fix: str


class DiagnosisModel(BaseModel):
    model_config = ConfigDict(extra="allow")
    url: str
    page_type: Literal["feature", "blog-listicle", "guide", "comparison", "landing", "glossary"]
    primary_query: str
    scorecard: dict[str, int]
    defects: list[DefectModel]
    gap_entity_matrix: dict
    performance: Optional[dict] = None
    root_causes: list[str]
    keep_list: list[str]


class ContentStateModel(BaseModel):
    # extra="allow": TypedDicts may be extended additively; unknown keys must
    # never make a hand-off fail, only missing/invalid required ones.
    model_config = ConfigDict(extra="allow")
    mode: Literal["rebuild", "net_new"]
    page_type: str
    primary_keyword: str
    research_dossier: dict
    brand_assets: dict
    audience: str
    canonical_sources: list[str]
    source_precedence: list[str] = _DEFAULT_SOURCE_PRECEDENCE
    facts_ledger: list[FactModel]
    verify_list: list[str]
    conflicts: list[dict]
    route_back_count: dict[str, int]
    human_checkpoints: list[str]
    # optional working/package fields with type checks when present
    keyword_cluster: Optional[list[dict]] = None
    keep_list: Optional[list[str]] = None
    failure_modes: Optional[list[str]] = None
    sections: Optional[dict[str, str]] = None
    faq: Optional[list[dict]] = None
    draft: Optional[str] = None
    schema_jsonld: Optional[dict] = None
    package_out: Optional[dict] = None
    outline: Optional[dict] = None
    brief: Optional[dict] = None
    critic_report: Optional[dict] = None


class AuditStateModel(BaseModel):
    model_config = ConfigDict(extra="allow")
    url: str
    page: Optional[dict] = None
    page_type: Optional[str] = None
    primary_query: Optional[str] = None
    diagnosis: Optional[DiagnosisModel] = None
    master_report_md: Optional[str] = None


def validate_state(state: dict, after_node: str) -> None:
    """Validate the merged state after `after_node`.

    Pipeline is inferred from shape: content state always carries `mode`;
    audit state always carries `url` from intake. Raises StateValidationError.
    """
    model: type[BaseModel]
    if "mode" in state:
        model = ContentStateModel
    elif "url" in state:
        model = AuditStateModel
    else:
        raise StateValidationError(
            after_node,
            [{"msg": "state matches neither ContentState (no 'mode') nor AuditState (no 'url')"}],
        )
    try:
        model.model_validate(state)
    except ValidationError as e:
        raise StateValidationError(after_node, e.errors()) from e


def validate_diagnosis(diagnosis: dict) -> None:
    """Validate a Diagnosis object at the pipeline seam."""
    try:
        DiagnosisModel.model_validate(diagnosis)
    except ValidationError as e:
        raise StateValidationError("diagnosis_seam", e.errors()) from e


def new_content_state(**kwargs: Any) -> ContentState:
    """Build a ContentState with quality-spine fields initialized."""
    base: dict[str, Any] = {
        "source_precedence": list(_DEFAULT_SOURCE_PRECEDENCE),
        "facts_ledger": [],
        "verify_list": [],
        "conflicts": [],
        "route_back_count": {},
        "human_checkpoints": [],
    }
    base.update(kwargs)
    return base  # type: ignore[return-value]
