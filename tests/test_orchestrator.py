"""End-to-end pipeline through the LangGraph orchestrator, on the mock provider."""

from __future__ import annotations

import pytest

from rfp import config, db, orchestrator

SAMPLES = config.SAMPLE_PDF_DIR
ERROR_CASES = SAMPLES / "error_cases"

requires_samples = pytest.mark.skipif(
    not (SAMPLES / "nexaworks_proposal.pdf").exists(),
    reason="run scripts/generate_sample_pdfs.py first",
)

SUPPLIER_SPECS = [
    ("Apex Systems", "2026-09-08", 4.2, "apex_systems_proposal.pdf"),
    ("BrightPath Tech", "2026-09-11", 2.5, "brightpath_tech_proposal.pdf"),
    ("NexaWorks", "2026-09-09", 4.0, "nexaworks_proposal.pdf"),
    ("Orbit Digital", "2026-09-10", 4.6, "orbit_digital_proposal.pdf"),
]


@pytest.fixture
def temp_db(tmp_path):
    path = tmp_path / "run.db"
    db.init_db(path)
    return str(path)


def suppliers(count: int = 4) -> list[dict]:
    return [
        {"supplier_name": name, "submission_date": date,
         "experience_rating": rating, "source": SAMPLES / filename,
         "source_name": filename}
        for name, date, rating, filename in SUPPLIER_SPECS[:count]
    ]


@requires_samples
def test_full_run_ranks_every_supplier(temp_db):
    result = orchestrator.run_evaluation(suppliers(), provider="mock", db_path=temp_db)

    assert result["status"] == "COMPLETED"
    assert len(result["suppliers"]) == 4
    assert [s["final_rank"] for s in result["suppliers"]] == [1, 2, 3, 4]
    assert len(result["tie_breaks"]) == 3
    assert result["rfp_run_id"].startswith("RFP-")


@requires_samples
def test_run_is_persisted_and_reloadable(temp_db):
    result = orchestrator.run_evaluation(suppliers(), provider="mock", db_path=temp_db)

    stored = db.load_run(result["rfp_run_id"], temp_db)
    assert stored is not None
    assert stored["status"] == "COMPLETED"
    assert len(stored["suppliers"]) == 4

    rows = db.supplier_rows_for_run(result["rfp_run_id"], temp_db)
    assert [r["final_rank"] for r in rows] == [1, 2, 3, 4]
    assert db.list_runs(path=temp_db)[0]["rfp_run_id"] == result["rfp_run_id"]


@requires_samples
def test_agent_trace_visits_every_stage(temp_db):
    result = orchestrator.run_evaluation(suppliers(), provider="mock", db_path=temp_db)
    steps = [entry["step"] for entry in result["agent_trace"]]

    assert steps[0] == "load_criteria"
    assert steps[-1] == "persist_results"
    for stage in ("extract_document", "evaluate_supplier", "validate_output",
                  "score_benchmark_rank"):
        assert steps.count(stage) >= 1
    assert steps.count("evaluate_supplier") == 4      # one call per supplier


@requires_samples
def test_criteria_are_reloaded_from_the_database_at_run_time(temp_db):
    """Editing criteria changes the next run without restarting anything."""
    edited = [
        db.Criterion(1, "Technical Capability", "Architecture and scalability.",
                     70.0, 10.0, True),
        db.Criterion(2, "Implementation Plan", "Phases and milestones.",
                     30.0, 10.0, True),
    ]
    db.save_criteria(edited, temp_db)
    result = orchestrator.run_evaluation(suppliers(2), provider="mock", db_path=temp_db)

    assert len(result["criteria"]) == 2
    assert result["criteria"][0]["weight"] == 70.0
    for supplier in result["suppliers"]:
        assert len(supplier["criteria"]) == 2


@requires_samples
def test_identical_runs_produce_identical_rankings(temp_db):
    """Determinism after validation: same inputs, same ordering and same numbers."""
    first = orchestrator.run_evaluation(suppliers(), provider="mock", db_path=temp_db)
    second = orchestrator.run_evaluation(suppliers(), provider="mock", db_path=temp_db)

    def shape(result):
        return [(s["final_rank"], s["supplier_name"], s["absolute_score"], s["ppi"])
                for s in result["suppliers"]]

    assert shape(first) == shape(second)
    assert first["rfp_run_id"] != second["rfp_run_id"]     # but they are separate runs


