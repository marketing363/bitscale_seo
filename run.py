"""CLI entrypoint (BUILD-SPEC §10).

  python run.py audit   --url https://… [--gsc path.zip] [--keyword "…"] [--out runs/<ts>/]
  python run.py content --mode rebuild --diagnosis runs/<ts>/diagnosis.json --inputs inputs.json
  python run.py content --mode net_new --inputs inputs.json
  python run.py eval
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console

console = Console()

NET_NEW_REQUIRED = [
    "seed_keyword", "business_context", "page_type", "audience",
    "canonical_sources", "brand_assets",
]


def load_inputs(path: str, required: list[str]) -> dict:
    """Validate inputs.json; missing required field → print exactly which and exit 2."""
    p = Path(path)
    if not p.exists():
        console.print(f"[red]inputs file not found: {path}[/red]")
        sys.exit(2)
    try:
        data = json.loads(p.read_text())
    except json.JSONDecodeError as e:
        console.print(f"[red]inputs file is not valid JSON: {path} ({e})[/red]")
        sys.exit(2)
    missing = [f for f in required if f not in data or data[f] in (None, "", [])]
    if missing:
        for f in missing:
            console.print(f"[red]missing required input field: {f}[/red]")
        sys.exit(2)
    return data


def new_run_dir(base: str | None = None, account=None) -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if base:
        d = Path(base)
    elif account is not None:
        d = account.runs_dir / ts          # account runs stay inside the workspace
    else:
        d = Path("runs") / ts
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_account_or_exit(domain: str):
    from workspaces import WorkspaceError, load_account
    try:
        return load_account(domain)
    except WorkspaceError as e:
        console.print(f"[red]{e}[/red]")
        sys.exit(2)


def sqlite_checkpointer(run_dir: Path):
    """SQLite checkpointer (BUILD-SPEC §2, Phase 3) — checkpoint lives in the run dir."""
    import sqlite3

    from langgraph.checkpoint.sqlite import SqliteSaver
    conn = sqlite3.connect(run_dir / "checkpoint.sqlite", check_same_thread=False)
    return SqliteSaver(conn)


def cmd_audit(args) -> int:
    from graphs.audit_graph import build_audit_graph
    account = load_account_or_exit(args.account) if args.account else None
    run_dir = new_run_dir(args.out, account=account)
    graph = build_audit_graph(checkpointer=sqlite_checkpointer(run_dir))
    state = {"url": args.url}
    # explicit flags override account config; account fills the gaps
    gsc_path = args.gsc or (str(p) if account and (p := account.latest_gsc_export()) else None)
    if gsc_path:
        state["gsc_path"] = gsc_path
    if args.keyword:
        state["primary_query"] = args.keyword
    result = graph.invoke(state, config={"configurable": {"thread_id": run_dir.name}})
    (run_dir / "diagnosis.json").write_text(json.dumps(result.get("diagnosis"), indent=2))
    (run_dir / "master_report.md").write_text(result.get("master_report_md", ""))
    (run_dir / "runlog.md").write_text(_runlog_md(result.get("_runlog", []), result))
    (run_dir / "state.json").write_text(json.dumps(
        {k: v for k, v in result.items() if k != "page"}, indent=2, default=str))
    d = result.get("diagnosis", {})
    console.print(f"[green]audit complete — {len(d.get('defects', []))} defects, "
                  f"{len(d.get('keep_list', []))} keep-list items → {run_dir}[/green]")
    console.print(f"next: python run.py content --mode rebuild --diagnosis {run_dir / 'diagnosis.json'}"
                  + (f" --account {account.domain}" if account else " --inputs inputs.json"))
    return 0


def write_run_artifacts(run_dir: Path, result: dict) -> None:
    """Persist ledger, package, runlog, and a final state snapshot."""
    (run_dir / "ledger.json").write_text(json.dumps(result.get("facts_ledger", []), indent=2))
    package = result.get("package_out", {})
    (run_dir / "package_out.json").write_text(json.dumps(package, indent=2))
    (run_dir / "package_out.md").write_text(_package_md(package))
    (run_dir / "runlog.md").write_text(_runlog_md(result.get("_runlog", []), result))
    snapshot = {k: v for k, v in result.items() if k != "_runlog"}
    (run_dir / "state.json").write_text(json.dumps(snapshot, indent=2, default=str))


def _package_md(p: dict) -> str:
    lines = ["# Content Package", ""]
    lines += ["## Title variants"] + [f"- {t}" for t in p.get("title_variants", [])]
    lines += ["", f"**Meta:** {p.get('meta', '')}", "", "## Copy", "", p.get("full_copy", ""), ""]
    if p.get("internal_links"):
        lines += ["## Internal links"] + [f"- {l}" for l in p["internal_links"]]
    if p.get("human_checkpoints") or p.get("unresolved_verify"):
        lines += ["", "## Unresolved human checkpoints"]
        lines += [f"- {h}" for h in p.get("human_checkpoints", [])]
        lines += [f"- (VERIFY) {v}" for v in p.get("unresolved_verify", [])]
    return "\n".join(lines) + "\n"


def _runlog_md(runlog: list, result: dict) -> str:
    import yaml
    budgets = yaml.safe_load(Path("config.yaml").read_text()).get("budgets", {})
    total_cost = round(sum(e.get("cost_usd", 0) for e in runlog), 4)
    total_ms = round(sum(e.get("duration_ms", 0) for e in runlog), 1)
    lines = [
        "# Run log", "",
        f"- total cost: **${total_cost}** (budget ${budgets.get('max_cost_usd_per_page', '–')})",
        f"- total node time: **{total_ms / 1000:.1f}s** (budget {budgets.get('max_minutes_per_page', '–')} min)",
        f"- route-back counts: {result.get('route_back_count', {})}",
        "",
    ]
    if budgets.get("max_cost_usd_per_page") and total_cost > budgets["max_cost_usd_per_page"]:
        lines.insert(3, f"- ⚠️ **COST BUDGET EXCEEDED** (${total_cost} > ${budgets['max_cost_usd_per_page']})")
    for e in runlog:
        lines.append(f"## {e['node']}")
        lines.append(f"- output keys: {', '.join(e.get('output_keys', [])) or '(none)'}")
        if "duration_ms" in e:
            lines.append(f"- duration: {e['duration_ms']} ms" +
                         (f" · cost: ${e['cost_usd']}" if e.get("usage") else ""))
        for u in e.get("usage", []):
            lines.append(f"- model call: {u['model']} — {u['input_tokens']} in / {u['output_tokens']} out (${u['cost_usd']})")
        for g in e.get("guardrails", []):
            lines.append(f"- guardrail: {g}")
        lines.append("")
    return "\n".join(lines) + "\n"


def cmd_content(args) -> int:
    from graphs.content_graph import build_content_graph
    from state import (
        EscalateToHuman,
        HumanInputRequired,
        new_content_state,
        validate_diagnosis,
    )

    if args.resume:
        return _resume_content(Path(args.resume))
    if not args.mode:
        console.print("[red]--mode is required (or use --resume runs/<ts>)[/red]")
        return 2

    if getattr(args, "fake", False):
        from fakes import ScriptedLLM, make_cold_script, make_rebuild_script
        from llm import set_client
        script = make_cold_script() if args.mode == "net_new" else make_rebuild_script()
        set_client(ScriptedLLM(script))

    account = load_account_or_exit(args.account) if args.account else None
    acct = account.content_inputs() if account else {}
    run_dir = new_run_dir(args.out, account=account)
    (run_dir / "run.json").write_text(json.dumps(
        {"pipeline": "content", "mode": args.mode, "fake": bool(args.fake),
         "thread_id": run_dir.name}, indent=2))
    if args.mode == "net_new":
        # account config can satisfy fields so inputs.json may carry only the rest
        required = [f for f in NET_NEW_REQUIRED if f not in ("canonical_sources", "brand_assets", "audience") or not acct.get(f)]
        inputs = load_inputs(args.inputs, required)
        dossier = inputs.get("research_dossier", {})
        dossier.setdefault("business_context", inputs.get("business_context", ""))
        state = new_content_state(
            mode="net_new",
            page_type=inputs["page_type"],
            primary_keyword=inputs["seed_keyword"],
            research_dossier=dossier,
            brand_assets=inputs.get("brand_assets") or acct.get("brand_assets", {}),
            audience=inputs.get("audience") or acct.get("audience", ""),
            canonical_sources=inputs.get("canonical_sources") or acct.get("canonical_sources", []),
        )
    else:
        if not args.diagnosis:
            console.print("[red]--diagnosis is required for --mode rebuild[/red]")
            return 2
        diagnosis = json.loads(Path(args.diagnosis).read_text())
        validate_diagnosis(diagnosis)
        inputs = {}
        if args.inputs:
            required = [] if account else ["canonical_sources", "brand_assets", "audience"]
            inputs = load_inputs(args.inputs, required)
        elif not account:
            console.print("[red]rebuild needs --inputs inputs.json or --account <domain>[/red]")
            return 2
        state = new_content_state(
            mode="rebuild",
            page_type=diagnosis["page_type"],
            target_url=diagnosis["url"],
            primary_keyword=diagnosis["primary_query"],
            research_dossier=inputs.get("research_dossier", {}),
            brand_assets=inputs.get("brand_assets") or acct.get("brand_assets", {}),
            audience=inputs.get("audience") or acct.get("audience", ""),
            canonical_sources=inputs.get("canonical_sources") or acct.get("canonical_sources", []),
            gap_entity_matrix=diagnosis["gap_entity_matrix"],
            keep_list=diagnosis["keep_list"],
            failure_modes=[d["description"] for d in diagnosis["defects"]],
        )
        # inherit GSC head queries the audit surfaced (feeds intent governance)
        hq = (diagnosis.get("intent_contract") or {}).get("head_queries")
        if hq:
            state["head_queries"] = hq
    bp = inputs.get("brand_profile") or acct.get("brand_profile")
    if bp:
        state["brand_profile"] = bp
    # GSC head queries (real buyer vocabulary) — from --gsc or the brand's gsc/ folder
    gsc_path = args.gsc or (str(p) if account and (p := account.latest_gsc_export()) else None)
    if gsc_path and not state.get("head_queries"):
        from tools.gsc import parse_gsc_export
        try:
            state["head_queries"] = parse_gsc_export(gsc_path).get("queries", [])
            console.print(f"[dim]loaded {len(state['head_queries'])} GSC queries from {Path(gsc_path).name}[/dim]")
        except Exception as e:
            console.print(f"[yellow]could not parse GSC export {gsc_path}: {e}[/yellow]")
    if acct.get("source_precedence"):
        state["source_precedence"] = acct["source_precedence"]
    if account and account.sitemap:
        state["sitemap"] = account.sitemap
    cluster_map = inputs.get("cluster_map") or acct.get("cluster_map")
    if cluster_map:
        state["cluster_map"] = cluster_map
    graph = build_content_graph(checkpointer=sqlite_checkpointer(run_dir))
    config = {"configurable": {"thread_id": run_dir.name}, "recursion_limit": 100}
    try:
        result = graph.invoke(state, config=config)
    except HumanInputRequired as e:
        console.print(f"[yellow]HALT — human input required: {e}[/yellow]")
        return 1
    except EscalateToHuman as e:
        console.print(f"[red]Escalated to human: {e}[/red]")
        snapshot = graph.get_state(config).values
        write_run_artifacts(run_dir, snapshot)
        console.print(f"[yellow]partial artifacts → {run_dir}[/yellow]")
        return 1
    write_run_artifacts(run_dir, result)
    verdict = (result.get("critic_report") or {}).get("verdict", "?")
    console.print(f"[green]content run complete (critic: {verdict}) → {run_dir}[/green]")
    return 0


def _resume_content(run_dir: Path) -> int:
    """Resume an interrupted content run from its SQLite checkpoint (Phase 5)."""
    from graphs.content_graph import build_content_graph
    from state import EscalateToHuman

    meta_path = run_dir / "run.json"
    if not meta_path.exists():
        console.print(f"[red]no run.json in {run_dir} — not a resumable run[/red]")
        return 2
    meta = json.loads(meta_path.read_text())
    if not (run_dir / "checkpoint.sqlite").exists():
        console.print(f"[red]no checkpoint.sqlite in {run_dir}[/red]")
        return 2
    if meta.get("fake"):
        from fakes import ScriptedLLM, make_cold_script, make_rebuild_script
        from llm import set_client
        script = make_cold_script() if meta["mode"] == "net_new" else make_rebuild_script(poison_first_pass=False)
        set_client(ScriptedLLM(script))

    graph = build_content_graph(checkpointer=sqlite_checkpointer(run_dir))
    config = {"configurable": {"thread_id": meta["thread_id"]}, "recursion_limit": 100}
    if not graph.get_state(config).values:
        console.print(f"[yellow]checkpoint in {run_dir} is empty (run died before the first "
                      "node completed) — nothing to resume; start the run again.[/yellow]")
        return 2
    try:
        result = graph.invoke(None, config=config)  # None = continue from checkpoint
    except EscalateToHuman as e:
        console.print(f"[red]Escalated to human: {e}[/red]")
        return 1
    write_run_artifacts(run_dir, result)
    verdict = (result.get("critic_report") or {}).get("verdict", "?")
    console.print(f"[green]resumed run complete (critic: {verdict}) → {run_dir}[/green]")
    return 0


def cmd_eval(_args) -> int:
    from eval.run_eval import main as eval_main
    return eval_main()


def cmd_account(args) -> int:
    from workspaces import WorkspaceError, add_account, list_accounts, load_account
    if args.action in ("add", "show") and not args.domain:
        console.print(f"[red]account {args.action} requires a domain, e.g. `run.py account {args.action} example.com`[/red]")
        return 2
    try:
        if args.action == "add":
            root = add_account(args.domain)
            console.print(f"[green]brand created → {root}[/green]")
            console.print("Next: fill in account.yaml (canonical_sources, audience), "
                          "brand_profile.json (the selling brief), and brand_assets.json; "
                          "drop GSC exports into gsc/.")
        elif args.action == "list":
            accounts = list_accounts()
            if not accounts:
                console.print("no accounts yet — `python run.py account add <domain>`")
            for a in accounts:
                console.print(f"- {a}")
        elif args.action == "show":
            acc = load_account(args.domain)
            console.print_json(json.dumps({
                "domain": acc.domain,
                "audience": acc.audience,
                "canonical_sources": acc.canonical_sources,
                "source_precedence": acc.source_precedence,
                "sitemap": acc.sitemap,
                "gsc_mode": acc.gsc_mode,
                "latest_gsc_export": str(p) if (p := acc.latest_gsc_export()) else None,
                "brand_assets_keys": sorted(acc.brand_assets),
                "runs": sorted(p.name for p in acc.runs_dir.iterdir()) if acc.runs_dir.exists() else [],
            }))
    except WorkspaceError as e:
        console.print(f"[red]{e}[/red]")
        return 2
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="run.py", description="SEO/GEO agentic platform")
    sub = parser.add_subparsers(dest="command", required=True)

    p_audit = sub.add_parser("audit", help="Pipeline A: audit a live URL")
    p_audit.add_argument("--url", required=True)
    p_audit.add_argument("--account", help="workspace domain to run under (fills GSC + config)")
    p_audit.add_argument("--gsc")
    p_audit.add_argument("--keyword")
    p_audit.add_argument("--out")
    p_audit.set_defaults(fn=cmd_audit)

    p_content = sub.add_parser("content", help="Pipeline B: generate content")
    p_content.add_argument("--mode", choices=["rebuild", "net_new"])
    p_content.add_argument("--account", help="workspace domain to run under (fills canonical sources, brand assets, audience)")
    p_content.add_argument("--diagnosis")
    p_content.add_argument("--gsc", help="GSC export (zip/csv) → head queries for vocabulary mirroring")
    p_content.add_argument("--inputs")
    p_content.add_argument("--out")
    p_content.add_argument("--fake", action="store_true",
                           help="run with the offline scripted LLM (no API key needed)")
    p_content.add_argument("--resume", metavar="runs/<ts>",
                           help="resume an interrupted run from its checkpoint")
    p_content.set_defaults(fn=cmd_content)

    p_eval = sub.add_parser("eval", help="GO/KILL eval gate (rubric + seeded errors)")
    p_eval.set_defaults(fn=cmd_eval)

    p_account = sub.add_parser("account", help="manage multi-domain workspaces")
    p_account.add_argument("action", choices=["add", "list", "show"])
    p_account.add_argument("domain", nargs="?")
    p_account.set_defaults(fn=cmd_account)

    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
