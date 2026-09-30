"""The agent layer: offline scorer, provider guards, and fault injection."""

from __future__ import annotations

import json

import pytest

from rfp.agents.evaluation_agent import (
    FAULT_MODES,
    EvaluationAgent,
    EvaluationError,
    corrupt_response,
    mock_evaluate,
)
from rfp.prompts import SENTINEL_NO_EVIDENCE, build_user_prompt, format_criteria_block
from rfp.tools.validation_tool import validate_raw_response

DOC = (
    "Our architecture uses Kubernetes with PostgreSQL and automated failover. "
    "Integration is over SIP2 and SAML single sign-on, documented with OpenAPI. "
    "We hold ISO 27001 certification and encrypt data with AES-256 over TLS 1.3, "
    "with an annual penetration test and full audit logging. "
    "Support is 24x7 with a one hour response target, a named service delivery "
    "manager and service credits. We have delivered nine comparable projects."
)


# ---------------------------------------------------------------------------
# prompt construction
# ---------------------------------------------------------------------------
def test_criteria_block_is_built_from_the_database(default_criteria):
    block = format_criteria_block(default_criteria)
    for criterion in default_criteria:
        assert criterion.name in block
        assert f"criterion_id: {criterion.criterion_id}" in block
        assert f"0 to {criterion.max_score:g}" in block


def test_weights_are_never_sent_to_the_model(default_criteria):
    """Weighting is a commercial decision; the model must not see it."""
    prompt = build_user_prompt("Apex Systems", DOC, default_criteria)
    assert "30" not in format_criteria_block(default_criteria)
    assert "weight" not in prompt.lower()


def test_prompt_carries_the_document_and_the_supplier(default_criteria):
    prompt = build_user_prompt("Apex Systems", DOC, default_criteria)
    assert "Apex Systems" in prompt
    assert DOC in prompt
    assert f"exactly {len(default_criteria)} results" in prompt


# ---------------------------------------------------------------------------
# offline scorer
# ---------------------------------------------------------------------------
def test_mock_returns_one_entry_per_criterion(default_criteria):
    payload = json.loads(mock_evaluate("Apex Systems", DOC, default_criteria))
    assert len(payload["criteria"]) == len(default_criteria)
    assert payload["supplier_name"] == "Apex Systems"
    assert payload["overall_summary"]


def test_mock_is_deterministic(default_criteria):
    """Byte-identical output for identical input -- tests must not flake."""
    first = mock_evaluate("Apex Systems", DOC, default_criteria)
    second = mock_evaluate("Apex Systems", DOC, default_criteria)
    assert first == second


def test_mock_scores_stay_inside_the_range(default_criteria):
    payload = json.loads(mock_evaluate("Apex Systems", DOC, default_criteria))
    for item, criterion in zip(payload["criteria"], default_criteria):
        assert 0 <= item["score"] <= criterion.max_score


def test_mock_evidence_is_verbatim_and_verifiable(default_criteria):
    """Quotes must survive the validator's evidence check, like a real model's."""
    raw = mock_evaluate("Apex Systems", DOC, default_criteria)
    result = validate_raw_response(
        raw, default_criteria, supplier_name="Apex Systems", document_text=DOC
    )
    for scored in result.criteria:
        if scored.evidence != SENTINEL_NO_EVIDENCE:
            assert scored.evidence in DOC
            assert scored.evidence_verified


def test_mock_scores_zero_with_the_sentinel_when_nothing_matches(default_criteria):
    payload = json.loads(mock_evaluate("Empty Ltd", "Nothing relevant here.",
                                       default_criteria))
    assert all(item["score"] == 0 for item in payload["criteria"])
    assert all(item["evidence"] == SENTINEL_NO_EVIDENCE for item in payload["criteria"])


