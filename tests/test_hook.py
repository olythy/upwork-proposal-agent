"""Tests for .claude/hooks/pre-submit-gate.py — the human-approval gate.

These run the real script as a subprocess (not a mock of its internals),
mocking only the human's keystroke: either by closing stdin immediately
(simulating "nothing typed") or via --test-mode --input (the script's own,
explicit, non-default bypass for exactly this purpose). Every run points
--data-dir at a temporary directory so the real proposal_log.json is never
touched.
"""

from __future__ import annotations

import json
import subprocess
import sys

from conftest import HOOK_SCRIPT


def _run_hook(*extra_args: str, stdin_input: str | None = "") -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(HOOK_SCRIPT), *extra_args]
    return subprocess.run(
        cmd,
        input=stdin_input,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_blocks_when_no_input_given(draft_file, passing_report_file, tmp_data_dir):
    # stdin_input="" closes stdin immediately after opening -> input() hits EOF.
    result = _run_hook(
        "--draft",
        str(draft_file),
        "--report",
        str(passing_report_file),
        "--data-dir",
        str(tmp_data_dir),
        stdin_input="",
    )
    assert result.returncode != 0
    assert "No input received (EOF)" in result.stdout or "No input received (EOF)" in result.stderr


def test_blocks_when_report_did_not_pass(draft_file, failing_report_file, tmp_data_dir):
    result = _run_hook(
        "--draft",
        str(draft_file),
        "--report",
        str(failing_report_file),
        "--data-dir",
        str(tmp_data_dir),
        "--test-mode",
        "--input",
        "APPROVED",
    )
    assert result.returncode != 0
    assert "BLOCKED" in result.stderr
    assert "has not passed validation" in result.stderr


def test_invalid_response_is_rejected_until_valid_one_given(draft_file, passing_report_file, tmp_data_dir):
    # Interactive (non-test-mode) path: garbage first, then a real answer.
    result = _run_hook(
        "--draft",
        str(draft_file),
        "--report",
        str(passing_report_file),
        "--data-dir",
        str(tmp_data_dir),
        stdin_input="not a real answer\nAPPROVED\n",
    )
    assert result.returncode == 0
    assert 'Invalid response. Type exactly "APPROVED"' in result.stdout
    assert "APPROVED. Logged decision:" in result.stdout


def test_approved_logs_decision_and_updates_draft_status(draft_file, passing_report_file, tmp_data_dir):
    result = _run_hook(
        "--draft",
        str(draft_file),
        "--report",
        str(passing_report_file),
        "--data-dir",
        str(tmp_data_dir),
        "--test-mode",
        "--input",
        "APPROVED",
    )
    assert result.returncode == 0
    assert "APPROVED. Logged decision:" in result.stdout

    updated_draft = json.loads(draft_file.read_text(encoding="utf-8"))
    assert updated_draft["meta"]["status"] == "approved"

    log = json.loads((tmp_data_dir / "proposal_log.json").read_text(encoding="utf-8"))
    assert len(log["entries"]) == 1
    entry = log["entries"][0]
    assert entry["decision"] == "approved"
    assert entry["full_draft"] == updated_draft  # the approved draft was logged in full
    assert entry["summary"]  # derived from opening_observation, non-empty
    assert entry["job_title_or_hash"] == updated_draft["meta"]["job_posting_hash"]


def test_edit_does_not_approve_and_logs_edited(draft_file, passing_report_file, tmp_data_dir):
    result = _run_hook(
        "--draft",
        str(draft_file),
        "--report",
        str(passing_report_file),
        "--data-dir",
        str(tmp_data_dir),
        "--test-mode",
        "--input",
        "EDIT: shorten the closing",
    )
    assert result.returncode == 3
    assert "EDIT REQUESTED" in result.stdout
    assert "shorten the closing" in result.stdout

    updated_draft = json.loads(draft_file.read_text(encoding="utf-8"))
    assert updated_draft["meta"]["status"] == "draft"  # unchanged, not approved

    log = json.loads((tmp_data_dir / "proposal_log.json").read_text(encoding="utf-8"))
    assert len(log["entries"]) == 1
    entry = log["entries"][0]
    assert entry["decision"] == "edited"
    assert entry["notes"] == "shorten the closing"
    assert entry["full_draft"] == updated_draft  # the pre-edit draft was logged for context


def test_final_text_opens_with_greeting_and_closes_with_signed_sign_off(
    draft_file, passing_report_file, tmp_data_dir
):
    result = _run_hook(
        "--draft",
        str(draft_file),
        "--report",
        str(passing_report_file),
        "--data-dir",
        str(tmp_data_dir),
        "--test-mode",
        "--input",
        "APPROVED",
    )
    assert result.returncode == 0

    marker = "Final text (paste this into Upwork):\n\n"
    start = result.stdout.index(marker) + len(marker)
    end = result.stdout.index("\n\nAPPROVED. Logged decision:")
    final_text = result.stdout[start:end]

    draft = json.loads(draft_file.read_text(encoding="utf-8"))
    assert final_text.startswith(draft["greeting"])
    assert final_text.rstrip().endswith(f"{draft['sign_off']}\nKároly")
    # Each claim is its own paragraph, not merged into one dense block.
    for claim in draft["relevant_experience"]["claims"]:
        assert f"\n\n{claim['text']}\n\n" in f"\n\n{final_text}\n\n"


def test_rejected_without_reason_logs_decision_and_does_not_approve(
    draft_file, passing_report_file, tmp_data_dir
):
    result = _run_hook(
        "--draft",
        str(draft_file),
        "--report",
        str(passing_report_file),
        "--data-dir",
        str(tmp_data_dir),
        "--test-mode",
        "--input",
        "REJECTED",
    )
    assert result.returncode == 2
    assert "REJECTED — this draft will not be sent." in result.stdout
    assert "Reason:" not in result.stdout

    updated_draft = json.loads(draft_file.read_text(encoding="utf-8"))
    assert updated_draft["meta"]["status"] == "rejected"

    log = json.loads((tmp_data_dir / "proposal_log.json").read_text(encoding="utf-8"))
    assert len(log["entries"]) == 1
    entry = log["entries"][0]
    assert entry["decision"] == "rejected"
    assert entry["notes"] is None
    assert entry["full_draft"] == updated_draft


def test_rejected_with_reason_is_logged_as_notes(draft_file, passing_report_file, tmp_data_dir):
    result = _run_hook(
        "--draft",
        str(draft_file),
        "--report",
        str(passing_report_file),
        "--data-dir",
        str(tmp_data_dir),
        "--test-mode",
        "--input",
        "REJECTED: just a test run, not a real application",
    )
    assert result.returncode == 2
    assert "Reason: just a test run, not a real application" in result.stdout

    log = json.loads((tmp_data_dir / "proposal_log.json").read_text(encoding="utf-8"))
    assert log["entries"][0]["notes"] == "just a test run, not a real application"


def test_rejected_does_not_require_a_gate_token(draft_file, passing_report_file, tmp_data_dir):
    # No issue_gate_token call is made on this path — if log_decision ever
    # required one for "rejected" too, this would fail with a clear error
    # instead of succeeding.
    result = _run_hook(
        "--draft",
        str(draft_file),
        "--report",
        str(passing_report_file),
        "--data-dir",
        str(tmp_data_dir),
        "--test-mode",
        "--input",
        "REJECTED",
    )
    assert result.returncode == 2
    assert "gate_token" not in result.stdout
    assert "gate_token" not in result.stderr


def test_test_mode_without_input_errors_out(draft_file, passing_report_file, tmp_data_dir):
    result = _run_hook(
        "--draft",
        str(draft_file),
        "--report",
        str(passing_report_file),
        "--data-dir",
        str(tmp_data_dir),
        "--test-mode",
    )
    assert result.returncode != 0
    assert "--test-mode requires --input" in result.stdout or "--test-mode requires --input" in result.stderr
