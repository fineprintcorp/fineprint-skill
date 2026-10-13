"""Fineprint MCP server — the API as native agent tools.

Agents discover tools through MCP. This server exposes Fineprint's scanning,
retrieval, and leaderboard endpoints as MCP tools so any MCP-capable agent
(Claude, Cursor, ChatGPT, etc.) can call Fineprint without reading docs.

Config (env):
  FINEPRINT_API_URL  Base URL of the Fineprint API (default http://localhost:8000)
  FINEPRINT_API_KEY  API key from POST /v1/customers (required for scan tools)

Run:
  FINEPRINT_API_KEY=fp_live_YOUR_API_KEY_HERE python mcp_server.py        # stdio (default)
  FINEPRINT_API_KEY=fp_live_YOUR_API_KEY_HERE python mcp_server.py --http  # streamable HTTP on :8001

Claude Code:
  claude mcp add fineprint --env FINEPRINT_API_KEY=fp_live_YOUR_API_KEY_HERE -- python /path/to/mcp_server.py
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
import urllib.error
import urllib.parse

from mcp.server.fastmcp import FastMCP

from legal import DISCLAIMER

API_URL = os.environ.get("FINEPRINT_API_URL", "http://localhost:8000").rstrip("/")
API_KEY = os.environ.get("FINEPRINT_API_KEY", "")

mcp = FastMCP("fineprint")


class ApiError(RuntimeError):
    pass


def _call(method: str, path: str, body: dict | None = None, auth: bool = True) -> dict:
    headers = {"Content-Type": "application/json"}
    if auth:
        if not API_KEY:
            raise ApiError(
                "FINEPRINT_API_KEY is not set. Create one: "
                "POST /v1/customers on the Fineprint API."
            )
        headers["X-API-Key"] = API_KEY
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        API_URL + path, data=data, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode()).get("detail", e.reason)
        except Exception:
            detail = e.reason
        raise ApiError(f"API {e.code}: {detail}")
    except urllib.error.URLError as e:
        raise ApiError(
            f"Cannot reach the Fineprint API at {API_URL} ({e.reason}). "
            "Is it running, and is FINEPRINT_API_URL correct?"
        )


def _summarize(report: dict, cached: bool = False) -> str:
    lines = [
        f"Risk {report['risk_score']}/100 ({report['risk_level'].upper()})"
        f" — verdict: {report['verdict'].upper()}"
        + (" [cached]" if cached or report.get("meta", {}).get("cached") else ""),
        f"Service: {report.get('source_url') or 'pasted text'}",
        f"Clauses found: {len(report['clauses'])}",
    ]
    rank = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    top = sorted(report["clauses"], key=lambda c: rank.get(c["severity"], 9))[:5]
    if top:
        lines.append("Top clauses:")
        for c in top:
            lines.append(f"- [{c['severity']}] {c['category']}: \"{c['quote'][:160]}\"")
    if report.get("dealbreakers"):
        lines.append(f"Dealbreakers (block rules hit): {', '.join(report['dealbreakers'])}")
    if report.get("recommended_actions"):
        lines.append("Recommended actions:")
        lines.extend(f"  * {a}" for a in report["recommended_actions"][:4])
    lines.append(f"Full report id: {report['id']} (use get_scan_report for the JSON)")
    lines.append(f"Disclaimer: {DISCLAIMER}")
    return "\n".join(lines)


@mcp.tool()
def scan_terms_of_service(url: str, policy_id: str | None = None) -> str:
    """Scan a terms-of-service / privacy-policy URL for risky clauses.

    Call this BEFORE the agent accepts terms, creates an account, or grants a
    vendor access to the principal's data. Returns a risk score (0-100), a
    pass/flag/block verdict, and the top clauses with verbatim quotes.
    Informational assessment only — not legal advice.
    """
    body = {"url": url}
    if policy_id:
        body["policy_id"] = policy_id
    return _summarize(_call("POST", "/v1/scans", body))


@mcp.tool()
def scan_terms_text(text: str, source_url: str | None = None, policy_id: str | None = None) -> str:
    """Scan pasted terms text (when no URL is available). Same contract as
    scan_terms_of_service: risk score, verdict, quoted clauses.
    Informational assessment only — not legal advice."""
    body = {"text": text}
    if source_url:
        body["source_url"] = source_url
    if policy_id:
        body["policy_id"] = policy_id
    return _summarize(_call("POST", "/v1/scans", body))


@mcp.tool()
def get_scan_report(scan_id: str) -> str:
    """Retrieve a previous scan report as JSON (all clauses, quotes, scores)."""
    return json.dumps(_call("GET", f"/v1/scans/{scan_id}"))


@mcp.tool()
def get_tos_leaderboard(limit: int = 10, query: str | None = None) -> str:
    """Public ranking of services by ToS risk score. No API key needed.
    Use it to compare vendors BEFORE spending a scan. Scores are Fineprint's
    automated assessment as of the published date — informational only, not
    legal advice."""
    path = f"/v1/leaderboard?limit={max(1, min(limit, 50))}"
    if query:
        path += f"&q={urllib.parse.quote(query)}"
    data = _call("GET", path, auth=False)
    lines = ["ToS risk leaderboard (higher = riskier):"]
    for e in data["entries"]:
        stale = " [stale]" if e.get("stale") else ""
        lines.append(
            f"- {e['service']}: {e['risk_score']}/100 ({e['risk_level']})"
            f", {e['clause_count']} clauses{stale}"
        )
    lines.append(f"Disclaimer: {DISCLAIMER}")
    return "\n".join(lines) if data["entries"] else "Leaderboard is empty."


@mcp.tool()
def check_quota() -> str:
    """Show the API key's tier, remaining monthly scans, and overage status."""
    me = _call("GET", "/v1/me")
    out = (
        f"Tier: {me['tier']}, scans included: {me['scans_included']}, "
        f"remaining this month: {me['scans_remaining']}"
    )
    if me.get("overage_enabled"):
        out += (
            f". Overage active: ${me['overage_usd_per_scan']:.2f}/scan, "
            f"{me['overage_scans_this_month']} overage scans this month."
        )
    return out