@requires_samples
def test_unreadable_pdf_is_skipped_without_killing_the_run(temp_db):
    specs = suppliers(3) + [{
        "supplier_name": "Broken Ltd", "submission_date": "2026-09-12",
        "experience_rating": 3.0, "source": ERROR_CASES / "not_a_pdf.pdf",
        "source_name": "not_a_pdf.pdf",
    }]
    result = orchestrator.run_evaluation(specs, provider="mock", db_path=temp_db)

    assert result["status"] == "COMPLETED"
    assert len(result["suppliers"]) == 3
    assert "Broken Ltd" not in [s["supplier_name"] for s in result["suppliers"]]
    assert result["skipped"][0]["supplier_name"] == "Broken Ltd"
    assert result["skipped"][0]["code"] == "NOT_A_PDF"


@requires_samples
def test_scanned_pdf_is_skipped_with_the_right_code(temp_db):
    specs = suppliers(2) + [{
        "supplier_name": "Scanned Ltd", "submission_date": "2026-09-12",
        "experience_rating": 3.0, "source": ERROR_CASES / "scanned_no_text.pdf",
        "source_name": "scanned_no_text.pdf",
    }]
    result = orchestrator.run_evaluation(specs, provider="mock", db_path=temp_db)

    assert result["skipped"][0]["code"] == "NO_TEXT_LAYER"
    assert len(result["suppliers"]) == 2


@requires_samples
def test_fault_malformed_values_reports_five_warnings(temp_db):
    result = orchestrator.run_evaluation(
        suppliers(), provider="mock", fault="malformed_values", db_path=temp_db
    )
    first_supplier = SUPPLIER_SPECS[0][0]
    warnings = [w for w in result["warnings"] if w.startswith(first_supplier)]

    assert len(warnings) == 5
    assert result["status"] == "COMPLETED"
    assert len(result["suppliers"]) == 4       # the faulted supplier stays visible


@requires_samples
def test_fault_invalid_json_once_retries_and_recovers(temp_db):
    result = orchestrator.run_evaluation(
        suppliers(), provider="mock", fault="invalid_json_once", db_path=temp_db
    )
    first_supplier = SUPPLIER_SPECS[0][0]
    calls = [c for c in result["raw_llm_outputs"] if c["supplier_name"] == first_supplier]

    assert [c["attempt"] for c in calls] == [1, 2]    # exactly one retry
    assert not any("not valid JSON" in w for w in result["warnings"])
    assert any(s["supplier_name"] == first_supplier and s["absolute_score"] > 0
               for s in result["suppliers"])


@requires_samples
def test_fault_invalid_json_always_defaults_to_zero_but_keeps_the_supplier(temp_db):
    result = orchestrator.run_evaluation(
        suppliers(), provider="mock", fault="invalid_json_always", db_path=temp_db
    )
    first_supplier = SUPPLIER_SPECS[0][0]
    row = next(s for s in result["suppliers"] if s["supplier_name"] == first_supplier)

    assert row["absolute_score"] == 0.0
    assert row["ppi"] == 0.0
    assert row["final_rank"] == 4               # last, but still present
    assert row["parse_failed"] is True


@requires_samples
def test_retry_stops_after_one_attempt(temp_db):
    """The repair prompt is sent once, never in a loop."""
    result = orchestrator.run_evaluation(
        suppliers(1) + suppliers(2)[1:], provider="mock",
        fault="invalid_json_always", db_path=temp_db,
    )
    first_supplier = SUPPLIER_SPECS[0][0]
    calls = [c for c in result["raw_llm_outputs"] if c["supplier_name"] == first_supplier]
    assert len(calls) == orchestrator.MAX_LLM_ATTEMPTS == 2


@requires_samples
def test_result_document_carries_everything_the_ui_needs(temp_db):
    result = orchestrator.run_evaluation(suppliers(), provider="mock", db_path=temp_db)
    for key in ("rfp_run_id", "created_at", "completed_at", "status", "llm_provider",
                "llm_model", "criteria", "suppliers", "benchmarks", "tie_breaks",
                "skipped", "warnings", "agent_trace", "raw_llm_outputs", "formulas"):
        assert key in result, f"missing {key}"

    supplier = result["suppliers"][0]
    for key in ("absolute_score", "ppi", "final_rank", "tie_break_reason", "criteria"):
        assert key in supplier
    for key in ("score", "benchmark", "gap", "relative_pct", "weighted_points",
                "status", "evidence_verified", "justification", "evidence"):
        assert key in supplier["criteria"][0]


@requires_samples
def test_bad_criteria_weights_abort_before_any_llm_call(temp_db):
    with db.connect(temp_db) as conn:
        conn.execute("UPDATE evaluation_criteria SET weight = 5 WHERE criterion_id = 1")
        conn.commit()

    result = orchestrator.run_evaluation(suppliers(), provider="mock", db_path=temp_db)

    assert result["status"] == "FAILED"
    assert "must total" in result["error"]
    assert result["raw_llm_outputs"] == []      # nothing was ever sent
