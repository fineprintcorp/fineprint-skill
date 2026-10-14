#!/usr/bin/env python3
"""Blocked-action demo: an agent that checks the terms BEFORE onboarding.

Simulates an onboarding agent with a standing policy:

  * never automate against terms that prohibit it;
  * official channels only where the terms restrict automation;
  * when permission is unclear, stop and escalate to the human.

Every score, verdict, and quote comes from Fineprint's live public
leaderboard (no API key needed). Fineprint returns the decision and the
evidence; the host application (here, this script) enforces it.

Usage:
    python3 demo/agent_onboarding_demo.py                 # discord, github, duckduckgo
    python3 demo/agent_onboarding_demo.py stripe figma    # your pick

Env:
    FINEPRINT_API_URL   default https://fineprint-production-4588.up.railway.app
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request

BASE = os.environ.get(
    "FINEPRINT_API_URL", "https://fineprint-production-4588.up.railway.app"
).rstrip("/")

AGENT_CATEGORIES = [
    "bot_automation_ban",
    "automation_permitted",
    "account_delegation",
    "ai_agent_terms",
]


def fetch_leaderboard() -> list[dict]:
    req = urllib.request.Request(
        f"{BASE}/v1/leaderboard?limit=50",
        headers={"User-Agent": "fineprint-onboarding-demo/1.0"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp).get("entries", [])


def agent_clause(entry: dict) -> dict | None:
    top = entry.get("top_clauses") or []
    for cat in AGENT_CATEGORIES:
        for clause in top:
            if clause.get("category") == cat:
                return clause
    return top[0] if top else None


def run_agent(entry: dict) -> str:
    """Run the simulated onboarding agent against one leaderboard entry.
    Returns the outcome: BLOCKED / PROCEED / PROCEED (official channels) /
    ESCALATED."""
    name = entry["service"]
    friendliness = entry.get("agent_friendliness", "unclear")
    print(f"▸ TASK — Onboard {name}: create an account and start using it "
          f"on behalf of my principal.")
    print(f"▸ PRE-FLIGHT — Before accepting any terms, checking {name} "
          f"with Fineprint…")
    print(f"  Fineprint: risk {entry['risk_score']}/100 "
          f"({entry['risk_level']}) · agent-friendliness: "
          f"{friendliness.upper()} · {entry['clause_count']} clauses on record")
    clause = agent_clause(entry)
    if clause:
        evidence = clause.get("quote") or clause.get("title", "")
        print(f"  Evidence [{clause['category']} · {clause['severity']}]: "
              f"\"{evidence}\"")
    print("▸ POLICY — Never automate against prohibiting terms · official "
          "channels only where restricted · unclear permission means stop "
          "and ask.")
    if friendliness == "hostile":
        print("■ BLOCKED — These terms prohibit the automated access this "
              "onboarding requires. The account was NOT created and no "
              "terms were accepted.")
        print(f"→ ESCALATION TO PRINCIPAL — \"I stopped the {name} "
              f"onboarding: its terms prohibit automated access, and the "
              f"violation would fall on you. Options: get written permission "
              f"first, use it manually, or pick an alternative — I can "
              f"check one in seconds.\"")
        return "BLOCKED"
    if friendliness == "restricted":
        print("■ PROCEED — OFFICIAL CHANNELS ONLY. Automation is permitted "
              "through the vendor's official API/OAuth and prohibited "
              "outside it. Plan adjusted: no scraping, no unofficial "
              "clients.")
        return "PROCEED (official channels only)"
    if friendliness == "friendly":
        print("■ PROCEED — Automation is explicitly permitted by the terms.")
        return "PROCEED"
    print("■ ESCALATED — The terms neither permit nor prohibit agent use. "
          "No evidence of permission is not permission: onboarding paused "
          "until a human decides.")
    return "ESCALATED"


def main(argv: list[str]) -> int:
    entries = fetch_leaderboard()
    by_service = {e["service"]: e for e in entries}
    wanted = [a.lower() for a in argv] or ["discord", "github", "duckduckgo"]
    outcomes = {}
    for service in wanted:
        entry = by_service.get(service)
        if entry is None:
            print(f"! {service}: not on the public leaderboard "
                  f"({', '.join(sorted(by_service))})")
            continue
        outcomes[service] = run_agent(entry)
        print()
    print("Summary:", " · ".join(f"{s} → {o}" for s, o in outcomes.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
