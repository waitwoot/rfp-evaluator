"""One test per normalisation rule in the validation table."""

from __future__ import annotations

import json

import pytest

from rfp.tools.validation_tool import (
    SENTINEL_NO_EVIDENCE,
    JSONParseError,
    coerce_score,
    defaulted_evaluation,
    parse_llm_json,
    validate_evaluation,
    validate_raw_response,
    verify_evidence,
)

DOC_TEXT = (
    "Apex Systems holds ISO 27001:2022 certification, most recently audited in "
    "March 2026.\nMember data is encrypted at rest using AES-256 and in transit "
    "using   TLS 1.3."
)


def payload(criteria, **overrides):
    """A well-formed response for the given criteria, before any corruption."""
    body = {
        "supplier_name": "Apex Systems",
        "criteria": [
            {
                "criterion_id": c.criterion_id,
                "score": 7,
                "max_score": c.max_score,
                "justification": f"Reasoning for {c.name}.",
                "evidence": "Apex Systems holds ISO 27001:2022 certification",
            }
            for c in criteria
        ],
        "risks": ["Higher price than peers."],
        "overall_summary": "Strong technical and security posture.",
    }
    body.update(overrides)
    return body


# ---------------------------------------------------------------------------
# JSON recovery
# ---------------------------------------------------------------------------
def test_parses_plain_json():
    assert parse_llm_json('{"a": 1}') == {"a": 1}


def test_strips_code_fences():
    raw = '```json\n{"supplier_name": "Apex Systems"}\n```'
    assert parse_llm_json(raw)["supplier_name"] == "Apex Systems"


def test_strips_chatter_around_the_object():
    raw = 'Sure! Here is the evaluation you asked for:\n{"score": 8}\nHope that helps.'
    assert parse_llm_json(raw) == {"score": 8}


def test_braces_inside_strings_do_not_confuse_the_scanner():
    raw = 'Note: {"evidence": "the vendor wrote {see annex B} in the proposal"}'
    assert parse_llm_json(raw)["evidence"] == "the vendor wrote {see annex B} in the proposal"


def test_unparseable_response_raises():
    with pytest.raises(JSONParseError):
        parse_llm_json("I am afraid I cannot help with that request.")


def test_json_array_is_not_accepted_as_an_object():
    with pytest.raises(JSONParseError):
        parse_llm_json("[1, 2, 3]")


# ---------------------------------------------------------------------------
# score coercion
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "value,expected",
    [
        (8, 8.0), (8.5, 8.5), ("8", 8.0), ("8.5", 8.5),
        ("7/10", 7.0),            # "7 out of 10" written as a fraction
        ("7 out of 10", 7.0),
        (" 6 ", 6.0),
        ("eight", None),          # spelled out -> not a number
        ("", None), (None, None), ("N/A", None),
        (True, None), (False, None),   # bool is an int subclass; must not pass
    ],
)
def test_coerce_score(value, expected):
    assert coerce_score(value) == expected


# ---------------------------------------------------------------------------
# validation rules
# ---------------------------------------------------------------------------
def test_clean_payload_produces_no_warnings(default_criteria):
    result = validate_evaluation(
        payload(default_criteria), default_criteria,
        supplier_name="Apex Systems", document_text=DOC_TEXT,
    )
    assert result.warnings == []
    assert len(result.criteria) == len(default_criteria)
    assert all(c.status == "OK" for c in result.criteria)
    assert all(c.evidence_verified for c in result.criteria)


def test_score_above_max_is_clipped(default_criteria):
    body = payload(default_criteria)
    body["criteria"][0]["score"] = 14
    result = validate_evaluation(
        body, default_criteria, supplier_name="Apex Systems", document_text=DOC_TEXT
    )
    assert result.criteria[0].score == 10.0
    assert result.criteria[0].status == "CLIPPED"
    assert any("exceeds the maximum" in w for w in result.warnings)


def test_negative_score_is_clipped_to_zero(default_criteria):
    body = payload(default_criteria)
    body["criteria"][0]["score"] = -3
    result = validate_evaluation(
        body, default_criteria, supplier_name="Apex Systems", document_text=DOC_TEXT
    )
    assert result.criteria[0].score == 0.0
    assert result.criteria[0].status == "CLIPPED"


