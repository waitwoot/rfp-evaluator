"""SQLite persistence layer.

Everything the app stores lives here: the editable criteria, and the full
audit trail of every run. A run is written in ONE transaction so a crash
mid-write can never leave a half-persisted leaderboard.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

from rfp import config

# Seeded on first init and restored by "Reset to defaults" in the UI.
# Weights total 100; every criterion is scored out of 10.
SEED_CRITERIA: tuple[tuple[int, str, str, float, float], ...] = (
    (
        1,
        "Technical Capability",
        "Architecture and technology stack, scalability and performance, "
        "integration approach with existing systems, and overall technical depth "
        "demonstrated in the proposed solution.",
        30.0,
        10.0,
    ),
    (
        2,
        "Implementation Plan",
        "Project phases and realism of the timeline, named milestones and "
        "deliverables, team composition and resourcing, data migration and "
        "cutover approach, and how delivery risk is managed.",
        20.0,
        10.0,
    ),
    (
        3,
        "Commercial Value",
        "Total cost of ownership, transparency and completeness of the price "
        "breakdown, stated commercial assumptions, payment terms, and overall "
        "value for money relative to what is delivered.",
        20.0,
        10.0,
    ),
    (
        4,
        "Security & Compliance",
        "Named certifications and standards, data protection and residency, "
        "access control and encryption, audit logging, regulatory compliance, "
        "and documented risk controls.",
        20.0,
        10.0,
    ),
    (
        5,
        "Support & Experience",
        "Support model and response/resolution SLAs, training and handover, "
        "account management, and relevant past projects with verifiable "
        "references.",
        10.0,
        10.0,
    ),
)


@dataclass(frozen=True)
class Criterion:
    """One row of ``evaluation_criteria``."""

    criterion_id: int
    name: str
    description: str
    weight: float
    max_score: float
    is_active: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Criterion":
        return cls(
            criterion_id=int(row["criterion_id"]),
            name=str(row["name"]),
            description=str(row["description"]),
            weight=float(row["weight"]),
            max_score=float(row["max_score"]),
            is_active=bool(row["is_active"]),
        )


class WeightError(ValueError):
    """Raised when active criteria weights do not total 100."""


# --------------------------------------------------------------------------
# connection handling
# --------------------------------------------------------------------------
@contextmanager
def connect(path: str | Path | None = None) -> Iterator[sqlite3.Connection]:
    """Yield a connection with row access by name and FK enforcement on."""
    target = Path(path) if path is not None else config.db_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
    finally:
        conn.close()


def init_db(path: str | Path | None = None, *, seed: bool = True) -> Path:
    """Create the schema if absent and (optionally) seed default criteria."""
    target = Path(path) if path is not None else config.db_path()
    schema_sql = config.SCHEMA_PATH.read_text(encoding="utf-8")
    with connect(target) as conn:
        conn.executescript(schema_sql)
        if seed:
            _seed_criteria_if_empty(conn)
        conn.commit()
    return target


def _seed_criteria_if_empty(conn: sqlite3.Connection) -> bool:
    """Insert the default criteria only when the table is empty."""
    existing = conn.execute("SELECT COUNT(*) FROM evaluation_criteria").fetchone()[0]
    if existing:
        return False
    conn.executemany(
        "INSERT INTO evaluation_criteria "
        "(criterion_id, name, description, weight, max_score, is_active) "
        "VALUES (?, ?, ?, ?, ?, 1)",
        SEED_CRITERIA,
    )
    return True


# --------------------------------------------------------------------------
# criteria
# --------------------------------------------------------------------------
def load_criteria(
    path: str | Path | None = None, *, active_only: bool = True
) -> list[Criterion]:
    """Read criteria from the DB.

    The orchestrator calls this at evaluation time (never from a cached copy),
    so edits made in the Criteria tab take effect on the very next run.
    """
    sql = "SELECT * FROM evaluation_criteria"
    if active_only:
        sql += " WHERE is_active = 1"
    sql += " ORDER BY criterion_id"
    with connect(path) as conn:
        return [Criterion.from_row(r) for r in conn.execute(sql)]


def active_weight_total(criteria: Iterable[Criterion]) -> float:
    return round(sum(c.weight for c in criteria if c.is_active), 6)


def validate_weights(criteria: Sequence[Criterion]) -> None:
    """Raise WeightError unless the active weights total 100."""
    active = [c for c in criteria if c.is_active]
    if not active:
        raise WeightError("At least one criterion must be active.")
    total = active_weight_total(active)
    if abs(total - config.WEIGHT_TOTAL) > config.WEIGHT_TOLERANCE:
        raise WeightError(
            f"Active criteria weights total {total:g}%, but must total "
            f"{config.WEIGHT_TOTAL:g}%."
        )
    for c in active:
        if c.max_score <= 0:
            raise WeightError(f"'{c.name}' has max_score {c.max_score:g}; must be > 0.")


def save_criteria(
    criteria: Sequence[Criterion], path: str | Path | None = None
) -> None:
    """Replace the criteria table wholesale, refusing invalid weight totals."""
    validate_weights(criteria)
    rows = [
        (c.criterion_id, c.name, c.description, c.weight, c.max_score, int(c.is_active))
        for c in criteria
    ]
    with connect(path) as conn:
        try:
            conn.execute("BEGIN")
            conn.execute("DELETE FROM evaluation_criteria")
            conn.executemany(
                "INSERT INTO evaluation_criteria "
                "(criterion_id, name, description, weight, max_score, is_active) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                rows,
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def reset_criteria(path: str | Path | None = None) -> list[Criterion]:
    """Restore the five seeded criteria."""
    with connect(path) as conn:
        try:
            conn.execute("BEGIN")
            conn.execute("DELETE FROM evaluation_criteria")
            conn.executemany(
                "INSERT INTO evaluation_criteria "
                "(criterion_id, name, description, weight, max_score, is_active) "
                "VALUES (?, ?, ?, ?, ?, 1)",
                SEED_CRITERIA,
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return load_criteria(path, active_only=False)


# --------------------------------------------------------------------------
# runs
# --------------------------------------------------------------------------
def create_run(
    rfp_run_id: str,
    created_at: str,
    *,
    llm_provider: str,
    llm_model: str,
    supplier_count: int,
    criteria_snapshot: Sequence[dict[str, Any]] | None = None,
    path: str | Path | None = None,
) -> None:
    """Register a run as CREATED before any LLM call happens."""
    with connect(path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO rfp_runs "
            "(rfp_run_id, created_at, status, llm_provider, llm_model, "
            " supplier_count, criteria_snapshot) "
            "VALUES (?, ?, 'CREATED', ?, ?, ?, ?)",
            (
                rfp_run_id,
                created_at,
                llm_provider,
                llm_model,
                supplier_count,
                json.dumps(list(criteria_snapshot or []), ensure_ascii=False),
            ),
        )
        conn.commit()


def mark_run_status(
    rfp_run_id: str,
    status: str,
    *,
    completed_at: str | None = None,
    warnings: Sequence[str] | None = None,
    path: str | Path | None = None,
) -> None:
    with connect(path) as conn:
        conn.execute(
            "UPDATE rfp_runs SET status = ?, completed_at = COALESCE(?, completed_at), "
            "warnings_json = COALESCE(?, warnings_json) WHERE rfp_run_id = ?",
            (
                status,
                completed_at,
                json.dumps(list(warnings), ensure_ascii=False) if warnings is not None else None,
                rfp_run_id,
            ),
        )
        conn.commit()


def persist_run(result: dict[str, Any], path: str | Path | None = None) -> None:
    """Write the finished run — header row plus every supplier — atomically.

    ``result`` is the orchestrator's complete result document; it is stored
    verbatim in ``run_json`` so the History tab can reproduce any past run
    without recomputing anything.
    """
    run_id = result["rfp_run_id"]
    suppliers = result.get("suppliers", [])
    run_json = json.dumps(result, ensure_ascii=False, indent=2)

    supplier_rows = [
        (
            run_id,
            s["supplier_name"],
            s.get("submission_date"),
            s.get("experience_rating"),
            s.get("absolute_score"),
            s.get("ppi"),
            s.get("final_rank"),
            json.dumps(s, ensure_ascii=False),
        )
        for s in suppliers
    ]

    with connect(path) as conn:
        try:
            conn.execute("BEGIN")
            conn.execute(
                "INSERT OR REPLACE INTO rfp_runs "
                "(rfp_run_id, created_at, status, completed_at, llm_provider, "
                " llm_model, supplier_count, criteria_snapshot, warnings_json, run_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    result.get("created_at"),
                    result.get("status", "COMPLETED"),
                    result.get("completed_at"),
                    result.get("llm_provider"),
                    result.get("llm_model"),
                    len(suppliers),
                    json.dumps(result.get("criteria", []), ensure_ascii=False),
                    json.dumps(result.get("warnings", []), ensure_ascii=False),
                    run_json,
                ),
            )
            conn.execute("DELETE FROM supplier_results WHERE rfp_run_id = ?", (run_id,))
            conn.executemany(
                "INSERT INTO supplier_results "
                "(rfp_run_id, supplier_name, submission_date, experience_rating, "
                " absolute_score, ppi, final_rank, result_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                supplier_rows,
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def list_runs(limit: int = 50, path: str | Path | None = None) -> list[dict[str, Any]]:
    """Run summaries for the History tab, newest first."""
    with connect(path) as conn:
        rows = conn.execute(
            "SELECT rfp_run_id, created_at, status, completed_at, llm_provider, "
            "       llm_model, supplier_count "
            "FROM rfp_runs ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def load_run(rfp_run_id: str, path: str | Path | None = None) -> dict[str, Any] | None:
    """Rehydrate a stored run document, or None if the id is unknown."""
    with connect(path) as conn:
        row = conn.execute(
            "SELECT * FROM rfp_runs WHERE rfp_run_id = ?", (rfp_run_id,)
        ).fetchone()
        if row is None:
            return None
        if row["run_json"]:
            return json.loads(row["run_json"])
        # Header persisted but the run never completed: rebuild what we can.
        supplier_rows = conn.execute(
            "SELECT * FROM supplier_results WHERE rfp_run_id = ? ORDER BY final_rank",
            (rfp_run_id,),
        ).fetchall()
    return {
        "rfp_run_id": row["rfp_run_id"],
        "created_at": row["created_at"],
        "status": row["status"],
        "completed_at": row["completed_at"],
        "llm_provider": row["llm_provider"],
        "llm_model": row["llm_model"],
        "criteria": json.loads(row["criteria_snapshot"] or "[]"),
        "warnings": json.loads(row["warnings_json"] or "[]"),
        "suppliers": [json.loads(r["result_json"] or "{}") for r in supplier_rows],
    }


def supplier_rows_for_run(
    rfp_run_id: str, path: str | Path | None = None
) -> list[dict[str, Any]]:
    """Raw SQLite rows, shown in the Run details tab as persistence evidence."""
    with connect(path) as conn:
        rows = conn.execute(
            "SELECT rfp_run_id, supplier_name, submission_date, experience_rating, "
            "       absolute_score, ppi, final_rank "
            "FROM supplier_results WHERE rfp_run_id = ? "
            "ORDER BY final_rank, supplier_name",
            (rfp_run_id,),
        ).fetchall()
    return [dict(r) for r in rows]
