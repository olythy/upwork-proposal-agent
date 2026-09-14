"""Thin FastAPI wrapper exposing the profile_store's five tools over HTTP,
for environments where a stdio MCP connection isn't practical (e.g. a
container reachable from a browser or another service). Uses the same
store.py logic as the MCP server, so behavior is identical either way.

Run locally:
    uvicorn profile_store.api:app --reload --app-dir mcp-server

Endpoints:
    GET  /experience
    POST /past_proposals        {"filter"?, "limit"?, "offset"?}  -> lightweight, paginated
    GET  /proposal_detail/{id}  -> one full record, including full_draft
    POST /gate_token            {"proposal_id"} -> one-time token required for an "approved" decision
    POST /log_decision          {"proposal_id", "decision", "draft"?, "notes"?, "gate_token"?}
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fastapi import FastAPI, HTTPException  # noqa: E402
from pydantic import BaseModel  # noqa: E402

import store  # noqa: E402

app = FastAPI(title="Upwork Proposal Agent — profile_store API")


class PastProposalsRequest(BaseModel):
    filter: dict | None = None
    limit: int = store.DEFAULT_LIST_LIMIT
    offset: int = 0


class GateTokenRequest(BaseModel):
    proposal_id: str


class LogDecisionRequest(BaseModel):
    proposal_id: str
    decision: str
    draft: dict | None = None
    notes: str | None = None
    gate_token: str | None = None


@app.get("/experience")
def experience() -> dict:
    return store.get_experience()


@app.post("/past_proposals")
def past_proposals(body: PastProposalsRequest | None = None) -> dict:
    body = body or PastProposalsRequest()
    return store.get_past_proposals(body.filter, body.limit, body.offset)


@app.get("/proposal_detail/{proposal_id}")
def proposal_detail(proposal_id: str) -> dict:
    try:
        return store.get_proposal_detail(proposal_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/gate_token")
def gate_token_endpoint(body: GateTokenRequest) -> dict:
    return {"gate_token": store.issue_gate_token(body.proposal_id)}


@app.post("/log_decision")
def log_decision_endpoint(body: LogDecisionRequest) -> dict:
    if body.decision not in store.VALID_DECISIONS:
        raise HTTPException(
            status_code=400,
            detail=f"invalid decision {body.decision!r}; must be one of {store.VALID_DECISIONS}",
        )
    try:
        return store.log_decision(
            proposal_id=body.proposal_id,
            decision=body.decision,
            draft=body.draft,
            notes=body.notes,
            gate_token=body.gate_token,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
