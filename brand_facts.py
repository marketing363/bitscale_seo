"""Seed the Facts Ledger from owner-supplied brand data (architecture: c1).

The brand_profile + brand_assets are owner-asserted truth. Turning them into
*verified* ledger facts lets writers cite them (so they aren't forced to write
[VERIFY]); numeric facts get a claim_pattern so fact_diff can defend them.
Deterministic, no model calls.
"""
from __future__ import annotations

import re


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-")[:48] or "fact"


def facts_from_brand(brand_profile: dict, brand_assets: dict) -> list[dict]:
    facts: list[dict] = []
    seen: set[str] = set()

    def add(fid: str, claim: str, value: str, pattern: str | None = None,
            source: str = "brand_profile"):
        if not value or not str(value).strip():
            return
        base, i = fid, 1
        while fid in seen:
            i += 1
            fid = f"{base}-{i}"
        seen.add(fid)
        f = {"id": fid, "claim": claim, "value": str(value),
             "source_url": source, "verified_by": "c1_source_reconciler", "status": "verified"}
        if pattern:
            f["claim_pattern"] = pattern
        facts.append(f)

    bp = brand_profile or {}
    hv = bp.get("how_it_works_verified") or {}

    # engine count — numeric, defended by fact_diff
    n = hv.get("engines_count")
    if n:
        engines = ", ".join(hv.get("engines", []))
        add("engines-count", "Number of AI engines tracked",
            f"{n} ({engines})" if engines else str(n),
            pattern=r"\b(\d+|two|three|four|five|six|seven|eight|nine|ten)\s+(?:major\s+)?(?:AI\s+)?engines")
    if hv.get("team"):
        add("team-size", "Team members per account", hv["team"],
            pattern=r"\b(\d+|ten|twenty)\s+(?:team\s+)?members")
    for key, claim in (("data_method", "How buyer questions are captured"),
                       ("output_mechanism", "How prompts become recommendations"),
                       ("generates", "What the platform generates"),
                       ("cadence", "Run cadence")):
        if hv.get(key):
            add(_slug(key), claim, hv[key])

    for vp in bp.get("value_props", []):
        add(_slug(vp)[:40] or "value-prop", "Value proposition", vp)
    for d in bp.get("differentiators", []):
        add("diff-" + _slug(d)[:32], "Differentiator", d)
    for f in bp.get("features", []):
        if isinstance(f, dict) and f.get("name"):
            add("feat-" + _slug(f["name"]), f"Feature: {f['name']}",
                f.get("what_it_does") or f["name"])
    for pp in bp.get("proof_points", []):
        add("proof-" + _slug(pp)[:32], "Proof point", pp)

    # approved testimonials -> verified facts (E-E-A-T / social proof)
    for t in (brand_assets or {}).get("testimonials", []):
        if isinstance(t, dict) and t.get("permission") is True and t.get("quote"):
            who = ", ".join(x for x in (t.get("author"), t.get("title"), t.get("company")) if x)
            add("testimonial-" + _slug(t.get("company") or t.get("author") or "x"),
                f"Approved testimonial ({who})", t["quote"], source=t.get("source", "brand_assets"))
    return facts
