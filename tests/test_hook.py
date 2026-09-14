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
