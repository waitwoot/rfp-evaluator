-- Agentic RFP Evaluation -- SQLite schema
-- Three tables: the editable criteria, one row per evaluation run, and one
-- row per supplier within a run. The *_json columns hold the full audit trail
-- so any historical run can be replayed in the UI exactly as it was scored.

PRAGMA foreign_keys = ON;

-- Scoring criteria. Editable in the UI; active weights must total 100.
CREATE TABLE IF NOT EXISTS evaluation_criteria (
    criterion_id INTEGER PRIMARY KEY,
    name         TEXT    NOT NULL UNIQUE,
    description  TEXT    NOT NULL,            -- "what to inspect", injected into the prompt
    weight       REAL    NOT NULL CHECK (weight >= 0),
    max_score    REAL    NOT NULL CHECK (max_score > 0),
    is_active    INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1))
);

-- One evaluation run.
CREATE TABLE IF NOT EXISTS rfp_runs (
    rfp_run_id        TEXT PRIMARY KEY,
    created_at        TEXT NOT NULL,
    status            TEXT NOT NULL
                      CHECK (status IN ('CREATED', 'RUNNING', 'COMPLETED', 'FAILED')),
    completed_at      TEXT,
    llm_provider      TEXT,
    llm_model         TEXT,
    supplier_count    INTEGER NOT NULL DEFAULT 0,
    criteria_snapshot TEXT,   -- JSON: the criteria exactly as they were at run time
    warnings_json     TEXT,   -- JSON: run-level validation warnings
    run_json          TEXT    -- JSON: the complete result document (exportable)
);

-- One supplier inside a run. Scalars are duplicated out of result_json so the
-- leaderboard and History tab can be read with plain SQL.
CREATE TABLE IF NOT EXISTS supplier_results (
    rfp_run_id        TEXT NOT NULL,
    supplier_name     TEXT NOT NULL,
    submission_date   TEXT,
    experience_rating REAL,
    absolute_score    REAL,
    ppi               REAL,
    final_rank        INTEGER,
    result_json       TEXT,   -- JSON: per-criterion scores, evidence, warnings
    PRIMARY KEY (rfp_run_id, supplier_name),
    FOREIGN KEY (rfp_run_id) REFERENCES rfp_runs (rfp_run_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_supplier_results_rank
    ON supplier_results (rfp_run_id, final_rank);

CREATE INDEX IF NOT EXISTS idx_rfp_runs_created
    ON rfp_runs (created_at DESC);