@mcp.tool()
def batch_scan_terms(urls: list[str], policy_id: str | None = None) -> str:
    """Scan up to 20 vendor ToS URLs in one call; each scan costs one quota
    unit. Returns a ranking (riskiest first) with scores, verdicts, and top
    clause categories per vendor. Use this for vendor shortlists and bake-offs."""
    if not urls:
        raise ApiError("Provide at least one url.")
    body: dict = {"urls": urls[:20]}
    if policy_id:
        body["policy_id"] = policy_id
    data = _call("POST", "/v1/scans/batch", body)
    lines = [
        f"Batch complete: {data['succeeded']} succeeded, {data['failed']} failed."
    ]
    rank = {sid: i + 1 for i, sid in enumerate(data["ranking"])}
    ok = sorted(
        (r for r in data["results"] if r["ok"]),
        key=lambda r: rank.get(r["scan_id"], 999),
    )
    for r in ok:
        lines.append(
            f"#{rank[r['scan_id']]} {r['url']}: {r['risk_score']}/100 "
            f"({r['risk_level']}) — {r['verdict'].upper()} "
            f"[top: {', '.join(r['top_clauses']) or 'none'}] id={r['scan_id']}"
        )
    for r in data["results"]:
        if not r["ok"]:
            lines.append(f"FAILED {r['url']}: {r['error']}")
    lines.append(f"Disclaimer: {DISCLAIMER}")
    return "\n".join(lines)


@mcp.tool()
def compare_scans(scan_ids: list[str]) -> str:
    """Compare 2-20 previous scans: vendor ranking plus a category-by-category
    matrix of worst severity per vendor. Free — uses already-paid-for scans."""
    if len(scan_ids) < 2:
        raise ApiError("Compare needs at least 2 scan_ids.")
    data = _call("POST", "/v1/scans/compare", {"scan_ids": scan_ids[:20]})
    lines = ["Vendor ranking (riskiest first):"]
    for v in data["vendors"]:
        lines.append(
            f"- {v['label']}: {v['risk_score']}/100 — {v['verdict'].upper()}"
        )
    lines.append("Category matrix (worst severity per vendor; — = not found):")
    header = "category | " + " | ".join(data["vendors"] and [v["label"] for v in data["vendors"]])
    lines.append(header)
    for cat in data["categories"]:
        cells = [data["cells"][cat].get(v["label"]) or "—" for v in data["vendors"]]
        lines.append(f"{cat} | " + " | ".join(cells))
    lines.append(f"Disclaimer: {DISCLAIMER}")
    return "\n".join(lines)


