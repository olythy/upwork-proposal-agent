"""Shared storage logic for the profile_store: used by both the MCP stdio
server (server.py) and the FastAPI HTTP wrapper (api.py), so the two
transports can never drift into different behavior.

The data directory defaults to the real, on-disk profile_store/data/, but
can be overridden with the PROFILE_STORE_DATA_DIR environment variable —
tests and CI use this to point at a temporary directory so they never read
or write the real experience_profile.json / proposal_log.json."""

from __future__ import annotations

import json
import os
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_DEFAULT_DATA_DIR = Path(__file__).parent / "data"
DATA_DIR = Path(os.environ.get("PROFILE_STORE_DATA_DIR", _DEFAULT_DATA_DIR))
EXPERIENCE_PATH = DATA_DIR / "experience_profile.json"
LOG_PATH = DATA_DIR / "proposal_log.json"
GATE_TOKENS_PATH = DATA_DIR / ".gate_tokens.json"

VALID_DECISIONS = ("approved", "edited", "rejected")
GATE_TOKEN_TTL_SECONDS = 300

# The fields returned by get_past_proposals — deliberately excludes
# full_draft (and notes) so browsing history doesn't flood the caller's
# context. Use get_proposal_detail() for a specific entry's full record.
SUMMARY_FIELDS = ("proposal_id", "logged_at", "job_title_or_hash", "decision", "target_rate", "summary")

DEFAULT_LIST_LIMIT = 5
_SUMMARY_MAX_CHARS = 140
_SUMMARY_MIN_CHARS = 48


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _save_json(path: Path, data: Any) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def get_experience() -> dict:
    """Return the full experience_profile.json content — the single source of
    truth for real, evidence-backed work history. Never fabricate entries;
    this is exactly what is on disk."""
    try:
        return _load_json(EXPERIENCE_PATH)
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            f"{EXPERIENCE_PATH} not found. Run `make install` first — it bootstraps a "
            "placeholder from experience_profile.example.json that you then replace with "
            "your own real experience."
        ) from exc


def _summarize(text: str | None, max_chars: int = _SUMMARY_MAX_CHARS) -> str:
    """One-line summary of `text`: the first sentence, plus however many
    more sentences it takes to pass a minimum length, then a truncated
    prefix if that's still too long. No LLM/embedding call — just a cheap,
    deterministic trim.

    Stopping at the first sentence alone used to be enough, but a job
    posting can require the proposal to open with a short compliance
    phrase (e.g. "MVP READY."), which would otherwise become the entire
    summary — accurate, but useless for browsing history later. Pulling in
    more sentences until there's actually something to read fixes that."""
    text = (text or "").strip()
    if not text:
        return ""

    sentences = [s.strip() for s in text.split(". ") if s.strip()]
    summary = sentences[0] if sentences else text

    i = 1
    while len(summary) < _SUMMARY_MIN_CHARS and i < len(sentences):
        summary = f"{summary}. {sentences[i]}"
        i += 1

    if not summary.endswith((".", "!", "?")):
        summary += "."

    if len(summary) <= max_chars:
        return summary
    return summary[: max_chars - 1].rstrip() + "…"


def _matches_filter(entry: dict, filter: dict) -> bool:
    for key, value in filter.items():
        if key == "keyword":
            haystack = f"{entry.get('job_title_or_hash', '')} {entry.get('summary', '')}".lower()
            if str(value).lower() not in haystack:
                return False
        elif entry.get(key) != value:
            return False
    return True


def get_past_proposals(filter: dict | None = None, limit: int = DEFAULT_LIST_LIMIT, offset: int = 0) -> dict:
    """Return a lightweight, paginated page of proposal_log entries, newest
    first — NEVER includes full_draft (or notes), so browsing history can't
    flood the caller's context as the log grows. Call
    get_proposal_detail(proposal_id) for one entry's full record when you
    actually need it.

    filter (optional): exact-match any stored field (e.g. {"decision":
    "approved"}), or {"keyword": "..."} for a simple, case-insensitive
    substring search over job_title_or_hash + summary — no embeddings, just
    a plain text match.
    """
    log = _load_json(LOG_PATH)
    entries = log.get("entries", [])
    if filter:
        entries = [e for e in entries if _matches_filter(e, filter)]
    entries = sorted(entries, key=lambda e: e.get("logged_at", ""), reverse=True)
    total_matches = len(entries)
    page = entries[offset : offset + limit]
    results = [{field: entry.get(field) for field in SUMMARY_FIELDS} for entry in page]
    return {
        "results": results,
        "has_more": offset + limit < total_matches,
        "total_matches": total_matches,
    }


