"""Schema-shape tests for proposal_schema.json. These check structure only
— truthfulness of claims is check_source_refs' job (test_validation.py)."""

from __future__ import annotations

import copy

import jsonschema
import pytest


def test_valid_draft_passes(valid_draft, proposal_schema):
    jsonschema.validate(valid_draft, proposal_schema)


def test_draft_with_fake_source_ref_still_matches_schema(draft_with_fake_source_ref, proposal_schema):
    # The schema only checks the source_ref *shape* (exp-NNN), not whether
    # it exists in the profile — that's the validator's job, not the
    # schema's. This asserts that boundary explicitly.
    jsonschema.validate(draft_with_fake_source_ref, proposal_schema)


@pytest.mark.parametrize(
    "missing_field",
    [
        "opening_observation",
        "problem_understanding",
        "relevant_experience",
        "insight_or_question",
        "closing",
        "meta",
    ],
)
def test_missing_required_top_level_field_fails(valid_draft, proposal_schema, missing_field):
    draft = copy.deepcopy(valid_draft)
    del draft[missing_field]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(draft, proposal_schema)


@pytest.mark.parametrize("missing_field", ["job_posting_hash", "created_at", "status"])
def test_missing_meta_field_fails(valid_draft, proposal_schema, missing_field):
    draft = copy.deepcopy(valid_draft)
    del draft["meta"][missing_field]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(draft, proposal_schema)


def test_empty_claims_list_fails(valid_draft, proposal_schema):
    draft = copy.deepcopy(valid_draft)
    draft["relevant_experience"]["claims"] = []
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(draft, proposal_schema)


def test_claim_missing_source_ref_fails(valid_draft, proposal_schema):
    draft = copy.deepcopy(valid_draft)
    del draft["relevant_experience"]["claims"][0]["source_ref"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(draft, proposal_schema)


@pytest.mark.parametrize("bad_ref", ["exp-99", "exp-0001", "abc", "exp-", ""])
def test_source_ref_pattern_rejects_malformed_ids(valid_draft, proposal_schema, bad_ref):
    draft = copy.deepcopy(valid_draft)
    draft["relevant_experience"]["claims"][0]["source_ref"] = bad_ref
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(draft, proposal_schema)


def test_invalid_status_enum_fails(valid_draft, proposal_schema):
    draft = copy.deepcopy(valid_draft)
    draft["meta"]["status"] = "not-a-real-status"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(draft, proposal_schema)


def test_unknown_top_level_field_fails(valid_draft, proposal_schema):
    draft = copy.deepcopy(valid_draft)
    draft["made_up_field"] = "should not be allowed"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(draft, proposal_schema)


def test_optional_fields_are_actually_optional(valid_draft, proposal_schema):
    draft = copy.deepcopy(valid_draft)
    assert "target_rate" not in draft
    assert "availability" not in draft
    jsonschema.validate(draft, proposal_schema)
