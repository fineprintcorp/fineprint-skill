"""Fineprint MCP server — the API as native agent tools.

Agents discover tools through MCP. This server exposes Fineprint's scanning,
retrieval, and leaderboard endpoints as MCP tools so any MCP-capable agent
(Claude, Cursor, ChatGPT, etc.) can call Fineprint without reading docs.

Config (env):
  FINEPRINT_API_URL  Base URL of the Fineprint API (default https://fineprint-production-4588.up.railway.app)
  FINEPRINT_API_KEY  API key from POST /v1/customers (required for scan tools)
  When served over HTTP (the hosted /mcp endpoint in api.py, or --http
  mode), per-request caller keys are read from the X-API-Key /
  Authorization header, and keyless callers fall back to per-IP anonymous
  trial keys. Stdio mode has no request context and always uses the env
  key — the HTTP fallback keys off the request context's presence, never
  a global flag, so the two modes can't leak into each other.

Run:
  FINEPRINT_API_KEY=fp_live_YOUR_API_KEY_HERE python mcp_server.py        # stdio (default)
  FINEPRINT_API_KEY=fp_live_YOUR_API_KEY_HERE python mcp_server.py --http  # streamable HTTP on :8001 (root path)

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
from mcp.server.transport_security import TransportSecuritySettings

from legal import DISCLAIMER

API_URL = os.environ.get("FINEPRINT_API_URL", "https://fineprint-production-4588.up.railway.app").rstrip("/")
API_KEY = os.environ.get("FINEPRINT_API_KEY", "")

# stateless_http + json_response: the hosted mount serves many unrelated
# callers; per-request JSON responses need no session bookkeeping.
# streamable_http_path="/" so api.py can mount this app at exactly /mcp.
# transport_security: the SDK's DNS-rebinding protection rejects unknown
# Host headers with 421, so the production host must be allowlisted (plus
# loopback for local use/tests). Extra hosts (e.g. a future custom domain)
# can be added via FINEPRINT_MCP_ALLOWED_HOSTS, comma-separated.
_extra_hosts = [
    h.strip()
    for h in os.environ.get("FINEPRINT_MCP_ALLOWED_HOSTS", "").split(",")
    if h.strip()
]
mcp = FastMCP(
    "fineprint",
    stateless_http=True,
    json_response=True,
    streamable_http_path="/",
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[
            "fineprint-production-4588.up.railway.app",
            "fineprint-production-4588.up.railway.app:*",
            "127.0.0.1:*",
            "localhost:*",
            "[::1]:*",
            "testserver",
            "testserver:*",
        ]
        + _extra_hosts
        + [f"{h}:*" for h in _extra_hosts],
        allowed_origins=[
            "https://fineprint-production-4588.up.railway.app",
            "https://fineprint-production-4588.up.railway.app:*",
            "http://127.0.0.1:*",
            "http://localhost:*",
            "http://testserver",
        ],
    ),
)

class ApiError(RuntimeError):
    pass


def _request_headers():
    """Headers of the current MCP-over-HTTP request, or None (stdio mode,
    or outside a request). Never raises."""
    try:
        ctx = mcp.get_context()
        req = ctx.request_context.request
        return req.headers if req is not None else None
    except Exception:
        return None


def _caller_key() -> str | None:
    """The hosted caller's own API key, from the X-API-Key header or an
    Authorization: Bearer header on the MCP request."""
    h = _request_headers()
    if not h:
        return None
    key = h.get("x-api-key")
    if key:
        return key.strip()
    auth = h.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    return None


def _caller_xff() -> str | None:
    h = _request_headers()
    return h.get("x-forwarded-for") if h else None


# Anonymous trial keys for keyless hosted callers, cached per caller IP for
# the life of the process. The API caps anonymous issuance per IP per day,
# so re-minting per call would burn the cap; one key per IP is the design.
_anon_keys: dict[str, str] = {}


def _anon_key() -> str:
    xff = _caller_xff() or ""
    ip = xff.split(",")[-1].strip() if xff else "hosted-local"
    key = _anon_keys.get(ip)
    if key:
        return key
    if len(_anon_keys) > 10_000:  # unbounded-IP safety valve
        _anon_keys.clear()
    # ref tags these keys in the admin traffic split as external agents
    # arriving via the hosted MCP endpoint (not internal, not direct).
    data = _call("POST", "/v1/customers/anonymous", {"ref": "mcp-hosted"}, auth=False)
    key = data["api_key"]
    _anon_keys[ip] = key
    return key


def _call(method: str, path: str, body: dict | None = None, auth: bool = True) -> dict:
    headers = {"Content-Type": "application/json"}
    # Forward the caller's X-Forwarded-For so the API's per-IP logic
    # (anonymous issuance caps, analytics) sees the real caller, not the
    # loopback hop from the hosted MCP layer.
    xff = _caller_xff()
    if xff:
        headers["X-Forwarded-For"] = xff
    if auth:
        key = _caller_key() or API_KEY
        if not key and _request_headers() is not None:
            # HTTP transport with no caller key: anonymous trial fallback.
            key = _anon_key()
        if not key:
            raise ApiError(
                "FINEPRINT_API_KEY is not set. Create one: "
                "POST /v1/customers on the Fineprint API."
            )
        headers["X-API-Key"] = key
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
    aa = report.get("agent_access") or {}
    if aa:
        lines.append(
            f"Agent access: automated={aa.get('automated_access')}, "
            f"delegation={aa.get('account_delegation')}, "
            f"ai_terms={aa.get('ai_agent_terms')}, "
            f"official_channels_required={aa.get('official_channels_required')} "
            f"(friendliness verdict: {report.get('agent_friendliness')})"
        )
    if report.get("analysis_complete") is False:
        lines.append("WARNING: analysis incomplete — the document was truncated; findings cover only part of it and this is not a clean pass.")
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
    return json.dumps(_call("GET", f"/v1/scans/{urllib.parse.quote(scan_id, safe='')}"))


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
def check_agent_access(service: str) -> str:
    """Pre-flight check: can an AI agent use this service at all, and on
    what terms? Answers from Fineprint's published leaderboard WITHOUT a
    scan and without spending quota — call this BEFORE scan_terms_of_service
    or before signing a principal up for anything. Returns the structured
    decision (automated access, account delegation, AI-agent terms,
    official-channels requirement) plus the overall friendliness verdict.
    If the service is unknown, run scan_terms_of_service on its terms URL."""
    data = _call("GET", f"/v1/agent-access/{urllib.parse.quote(service)}",
                 auth=False)
    if not data.get("known"):
        return (
            f"{service}: no verified scan published yet. "
            "Use scan_terms_of_service with the service's terms URL to check it.\n"
            f"Disclaimer: {DISCLAIMER}"
        )
    acc = data.get("agent_access") or {}
    channels = acc.get("official_channels_required")
    channels_s = (
        "yes — official channels only" if channels is True
        else "no" if channels is False
        else "unknown"
    )
    lines = [
        f"{data['service']}: agent-friendliness {str(data.get('agent_friendliness', 'unclear')).upper()}"
        f" · risk {data.get('risk_score')}/100 ({data.get('risk_level')})",
        f"- Automated access: {acc.get('automated_access', 'unclear')}",
        f"- Account delegation: {acc.get('account_delegation', 'unclear')}",
        f"- AI-agent terms: {acc.get('ai_agent_terms', 'not_mentioned')}",
        f"- Official channels required: {channels_s}",
    ]
    for note in (data.get("agent_friendliness_notes") or [])[:3]:
        lines.append(f"  · {note}")
    lines.append(f"Full report: {data.get('full_report')}")
    lines.append(f"Disclaimer: {DISCLAIMER}")
    return "\n".join(lines)


@mcp.tool()
def terms_check(service: str = "", url: str = "", action: str = "") -> str:
    """Get a signed Act-Time Terms Receipt BEFORE acting on a service:
    what its terms said at this moment (risk score, agent-friendliness
    verdict, the verbatim clauses behind it), pinned to the terms
    document's hash and signed so anyone can verify it later — the
    evidence record for 'the agent checked before it acted'. Pass
    `service` for a published leaderboard service (e.g. 'discord') or
    `url` for any terms document. `action` optionally records what the
    agent was about to do (stored as caller-asserted; it is never
    witnessed). A receipt served from the board/cache costs no scan unit
    (monthly allowance); one that triggers a fresh scan consumes one."""
    body: dict = {}
    if service:
        body["service"] = service
    if url:
        body["url"] = url
    if action:
        body["action_context"] = {"action": action}
    if not body:
        return "Provide a service slug (e.g. 'discord') or a terms URL."
    data = _call("POST", "/v1/terms-check", body)
    lines = [
        f"Terms receipt {data['receipt_id']} — {data.get('service') or data.get('source_url')}",
        f"Risk: {data['risk_score']}/100 ({data['risk_level']}); "
        f"agent access: {data['agent_friendliness']}",
        f"Pinned terms hash: {data.get('content_hash')}",
        f"Verify: {data.get('verify_url')}",
        "Top clauses:",
    ]
    for c in data.get("top_clauses", []):
        lines.append(f"- [{c['severity']}] {c['title']} ({c['category']})")
    lines.append(f"Disclaimer: {DISCLAIMER}")
    return "\n".join(lines)


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
    Categories come from the 21-category taxonomy, e.g.
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
    data = _call("GET", f"/v1/scans/{urllib.parse.quote(scan_id, safe='')}/playbook")
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