def test_mock_separates_a_strong_document_from_a_weak_one(default_criteria):
    strong = json.loads(mock_evaluate("Strong", DOC, default_criteria))
    weak = json.loads(mock_evaluate("Weak", "We will do the work well.",
                                    default_criteria))
    assert sum(i["score"] for i in strong["criteria"]) > \
        sum(i["score"] for i in weak["criteria"])


# ---------------------------------------------------------------------------
# provider guards
# ---------------------------------------------------------------------------
def test_unknown_provider_is_rejected():
    with pytest.raises(EvaluationError, match="Unknown provider"):
        EvaluationAgent(provider="gemini")


def test_openai_provider_without_a_key_is_rejected():
    with pytest.raises(EvaluationError, match="No API key"):
        EvaluationAgent(provider="openai", model="gpt-4o", api_key="")


def test_openai_provider_without_a_model_is_rejected():
    with pytest.raises(EvaluationError, match="No model configured"):
        EvaluationAgent(provider="openai", model="", api_key="sk-test")


def test_mock_provider_needs_neither_key_nor_model():
    agent = EvaluationAgent(provider="mock")
    assert agent.is_mock
    assert agent.model
    assert "mock" in agent.description


def test_invalid_fault_mode_is_ignored_rather_than_crashing():
    assert EvaluationAgent(provider="mock", fault="nonsense").fault is None
    assert EvaluationAgent(provider="mock", fault="malformed_values").fault == \
        "malformed_values"


# ---------------------------------------------------------------------------
# fault injection
# ---------------------------------------------------------------------------
def test_corruption_produces_exactly_five_validation_warnings(default_criteria):
    """Six defects go in; five produce warnings. Code fences are silent."""
    clean = mock_evaluate("Apex Systems", DOC, default_criteria)
    corrupted = corrupt_response(clean, default_criteria)

    assert corrupted.startswith("```")          # defect 6, handled silently
    result = validate_raw_response(
        corrupted, default_criteria, supplier_name="Apex Systems", document_text=DOC
    )
    assert len(result.warnings) == 5
    assert result.parse_failed is False
    assert len(result.criteria) == len(default_criteria)


def test_corruption_covers_each_documented_defect(default_criteria):
    clean = mock_evaluate("Apex Systems", DOC, default_criteria)
    result = validate_raw_response(
        corrupt_response(clean, default_criteria), default_criteria,
        supplier_name="Apex Systems", document_text=DOC,
    )
    statuses = {c.criterion_id: c.status for c in result.criteria}
    joined = " | ".join(result.warnings)

    assert statuses[default_criteria[0].criterion_id] == "CLIPPED"
    assert statuses[default_criteria[1].criterion_id] == "DEFAULTED_INVALID"
    assert statuses[default_criteria[2].criterion_id] == "DEFAULTED_MISSING"
    assert "unknown criterion" in joined.lower()
    assert "Duplicate entry" in joined


def test_agent_only_faults_the_supplier_it_is_told_to(default_criteria):
    agent = EvaluationAgent(provider="mock", fault="malformed_values")
    faulted = agent.evaluate("First", DOC, default_criteria, apply_fault=True)
    clean = agent.evaluate("Second", DOC, default_criteria, apply_fault=False)
    assert faulted.faulted and faulted.raw.startswith("```")
    assert not clean.faulted and not clean.raw.startswith("```")


def test_invalid_json_once_recovers_on_the_second_attempt(default_criteria):
    agent = EvaluationAgent(provider="mock", fault="invalid_json_once")
    first = agent.evaluate("First", DOC, default_criteria, attempt=1, apply_fault=True)
    second = agent.evaluate("First", DOC, default_criteria, attempt=2,
                            previous_response=first.raw, apply_fault=True)
    assert "{" not in first.raw
    assert json.loads(second.raw)["supplier_name"] == "First"


def test_invalid_json_always_never_recovers(default_criteria):
    agent = EvaluationAgent(provider="mock", fault="invalid_json_always")
    for attempt in (1, 2):
        call = agent.evaluate("First", DOC, default_criteria, attempt=attempt,
                              apply_fault=True)
        assert "{" not in call.raw


