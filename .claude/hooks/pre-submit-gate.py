#!/usr/bin/env python3
"""Human approval gate for Upwork proposal drafts.

Runs at the point where a validated draft (proposal_schema.json, status
"validated") is about to be moved to "ready_to_submit" / actually sent.
It prints the draft and the validator report, then BLOCKS until the human
operator types an explicit response:

  - "APPROVED"       -> the draft is approved as-is; requests a single-use
                         gate_token from `issue_gate_token`, then logs the
                         decision via `log_decision` (which refuses any
                         "approved" decision without a valid, matching
                         token) and marks the draft's meta.status as
                         "approved".
  - "EDIT: <text>"    -> the draft is NOT approved; the edit instruction is
                         printed back (and logged as decision "edited") so
                         the calling workflow can route it back to the ACT
                         step of draft-proposal for a rewrite.
  - "REJECTED"        -> the draft is dropped outright — not because it
    / "REJECTED: <reason>"  needs editing, but because the human doesn't
                         want to send it at all (e.g. a test run, or a
                         posting no longer worth applying to). Logged as
                         decision "rejected" (no gate_token needed, same as
                         "edited") and marks the draft's meta.status as
                         "rejected". The reason after the colon is optional.

Nothing may reach "ready_to_submit" without one of these three explicit
human responses. There is no default/timeout path that approves
automatically.

For automated tests ONLY, pass --test-mode together with --input, which
supplies the human response non-interactively instead of blocking on stdin.
This flag must never be used for a real submission — it exists solely so CI
/ test scripts can exercise this gate's logic without a human at the keyboard.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent.parent
SERVER_SCRIPT = PROJECT_ROOT / "mcp-server" / "profile_store" / "server.py"
VENV_PYTHON = PROJECT_ROOT / ".venv" / "bin" / "python"

# The sign-off phrase (e.g. "Best,") is the skill's call, matched to the
# posting's register — but the name itself never varies, so it's appended
# here rather than asked of the skill on every draft.
SIGNER_NAME = "Károly"


def _python_for_server() -> str:
    if VENV_PYTHON.exists():
        return str(VENV_PYTHON)
    return sys.executable


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: dict) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def render_draft(draft: dict) -> str:
    lines = ["=" * 72, "PROPOSAL DRAFT", "=" * 72]
    lines.append(f"\n[Greeting]\n{draft.get('greeting', '')}")
    lines.append(f"\n[1] Opening observation:\n{draft.get('opening_observation', '')}")
    lines.append(f"\n[2] Problem understanding:\n{draft.get('problem_understanding', '')}")
    claims = draft.get("relevant_experience", {}).get("claims", [])
    lines.append("\n[3] Relevant experience (claims):")
    for c in claims:
        lines.append(f"  - {c.get('text', '')}  [source_ref: {c.get('source_ref', '???')}]")
    lines.append(f"\n[4-5] Insight / question:\n{draft.get('insight_or_question', '')}")
    lines.append(f"\n[6-7] Closing:\n{draft.get('closing', '')}")
    if draft.get("target_rate"):
        lines.append(f"\nTarget rate: {draft['target_rate']}")
    if draft.get("availability"):
        lines.append(f"Availability: {draft['availability']}")
    lines.append(f"\n[Sign-off]\n{draft.get('sign_off', '')}\n{SIGNER_NAME}")
    lines.append(f"\nStatus: {draft.get('meta', {}).get('status', 'unknown')}")
    return "\n".join(lines)


def render_final_text(draft: dict) -> str:
    """Plain-prose rendering of the approved draft, suitable for pasting
    straight into Upwork. Shown to the human at approval time; the
    structured `draft` itself (not this rendering) is what gets logged as
    `full_draft` — this text can always be regenerated from it later.

    Each claim gets its own paragraph rather than being merged into one —
    a proposal with several claims fused into a single dense block reads
    as a wall of text; keeping them as separate short paragraphs doesn't."""
    paragraphs = [draft.get("greeting", "")]
    paragraphs.append(draft.get("opening_observation", ""))
    paragraphs.append(draft.get("problem_understanding", ""))
    claims = draft.get("relevant_experience", {}).get("claims", [])
    paragraphs.extend(c.get("text", "") for c in claims)
    paragraphs.append(draft.get("insight_or_question", ""))
    paragraphs.append(draft.get("closing", ""))
    extras = []
    if draft.get("target_rate"):
        extras.append(f"Rate: {draft['target_rate']}")
    if draft.get("availability"):
        extras.append(f"Availability: {draft['availability']}")
    if extras:
        paragraphs.append(" | ".join(extras))
    sign_off = draft.get("sign_off", "")
    if sign_off:
        paragraphs.append(f"{sign_off}\n{SIGNER_NAME}")
    return "\n\n".join(p for p in paragraphs if p)


def render_report(report: dict) -> str:
    lines = ["=" * 72, "VALIDATION REPORT", "=" * 72]
    lines.append(f"Status: {report.get('status', 'unknown')}")
    issues = report.get("issues", [])
    if issues:
        lines.append("Issues:")
        for i in issues:
            lines.append(f"  - [{i.get('field')}] {i.get('problem')}")
            if i.get("suggestion"):
                lines.append(f"      suggestion: {i['suggestion']}")
    else:
        lines.append("No issues.")
    return "\n".join(lines)