def test_non_numeric_score_defaults_to_zero(default_criteria):
    body = payload(default_criteria)
    body["criteria"][1]["score"] = "eight"
    result = validate_evaluation(
        body, default_criteria, supplier_name="Apex Systems", document_text=DOC_TEXT
    )
    assert result.criteria[1].score == 0.0
    assert result.criteria[1].status == "DEFAULTED_INVALID"
    assert any("is not a number" in w for w in result.warnings)


def test_null_score_defaults_to_zero(default_criteria):
    body = payload(default_criteria)
    body["criteria"][2]["score"] = None
    result = validate_evaluation(
        body, default_criteria, supplier_name="Apex Systems", document_text=DOC_TEXT
    )
    assert result.criteria[2].status == "DEFAULTED_INVALID"


def test_fraction_score_is_parsed_as_its_numerator(default_criteria):
    body = payload(default_criteria)
    body["criteria"][0]["score"] = "7/10"
    result = validate_evaluation(
        body, default_criteria, supplier_name="Apex Systems", document_text=DOC_TEXT
    )
    assert result.criteria[0].score == 7.0
    assert result.criteria[0].status == "OK"


def test_missing_criterion_is_added_with_zero(default_criteria):
    body = payload(default_criteria)
    removed = body["criteria"].pop(3)
    result = validate_evaluation(
        body, default_criteria, supplier_name="Apex Systems", document_text=DOC_TEXT
    )
    assert len(result.criteria) == len(default_criteria)
    missing = next(c for c in result.criteria if c.criterion_id == removed["criterion_id"])
    assert missing.score == 0.0
    assert missing.status == "DEFAULTED_MISSING"
    assert any("missing from the model response" in w for w in result.warnings)


def test_unknown_criterion_id_is_dropped(default_criteria):
    body = payload(default_criteria)
    body["criteria"].append(
        {"criterion_id": 99, "score": 10, "max_score": 10,
         "justification": "Invented.", "evidence": "Invented."}
    )
    result = validate_evaluation(
        body, default_criteria, supplier_name="Apex Systems", document_text=DOC_TEXT
    )
    assert len(result.criteria) == len(default_criteria)
    assert 99 not in [c.criterion_id for c in result.criteria]
    assert any("unknown criterion" in w.lower() for w in result.warnings)


def test_duplicate_criterion_keeps_the_first(default_criteria):
    body = payload(default_criteria)
    first = dict(body["criteria"][0])
    first["score"] = 1            # the later duplicate must be discarded
    body["criteria"].append(first)
    result = validate_evaluation(
        body, default_criteria, supplier_name="Apex Systems", document_text=DOC_TEXT
    )
    assert result.criteria[0].score == 7.0
    assert any("Duplicate entry" in w for w in result.warnings)


def test_missing_id_is_matched_by_name(default_criteria):
    body = payload(default_criteria)
    body["criteria"][0].pop("criterion_id")
    body["criteria"][0]["criterion_name"] = default_criteria[0].name
    result = validate_evaluation(
        body, default_criteria, supplier_name="Apex Systems", document_text=DOC_TEXT
    )
    assert result.criteria[0].score == 7.0
    assert any("matched by name" in w for w in result.warnings)


def test_database_max_score_overrides_the_model(default_criteria):
    body = payload(default_criteria)
    body["criteria"][0]["max_score"] = 100      # model invented its own scale
    body["criteria"][0]["score"] = 9
    result = validate_evaluation(
        body, default_criteria, supplier_name="Apex Systems", document_text=DOC_TEXT
    )
    assert result.criteria[0].max_score == 10.0
    assert result.criteria[0].score == 9.0
    assert any("database value applied" in w for w in result.warnings)


