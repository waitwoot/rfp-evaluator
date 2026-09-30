"""Orchestrator agent -- a LangGraph StateGraph driving the whole evaluation.

    load_criteria
         |
    extract_document <-------------------+
         |  (unreadable PDF -> skip)      |
    evaluate_supplier <--+                |
         |               | (bad JSON,     |
    validate_output -----+  retry once)   |
         |                                |
    next_supplier ----------------------- + (more suppliers)
         |  (none left)
    score_benchmark_rank
         |
    persist_results

Conditional edges cover: retry on unparseable JSON (once), skip an unreadable
document without killing the run, loop over suppliers, and abort on a fatal
provider error. Every node appends to an agent trace that the UI renders live.

recursion_limit is raised to 500: LangGraph counts every node visit, and four
suppliers times five nodes plus retries comfortably exceeds the default of 25.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from operator import add
from typing import Annotated, Any, Callable, Sequence, TypedDict

from langgraph.graph import END, START, StateGraph

from rfp import config, db
from rfp.agents.evaluation_agent import AgentCall, EvaluationAgent, EvaluationError
from rfp.tools import document_tool, ranking_tool, validation_tool
from rfp.tools.document_tool import DocumentError
from rfp.tools.ranking_tool import SupplierInput

MAX_LLM_ATTEMPTS = 2       # first call, then exactly one repair retry

FORMULAS = {
    "weighted_points": "score / max_score x weight",
    "absolute_score": "sum of weighted points across all active criteria (0-100)",
    "benchmark": "highest validated score for that criterion across this run",
    "gap": "score - benchmark (0 for the criterion leader, otherwise negative)",
    "relative_performance_pct": "score / benchmark x 100 (0 for everyone if benchmark is 0)",
    "ppi": "sum(relative % x weight) / sum(weight)",
    "tie_breaks": "1. higher PPI (4dp)  2. earlier submission date  "
                  "3. higher experience rating  4. supplier name A-Z",
}


class RunState(TypedDict, total=False):
    rfp_run_id: str
    created_at: str
    criteria: list
    suppliers: list[dict]
    index: int
    attempts: int
    current_document: dict | None
    current_text: str
    current_raw: str | None
    needs_retry: bool
    fatal_error: str | None
    ranking: dict
    # accumulating channels -- nodes return only their new items
    trace: Annotated[list[dict], add]
    warnings: Annotated[list[str], add]
    evaluations: Annotated[list[Any], add]
    skipped: Annotated[list[dict], add]
    agent_calls: Annotated[list[dict], add]


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def new_run_id() -> str:
    return f"RFP-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"


def build_graph(
    agent: EvaluationAgent,
    *,
    db_path: str | None = None,
    on_step: Callable[[dict], None] | None = None,
):
    """Compile the StateGraph. ``on_step`` receives each trace entry live."""

    def step(label: str, detail: str, status: str = "ok", **extra) -> dict:
        entry = {"step": label, "detail": detail, "status": status,
                 "at": _now(), **extra}
        if on_step:
            on_step(entry)
        return entry

    # -- nodes -------------------------------------------------------------
    def load_criteria(state: RunState) -> dict:
        criteria = db.load_criteria(db_path, active_only=True)
        try:
            db.validate_weights(criteria)
        except db.WeightError as exc:
            return {
                "fatal_error": str(exc),
                "trace": [step("load_criteria", str(exc), "error")],
            }

        db.create_run(
            state["rfp_run_id"], state["created_at"],
            llm_provider=agent.provider, llm_model=agent.model,
            supplier_count=len(state["suppliers"]),
            criteria_snapshot=[c.to_dict() for c in criteria],
            path=db_path,
        )
        return {
            "criteria": criteria,
            "trace": [step(
                "load_criteria",
                f"Loaded {len(criteria)} active criteria from SQLite "
                f"(weights total {db.active_weight_total(criteria):g}%).",
                criteria=[c.name for c in criteria],
            )],
        }

    def extract_document(state: RunState) -> dict:
        supplier = state["suppliers"][state["index"]]
        name = supplier["supplier_name"]
        try:
            extracted = document_tool.extract_document(
                supplier["source"], source_name=supplier.get("source_name")
            )
        except DocumentError as exc:
            return {
                "current_document": None,
                "current_text": "",
                "skipped": [{"supplier_name": name, "reason": exc.message,
                             "code": exc.code}],
                "warnings": [f"{name}: skipped -- {exc.message}"],
                "trace": [step("extract_document",
                               f"{name}: {exc.message}", "error", supplier=name)],
            }
        return {
            "current_document": extracted.to_dict(),
            "current_text": extracted.text,
            "attempts": 0,
            "current_raw": None,
            "warnings": [f"{name}: {w}" for w in extracted.warnings],
            "trace": [step(
                "extract_document",
                f"{name}: extracted {extracted.char_count:,} characters from "
                f"{extracted.page_count} pages via {extracted.extractor}.",
                "warn" if extracted.warnings else "ok", supplier=name,
            )],
        }

    def evaluate_supplier(state: RunState) -> dict:
        supplier = state["suppliers"][state["index"]]
        name = supplier["supplier_name"]
        attempt = state.get("attempts", 0) + 1
        is_first_supplier = state["index"] == 0

        try:
            call: AgentCall = agent.evaluate(
                name, state["current_text"], state["criteria"],
                attempt=attempt,
                previous_response=state.get("current_raw"),
                apply_fault=is_first_supplier,
            )
        except EvaluationError as exc:
            return {
                "fatal_error": f"{name}: {exc}",
                "trace": [step("evaluate_supplier", f"{name}: {exc}", "error",
                               supplier=name)],
            }

        note = f"{name}: model replied with {len(call.raw):,} characters"
        note += f" (attempt {attempt} of {MAX_LLM_ATTEMPTS})" if attempt > 1 else ""
        if call.faulted:
            note += f" [fault injection active: {agent.fault}]"

        return {
            "current_raw": call.raw,
            "attempts": attempt,
            "agent_calls": [{
                "supplier_name": name, "attempt": attempt,
                "provider": call.provider, "model": call.model,
                "faulted": call.faulted, "prompt_chars": call.prompt_chars,
                "raw": call.raw,
            }],
            "trace": [step("evaluate_supplier", note,
                           "warn" if call.faulted else "ok", supplier=name)],
        }

    def validate_output(state: RunState) -> dict:
        supplier = state["suppliers"][state["index"]]
        name = supplier["supplier_name"]
        evaluation = validation_tool.validate_raw_response(
            state.get("current_raw") or "", state["criteria"],
            supplier_name=name, document_text=state.get("current_text", ""),
        )

        can_retry = evaluation.parse_failed and state.get("attempts", 0) < MAX_LLM_ATTEMPTS
        if can_retry:
            return {
                "needs_retry": True,
                "trace": [step("validate_output",
                               f"{name}: response was not valid JSON; sending one "
                               "repair retry.", "warn", supplier=name)],
            }

        status = "ok"
        if evaluation.parse_failed:
            status = "error"
            detail = (f"{name}: still unparseable after the retry; all criteria "
                      "defaulted to 0 and the supplier stays on the leaderboard.")
        elif evaluation.warnings:
            status = "warn"
            detail = (f"{name}: validated with {len(evaluation.warnings)} "
                      f"correction(s) applied.")
        else:
            detail = f"{name}: validated cleanly, no corrections needed."

        return {
            "needs_retry": False,
            "evaluations": [SupplierInput(
                supplier_name=name,
                submission_date=supplier.get("submission_date"),
                experience_rating=supplier.get("experience_rating"),
                evaluation=evaluation,
                document_info=state.get("current_document") or {},
            )],
            "warnings": [f"{name}: {w}" for w in evaluation.warnings],
            "trace": [step("validate_output", detail, status, supplier=name)],
        }

    def next_supplier(state: RunState) -> dict:
        return {"index": state["index"] + 1, "attempts": 0,
                "current_raw": None, "needs_retry": False}

    def score_benchmark_rank(state: RunState) -> dict:
        evaluations = state.get("evaluations", [])
        ranking = ranking_tool.rank_suppliers(evaluations, state["criteria"])
        leader = ranking["suppliers"][0]["supplier_name"] if ranking["suppliers"] else "none"
        return {
            "ranking": ranking,
            "warnings": list(ranking["warnings"]),
            "trace": [step(
                "score_benchmark_rank",
                f"Computed weighted scores, peer benchmarks, PPI and ranks for "
                f"{len(evaluations)} supplier(s) in Python. Leader: {leader}.",
            )],
        }

    def persist_results(state: RunState) -> dict:
        result = _assemble_result(state, agent)
        db.persist_run(result, db_path)
        return {"trace": [step(
            "persist_results",
            f"Stored run {result['rfp_run_id']} and "
            f"{len(result['suppliers'])} supplier row(s) in SQLite "
            "in a single transaction.",
        )]}

    # -- routers -----------------------------------------------------------
    def after_load(state: RunState) -> str:
        if state.get("fatal_error"):
            return "abort"
        return "rank" if not state["suppliers"] else "extract"

    def after_extract(state: RunState) -> str:
        return "evaluate" if state.get("current_document") else "next"

    def after_evaluate(state: RunState) -> str:
        return "abort" if state.get("fatal_error") else "validate"

    def after_validate(state: RunState) -> str:
        return "retry" if state.get("needs_retry") else "next"

    def after_next(state: RunState) -> str:
        return "extract" if state["index"] < len(state["suppliers"]) else "rank"

    # -- wiring ------------------------------------------------------------
    graph = StateGraph(RunState)
    graph.add_node("load_criteria", load_criteria)
    graph.add_node("extract_document", extract_document)
    graph.add_node("evaluate_supplier", evaluate_supplier)
    graph.add_node("validate_output", validate_output)
    graph.add_node("next_supplier", next_supplier)
    graph.add_node("score_benchmark_rank", score_benchmark_rank)
    graph.add_node("persist_results", persist_results)

    graph.add_edge(START, "load_criteria")
    graph.add_conditional_edges("load_criteria", after_load, {
        "extract": "extract_document",
        "rank": "score_benchmark_rank",
        "abort": END,
    })
    graph.add_conditional_edges("extract_document", after_extract, {
        "evaluate": "evaluate_supplier",
        "next": "next_supplier",
    })
    graph.add_conditional_edges("evaluate_supplier", after_evaluate, {
        "validate": "validate_output",
        "abort": END,
    })
    graph.add_conditional_edges("validate_output", after_validate, {
        "retry": "evaluate_supplier",
        "next": "next_supplier",
    })
    graph.add_conditional_edges("next_supplier", after_next, {
        "extract": "extract_document",
        "rank": "score_benchmark_rank",
    })
    graph.add_edge("score_benchmark_rank", "persist_results")
    graph.add_edge("persist_results", END)
    return graph.compile()


def _assemble_result(state: RunState, agent: EvaluationAgent) -> dict[str, Any]:
    ranking = state.get("ranking") or {"suppliers": [], "benchmarks": {}, "tie_breaks": []}
    criteria = state.get("criteria", [])
    return {
        "rfp_run_id": state["rfp_run_id"],
        "created_at": state["created_at"],
        "completed_at": _now(),
        "status": "FAILED" if state.get("fatal_error") else "COMPLETED",
        "llm_provider": agent.provider,
        "llm_model": agent.model,
        "llm_base_url": agent.base_url,
        "fault_mode": agent.fault,
        "criteria": [c.to_dict() for c in criteria],
        "suppliers": ranking["suppliers"],
        "benchmarks": ranking["benchmarks"],
        "tie_breaks": ranking["tie_breaks"],
        "skipped": state.get("skipped", []),
        "warnings": state.get("warnings", []),
        "agent_trace": state.get("trace", []),
        "raw_llm_outputs": state.get("agent_calls", []),
        "formulas": FORMULAS,
        "error": state.get("fatal_error"),
    }


def run_evaluation(
    suppliers: Sequence[dict],
    *,
    provider: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    fault: str | None = None,
    db_path: str | None = None,
    on_step: Callable[[dict], None] | None = None,
) -> dict[str, Any]:
    """Run one full evaluation and return the complete result document.

    Each supplier dict needs: supplier_name, submission_date,
    experience_rating, source (path or bytes) and optionally source_name.
    """
    agent = EvaluationAgent(provider=provider, model=model, base_url=base_url,
                            api_key=api_key, fault=fault)
    app = build_graph(agent, db_path=db_path, on_step=on_step)

    run_id, created_at = new_run_id(), _now()
    initial: RunState = {
        "rfp_run_id": run_id, "created_at": created_at,
        "suppliers": list(suppliers), "index": 0, "attempts": 0,
        "criteria": [], "trace": [], "warnings": [], "evaluations": [],
        "skipped": [], "agent_calls": [], "current_raw": None,
        "needs_retry": False, "fatal_error": None,
    }

    try:
        final = app.invoke(
            initial, config={"recursion_limit": config.GRAPH_RECURSION_LIMIT}
        )
    except Exception as exc:  # noqa: BLE001 - surfaced to the UI, never swallowed
        db.mark_run_status(run_id, "FAILED", completed_at=_now(),
                           warnings=[str(exc)], path=db_path)
        raise

    result = _assemble_result(final, agent)
    if result["status"] == "FAILED":
        db.mark_run_status(run_id, "FAILED", completed_at=result["completed_at"],
                           warnings=result["warnings"] + [result["error"] or ""],
                           path=db_path)
    return result
