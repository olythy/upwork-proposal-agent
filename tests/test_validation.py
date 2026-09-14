"""Unit tests for the deterministic checks in
mcp-server/profile_store/validation.py — the module the proposal-validator
subagent calls instead of eyeballing these rules itself."""

from __future__ import annotations

import copy

import validation

# ---------------------------------------------------------------------------
# check_source_refs
# ---------------------------------------------------------------------------


def test_check_source_refs_all_valid_returns_empty(valid_draft, test_profile):
    assert validation.check_source_refs(valid_draft, test_profile) == []


def test_check_source_refs_catches_fabricated_exp_008(draft_with_fake_source_ref, test_profile):
    # This is exactly the scenario documented in examples/sample_run.md: a
    # claim citing exp-008, which does not exist in the real profile.
    issues = validation.check_source_refs(draft_with_fake_source_ref, test_profile)
    assert len(issues) == 1
    assert "exp-008" in issues[0]
    assert "claims[2]" in issues[0]


def test_check_source_refs_catches_missing_source_ref(valid_draft, test_profile):
    draft = copy.deepcopy(valid_draft)
    del draft["relevant_experience"]["claims"][0]["source_ref"]
    issues = validation.check_source_refs(draft, test_profile)
    assert len(issues) == 1
    assert "claims[0]" in issues[0]


def test_check_source_refs_no_claims_returns_empty(test_profile):
    draft = {"relevant_experience": {"claims": []}}
    assert validation.check_source_refs(draft, test_profile) == []


# ---------------------------------------------------------------------------
# check_banned_phrases
# ---------------------------------------------------------------------------


def test_check_banned_phrases_clean_text_returns_empty():
    text = "Happy to walk through the approach on a short call."
    assert validation.check_banned_phrases(text) == []


def test_check_banned_phrases_detects_default_phrase():
    text = "As an AI, I am confident that I'd love to help with this."
    found = validation.check_banned_phrases(text)
    assert "As an AI" in found
    assert "I am confident that" in found
    assert "I'd love to help" in found


def test_check_banned_phrases_is_case_insensitive():
    text = "DEAR SIR/MADAM, thanks for the posting."
    assert "Dear Sir/Madam" in validation.check_banned_phrases(text)


def test_check_banned_phrases_respects_custom_list():
    text = "This uses a totally custom banned phrase right here."
    found = validation.check_banned_phrases(text, banned=["custom banned phrase"])
    assert found == ["custom banned phrase"]


# ---------------------------------------------------------------------------
# check_required_fields
# ---------------------------------------------------------------------------


def test_check_required_fields_complete_draft_returns_empty(valid_draft):
    assert validation.check_required_fields(valid_draft) == []


def test_check_required_fields_catches_missing_top_level_field(valid_draft):
    draft = copy.deepcopy(valid_draft)
    del draft["closing"]
    missing = validation.check_required_fields(draft)
    assert "closing" in missing


def test_check_required_fields_catches_missing_meta_subfield(valid_draft):
    draft = copy.deepcopy(valid_draft)
    del draft["meta"]["status"]
    missing = validation.check_required_fields(draft)
    assert "meta.status" in missing


def test_check_required_fields_catches_empty_claims(valid_draft):
    draft = copy.deepcopy(valid_draft)
    draft["relevant_experience"]["claims"] = []
    missing = validation.check_required_fields(draft)
    assert "relevant_experience.claims" in missing


def test_check_required_fields_catches_claim_missing_text(valid_draft):
    draft = copy.deepcopy(valid_draft)
    del draft["relevant_experience"]["claims"][0]["text"]
    missing = validation.check_required_fields(draft)
    assert "relevant_experience.claims[0].text" in missing


# ---------------------------------------------------------------------------
# check_length
# ---------------------------------------------------------------------------


def test_check_length_within_range_true():
    text = " ".join(["word"] * 200)
    assert validation.check_length(text) is True


def test_check_length_too_short_false():
    text = " ".join(["word"] * 50)
    assert validation.check_length(text) is False


def test_check_length_too_long_false():
    text = " ".join(["word"] * 500)
    assert validation.check_length(text) is False


def test_check_length_boundaries_inclusive():
    assert validation.check_length(" ".join(["word"] * 150), min_words=150, max_words=350) is True
    assert validation.check_length(" ".join(["word"] * 350), min_words=150, max_words=350) is True
    assert validation.check_length(" ".join(["word"] * 149), min_words=150, max_words=350) is False
    assert validation.check_length(" ".join(["word"] * 351), min_words=150, max_words=350) is False


def test_check_length_custom_range():
    text = " ".join(["word"] * 10)
    assert validation.check_length(text, min_words=5, max_words=20) is True
    assert validation.check_length(text, min_words=15, max_words=20) is False


# ---------------------------------------------------------------------------
# run_checks (orchestration used by the validator subagent's CLI call)
# ---------------------------------------------------------------------------


def test_run_checks_on_valid_draft_reports_all_clear(valid_draft, test_profile):
    report = validation.run_checks(valid_draft, test_profile)
    assert report["invalid_source_refs"] == []
    assert report["banned_phrases_found"] == []
    assert report["missing_required_fields"] == []
    assert report["length_ok"] is True


def test_run_checks_on_fabricated_source_ref_draft_flags_it(draft_with_fake_source_ref, test_profile):
    report = validation.run_checks(draft_with_fake_source_ref, test_profile)
    assert len(report["invalid_source_refs"]) == 1
    assert "exp-008" in report["invalid_source_refs"][0]
