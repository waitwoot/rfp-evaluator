"""Persistence: criteria editing rules, and the atomic run write."""

from __future__ import annotations

import json

import pytest

from rfp import db
from rfp.db import Criterion, WeightError


@pytest.fixture
def temp_db(tmp_path):
    path = tmp_path / "test.db"
    db.init_db(path)
    return path


def test_init_seeds_five_criteria_totalling_100(temp_db):
    criteria = db.load_criteria(temp_db)
    assert len(criteria) == 5
    assert db.active_weight_total(criteria) == 100.0
    assert all(c.max_score == 10.0 for c in criteria)


def test_init_is_idempotent(temp_db):
    db.init_db(temp_db)
    db.init_db(temp_db)
    assert len(db.load_criteria(temp_db)) == 5


def test_weights_must_total_100(temp_db):
    criteria = db.load_criteria(temp_db)
    broken = [*criteria[:-1], Criterion(5, "Support & Experience", "d", 25.0, 10.0, True)]
    with pytest.raises(WeightError, match="115"):
        db.save_criteria(broken, temp_db)


def test_rejected_save_leaves_the_table_untouched(temp_db):
    before = db.load_criteria(temp_db)
    with pytest.raises(WeightError):
        db.save_criteria([Criterion(1, "Solo", "d", 42.0, 10.0, True)], temp_db)
    assert db.load_criteria(temp_db) == before


def test_valid_edit_is_saved(temp_db):
    edited = [
        Criterion(1, "Technical Capability", "d", 40.0, 10.0, True),
        Criterion(2, "Implementation Plan", "d", 20.0, 10.0, True),
        Criterion(3, "Commercial Value", "d", 20.0, 10.0, True),
        Criterion(4, "Security & Compliance", "d", 20.0, 10.0, True),
    ]
    db.save_criteria(edited, temp_db)
    reloaded = db.load_criteria(temp_db)
    assert len(reloaded) == 4
    assert reloaded[0].weight == 40.0


def test_deactivated_criteria_are_excluded_but_retained(temp_db):
    criteria = db.load_criteria(temp_db)
    # deactivate Support & Experience, push its 10% onto Technical Capability
    edited = [
        Criterion(c.criterion_id, c.name, c.description,
                  40.0 if c.criterion_id == 1 else c.weight,
                  c.max_score,
                  c.criterion_id != 5)
        for c in criteria
    ]
    db.save_criteria(edited, temp_db)
    assert len(db.load_criteria(temp_db, active_only=True)) == 4
    assert len(db.load_criteria(temp_db, active_only=False)) == 5


def test_all_inactive_is_rejected(temp_db):
    criteria = [
        Criterion(c.criterion_id, c.name, c.description, c.weight, c.max_score, False)
        for c in db.load_criteria(temp_db)
    ]
    with pytest.raises(WeightError, match="[Aa]t least one"):
        db.save_criteria(criteria, temp_db)


def test_zero_max_score_is_rejected(temp_db):
    criteria = db.load_criteria(temp_db)
    broken = [
        Criterion(c.criterion_id, c.name, c.description, c.weight,
                  0.0 if c.criterion_id == 1 else c.max_score, True)
        for c in criteria
    ]
    with pytest.raises(WeightError, match="max_score"):
        db.save_criteria(broken, temp_db)


def test_reset_restores_the_defaults(temp_db):
    db.save_criteria([Criterion(1, "Only", "d", 100.0, 10.0, True)], temp_db)
    assert len(db.load_criteria(temp_db)) == 1
    db.reset_criteria(temp_db)
    assert db.active_weight_total(db.load_criteria(temp_db)) == 100.0


# ---------------------------------------------------------------------------
# runs
# ---------------------------------------------------------------------------
def sample_run(run_id="RFP-20260928-ABC123"):
    return {
        "rfp_run_id": run_id,
        "created_at": "2026-09-28T09:00:00",
        "completed_at": "2026-09-28T09:03:00",
        "status": "COMPLETED",
        "llm_provider": "mock",
        "llm_model": "mock-keyword-scorer",
        "criteria": [{"criterion_id": 1, "name": "Technical Capability", "weight": 30.0}],
        "warnings": ["Apex Systems: score 14 exceeds the maximum 10; clipped."],
        "suppliers": [
            {"supplier_name": "NexaWorks", "submission_date": "2026-09-09",
             "experience_rating": 4.0, "absolute_score": 82.0, "ppi": 94.5,
             "final_rank": 1, "criteria": [], "risks": []},
            {"supplier_name": "Apex Systems", "submission_date": "2026-09-08",
             "experience_rating": 4.2, "absolute_score": 79.0, "ppi": 91.2,
             "final_rank": 2, "criteria": [], "risks": []},
        ],
    }


def test_run_round_trips_exactly(temp_db):
    run = sample_run()
    db.persist_run(run, temp_db)
    assert db.load_run(run["rfp_run_id"], temp_db) == run


def test_supplier_scalars_are_queryable_with_plain_sql(temp_db):
    db.persist_run(sample_run(), temp_db)
    rows = db.supplier_rows_for_run("RFP-20260928-ABC123", temp_db)
    assert [r["supplier_name"] for r in rows] == ["NexaWorks", "Apex Systems"]
    assert rows[0]["final_rank"] == 1
    assert rows[0]["ppi"] == 94.5


def test_history_lists_runs_newest_first(temp_db):
    first = sample_run("RFP-A")
    first["created_at"] = "2026-09-01T09:00:00"
    second = sample_run("RFP-B")
    second["created_at"] = "2026-09-20T09:00:00"
    db.persist_run(first, temp_db)
    db.persist_run(second, temp_db)
    assert [r["rfp_run_id"] for r in db.list_runs(path=temp_db)] == ["RFP-B", "RFP-A"]


def test_rerunning_the_same_id_replaces_supplier_rows(temp_db):
    db.persist_run(sample_run(), temp_db)
    shrunk = sample_run()
    shrunk["suppliers"] = shrunk["suppliers"][:1]
    db.persist_run(shrunk, temp_db)
    assert len(db.supplier_rows_for_run("RFP-20260928-ABC123", temp_db)) == 1


def test_unknown_run_returns_none(temp_db):
    assert db.load_run("RFP-NOPE", temp_db) is None


def test_failed_run_before_completion_is_still_readable(temp_db):
    db.create_run("RFP-PENDING", "2026-09-28T09:00:00", llm_provider="openai",
                  llm_model="gpt-oss-120b", supplier_count=4,
                  criteria_snapshot=[{"criterion_id": 1}], path=temp_db)
    db.mark_run_status("RFP-PENDING", "FAILED", completed_at="2026-09-28T09:01:00",
                       warnings=["API key rejected"], path=temp_db)
    loaded = db.load_run("RFP-PENDING", temp_db)
    assert loaded["status"] == "FAILED"
    assert loaded["warnings"] == ["API key rejected"]
    assert loaded["suppliers"] == []


def test_persisted_run_json_is_valid_json(temp_db):
    db.persist_run(sample_run(), temp_db)
    with db.connect(temp_db) as conn:
        raw = conn.execute(
            "SELECT run_json FROM rfp_runs WHERE rfp_run_id = ?",
            ("RFP-20260928-ABC123",),
        ).fetchone()[0]
    assert json.loads(raw)["suppliers"][0]["supplier_name"] == "NexaWorks"