def _load_gate_tokens() -> dict:
    if not GATE_TOKENS_PATH.exists():
        return {}
    try:
        return _load_json(GATE_TOKENS_PATH)
    except (json.JSONDecodeError, FileNotFoundError):
        return {}


def _save_gate_tokens(tokens: dict) -> None:
    _save_json(GATE_TOKENS_PATH, tokens)


def issue_gate_token(proposal_id: str) -> str:
    """Issue a single-use approval token for `proposal_id`. Meant to be
    called by pre-submit-gate.py's own approval branch, immediately after
    it receives an "APPROVED" response — not called speculatively by
    anything that hasn't actually reached that point. log_decision()
    requires a valid, matching, unexpired token for decision="approved":
    this turns "the gate should have run" from a convention someone has to
    remember into something the code itself refuses to skip. It does not
    (and cannot, from inside this same trust boundary) prove a human
    genuinely typed the response — see README's Design decisions section."""
    token = secrets.token_hex(16)
    tokens = _load_gate_tokens()
    tokens[token] = {"proposal_id": proposal_id, "issued_at": datetime.now(UTC).isoformat()}
    _save_gate_tokens(tokens)
    return token


def _consume_gate_token(token: str, proposal_id: str) -> None:
    """Validate and consume (single-use) a gate token for `proposal_id`.
    Raises ValueError if it's missing, was issued for a different proposal,
    or has expired."""
    tokens = _load_gate_tokens()
    record = tokens.pop(token, None)  # remove regardless of outcome: single-use
    _save_gate_tokens(tokens)
    if record is None:
        raise ValueError(
            "approved decision requires a valid gate_token — call issue_gate_token() "
            "from pre-submit-gate.py's real approval branch first"
        )
    if record["proposal_id"] != proposal_id:
        raise ValueError("gate_token was issued for a different proposal_id")
    age = (datetime.now(UTC) - datetime.fromisoformat(record["issued_at"])).total_seconds()
    if age > GATE_TOKEN_TTL_SECONDS:
        raise ValueError(f"gate_token expired ({age:.0f}s old, max {GATE_TOKEN_TTL_SECONDS}s)")


def get_proposal_detail(proposal_id: str) -> dict:
    """Return the full record for one proposal_log entry, including
    full_draft. Only call this for a specific entry you actually need in
    full — not for every result get_past_proposals returns."""
    log = _load_json(LOG_PATH)
    for entry in log.get("entries", []):
        if entry.get("proposal_id") == proposal_id:
            return entry
    raise ValueError(f"no proposal_log entry found with proposal_id={proposal_id!r}")


def log_decision(
    proposal_id: str,
    decision: str,
    draft: dict | None = None,
    notes: str | None = None,
    gate_token: str | None = None,
) -> dict:
    """Append a decision record for a proposal to proposal_log.json and
    return the saved record. `decision` must be one of: approved, edited,
    rejected. `draft` is the full proposal_schema object, if available at
    decision time — it's stored as `full_draft` and used to derive the
    lightweight summary fields (job_title_or_hash, target_rate, summary)
    that get_past_proposals reads without ever touching full_draft itself.

    `gate_token` is REQUIRED when decision="approved" — it must come from
    issue_gate_token(proposal_id), which pre-submit-gate.py calls only
    after receiving a real "APPROVED" response. This is not required for
    "edited"/"rejected", since those don't claim a final human approval."""
    if decision not in VALID_DECISIONS:
        raise ValueError(f"invalid decision {decision!r}; must be one of {VALID_DECISIONS}")
    if decision == "approved":
        if not gate_token:
            raise ValueError(
                "approved decision requires a gate_token — run pre-submit-gate.py; "
                "a token is only issued after it receives a real APPROVED response"
            )
        _consume_gate_token(gate_token, proposal_id)
    log = _load_json(LOG_PATH)
    meta = (draft or {}).get("meta", {})
    record = {
        "proposal_id": proposal_id,
        "decision": decision,
        "job_title_or_hash": meta.get("job_posting_hash", proposal_id),
        "target_rate": (draft or {}).get("target_rate"),
        "summary": _summarize((draft or {}).get("opening_observation")),
        "full_draft": draft,
        "notes": notes,
        "logged_at": datetime.now(UTC).isoformat(),
    }
    log.setdefault("entries", []).append(record)
    _save_json(LOG_PATH, log)
    return record
