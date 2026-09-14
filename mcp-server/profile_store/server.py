#!/usr/bin/env python3
"""Stdio MCP server exposing the Upwork proposal agent's profile store.

Five tools:
  - get_experience()                       -> full experience_profile.json content
  - get_past_proposals(filter?, limit, offset)  -> lightweight, paginated proposal_log summaries
  - get_proposal_detail(proposal_id)       -> one full proposal_log record, including full_draft
  - issue_gate_token(proposal_id)          -> single-use token required to log an "approved" decision
  - log_decision(...)                      -> append a decision record to proposal_log.json

The actual read/write logic lives in store.py, shared with the FastAPI
wrapper in api.py so both transports behave identically.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mcp.server.mcpserver import MCPServer  # noqa: E402
from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402

import store  # noqa: E402

mcp = MCPServer("profile_store")


@mcp.tool()
def get_experience() -> dict:
    """Return the full experience_profile.json content — the single source of
    truth for real, evidence-backed work history. Never fabricate entries;
    this is exactly what is on disk."""
    return store.get_experience()


@mcp.tool()
def get_past_proposals(
    filter: dict | None = None, limit: int = store.DEFAULT_LIST_LIMIT, offset: int = 0
) -> dict:
    """Return a lightweight, paginated page of proposal_log entries, newest
    first — NEVER includes full_draft, so it's safe to call without
    flooding your context as the log grows. Keep `limit` small; call
    get_proposal_detail(proposal_id) only for a specific entry you actually
    need in full.

    filter (optional): exact-match any stored field (e.g. {"decision":
    "approved"}), or {"keyword": "..."} for a simple, case-insensitive
    substring search over job_title_or_hash + summary."""
    return store.get_past_proposals(filter, limit, offset)


@mcp.tool()
def get_proposal_detail(proposal_id: str) -> dict:
    """Return the full record for one proposal_log entry, including
    full_draft. Only call this for a specific entry you actually need in
    full — not for every result get_past_proposals returns."""
    try:
        return store.get_proposal_detail(proposal_id)
    except ValueError as exc:
        # store.py stays transport-agnostic (plain ValueError); translate to
        # a deliberate ToolError here so the message actually reaches the
        # caller instead of being swallowed into a generic "Error executing
        # tool" (which is what happens to an un-translated exception).
        raise ToolError(str(exc)) from exc


@mcp.tool()
def issue_gate_token(proposal_id: str) -> str:
    """Issue a single-use, 5-minute token required to log_decision an
    "approved" decision for `proposal_id`. Only call this from
    pre-submit-gate.py's own approval branch, right after it receives a
    real "APPROVED" response — never speculatively, and never for a
    proposal you haven't just gotten explicit approval for."""
    return store.issue_gate_token(proposal_id)


@mcp.tool()
def log_decision(
    proposal_id: str,
    decision: str,
    draft: dict | None = None,
    notes: str | None = None,
    gate_token: str | None = None,
) -> dict:
    """Append a decision record for a proposal to proposal_log.json and return
    the saved record. `decision` must be one of: approved, edited, rejected.
    `draft` is the full proposal_schema object, stored as full_draft and used
    to derive the lightweight summary fields. `gate_token` (from
    issue_gate_token) is REQUIRED for decision="approved"."""
    try:
        return store.log_decision(proposal_id, decision, draft, notes, gate_token)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc


if __name__ == "__main__":
    mcp.run()
