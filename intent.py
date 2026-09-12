"""The intent contract (architecture v2) — the object that governs every page.

Built deterministically from page_type + cluster_map + (optional) GSC head
queries. `governed` is True only when the inputs that make intent governance
meaningful are present (a cluster_map and/or GSC head queries); otherwise the
page runs in single-page mode and the intent gates are no-ops — so legacy runs
are unchanged.
"""
from __future__ import annotations

from cluster_map import ClusterMap
from guardrails import classify_intent, owned_intent_types

# page_type -> primary intent type + one-sentence job statement
_PRIMARY_INTENT = {
    "feature": "commercial", "landing": "commercial",
    "listicle": "commercial", "blog-listicle": "commercial", "comparison": "commercial",
    "guide": "informational", "glossary": "informational",
}
_JOB = {
    "feature": "evaluate whether THIS product's feature does the job",
    "landing": "decide whether to start with THIS product",
    "comparison": "decide which option to choose",
    "listicle": "shortlist the best options to choose from",
    "blog-listicle": "shortlist the best options to choose from",
    "guide": "understand the concept and how to do it",
    "glossary": "understand what the term means",
}


def bucket_head_queries(queries: list[dict]) -> list[dict]:
    """Attach an intent_type (and keep language) to each GSC query row."""
    out = []
    for q in queries or []:
        term = q.get("query") or q.get("term") or ""
        if not term:
            continue
        out.append({
            "term": term,
            "impressions": q.get("impressions", 0),
            "position": q.get("position", 0),
            "intent_type": q.get("intent_type") or classify_intent(term),
            "language": q.get("language", "und"),
        })
    return out


def build_intent_contract(*, page_type: str, primary_keyword: str,
                          cluster_map: dict | None = None,
                          target_url: str = "",
                          head_queries: list[dict] | None = None,
                          required_template_sections: list[str] | None = None) -> dict:
    owned = sorted(owned_intent_types(page_type))
    cm = ClusterMap.from_config(cluster_map)
    head = bucket_head_queries(head_queries or [])

    delegated: dict[str, str] = {}
    if cm is not None:
        cur = (target_url or "").rstrip("/")
        own = cm.match(target_url) or cm.match(primary_keyword)
        page_intent = own.intent if own else primary_keyword
        for e in cm.entries:
            if e.url.rstrip("/") == cur or e.intent == page_intent:
                continue
            # a sibling whose intent type this page may not own → delegate to it
            if classify_intent(e.intent) not in owned:
                delegated[e.intent] = e.url
            else:
                # same intent-type sibling: still its own URL's territory
                delegated[e.intent] = e.url
    else:
        page_intent = primary_keyword

    governed = bool(cm is not None or head)
    return {
        "governed": governed,
        "page_type": page_type,
        "primary_keyword": primary_keyword,
        "primary_intent_type": _PRIMARY_INTENT.get(page_type, "commercial"),
        "job_statement": _JOB.get(page_type, "complete the task this page is for"),
        "page_intent": page_intent,
        "owned_intent_types": owned,
        "owned_query_classes": owned,
        "delegated_query_classes": delegated,
        "head_queries": head,
        "required_template_sections": required_template_sections or [],
    }
