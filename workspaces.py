"""Multi-domain workspace layer.

Each account (domain) owns an isolated folder:

    workspaces/<domain>/
    ├── account.yaml        # canonical sources, audience, precedence, gsc mode
    ├── brand_assets.json   # differentiators, author, approved testimonials
    ├── gsc/                # GSC export ZIPs/CSVs for THIS domain
    └── runs/               # this account's audit + content runs

Adding a domain is configuration, not code (like adding a GSC property).
Accounts are fully isolated: separate ledgers, runs, and assets — facts from
one account can never leak into another's content.

GSC connection modes: "export" (drop export files into gsc/) is live today;
"api" (per-domain OAuth) is reserved in the schema for a later phase.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

_GSC_MODES = ("export", "api")

ACCOUNT_TEMPLATE = """\
# Account configuration for {domain}
domain: {domain}

# Who this domain's content speaks to (used by the strategist + drafters)
audience: ""

# Pages that define ground truth for facts about this business.
# Order them by trust: docs/feature pages before marketing pages.
canonical_sources: []

# Source classes in precedence order (used when canonical pages disagree)
source_precedence: [owner, docs, feature_page, marketing, audit]

# Optional: sitemap URL for cannibalization checks
sitemap: ""

# Google Search Console connection
gsc:
  mode: export          # "export" today; "api" (OAuth) is a future upgrade
  exports_dir: gsc      # folder (inside this account) holding export ZIPs/CSVs

# Optional site cluster map (pillar + spokes). Lets the platform enforce
# "link, don't host" at the outline gate so a page never trespasses on a
# sibling's intent. Omit for single-page optimization.
# cluster_map:
#   pillar:
#     url: "https://example.com/topic"
#     intent: "topic"
#     keywords: ["topic"]
#   spokes:
#     - url: "https://example.com/topic/subtopic"
#       intent: "subtopic"
#       keywords: ["subtopic phrase", "another signal"]
"""

BRAND_ASSETS_TEMPLATE = {
    "differentiators": [],
    "author": {"name": "", "credentials": ""},
    "testimonials": [],
    "screenshots": [],
}

# The rich selling brief the strategist (c7) leans on. brand_assets stays the
# permission-gated factual source for E-E-A-T; brand_profile is what lets the
# page actually SELL. Everything optional — fill what you have.
BRAND_PROFILE_TEMPLATE = {
    "name": "",
    "one_liner": "",
    "category": "",
    "value_props": [],
    "features": [
        # {"name": "", "what_it_does": "", "proof": "", "canonical_url": ""}
    ],
    "icp": {"who": "", "personas": [], "jobs_to_be_done": []},
    "positioning": "",
    "objections": [
        # {"objection": "", "response": ""}
    ],
    "proof_points": [],
    "competitors": [
        # {"name": "", "how_we_differ": "", "url": ""}
    ],
    "pricing_notes": "",
    "cta": "",
}


class WorkspaceError(Exception):
    """Configuration problem with an account — message says exactly what."""


def workspaces_dir() -> Path:
    # per-brand data lives under brands/<domain>/. Env overrides for tests/deploys
    # (SEO_WORKSPACES_DIR kept for back-compat).
    return Path(os.environ.get("SEO_BRANDS_DIR")
                or os.environ.get("SEO_WORKSPACES_DIR")
                or "brands")


def _validate_domain(domain: str) -> str:
    d = domain.strip().lower()
    if not re.fullmatch(r"[a-z0-9]([a-z0-9\-.]*[a-z0-9])?", d):
        raise WorkspaceError(
            f"invalid domain '{domain}': use a bare domain like example.com "
            "(letters, digits, dots, hyphens)"
        )
    return d


@dataclass
class Account:
    domain: str
    root: Path
    audience: str = ""
    canonical_sources: list[str] = field(default_factory=list)
    source_precedence: list[str] = field(default_factory=lambda: ["owner", "docs", "feature_page", "marketing", "audit"])
    sitemap: str = ""
    gsc_mode: str = "export"
    gsc_dir: Path | None = None
    brand_assets: dict = field(default_factory=dict)
    brand_profile: dict = field(default_factory=dict)  # rich selling brief
    cluster_map: dict = field(default_factory=dict)   # pillar/spoke topology (L−1)

    @property
    def runs_dir(self) -> Path:
        return self.root / "runs"

    def latest_gsc_export(self) -> Path | None:
        """Most recent GSC export file in this account's gsc folder, if any."""
        if self.gsc_dir is None or not self.gsc_dir.exists():
            return None
        candidates = [p for p in self.gsc_dir.iterdir() if p.suffix.lower() in (".zip", ".csv")]
        return max(candidates, key=lambda p: p.stat().st_mtime) if candidates else None

    def content_inputs(self) -> dict:
        """The account-level fields that feed a content run's intake."""
        return {
            "audience": self.audience,
            "canonical_sources": list(self.canonical_sources),
            "source_precedence": list(self.source_precedence),
            "brand_assets": dict(self.brand_assets),
            "brand_profile": dict(self.brand_profile),
            "cluster_map": dict(self.cluster_map),
        }


