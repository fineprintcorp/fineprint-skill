# fineprint skill

**The pre-commit hook for agents.** Never accept terms unread.

This skill teaches your agent to scan terms of service with [Fineprint](https://fineprint-production-4588.up.railway.app/?ref=cursor) before accepting them on your behalf — signups, subscriptions, vendor agreements. Returns a 0–100 risk score, a pass/flag/block verdict, an agent-friendliness verdict (does the ToS even allow agents?), and every clause anchored to a verbatim quote.

## Install

```bash
npx skills add fineprintcorp/fineprint-skill --skill fineprint -g
```

## What the agent learns

- **The rule:** if you're about to accept terms, create an account, or subscribe to a service — scan first, then decide.
- **Check agent-friendliness first:** `hostile` means the ToS bans bots/automated access — and the violation lands on the user, not the agent. Treat like `block`.
- **Verdict handling:** `pass` → proceed · `flag` → surface clauses to the user · `block` → stop and ask.
- **Three ways to scan:** MCP server, REST API (free key, 25 scans/mo), or x402 pay-per-scan ($0.25, no signup).
- **Check the free leaderboard first** before spending a scan.