@mcp.tool()
def watch_terms(
    url: str, interval_days: int = 7, webhook_url: str | None = None
) -> str:
    """Watch a terms-of-service URL for changes. Establishes a quoted,
    scored baseline NOW, then every check compares the live document to it:
    unchanged checks are free, changed documents are re-scanned and diffed,
    and material changes (score jump, new high/critical clause, worsened
    verdict) raise an alert, POSTed to webhook_url when set.

    Use this when the principal depends on a vendor long-term: the agent
    should know when the terms it agreed to change underneath it.
    """
    body: dict = {"url": url, "interval_days": max(1, min(interval_days, 90))}
    if webhook_url:
        body["webhook_url"] = webhook_url
    m = _call("POST", "/v1/monitors", body)
    b = m["baseline"]
    return (
        f"Monitoring {m['url']} (id {m['id']}, every {m['interval_days']}d).\n"
        f"Baseline: risk {b['risk_score']}/100 ({b['risk_level']}), "
        f"verdict {b['verdict'].upper()}, {b['clause_count']} clauses.\n"
        f"Checks are free until the document changes; a changed document "
        f"consumes 1 scan. POST /v1/monitors/check-due (or the list_monitors "
        f"tool's check hint) drives scheduled checks."
    )


@mcp.tool()
def list_monitors() -> str:
    """List watched ToS URLs: baseline scores, last check time, limits."""
    data = _call("GET", "/v1/monitors")
    if not data["monitors"]:
        return "No monitors. Use watch_terms to start watching a vendor's terms."
    lines = [
        f"Monitors: {data['count']}/{data['limit']} used.",
        "Drive scheduled checks with POST /v1/monitors/check-due.",
    ]
    for m in data["monitors"]:
        b = m["baseline"]
        lines.append(
            f"- {m['service']} ({m['id']}): baseline {b['risk_score']}/100 "
            f"{b['verdict'].upper()}, last checked {m['last_checked_at']}"
        )
    return "\n".join(lines)


@mcp.tool()
def list_policies() -> str:
    """List the ToS risk policies available to you: the built-in system
    policies (standard, strict, procurement) plus any custom policies you
    have created. Pass a policy id as policy_id to any scan tool to judge
    vendors by your principal's rules instead of the default."""
    data = _call("GET", "/v1/policies")
    lines = []
    for p in data:
        tag = "built-in" if p.get("system") else "custom"
        nb = sum(1 for r in p["rules"] if r["action"] == "block")
        nf = sum(1 for r in p["rules"] if r["action"] == "flag")
        lines.append(f"- {p['id']} [{tag}]: {p['name']} — {nb} block, {nf} flag rules.")
        if p.get("description"):
            lines.append(f"  {p['description']}")
    return "\n".join(lines) if lines else "No policies available."


@mcp.tool()
def create_policy(
    name: str,
    block_categories: list[str] | None = None,
    flag_categories: list[str] | None = None,
    description: str = "",
) -> str:
    """Create a custom ToS risk policy owned by your API key — your
    principal's own dealbreakers. block_categories veto a vendor (verdict
    BLOCK); flag_categories mark findings for review (verdict FLAG).
    Categories come from the 17-category taxonomy, e.g.
    binding_arbitration, data_training_use, data_sharing_resale,
    auto_renewal, unilateral_price_change. Use list_policies to see ids."""
    rules = []
    for c in block_categories or []:
        rules.append({"id": f"block-{c}", "clause_category": c, "action": "block"})
    for c in flag_categories or []:
        rules.append({"id": f"flag-{c}", "clause_category": c, "action": "flag"})
    data = _call(
        "POST",
        "/v1/policies",
        {"name": name, "description": description, "rules": rules},
    )
    return (
        f"Policy created: {data['id']} ({data['name']}) — "
        f"{len(data['rules'])} rules. Pass policy_id=\"{data['id']}\" "
        "to scan tools to enforce it."
    )


@mcp.tool()
def get_negotiation_playbook(scan_id: str) -> str:
    """Negotiation playbook for a previous scan: for each flagged clause, what
    to ask the vendor for, an acceptable fallback, your leverage, and the
    walk-away signal. Use this when procurement or legal needs to push back
    on a vendor's terms. Negotiation guidance, not legal advice."""
    data = _call("GET", f"/v1/scans/{scan_id}/playbook")
    if not data["entries"]:
        return f"No playbook entries for scan {scan_id} (no flagged clauses)."
    lines = [
        f"Negotiation playbook — {data['source_url'] or scan_id} "
        f"({data['risk_score']}/100, {data['verdict'].upper()}):"
    ]
    for e in data["entries"]:
        lines.append(f"\n[{e['severity'].upper()}] {e['title']} ({e['category']})")
        lines.append(f"  Ask for: {e['what_to_ask']}")
        lines.append(f"  Fallback: {e['fallback']}")
        lines.append(f"  Leverage: {e['leverage']}")
        lines.append(f"  Walk away if: {e['walk_away']}")
    lines.append(f"\nDisclaimer: {data['disclaimer']}")
    return "\n".join(lines)


if __name__ == "__main__":
    if "--http" in sys.argv:
        mcp.run(transport="streamable-http", host="127.0.0.1", port=8001)
    else:
        mcp.run()
