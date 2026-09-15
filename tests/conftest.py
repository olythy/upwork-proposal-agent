"""Shared fixtures for the upwork-proposal-agent test suite.

The most important rule here: no test may read or write the real
mcp-server/profile_store/data/experience_profile.json or proposal_log.json.
Both are personal data, git-ignored, and not guaranteed to even exist (a
fresh checkout only ships the placeholder example). Every fixture below
works against a synthetic, self-contained profile and a temporary data
directory instead.
"""

from __future__ import annotations

import copy
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MCP_SERVER_DIR = ROOT / "mcp-server"
PROFILE_STORE_DIR = MCP_SERVER_DIR / "profile_store"
DATA_DIR = PROFILE_STORE_DIR / "data"
SCHEMA_PATH = ROOT / "schemas" / "proposal_schema.json"
SERVER_SCRIPT = PROFILE_STORE_DIR / "server.py"
HOOK_SCRIPT = ROOT / ".claude" / "hooks" / "pre-submit-gate.py"

# Make `import validation` / `import store` work without installing anything.
if str(PROFILE_STORE_DIR) not in sys.path:
    sys.path.insert(0, str(PROFILE_STORE_DIR))


def _venv_python() -> str:
    candidate = ROOT / ".venv" / "bin" / "python"
    return str(candidate) if candidate.exists() else sys.executable


@pytest.fixture()
def test_profile() -> dict:
    """A synthetic, self-contained experience_profile.json — not read from
    disk. The test suite must pass identically whether or not the real
    (personal, git-ignored) profile happens to exist locally, and must pass
    in CI, which only ever sees the neutral placeholder example."""
    return {
        "entries": [
            {
                "id": "exp-001",
                "title": "15+ years of full-stack development on complex, existing systems",
                "detail": "Long-running independent/full-stack experience focused on understanding "
                "complex, pre-existing systems and delivering stable, maintainable solutions.",
                "evidence": "resume",
            },
            {
                "id": "exp-006",
                "title": "Daily use of Claude Code",
                "detail": "Uses Claude Code regularly, on a daily basis, for development work, "
                "including subagents, skills, hooks and MCP servers.",
                "evidence": "this repo",
            },
        ]
    }


@pytest.fixture()
def proposal_schema() -> dict:
    with SCHEMA_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture()
def tmp_data_dir(tmp_path: Path, test_profile: dict) -> Path:
    """A temporary profile_store data directory: the synthetic test_profile
    plus a fresh, empty proposal_log.json. Point PROFILE_STORE_DATA_DIR /
    --data-dir at this instead of the real data/."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    with (data_dir / "experience_profile.json").open("w", encoding="utf-8") as f:
        json.dump(test_profile, f, ensure_ascii=False, indent=2)
    with (data_dir / "proposal_log.json").open("w", encoding="utf-8") as f:
        json.dump({"entries": []}, f)
    return data_dir


@pytest.fixture()
def python_executable() -> str:
    return _venv_python()


@pytest.fixture()
def valid_draft(test_profile: dict) -> dict:
    """A minimal, schema-valid, fully-passing proposal draft, built only
    from ids in the synthetic test_profile (exp-001, exp-006)."""
    ids = {e["id"] for e in test_profile["entries"]}
    assert {"exp-001", "exp-006"} <= ids, "fixture assumes exp-001/exp-006 exist in test_profile"
    return {
        "greeting": "Hi there,",
        "opening_observation": (
            "Your posting describes a pricing engine that keeps breaking whenever a new "
            "regional exception gets added, which usually means the exceptions were never "
            "designed as data in the first place."
        ),
        "problem_understanding": (
            "You have a live e-commerce system where pricing rules accumulated organically "
            "over time, and now every change to them is risky because nobody fully trusts "
            "which rule fires first."
        ),
        "relevant_experience": {
            "claims": [
                {
                    "text": (
                        "I've spent 15+ years working on messy, pre-existing production "
                        "systems where understanding what is actually happening comes before "
                        "any change."
                    ),
                    "source_ref": "exp-001",
                },
                {
                    "text": (
                        "I use Claude Code daily for my own development work, including "
                        "subagents, skills, hooks and MCP servers."
                    ),
                    "source_ref": "exp-006",
                },
            ]
        },
        "insight_or_question": (
            "One thing worth checking before any rewrite: are the current pricing "
            "exceptions covered by any automated tests at all, or would a refactor be "
            "flying blind? Knowing that changes how cautious the first pass needs to be, "
            "and how much of the existing behavior needs to be pinned down before anything "
            "moves."
        ),
        "closing": (
            "Happy to look at the current pricing code on a short call and sketch out "
            "where the risk actually lives."
        ),
        "sign_off": "Best,",
        "meta": {
            "job_posting_hash": "sha256:testfixturehash",
            "created_at": "2026-09-14T09:00:00Z",
            "status": "draft",
        },
    }


@pytest.fixture()
def draft_with_fake_source_ref(valid_draft: dict) -> dict:
    """Same as valid_draft, but with one claim citing exp-008, which does
    not exist anywhere in test_profile — the exact failure mode this whole
    project exists to catch (see examples/sample_run.md)."""
    draft = copy.deepcopy(valid_draft)
    draft["relevant_experience"]["claims"].append(
        {
            "text": "I've directly integrated SAP and NetSuite ERP systems into automated quote-generation pipelines.",
            "source_ref": "exp-008",
        }
    )
    return draft


def write_json(path: Path, data: dict) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


@pytest.fixture()
def draft_file(tmp_path: Path, valid_draft: dict) -> Path:
    path = tmp_path / "draft.json"
    write_json(path, valid_draft)
    return path


@pytest.fixture()
def passing_report_file(tmp_path: Path) -> Path:
    path = tmp_path / "report_pass.json"
    write_json(path, {"status": "pass", "issues": []})
    return path


@pytest.fixture()
def failing_report_file(tmp_path: Path) -> Path:
    path = tmp_path / "report_fail.json"
    write_json(
        path,
        {
            "status": "fail",
            "issues": [{"field": "x", "problem": "y", "suggestion": "z"}],
        },
    )
    return path


def _cleanup_pycache() -> None:
    cache = PROFILE_STORE_DIR / "__pycache__"
    if cache.exists():
        shutil.rmtree(cache, ignore_errors=True)


def pytest_sessionfinish(session, exitstatus) -> None:  # noqa: ARG001
    _cleanup_pycache()