def test_wrong_supplier_name_is_overridden_by_user_entry(default_criteria):
    body = payload(default_criteria, supplier_name="Apex Sistems Ltd")
    result = validate_evaluation(
        body, default_criteria, supplier_name="Apex Systems", document_text=DOC_TEXT
    )
    assert result.supplier_name == "Apex Systems"
    assert any("using the user-entered name" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# evidence verification
# ---------------------------------------------------------------------------
def test_evidence_matching_ignores_case_and_whitespace():
    assert verify_evidence("encrypted at rest using AES-256", DOC_TEXT)
    assert verify_evidence("ENCRYPTED   AT  REST\nUSING aes-256", DOC_TEXT)
    assert verify_evidence("in transit using TLS 1.3", DOC_TEXT)   # doc has 3 spaces


def test_fabricated_evidence_is_flagged_but_score_is_kept(default_criteria):
    body = payload(default_criteria)
    body["criteria"][0]["evidence"] = "Apex guarantees 99.999% uptime in all regions"
    result = validate_evaluation(
        body, default_criteria, supplier_name="Apex Systems", document_text=DOC_TEXT
    )
    assert result.criteria[0].score == 7.0          # score survives
    assert result.criteria[0].evidence_verified is False
    assert any("not found in the document" in w for w in result.warnings)


def test_no_evidence_sentinel_is_not_treated_as_fabrication(default_criteria):
    body = payload(default_criteria)
    body["criteria"][0]["evidence"] = SENTINEL_NO_EVIDENCE
    result = validate_evaluation(
        body, default_criteria, supplier_name="Apex Systems", document_text=DOC_TEXT
    )
    assert result.criteria[0].evidence_verified is False
    assert not any("not found in the document" in w for w in result.warnings)


def test_empty_evidence_becomes_the_sentinel(default_criteria):
    body = payload(default_criteria)
    body["criteria"][0]["evidence"] = ""
    result = validate_evaluation(
        body, default_criteria, supplier_name="Apex Systems", document_text=DOC_TEXT
    )
    assert result.criteria[0].evidence == SENTINEL_NO_EVIDENCE


# ---------------------------------------------------------------------------
# total failure
# ---------------------------------------------------------------------------
def test_unparseable_response_defaults_every_criterion_to_zero(default_criteria):
    result = validate_raw_response(
        "the model refused", default_criteria, supplier_name="Apex Systems"
    )
    assert result.parse_failed is True
    assert len(result.criteria) == len(default_criteria)
    assert all(c.score == 0.0 for c in result.criteria)
    assert all(c.status == "DEFAULTED_PARSE_FAILURE" for c in result.criteria)


def test_failed_supplier_stays_on_the_leaderboard(default_criteria):
    """Dropping it would change everyone else's benchmark, so it stays with zeros."""
    result = defaulted_evaluation(
        default_criteria, supplier_name="Ghost Ltd", reason="no JSON after retry"
    )
    assert result.supplier_name == "Ghost Ltd"
    assert len(result.criteria) == len(default_criteria)


def test_missing_criteria_list_defaults_everything(default_criteria):
    result = validate_evaluation(
        {"supplier_name": "Apex Systems"}, default_criteria,
        supplier_name="Apex Systems", document_text=DOC_TEXT,
    )
    assert all(c.status == "DEFAULTED_MISSING" for c in result.criteria)
    assert any("no 'criteria' list" in w for w in result.warnings)


def test_output_is_always_ordered_by_criterion_id(default_criteria):
    body = payload(default_criteria)
    body["criteria"].reverse()
    result = validate_evaluation(
        body, default_criteria, supplier_name="Apex Systems", document_text=DOC_TEXT
    )
    assert [c.criterion_id for c in result.criteria] == [
        c.criterion_id for c in default_criteria
    ]


def test_risks_accept_strings_or_objects(default_criteria):
    body = payload(default_criteria, risks=[{"risk": "Single point of failure"}, "Cost"])
    result = validate_evaluation(
        body, default_criteria, supplier_name="Apex Systems", document_text=DOC_TEXT
    )
    assert result.risks == ["Single point of failure", "Cost"]


def test_fenced_payload_survives_the_full_path(default_criteria):
    raw = "```json\n" + json.dumps(payload(default_criteria)) + "\n```"
    result = validate_raw_response(
        raw, default_criteria, supplier_name="Apex Systems", document_text=DOC_TEXT
    )
    assert result.parse_failed is False
    assert all(c.score == 7.0 for c in result.criteria)
