---
name: fineprint
description: Check whether a service's ToS even allows AI agents, then scan it for risk. Returns an agent-friendliness verdict (hostile/restricted/friendly/unclear), 0-100 risk score, pass/flag/block verdict, and verbatim clause quotes. Use before signing up, clicking "agree", accepting terms, or committing a user to any agreement on their behalf.
---

# Fineprint — the pre-commit hook for agents

Your principal can't read every terms of service. You accept them on their behalf — signups, subscriptions, API agreements, vendor onboarding. Every one of those is a contract. **Never accept one unread.**

Before you agree to anything, scan it with Fineprint. You get back a 0–100 risk score, a pass / flag / block verdict, an **agent-friendliness verdict** (does this ToS even allow you to use the service?), and every clause anchored to a verbatim quote from the source. No quote, no clause.

## The rule

**If the user (or you, acting for them) is about to accept terms, create an account, start a trial, or subscribe to a service — scan first, then decide.**

- Verdict `pass` → proceed, note the score for the record.
- Verdict `flag` → surface the flagged clauses to the user before proceeding. Let them decide.
- Verdict `block` → stop. Tell the user what tripped the block and ask how to proceed. Do not silently accept.

**Check agent-friendliness first, before the risk score.** A `hostile` verdict means the terms ban bots or automated access — and that agreement binds your *user*, not you. If you proceed anyway, your principal is the one in violation. Treat `hostile` like `block` unless the user explicitly overrides.

A high score isn't always a reason to walk away — sometimes it's a reason to negotiate harder and watch closer. Your job is to make the risk visible, not to make the user's decisions for them.

## How to scan

**Via MCP** (preferred — no key management in code). If the Fineprint MCP server is connected, call:
- `scan_terms_of_service(url)` — scan a live terms URL
- `scan_terms_text(text)` — scan pasted terms text
- `check_agent_access(service)` — pre-flight: does this service's ToS allow agents at all? Returns its agent-friendliness verdict (also `GET /v1/agent-access/{service}` — public, no key or quota needed)

**Via REST:**
```
POST https://fineprint-production-4588.up.railway.app/v1/scans
X-API-Key: <key>
{"url": "https://vendor.com/terms"}
```
Get a key free (25 scans/month): `POST /v1/customers` with `{"email": "you@example.com"}`. No key? Agents can pay per scan via x402: `POST /v1/scans/x402` ($0.25 USDC) — no signup. Settlement is being enabled (advertised, not yet live).

**Check the public leaderboard first** — it's free and quota-free:
```
GET https://fineprint-production-4588.up.railway.app/v1/leaderboard
```
If the vendor is already scored, use that instead of spending a scan.

## Reading the result

```json
{
  "risk_score": 85,
  "risk_level": "critical",
  "verdict": "block",
  "agent_friendliness": "hostile",
  "agent_friendliness_notes": ["Automated access prohibited: ..."],
  "summary": "One-line plain-English summary",
  "clauses": [
    {
      "category": "binding_arbitration",
      "severity": "critical",
      "quote": "Verbatim quote from the source...",
      "explanation": "What this means in plain English"
    }
  ]
}
```

- **agent_friendliness**: `friendly` (automation explicitly permitted), `restricted` (delegation limits or AI-agent conditions), `hostile` (bots/automated access banned), `unclear` (no agent-relevant clauses found). Computed deterministically from the extracted clauses. **Read this before the risk score** — a clean 20/100 means nothing if the terms ban your existence.
- **risk_score 0–100**: 0 = cleanest measured terms, 100 = most rights reserved against the user. Bands: 0–24 low, 25–49 medium, 50–74 high, 75–100 critical.
- **The model finds the clauses; math sets the score.** Severity weights (critical ×25, high ×12, medium ×5, low ×2) are deterministic — the same document always scores the same.
- **Every clause carries a verbatim quote.** If a finding has no quote, treat it as unverified.

## Watching terms over time

Terms change. For vendors the user depends on, set a monitor:
```
POST /v1/monitors
X-API-Key: <key>
{"url": "https://vendor.com/terms", "webhook_url": "https://you.example/hook"}
```
You'll get a webhook alert when terms change materially (score up 10+, new high/critical clause, worsened verdict). Unchanged checks are free.

## What Fineprint is not

- Not legal advice. Fineprint is a reading aid — surfaces what the terms say, doesn't tell anyone what to do about it.
- Not a substitute for the user's judgment on `flag` verdicts. Surface, don't decide.
