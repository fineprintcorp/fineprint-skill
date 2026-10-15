# Fineprint MCP Server

**The pre-commit hook for agents.** Never accept terms unread.

This repository contains the MCP server implementation for
[Fineprint](https://fineprint-production-4588.up.railway.app/), the
terms-of-service risk API for AI agents. The server scans a service's
terms before an agent accepts them — signups, subscriptions, vendor
agreements — and returns a 0–100 risk score, a pass/flag/block verdict,
an agent-friendliness verdict (does the ToS even allow agents?), and
every clause anchored to a verbatim quote.

## The MCP server

- **Implementation:** `mcp/mcp_server.py` — a FastMCP (Python) server
  exposing 13 tools covering scans by URL or text, agent-access checks,
  the public leaderboard, scan retrieval and PDF reports, monitors, and
  policy evaluation.
- **Container:** `mcp/Dockerfile`; published image
  `ghcr.io/fineprintcorp/fineprint-mcp` — also listed in the official MCP
  Registry as `io.github.fineprintcorp/fineprint` (see `server.json`).
- **Config:** `FINEPRINT_API_URL` (defaults to the production API) and
  `FINEPRINT_API_KEY` (free key from the API signup; free tier is
  25 scans/mo).

Run it locally:

```bash
cd mcp
FINEPRINT_API_KEY=<your key> python mcp_server.py
```

Claude Code:

```bash
claude mcp add fineprint --env FINEPRINT_API_KEY=<your key> -- python mcp/mcp_server.py
```

Or run the published container image — `server.json` carries the exact
package and environment declaration.

## The agent skill

The repository also ships a skill that teaches an agent *when* to call
the server:

- **The rule:** if you're about to accept terms, create an account, or subscribe to a service — scan first, then decide.
- **Check agent-friendliness first:** `hostile` means the ToS bans bots/automated access — and the violation lands on the user, not the agent. Treat like `block`.
- **Verdict handling:** `pass` → proceed · `flag` → surface clauses to the user · `block` → stop and ask.
- **Three ways to scan:** MCP server, REST API (free key, 25 scans/mo), or x402 pay-per-scan ($0.25, no signup; settlement being enabled).
- **Check the free leaderboard first** before spending a scan.

Install the skill:

```bash
npx skills add fineprintcorp/fineprint-skill --skill fineprint -g
```

Full skill text: `SKILL.md`. A zero-key demo lives in `demo/`.

## License

MIT (see `LICENSE`).
