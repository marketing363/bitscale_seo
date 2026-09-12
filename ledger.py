"""FactsLedger — append-only facts with provenance (BUILD-SPEC §6).

Rules:
- add() never overwrites: re-adding an existing id with a different value flips
  the fact to status="conflict" and records both values.
- Only this module mutates the underlying list[Fact].
- supports_number() does normalized numeric containment over VERIFIED facts only.
"""
from __future__ import annotations

import re

from state import Fact

_WORD_NUMS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20,
}

_SCALES = {
    "million": 1_000_000, "m": 1_000_000,
    "billion": 1_000_000_000, "b": 1_000_000_000,
    "thousand": 1_000, "k": 1_000,
}

_NUM_PAT = re.compile(
    r"(\d[\d,]*(?:\.\d+)?)\s*(million|billion|thousand|[MBK])?\b", re.I
)


def word_to_number(token: str) -> float | None:
    """Normalize a token ('nine', '4', '1,200') to a float, or None."""
    t = token.strip().lower().replace(",", "")
    if t in _WORD_NUMS:
        return float(_WORD_NUMS[t])
    m = re.fullmatch(r"\d+(?:\.\d+)?", t)
    if m:
        return float(t)
    # compound like "900 million"
    m = re.fullmatch(r"(\d[\d]*(?:\.\d+)?)\s*(million|billion|thousand|m|b|k)", t)
    if m:
        return float(m.group(1)) * _SCALES[m.group(2)]
    return None


def extract_numbers(text: str) -> set[float]:
    """All normalized numeric magnitudes in text (scale words applied)."""
    out: set[float] = set()
    for m in _NUM_PAT.finditer(text):
        base = float(m.group(1).replace(",", ""))
        scale = m.group(2)
        if scale:
            out.add(base * _SCALES[scale.lower()])
        else:
            out.add(base)
    for w, v in _WORD_NUMS.items():
        if re.search(rf"\b{w}\b", text, re.I):
            out.add(float(v))
    return out


class FactsLedger:
    """Append-only wrapper over list[Fact]."""

    def __init__(self, facts: list[Fact] | None = None):
        # operate on the provided list in place so graph state sees appends
        self._facts: list[Fact] = facts if facts is not None else []

    # -- read ----------------------------------------------------------------

    @property
    def facts(self) -> list[Fact]:
        return list(self._facts)

    def get(self, fact_id: str) -> Fact | None:
        for f in self._facts:
            if f["id"] == fact_id:
                return f
        return None

    def __len__(self) -> int:
        return len(self._facts)

    # -- write (append-only) ---------------------------------------------------

    def add(self, fact: Fact) -> Fact:
        """Append a fact. Same id + same value: no-op (returns existing).
        Same id + different value: existing entry becomes a conflict carrying
        all observed values — never overwritten.
        """
        existing = self.get(fact["id"])
        if existing is None:
            self._facts.append(dict(fact))  # type: ignore[arg-type]
            return self.get(fact["id"])  # type: ignore[return-value]
        if existing["value"] == fact["value"]:
            return existing
        values = existing.get("conflict_values") or [existing["value"]]
        if fact["value"] not in values:
            values.append(fact["value"])
        existing["status"] = "conflict"
        existing["conflict_values"] = values
        return existing

    # -- guardrail support -------------------------------------------------------

    def supports_number(self, s: str) -> bool:
        """True if any numeric magnitude in s appears in a verified fact's value."""
        candidates = extract_numbers(s.replace("$", "").replace("%", ""))
        if not candidates:
            return False
        verified_nums: set[float] = set()
        for f in self._facts:
            if f["status"] == "verified":
                verified_nums |= extract_numbers(f["value"])
        return bool(candidates & verified_nums)

    def verified_numbers(self) -> set[float]:
        out: set[float] = set()
        for f in self._facts:
            if f["status"] == "verified":
                out |= extract_numbers(f["value"])
        return out

    # -- rendering ----------------------------------------------------------------

    def to_markdown(self) -> str:
        if not self._facts:
            return "(ledger is empty)"
        lines = [
            "| id | claim | value | status | source |",
            "|---|---|---|---|---|",
        ]
        for f in self._facts:
            value = f["value"]
            if f["status"] == "conflict":
                value = " / ".join(f.get("conflict_values") or [value]) + " (CONFLICT)"
            lines.append(
                f"| {f['id']} | {f['claim']} | {value} | {f['status']} | {f['source_url']} |"
            )
        return "\n".join(lines)
