"""Site cluster map — the pillar/spoke topology a page must respect.

This is the missing site-level input. Each entry declares an intent and the one
URL that owns it. ClusterMap.match() maps free text (a section heading, a
subtopic, a keyword) to the entry that owns that intent, so the deterministic
`intent_boundary_check` guardrail can tell a page "link, don't host" when a
planned section belongs to a sibling.

State carries the cluster map as a plain dict (JSON/checkpoint-safe); nodes and
guardrails build a ClusterMap from it on demand.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_STOP = {"the", "and", "for", "with", "your", "you", "how", "what", "why",
         "best", "top", "guide", "vs", "a", "an", "to", "of", "in", "on"}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", (text or "").lower())).strip()


@dataclass(frozen=True)
class ClusterEntry:
    url: str
    intent: str                       # canonical intent label (also the key)
    keywords: tuple[str, ...] = ()    # phrases/words that signal this intent
    role: str = "spoke"               # "pillar" | "spoke"

    def _signal_words(self) -> set[str]:
        words = {w for w in _norm(self.intent).split() if len(w) > 3 and w not in _STOP}
        for kw in self.keywords:
            words |= {w for w in _norm(kw).split() if len(w) > 3 and w not in _STOP}
        return words

    def score(self, text: str) -> int:
        """+2 per multi-word keyword phrase present, +1 per significant word."""
        norm = _norm(text)
        s = 0
        for kw in self.keywords:
            nk = _norm(kw)
            if " " in nk and nk in norm:          # phrase hit is a strong signal
                s += 2
        present = {w for w in self._signal_words() if re.search(rf"\b{re.escape(w)}\b", norm)}
        return s + len(present)


@dataclass
class ClusterMap:
    entries: list[ClusterEntry] = field(default_factory=list)
    match_threshold: int = 2

    @classmethod
    def from_config(cls, data: dict | list | None) -> "ClusterMap | None":
        if not data:
            return None
        entries: list[ClusterEntry] = []

        def _add(d: dict, role: str):
            if d and d.get("url") and d.get("intent"):
                entries.append(ClusterEntry(
                    url=d["url"], intent=d["intent"],
                    keywords=tuple(d.get("keywords", [])), role=role))

        if isinstance(data, list):
            for d in data:
                _add(d, d.get("role", "spoke"))
        else:
            _add(data.get("pillar") or {}, "pillar")
            for d in data.get("spokes", []):
                _add(d, "spoke")
        return cls(entries) if entries else None

    def match(self, text: str) -> ClusterEntry | None:
        """Best-matching entry for free text, or None if nothing clears threshold."""
        best, best_score = None, 0
        for e in self.entries:
            sc = e.score(text)
            if sc > best_score:
                best, best_score = e, sc
        return best if best_score >= self.match_threshold else None

    def owner_of(self, text: str) -> str | None:
        m = self.match(text)
        return m.url if m else None
