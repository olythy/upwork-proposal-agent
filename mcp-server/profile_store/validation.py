"""Deterministic (non-LLM) checks for Upwork proposal drafts.

These are pure, side-effect-free functions. The proposal-validator subagent
calls this module for everything that doesn't require judgment — whether a
source_ref exists in the profile, whether a banned phrase is present,
whether a required field is missing, whether the word count is in range —
none of that needs an LLM to decide. The subagent's own judgment is reserved
for what actually requires reading comprehension: whether the narrative
genuinely satisfies each of the 7 structural roles (not just whether the
fields are non-empty), tone beyond the fixed banned-phrase list, and whether
hard data the job posting asked for is present.

Can be run standalone:
    python validation.py --draft draft.json --profile experience_profile.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DEFAULT_BANNED_PHRASES = [
    "I'd love to help",
    "As an AI",
    "I am confident that",
    "Dear Sir/Madam",
]

DEFAULT_MIN_WORDS = 150
DEFAULT_MAX_WORDS = 350

REQUIRED_TOP_LEVEL_FIELDS = [
    "opening_observation",
    "problem_understanding",
    "relevant_experience",
    "insight_or_question",
    "closing",
    "meta",
]
REQUIRED_CLAIM_FIELDS = ["text", "source_ref"]
REQUIRED_META_FIELDS = ["job_posting_hash", "created_at", "status"]


def check_source_refs(draft: dict, profile: dict) -> list[str]:
    """Return one issue string per claim whose source_ref does not exist in
    the profile's entries. Empty list means every claim is backed by a real
    entry."""
    valid_ids = {e.get("id") for e in profile.get("entries", [])}
    claims = draft.get("relevant_experience", {}).get("claims", [])
    issues: list[str] = []
    for i, claim in enumerate(claims):
        ref = claim.get("source_ref")
        if not ref or ref not in valid_ids:
            issues.append(
                f"relevant_experience.claims[{i}].source_ref: {ref!r} does not exist in experience_profile.json"
            )
    return issues


def check_banned_phrases(text: str, banned: list[str] | None = None) -> list[str]:
    """Return the subset of `banned` phrases that appear in `text`
    (case-insensitive substring match). Defaults to DEFAULT_BANNED_PHRASES."""
    banned = banned if banned is not None else DEFAULT_BANNED_PHRASES
    lowered = text.lower()
    return [phrase for phrase in banned if phrase.lower() in lowered]


def check_required_fields(draft: dict) -> list[str]:
    """Return dotted-path strings for every required field that is missing
    or empty (top-level fields, each claim's text/source_ref, and the meta
    sub-fields). Empty list means the shape is complete."""
    missing: list[str] = []

    for field in REQUIRED_TOP_LEVEL_FIELDS:
        if not draft.get(field):
            missing.append(field)

    claims = draft.get("relevant_experience", {}).get("claims")
    if not claims:
        missing.append("relevant_experience.claims")
    else:
        for i, claim in enumerate(claims):
            for field in REQUIRED_CLAIM_FIELDS:
                if not claim.get(field):
                    missing.append(f"relevant_experience.claims[{i}].{field}")

    meta = draft.get("meta") or {}
    for field in REQUIRED_META_FIELDS:
        if not meta.get(field):
            missing.append(f"meta.{field}")

    return missing


def check_length(text: str, min_words: int = DEFAULT_MIN_WORDS, max_words: int = DEFAULT_MAX_WORDS) -> bool:
    """Return whether the word count of `text` falls within
    [min_words, max_words] (inclusive)."""
    count = len(text.split())
    return min_words <= count <= max_words


def collect_text(draft: dict) -> str:
    """Concatenate every narrative text field, for banned-phrase and length
    checks that operate on the proposal as a whole."""
    parts = [
        draft.get("opening_observation", ""),
        draft.get("problem_understanding", ""),
        draft.get("insight_or_question", ""),
        draft.get("closing", ""),
    ]
    claims = draft.get("relevant_experience", {}).get("claims", [])
    parts.extend(c.get("text", "") for c in claims)
    return " ".join(p for p in parts if p)


def run_checks(
    draft: dict,
    profile: dict,
    banned_phrases: list[str] | None = None,
    min_words: int = DEFAULT_MIN_WORDS,
    max_words: int = DEFAULT_MAX_WORDS,
) -> dict:
    """Run all four deterministic checks and return a structured report the
    proposal-validator subagent layers its own judgment on top of."""
    text = collect_text(draft)
    return {
        "invalid_source_refs": check_source_refs(draft, profile),
        "banned_phrases_found": check_banned_phrases(text, banned_phrases),
        "missing_required_fields": check_required_fields(draft),
        "length_ok": check_length(text, min_words, max_words),
        "word_count": len(text.split()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic proposal checks.")
    parser.add_argument("--draft", required=True, help="Path to the proposal draft JSON file")
    parser.add_argument("--profile", required=True, help="Path to experience_profile.json")
    parser.add_argument("--min-words", type=int, default=DEFAULT_MIN_WORDS)
    parser.add_argument("--max-words", type=int, default=DEFAULT_MAX_WORDS)
    args = parser.parse_args()

    draft = json.loads(Path(args.draft).read_text(encoding="utf-8"))
    profile = json.loads(Path(args.profile).read_text(encoding="utf-8"))
    report = run_checks(draft, profile, min_words=args.min_words, max_words=args.max_words)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