def test_all_documented_fault_modes_are_accepted():
    for mode in FAULT_MODES:
        assert EvaluationAgent(provider="mock", fault=mode).fault == mode


# ---------------------------------------------------------------------------
# provider quirks
# ---------------------------------------------------------------------------
class _FakeBadRequest(Exception):
    """Stands in for openai.BadRequestError, which carries a parsed `body`."""

    def __init__(self, body):
        super().__init__("Error code: 400")
        self.body = body


def test_failed_generation_is_salvaged_from_a_flat_error_body():
    """Groq validates JSON server-side and returns the text in a 400.

    The OpenAI SDK unwraps the {"error": {...}} envelope, so the payload
    arrives flat. Salvaging it lets the normal repair-retry path handle a bad
    response instead of the whole run aborting.
    """
    from rfp.agents.evaluation_agent import _failed_generation

    exc = _FakeBadRequest({
        "message": "Failed to generate JSON.",
        "type": "invalid_request_error",
        "code": "json_validate_failed",
        "failed_generation": '{"supplier_name":"Apex Systems"',
    })
    assert _failed_generation(exc) == '{"supplier_name":"Apex Systems"'


def test_failed_generation_is_salvaged_from_a_nested_error_body():
    from rfp.agents.evaluation_agent import _failed_generation

    exc = _FakeBadRequest({"error": {"failed_generation": '{"a": 1}'}})
    assert _failed_generation(exc) == '{"a": 1}'


@pytest.mark.parametrize("body", [
    None,
    "plain string body",
    {"message": "Invalid API Key", "code": "invalid_api_key"},
    {"error": {"message": "model not found", "code": "model_not_found"}},
])
def test_genuine_errors_are_not_mistaken_for_salvageable_output(body):
    """A bad key or a retired model must still abort loudly."""
    from rfp.agents.evaluation_agent import _failed_generation

    assert _failed_generation(_FakeBadRequest(body)) is None


def test_json_mode_rejection_retries_without_json_mode(monkeypatch, default_criteria):
    """A server-side JSON rejection must trigger a plain retry, not a zero score.

    Groq validates JSON mode itself and 400s the whole completion. Our parser
    tolerates fences and prose, so asking again without response_format
    recovers the supplier instead of defaulting it to 0.
    """
    calls: list[dict] = []

    class _Completions:
        def create(self, **kwargs):
            calls.append(kwargs)
            if "response_format" in kwargs:
                raise _FakeBadRequest({
                    "code": "json_validate_failed",
                    "failed_generation": '{"supplier_name":"Apex Systems"',
                })

            class _Msg:
                content = '```json\n{"supplier_name":"Apex Systems","criteria":[]}\n```'

            class _Choice:
                message = _Msg()

            class _Response:
                choices = [_Choice()]

            return _Response()

    class _Chat:
        completions = _Completions()

    class _Client:
        chat = _Chat()

    agent = EvaluationAgent(provider="openai", model="m", api_key="sk-test")
    monkeypatch.setattr(agent, "_openai_client", lambda: _Client())

    raw = agent._call_openai("system", "user")

    assert len(calls) == 2
    assert "response_format" in calls[0] and "response_format" not in calls[1]
    assert "Apex Systems" in raw


def test_salvaged_text_is_used_when_the_plain_retry_also_fails(monkeypatch):
    """If both attempts fail, fall back to the salvaged text rather than dying."""
    class _Completions:
        def create(self, **kwargs):
            raise _FakeBadRequest({
                "code": "json_validate_failed",
                "failed_generation": '{"supplier_name":"Apex"',
            })

    class _Chat:
        completions = _Completions()

    class _Client:
        chat = _Chat()

    agent = EvaluationAgent(provider="openai", model="m", api_key="sk-test")
    monkeypatch.setattr(agent, "_openai_client", lambda: _Client())

    assert agent._call_openai("system", "user") == '{"supplier_name":"Apex"'