def add_account(domain: str) -> Path:
    """Scaffold a new account folder. Refuses to overwrite an existing one."""
    domain = _validate_domain(domain)
    root = workspaces_dir() / domain
    if root.exists():
        raise WorkspaceError(f"account '{domain}' already exists at {root}")
    (root / "gsc").mkdir(parents=True)
    (root / "runs").mkdir()
    (root / "account.yaml").write_text(ACCOUNT_TEMPLATE.format(domain=domain))
    (root / "brand_assets.json").write_text(json.dumps(BRAND_ASSETS_TEMPLATE, indent=2) + "\n")
    (root / "brand_profile.json").write_text(json.dumps(BRAND_PROFILE_TEMPLATE, indent=2) + "\n")
    return root


def list_accounts() -> list[str]:
    base = workspaces_dir()
    if not base.exists():
        return []
    return sorted(p.name for p in base.iterdir() if (p / "account.yaml").exists())


def load_account(domain: str) -> Account:
    """Load + validate an account. Raises WorkspaceError naming any problem."""
    domain = _validate_domain(domain)
    root = workspaces_dir() / domain
    cfg_path = root / "account.yaml"
    if not cfg_path.exists():
        known = ", ".join(list_accounts()) or "(none yet — `run.py account add <domain>`)"
        raise WorkspaceError(f"no account '{domain}' at {root}. Known accounts: {known}")

    cfg = yaml.safe_load(cfg_path.read_text()) or {}
    if cfg.get("domain") != domain:
        raise WorkspaceError(
            f"{cfg_path}: 'domain' is '{cfg.get('domain')}' but the folder is '{domain}'"
        )

    gsc_cfg = cfg.get("gsc") or {}
    gsc_mode = gsc_cfg.get("mode", "export")
    if gsc_mode not in _GSC_MODES:
        raise WorkspaceError(f"{cfg_path}: gsc.mode must be one of {_GSC_MODES}, got '{gsc_mode}'")
    if gsc_mode == "api":
        raise WorkspaceError(
            "gsc.mode 'api' is reserved for the OAuth upgrade and is not implemented yet; "
            "use mode 'export' and drop GSC export files into the account's gsc/ folder"
        )

    def _load_json(name: str) -> dict:
        p = root / name
        if not p.exists():
            return {}
        try:
            return json.loads(p.read_text())
        except json.JSONDecodeError as e:
            raise WorkspaceError(f"{p} is not valid JSON: {e}") from e

    return Account(
        domain=domain,
        root=root,
        audience=cfg.get("audience") or "",
        canonical_sources=list(cfg.get("canonical_sources") or []),
        source_precedence=list(cfg.get("source_precedence") or
                               ["owner", "docs", "feature_page", "marketing", "audit"]),
        sitemap=cfg.get("sitemap") or "",
        gsc_mode=gsc_mode,
        gsc_dir=root / (gsc_cfg.get("exports_dir") or "gsc"),
        brand_assets=_load_json("brand_assets.json"),
        brand_profile=_load_json("brand_profile.json"),
        cluster_map=cfg.get("cluster_map") or {},
    )