def prompt_for_decision(test_mode: bool, test_input: str | None) -> str:
    prompt = (
        "\nApprove this draft for submission?\n"
        "  Type APPROVED to approve as-is,\n"
        "  Type EDIT: <what to change> to send it back for a rewrite, or\n"
        "  Type REJECTED: <optional reason> to drop this one without editing.\n> "
    )
    if test_mode:
        if test_input is None:
            raise SystemExit("--test-mode requires --input")
        print(prompt, end="")
        print(test_input)
        return test_input
    while True:
        try:
            response = input(prompt).strip()
        except EOFError:
            raise SystemExit(
                "No input received (EOF) — the gate cannot proceed without an "
                "explicit APPROVED, EDIT:, or REJECTED response."
            ) from None
        if (
            response == "APPROVED"
            or response.startswith("EDIT: ")
            or response == "REJECTED"
            or response.startswith("REJECTED:")
        ):
            return response
        print(
            'Invalid response. Type exactly "APPROVED", "EDIT: <instruction>", or "REJECTED" / "REJECTED: <reason>".'
        )


def _server_params(data_dir: str | None) -> StdioServerParameters:
    env = dict(os.environ)
    if data_dir:
        env["PROFILE_STORE_DATA_DIR"] = data_dir
    return StdioServerParameters(command=_python_for_server(), args=[str(SERVER_SCRIPT)], env=env)


async def call_issue_gate_token(proposal_id: str, data_dir: str | None = None) -> str:
    """Get a single-use approval token for `proposal_id`. Call this ONLY
    right after receiving a real "APPROVED" response — never speculatively.
    log_decision() will refuse an "approved" decision without one."""
    params = _server_params(data_dir)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("issue_gate_token", {"proposal_id": proposal_id})
            if result.is_error:
                raise RuntimeError(f"issue_gate_token failed: {result.content}")
            return result.content[0].text  # plain string return, not JSON-encoded


async def call_log_decision(
    proposal_id: str,
    decision: str,
    draft: dict | None,
    notes: str | None,
    data_dir: str | None = None,
    gate_token: str | None = None,
) -> dict:
    params = _server_params(data_dir)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "log_decision",
                {
                    "proposal_id": proposal_id,
                    "decision": decision,
                    "draft": draft,
                    "notes": notes,
                    "gate_token": gate_token,
                },
            )
            if result.is_error:
                raise RuntimeError(f"log_decision failed: {result.content}")
            return json.loads(result.content[0].text)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--draft", required=True, help="Path to the proposal draft JSON file")
    parser.add_argument("--report", required=True, help="Path to the proposal-validator report JSON file")
    parser.add_argument(
        "--test-mode",
        action="store_true",
        help="Automated-test bypass: read the human decision from --input instead of stdin. Never use for a real submission.",
    )
    parser.add_argument(
        "--input",
        dest="test_input",
        default=None,
        help="Only used with --test-mode: the canned human response (e.g. 'APPROVED').",
    )
    parser.add_argument(
        "--data-dir",
        dest="data_dir",
        default=None,
        help="Override the profile_store data directory (sets PROFILE_STORE_DATA_DIR for the "
        "MCP server subprocess). Tests use this to point at a temp directory instead of the "
        "real experience_profile.json / proposal_log.json.",
    )
    args = parser.parse_args()

    draft_path = Path(args.draft)
    report_path = Path(args.report)
    draft = load_json(draft_path)
    report = load_json(report_path)

    print(render_draft(draft))
    print()
    print(render_report(report))

    if report.get("status") != "pass":
        print(
            "\nBLOCKED: this draft has not passed validation (status="
            f"{report.get('status')!r}). The human gate only runs on validated drafts.",
            file=sys.stderr,
        )
        return 1

    decision_text = prompt_for_decision(args.test_mode, args.test_input)
    proposal_id = draft.get("meta", {}).get("job_posting_hash", "unknown-proposal")

    if decision_text == "APPROVED":
        draft["meta"]["status"] = "approved"
        save_json(draft_path, draft)
        print("\nFinal text (paste this into Upwork):\n")
        print(render_final_text(draft))
        gate_token = asyncio.run(call_issue_gate_token(proposal_id, data_dir=args.data_dir))
        logged = asyncio.run(
            call_log_decision(
                proposal_id=proposal_id,
                decision="approved",
                draft=draft,
                notes=None,
                data_dir=args.data_dir,
                gate_token=gate_token,
            )
        )
        print("\nAPPROVED. Logged decision:")
        print(json.dumps(logged, ensure_ascii=False, indent=2))
        return 0

    if decision_text.startswith("EDIT: "):
        edit_instruction = decision_text[len("EDIT: ") :].strip()
        logged = asyncio.run(
            call_log_decision(
                proposal_id=proposal_id,
                decision="edited",
                draft=draft,
                notes=edit_instruction,
                data_dir=args.data_dir,
            )
        )
        print("\nEDIT REQUESTED — routing back to the ACT step with this instruction:")
        print(f"  {edit_instruction}")
        print("\nLogged decision:")
        print(json.dumps(logged, ensure_ascii=False, indent=2))
        return 3

    # REJECTED / REJECTED: <reason>
    reason = decision_text[len("REJECTED:") :].strip() if decision_text.startswith("REJECTED:") else None
    draft["meta"]["status"] = "rejected"
    save_json(draft_path, draft)
    logged = asyncio.run(
        call_log_decision(
            proposal_id=proposal_id,
            decision="rejected",
            draft=draft,
            notes=reason,
            data_dir=args.data_dir,
        )
    )
    print("\nREJECTED — this draft will not be sent.")
    if reason:
        print(f"  Reason: {reason}")
    print("\nLogged decision:")
    print(json.dumps(logged, ensure_ascii=False, indent=2))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
