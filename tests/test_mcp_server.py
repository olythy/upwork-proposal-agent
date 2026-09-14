"""End-to-end tests for the profile_store MCP server, over a real stdio
connection — not a mock. Every test points PROFILE_STORE_DATA_DIR at a
temporary data directory (tmp_data_dir fixture) so the real
experience_profile.json / proposal_log.json are never touched."""

from __future__ import annotations

import json
import os

import pytest
from conftest import SERVER_SCRIPT
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

pytestmark = pytest.mark.asyncio


def _server_params(data_dir, python_executable) -> StdioServerParameters:
    env = dict(os.environ)
    env["PROFILE_STORE_DATA_DIR"] = str(data_dir)
    return StdioServerParameters(command=python_executable, args=[str(SERVER_SCRIPT)], env=env)


def _sample_draft(job_posting_hash: str, opening: str, target_rate: str | None = None) -> dict:
    return {
        "opening_observation": opening,
        "problem_understanding": "Problem understanding text.",
        "relevant_experience": {"claims": [{"text": "A claim.", "source_ref": "exp-001"}]},
        "insight_or_question": "An insight and a question.",
        "closing": "Closing line.",
        "target_rate": target_rate,
        "meta": {
            "job_posting_hash": job_posting_hash,
            "created_at": "2026-09-14T09:00:00Z",
            "status": "approved",
        },
    }


async def _gate_token(session: ClientSession, proposal_id: str) -> str:
    result = await session.call_tool("issue_gate_token", {"proposal_id": proposal_id})
    return result.content[0].text


async def _approve(session: ClientSession, proposal_id: str, **kwargs):
    token = await _gate_token(session, proposal_id)
    return await session.call_tool(
        "log_decision", {"proposal_id": proposal_id, "decision": "approved", "gate_token": token, **kwargs}
    )


async def test_list_tools_exposes_all_five(tmp_data_dir, python_executable):
    params = _server_params(tmp_data_dir, python_executable)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = {t.name for t in tools.tools}
            assert names == {
                "get_experience",
                "get_past_proposals",
                "get_proposal_detail",
                "issue_gate_token",
                "log_decision",
            }


async def test_get_experience_returns_the_temp_profile(tmp_data_dir, python_executable, test_profile):
    params = _server_params(tmp_data_dir, python_executable)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("get_experience", {})
            data = json.loads(result.content[0].text)
            assert data == test_profile


async def test_get_past_proposals_starts_empty(tmp_data_dir, python_executable):
    params = _server_params(tmp_data_dir, python_executable)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("get_past_proposals", {})
            envelope = json.loads(result.content[0].text)
            assert envelope == {"results": [], "has_more": False, "total_matches": 0}


async def test_log_decision_then_get_past_proposals_round_trips(tmp_data_dir, python_executable):
    params = _server_params(tmp_data_dir, python_executable)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            draft = _sample_draft("sha256:job1", "Opening observation for job1.", target_rate="45 USD/hour")
            logged = await _approve(session, "sha256:job1", draft=draft, notes=None)
            record = json.loads(logged.content[0].text)
            assert record["proposal_id"] == "sha256:job1"
            assert record["decision"] == "approved"
            assert record["full_draft"] == draft
            assert record["job_title_or_hash"] == "sha256:job1"
            assert record["target_rate"] == "45 USD/hour"
            assert record["summary"] == "Opening observation for job1."
            assert "logged_at" in record

            past = await session.call_tool("get_past_proposals", {})
            envelope = json.loads(past.content[0].text)
            assert envelope["total_matches"] == 1
            assert envelope["has_more"] is False
            (summary,) = envelope["results"]
            assert summary["proposal_id"] == "sha256:job1"
            assert summary["summary"] == "Opening observation for job1."
            assert "full_draft" not in summary  # the whole point: never leak the full draft here


async def test_summary_expands_past_a_short_leading_compliance_phrase(tmp_data_dir, python_executable):
    # Regression test for a real run (MVP/SaaS proposal, 2026-09-14): the
    # job posting required the proposal to open with "MVP READY." — a
    # short, period-terminated compliance phrase the old summary heuristic
    # (cut at the first ". ") turned into the *entire* summary, which was
    # accurate but useless for browsing history later.
    params = _server_params(tmp_data_dir, python_executable)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            opening = (
                "MVP READY. You're not really asking for four CRUD screens — "
                "you're asking someone to decide, in real time, what has to exist "
                "before early users see this and what can wait until after the "
                "idea is validated, because building the wrong things fast is "
                "worse than building nothing at all."
            )
            draft = _sample_draft("sha256:mvp-job", opening)
            logged = await _approve(session, "sha256:mvp-job", draft=draft)
            record = json.loads(logged.content[0].text)

            assert record["summary"] != "MVP READY."
            assert len(record["summary"]) > len("MVP READY.")
            assert "CRUD screens" in record["summary"]


async def test_get_past_proposals_never_includes_full_draft_or_notes(tmp_data_dir, python_executable):
    params = _server_params(tmp_data_dir, python_executable)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            draft = _sample_draft("sha256:job1", "Opening observation.")
            await _approve(session, "sha256:job1", draft=draft, notes="a note")
            past = await session.call_tool("get_past_proposals", {})
            (summary,) = json.loads(past.content[0].text)["results"]
            assert set(summary.keys()) == {
                "proposal_id",
                "logged_at",
                "job_title_or_hash",
                "decision",
                "target_rate",
                "summary",
            }


async def test_get_past_proposals_default_limit_and_has_more(tmp_data_dir, python_executable):
    params = _server_params(tmp_data_dir, python_executable)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            # Log 8 entries — more than the default limit of 5.
            for i in range(8):
                draft = _sample_draft(f"sha256:job{i}", f"Opening observation {i}.")
                await _approve(session, f"sha256:job{i}", draft=draft)

            result = await session.call_tool("get_past_proposals", {})
            envelope = json.loads(result.content[0].text)
            assert envelope["total_matches"] == 8
            assert len(envelope["results"]) == 5  # default limit
            assert envelope["has_more"] is True
            # Newest first: job7 was logged last.
            assert envelope["results"][0]["proposal_id"] == "sha256:job7"
            assert envelope["results"][-1]["proposal_id"] == "sha256:job3"


async def test_get_past_proposals_pagination_with_offset(tmp_data_dir, python_executable):
    params = _server_params(tmp_data_dir, python_executable)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            for i in range(8):
                draft = _sample_draft(f"sha256:job{i}", f"Opening observation {i}.")
                await _approve(session, f"sha256:job{i}", draft=draft)

            result = await session.call_tool("get_past_proposals", {"limit": 5, "offset": 5})
            envelope = json.loads(result.content[0].text)
            assert len(envelope["results"]) == 3
            assert envelope["has_more"] is False
            assert envelope["results"][0]["proposal_id"] == "sha256:job2"


async def test_get_past_proposals_filters_by_decision(tmp_data_dir, python_executable):
    params = _server_params(tmp_data_dir, python_executable)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            await _approve(session, "p1")
            await session.call_tool("log_decision", {"proposal_id": "p2", "decision": "rejected"})

            result = await session.call_tool("get_past_proposals", {"filter": {"decision": "approved"}})
            envelope = json.loads(result.content[0].text)
            assert len(envelope["results"]) == 1
            assert envelope["results"][0]["proposal_id"] == "p1"


async def test_get_past_proposals_filters_by_keyword(tmp_data_dir, python_executable):
    params = _server_params(tmp_data_dir, python_executable)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            await _approve(
                session,
                "sha256:ecommerce-job",
                draft=_sample_draft("sha256:ecommerce-job", "A pricing engine for e-commerce."),
            )
            await _approve(
                session,
                "sha256:other-job",
                draft=_sample_draft("sha256:other-job", "An unrelated data pipeline."),
            )

            result = await session.call_tool("get_past_proposals", {"filter": {"keyword": "PRICING"}})
            envelope = json.loads(result.content[0].text)
            assert len(envelope["results"]) == 1
            assert envelope["results"][0]["proposal_id"] == "sha256:ecommerce-job"


async def test_get_proposal_detail_returns_full_record(tmp_data_dir, python_executable):
    params = _server_params(tmp_data_dir, python_executable)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            draft = _sample_draft("sha256:job1", "Opening observation.")
            await _approve(session, "sha256:job1", draft=draft, notes="a note")

            result = await session.call_tool("get_proposal_detail", {"proposal_id": "sha256:job1"})
            detail = json.loads(result.content[0].text)
            assert detail["proposal_id"] == "sha256:job1"
            assert detail["full_draft"] == draft
            assert detail["notes"] == "a note"


async def test_get_proposal_detail_missing_id_raises_sensible_error(tmp_data_dir, python_executable):
    params = _server_params(tmp_data_dir, python_executable)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("get_proposal_detail", {"proposal_id": "does-not-exist"})
            assert result.is_error
            assert "does-not-exist" in result.content[0].text


async def test_log_decision_rejects_invalid_decision_value(tmp_data_dir, python_executable):
    params = _server_params(tmp_data_dir, python_executable)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("log_decision", {"proposal_id": "p1", "decision": "maybe"})
            assert result.is_error


# --- Gate token: log_decision must refuse "approved" without one ---------


async def test_log_decision_approved_without_gate_token_fails(tmp_data_dir, python_executable):
    params = _server_params(tmp_data_dir, python_executable)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("log_decision", {"proposal_id": "p1", "decision": "approved"})
            assert result.is_error
            assert "gate_token" in result.content[0].text


async def test_log_decision_edited_and_rejected_do_not_need_a_gate_token(tmp_data_dir, python_executable):
    params = _server_params(tmp_data_dir, python_executable)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            edited = await session.call_tool(
                "log_decision", {"proposal_id": "p1", "decision": "edited", "notes": "shorten it"}
            )
            rejected = await session.call_tool("log_decision", {"proposal_id": "p2", "decision": "rejected"})
            assert not edited.is_error
            assert not rejected.is_error


async def test_gate_token_issued_for_one_proposal_rejected_for_another(tmp_data_dir, python_executable):
    params = _server_params(tmp_data_dir, python_executable)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            token = await _gate_token(session, "proposal-a")
            result = await session.call_tool(
                "log_decision", {"proposal_id": "proposal-b", "decision": "approved", "gate_token": token}
            )
            assert result.is_error
            assert "different proposal_id" in result.content[0].text


async def test_gate_token_is_single_use(tmp_data_dir, python_executable):
    params = _server_params(tmp_data_dir, python_executable)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            token = await _gate_token(session, "p1")
            first = await session.call_tool(
                "log_decision", {"proposal_id": "p1", "decision": "approved", "gate_token": token}
            )
            assert not first.is_error

            second = await session.call_tool(
                "log_decision", {"proposal_id": "p1", "decision": "approved", "gate_token": token}
            )
            assert second.is_error
            assert "gate_token" in second.content[0].text


async def test_gate_token_expires(tmp_data_dir, python_executable):
    import store  # the shared logic module, not the MCP transport

    params = _server_params(tmp_data_dir, python_executable)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            token = await _gate_token(session, "p1")

            # Rewrite the token's issued_at to look like it's older than the TTL.
            tokens_path = tmp_data_dir / ".gate_tokens.json"
            tokens = json.loads(tokens_path.read_text(encoding="utf-8"))
            tokens[token]["issued_at"] = "2000-01-01T00:00:00+00:00"
            tokens_path.write_text(json.dumps(tokens), encoding="utf-8")

            result = await session.call_tool(
                "log_decision", {"proposal_id": "p1", "decision": "approved", "gate_token": token}
            )
            assert result.is_error
            assert "expired" in result.content[0].text
            assert store.GATE_TOKEN_TTL_SECONDS > 0  # sanity: the constant we're testing against exists


async def test_data_files_on_disk_are_not_the_real_ones(tmp_data_dir, python_executable):
    # Sanity check on the fixture itself: writes must land in tmp_data_dir,
    # not in the real mcp-server/profile_store/data/.
    from conftest import DATA_DIR

    assert tmp_data_dir != DATA_DIR
    params = _server_params(tmp_data_dir, python_executable)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            await session.call_tool("log_decision", {"proposal_id": "isolated", "decision": "rejected"})

    real_log = json.loads((DATA_DIR / "proposal_log.json").read_text(encoding="utf-8"))
    assert all(e["proposal_id"] != "isolated" for e in real_log["entries"])
