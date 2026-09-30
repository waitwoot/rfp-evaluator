"""Agentic RFP Evaluation -- Streamlit front end.

Run with:  streamlit run app.py
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="Agentic RFP Evaluation",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --------------------------------------------------------------------------
# SECRETS -- must happen before anything reads configuration.
#
# Streamlit Community Cloud exposes deployment secrets through st.secrets, not
# through the process environment. Copying them into os.environ here means the
# rest of the codebase only ever needs to know about environment variables,
# and works identically on a laptop and on the cloud.
# --------------------------------------------------------------------------
SECRET_KEYS = (
    "LLM_PROVIDER", "LLM_MODEL", "LLM_BASE_URL", "LLM_API_KEY",
    "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
)


def hydrate_secrets_into_environment() -> list[str]:
    """Copy recognised secrets into os.environ. Returns the names found.

    Accepts both top-level keys and keys nested inside a [section], because
    both forms are common in Streamlit's secrets editor. Values already
    present in the environment win, so a local `export` still overrides.
    """
    found: list[str] = []

    def take(key: str, value: object) -> None:
        if key in SECRET_KEYS and isinstance(value, str) and value.strip():
            os.environ.setdefault(key, value.strip())
            found.append(key)

    try:
        secrets = st.secrets
    except Exception:            # no secrets.toml locally -- perfectly normal
        return found

    try:
        for key, value in secrets.items():
            if isinstance(value, str):
                take(key, value)
            elif hasattr(value, "items"):          # a [section] block
                for nested_key, nested_value in value.items():
                    take(nested_key, nested_value)
    except Exception:
        pass
    return sorted(set(found))


DETECTED_SECRETS = hydrate_secrets_into_environment()

from rfp import config, db, orchestrator, samples  # noqa: E402
from rfp.agents.evaluation_agent import FAULT_MODES  # noqa: E402
from rfp.db import Criterion, WeightError  # noqa: E402
from rfp.tools.document_tool import (  # noqa: E402
    DocumentError,
    bundled_sample_pdfs,
    extract_document,
)

STATUS_HELP = {
    "OK": "Scored normally.",
    "CLIPPED": "Model returned a score outside the allowed range; clamped.",
    "DEFAULTED_INVALID": "Model returned a non-numeric score; defaulted to 0.",
    "DEFAULTED_MISSING": "Model omitted this criterion; defaulted to 0.",
    "DEFAULTED_PARSE_FAILURE": "Model output was unusable even after a retry.",
}


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
@st.cache_resource
def ensure_database() -> str:
    path = str(config.db_path())
    db.init_db(path)
    return path


DB_PATH = ensure_database()


def current_result() -> dict | None:
    return st.session_state.get("result")


def parse_iso(value) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


# --------------------------------------------------------------------------
# sidebar
# --------------------------------------------------------------------------
def render_sidebar() -> str | None:
    st.sidebar.header("Configuration")

    # Read on every rerun, never cached at import: a secret saved on Streamlit
    # Cloud must take effect on the next interaction, not the next deploy.
    provider = config.get_provider()
    model = config.get_model(provider)
    base_url = config.get_base_url()
    has_key = bool(config.get_api_key(provider))

    st.sidebar.markdown(
        f"**Provider** `{provider}`  \n"
        f"**Model** `{model or '(not set)'}`  \n"
        f"**Base URL** `{base_url or '(provider default)'}`"
    )

    if provider == "mock":
        st.sidebar.info(
            "**Offline mock provider.** Scores come from a deterministic "
            "keyword scorer, not a language model. Set `LLM_PROVIDER`, "
            "`LLM_MODEL` and `LLM_API_KEY` for a real evaluation.",
            icon="🧪",
        )
    elif has_key:
        st.sidebar.success(f"API key loaded for `{provider}`.", icon="🔑")
    else:
        st.sidebar.error(
            f"No API key found for `{provider}`. Add `LLM_API_KEY` to the app "
            "secrets, then reboot the app.",
            icon="🚫",
        )

    # Names only -- never values. This single caption makes a broken
    # deployment diagnosable without any guesswork.
    st.sidebar.caption(
        "secrets detected: " + (", ".join(DETECTED_SECRETS) if DETECTED_SECRETS
                                else "none (using environment variables)")
    )

    st.sidebar.divider()
    st.sidebar.subheader("Validation demo")
    fault = st.sidebar.selectbox(
        "Fault injection",
        options=["(off)", *FAULT_MODES],
        help="Deliberately corrupts the FIRST supplier's model output so the "
             "validation layer can be demonstrated on demand.",
    )
    fault_mode = None if fault == "(off)" else fault
    if fault_mode:
        st.sidebar.warning(f"Fault injection active: `{fault_mode}`", icon="⚠️")

    st.sidebar.divider()
    st.sidebar.caption(f"SQLite: `{DB_PATH}`")
    return fault_mode


# --------------------------------------------------------------------------
# tab 1 -- criteria
# --------------------------------------------------------------------------
def tab_criteria() -> None:
    st.subheader("Evaluation criteria")
    st.caption(
        "Loaded from SQLite and re-read at the start of every run. Active "
        "weights must total 100%. Weights are never sent to the model -- they "
        "are applied in Python when the scores come back."
    )

    criteria = db.load_criteria(DB_PATH, active_only=False)
    frame = pd.DataFrame([c.to_dict() for c in criteria])
    frame = frame.rename(columns={
        "criterion_id": "ID", "name": "Criterion", "description": "What to inspect",
        "weight": "Weight %", "max_score": "Max score", "is_active": "Active",
    })

    edited = st.data_editor(
        frame,
        width="stretch",
        hide_index=True,
        num_rows="dynamic",
        key="criteria_editor",
        column_config={
            "ID": st.column_config.NumberColumn(width="small", step=1),
            "Criterion": st.column_config.TextColumn(width="medium", required=True),
            "What to inspect": st.column_config.TextColumn(
                width="large",
                help="Injected into the prompt so the model knows what to look for.",
            ),
            "Weight %": st.column_config.NumberColumn(
                width="small", min_value=0.0, max_value=100.0, step=1.0, format="%.1f"),
            "Max score": st.column_config.NumberColumn(
                width="small", min_value=0.5, max_value=100.0, step=1.0, format="%.1f"),
            "Active": st.column_config.CheckboxColumn(width="small"),
        },
    )

    active_total = float(edited.loc[edited["Active"] == True, "Weight %"].sum())  # noqa: E712
    left, right = st.columns([3, 1])
    with left:
        if abs(active_total - 100.0) <= config.WEIGHT_TOLERANCE:
            st.success(f"Active weights total {active_total:g}%.", icon="✅")
        else:
            st.error(
                f"Active weights total {active_total:g}% — they must total 100% "
                "before changes can be saved.", icon="🚫")
    with right:
        st.metric("Active criteria", int((edited["Active"] == True).sum()))  # noqa: E712

    save_col, reset_col = st.columns(2)
    with save_col:
        if st.button("Save criteria", type="primary", width="stretch"):
            try:
                updated = [
                    Criterion(
                        criterion_id=int(row["ID"]),
                        name=str(row["Criterion"]).strip(),
                        description=str(row["What to inspect"] or "").strip(),
                        weight=float(row["Weight %"]),
                        max_score=float(row["Max score"]),
                        is_active=bool(row["Active"]),
                    )
                    for _, row in edited.iterrows()
                    if str(row.get("Criterion") or "").strip()
                ]
                db.save_criteria(updated, DB_PATH)
            except WeightError as exc:
                st.error(str(exc), icon="🚫")
            except (TypeError, ValueError) as exc:
                st.error(f"Could not read the edited table: {exc}", icon="🚫")
            else:
                st.success("Criteria saved. The next run will use them.", icon="✅")
                st.rerun()
    with reset_col:
        if st.button("Reset to defaults", width="stretch"):
            db.reset_criteria(DB_PATH)
            st.success("Restored the five default criteria.", icon="↩️")
            st.rerun()


# --------------------------------------------------------------------------
# tab 2 -- suppliers and evaluate
# --------------------------------------------------------------------------
def collect_documents() -> list[dict]:
    """Return [{name, size, source, source_name}] from the chosen input mode."""
    mode = st.radio(
        "Document source",
        ["Use the bundled sample proposals", "Upload supplier PDFs"],
        horizontal=True,
        key="source_mode",
    )

    entries: list[dict] = []
    if mode.startswith("Use the bundled"):
        paths = bundled_sample_pdfs()
        if not paths:
            st.warning(
                "No bundled proposals found. Run "
                "`python scripts/generate_sample_pdfs.py` first.", icon="📄")
        for path in paths:
            entries.append({"name": path.name, "size": path.stat().st_size,
                            "source": path, "source_name": path.name})
        if paths:
            st.caption(f"{len(paths)} bundled proposals from `sample_pdfs/`.")
    else:
        uploads = st.file_uploader(
            "Supplier RFP responses (PDF)", type=["pdf"],
            accept_multiple_files=True, key="uploads",
            help="Upload at least two readable PDFs.",
        )
        for upload in uploads or []:
            entries.append({"name": upload.name, "size": upload.size,
                            "source": upload.getvalue(), "source_name": upload.name})
    return entries


def metadata_editor(entries: list[dict]) -> pd.DataFrame:
    rows = []
    for entry in entries:
        name, submitted, rating = samples.metadata_for(entry["name"])
        rows.append({
            "File": entry["name"],
            "Supplier name": name,
            "Submission date": parse_iso(submitted),
            "Experience rating": rating,
            "Size (KB)": round(entry["size"] / 1024, 1),
        })
    frame = pd.DataFrame(rows)

    return st.data_editor(
        frame,
        width="stretch",
        hide_index=True,
        key="supplier_meta",
        disabled=["File", "Size (KB)"],
        column_config={
            "File": st.column_config.TextColumn(width="medium"),
            "Supplier name": st.column_config.TextColumn(width="medium", required=True),
            "Submission date": st.column_config.DateColumn(
                width="small", format="YYYY-MM-DD",
                max_value=date.today(), help="Cannot be in the future."),
            "Experience rating": st.column_config.NumberColumn(
                width="small", min_value=0.0, max_value=5.0, step=0.1, format="%.1f",
                help="Historical experience with this supplier, 0 to 5."),
            "Size (KB)": st.column_config.NumberColumn(width="small", format="%.1f"),
        },
    )


def validate_inputs(entries: list[dict], meta: pd.DataFrame) -> list[str]:
    """Everything that must be true before a single token is sent to the model."""
    errors: list[str] = []

    if len(entries) < config.MIN_SUPPLIERS:
        errors.append(
            f"At least {config.MIN_SUPPLIERS} suppliers are required to compute "
            f"peer benchmarks — {len(entries)} provided.")

    criteria = db.load_criteria(DB_PATH, active_only=True)
    try:
        db.validate_weights(criteria)
    except WeightError as exc:
        errors.append(f"Criteria: {exc}")

    provider = config.get_provider()
    if provider != "mock" and not config.get_api_key(provider):
        errors.append(
            f"No API key is configured for provider '{provider}'. Add "
            "`LLM_API_KEY` to the app secrets, or set `LLM_PROVIDER = \"mock\"` "
            "to run offline.")

    if meta.empty:
        return errors

    seen: set[str] = set()
    for _, row in meta.iterrows():
        label = row["File"]
        name = str(row["Supplier name"] or "").strip()
        if not name:
            errors.append(f"{label}: a supplier name is required.")
        elif name.lower() in seen:
            errors.append(f"{label}: duplicate supplier name '{name}'.")
        else:
            seen.add(name.lower())

        submitted = parse_iso(row["Submission date"])
        if submitted is None:
            errors.append(f"{label}: a valid submission date is required.")
        elif submitted > date.today():
            errors.append(
                f"{label}: submission date {submitted.isoformat()} is in the future.")

        try:
            rating = float(row["Experience rating"])
        except (TypeError, ValueError):
            errors.append(f"{label}: experience rating must be a number between 0 and 5.")
        else:
            if not 0.0 <= rating <= 5.0:
                errors.append(
                    f"{label}: experience rating {rating:g} is outside the range 0-5.")

    for entry in entries:
        if entry["size"] > config.MAX_UPLOAD_BYTES:
            errors.append(
                f"{entry['name']}: {entry['size'] / 1_048_576:.1f} MB exceeds the "
                f"{config.MAX_UPLOAD_BYTES / 1_048_576:.0f} MB limit.")
            continue
        try:
            extract_document(entry["source"], source_name=entry["name"])
        except DocumentError as exc:
            errors.append(f"{entry['name']}: {exc.message}")

    return errors


def tab_evaluate(fault_mode: str | None) -> None:
    st.subheader("Suppliers and evaluation")

    entries = collect_documents()
    if not entries:
        st.info("Choose the bundled proposals or upload at least two PDFs.", icon="📄")
        return

    st.markdown("**Supplier metadata** — edit names, dates and ratings before running.")
    meta = metadata_editor(entries)

    errors = validate_inputs(entries, meta)
    if errors:
        st.error("**Cannot run yet:**\n\n" + "\n".join(f"- {e}" for e in errors),
                 icon="🚫")
    else:
        st.success(
            f"{len(entries)} readable documents, metadata valid, criteria total 100%.",
            icon="✅")

    run_clicked = st.button(
        "Evaluate suppliers", type="primary", disabled=bool(errors), width="stretch",
    )
    if not run_clicked:
        return

    by_file = {e["name"]: e for e in entries}
    suppliers = []
    for _, row in meta.iterrows():
        entry = by_file[row["File"]]
        submitted = parse_iso(row["Submission date"])
        suppliers.append({
            "supplier_name": str(row["Supplier name"]).strip(),
            "submission_date": submitted.isoformat() if submitted else None,
            "experience_rating": float(row["Experience rating"]),
            "source": entry["source"],
            "source_name": entry["source_name"],
        })

    failure: str | None = None
    with st.status("Running the agent graph…", expanded=True) as status:
        def on_step(entry: dict) -> None:
            icon = {"ok": "✅", "warn": "⚠️", "error": "❌"}.get(entry["status"], "•")
            st.write(f"{icon} **{entry['step']}** — {entry['detail']}")

        try:
            result = orchestrator.run_evaluation(
                suppliers,
                fault=fault_mode,
                db_path=DB_PATH,
                on_step=on_step,
            )
        except Exception as exc:              # noqa: BLE001
            failure = str(exc)
            status.update(label="Run failed", state="error")
        else:
            st.session_state["result"] = result
            if result["status"] == "FAILED":
                failure = result.get("error") or "The run failed."
                status.update(label="Run failed", state="error")
            else:
                status.update(
                    label=f"Completed — {result['rfp_run_id']}", state="complete",
                    expanded=False)

    # Rendered OUTSIDE the status block: st.status collapses on completion and
    # would hide the only explanation of what went wrong.
    if failure:
        st.error(f"**Run failed.** {failure}", icon="❌")
        return

    result = current_result()
    if result:
        st.success(
            f"Run `{result['rfp_run_id']}` completed — "
            f"{len(result['suppliers'])} suppliers ranked, "
            f"{len(result['warnings'])} warning(s). See the Leaderboard tab.",
            icon="🏁")


# --------------------------------------------------------------------------
# tab 3 -- leaderboard
# --------------------------------------------------------------------------
def tab_leaderboard() -> None:
    result = current_result()
    if not result:
        st.info("Run an evaluation first, or load one from History.", icon="📊")
        return

    st.subheader(f"Leaderboard — {result['rfp_run_id']}")
    rows = result["suppliers"]
    if not rows:
        st.warning("This run produced no ranked suppliers.", icon="⚠️")
        return

    frame = pd.DataFrame([{
        "Rank": r["final_rank"],
        "Supplier": r["supplier_name"],
        "Absolute score": r["absolute_score"],
        "PPI": r["ppi"],
        "Submitted": r["submission_date"],
        "Experience": r["experience_rating"],
        "Ranked above the next supplier because": r["tie_break_reason"],
    } for r in rows])

    st.dataframe(
        frame, width="stretch", hide_index=True,
        column_config={
            "Absolute score": st.column_config.ProgressColumn(
                format="%.2f", min_value=0, max_value=100, width="medium"),
            "PPI": st.column_config.NumberColumn(format="%.4f", width="small"),
            "Experience": st.column_config.NumberColumn(format="%.1f", width="small"),
            "Ranked above the next supplier because": st.column_config.TextColumn(
                width="large"),
        },
    )

    st.caption(
        "**Absolute score** measures a supplier against the maximum possible. "
        "**PPI** measures it against the best performer on each criterion in "
        "this run, so it changes if the peer group changes. Ranking uses PPI."
    )

    winner = rows[0]
    columns = st.columns(min(len(rows), 4))
    for column, row in zip(columns, rows):
        with column:
            st.metric(
                f"#{row['final_rank']} {row['supplier_name']}",
                f"PPI {row['ppi']:.2f}",
                delta=(None if row is winner
                       else f"{row['ppi'] - winner['ppi']:.2f} vs leader"),
                delta_color="inverse",
            )

    st.divider()
    st.markdown("**Per-criterion comparison** (scores side by side)")
    # Rendered with ProgressColumn rather than a pandas background gradient:
    # Styler.background_gradient silently requires matplotlib, which would add
    # a heavy dependency and crash this tab wherever it is not installed.
    matrix = pd.DataFrame(
        [{"Supplier": r["supplier_name"],
          **{c["criterion_name"]: c["score"] for c in r["criteria"]}}
         for r in rows]
    )
    max_score = max((c["max_score"] for c in rows[0]["criteria"]), default=10)
    st.dataframe(
        matrix, width="stretch", hide_index=True,
        column_config={
            c["criterion_name"]: st.column_config.ProgressColumn(
                format="%.1f", min_value=0, max_value=max_score, width="small")
            for c in rows[0]["criteria"]
        },
    )

    if result.get("skipped"):
        st.warning(
            "**Skipped documents:**\n\n" + "\n".join(
                f"- **{s['supplier_name']}** [{s['code']}] {s['reason']}"
                for s in result["skipped"]), icon="⏭️")


# --------------------------------------------------------------------------
# tab 4 -- scorecards
# --------------------------------------------------------------------------
def tab_scorecards() -> None:
    result = current_result()
    if not result or not result["suppliers"]:
        st.info("Run an evaluation first, or load one from History.", icon="🧾")
        return

    names = [r["supplier_name"] for r in result["suppliers"]]
    chosen = st.selectbox("Supplier", names, key="scorecard_supplier")
    row = next(r for r in result["suppliers"] if r["supplier_name"] == chosen)

    top = st.columns(4)
    top[0].metric("Rank", f"#{row['final_rank']}")
    top[1].metric("Absolute score", f"{row['absolute_score']:.2f}")
    top[2].metric("PPI", f"{row['ppi']:.4f}")
    top[3].metric("Experience", f"{row['experience_rating']:.1f}")

    if row.get("parse_failed"):
        st.error(
            "The model produced no usable output for this supplier even after a "
            "retry. Every criterion defaulted to 0. The supplier is kept on the "
            "leaderboard because removing it would change the peer benchmarks "
            "for everyone else.", icon="❌")

    if row.get("overall_summary"):
        st.markdown(f"> {row['overall_summary']}")

    frame = pd.DataFrame([{
        "Criterion": c["criterion_name"],
        "Score": c["score"],
        "Max": c["max_score"],
        "Benchmark": c["benchmark"],
        "Gap": c["gap"],
        "Relative %": c["relative_pct"],
        "Weight": c["weight"],
        "Weighted pts": c["weighted_points"],
        "Status": c["status"],
        "Evidence ✓": c["evidence_verified"],
    } for c in row["criteria"]])

    st.dataframe(
        frame, width="stretch", hide_index=True,
        column_config={
            "Relative %": st.column_config.NumberColumn(format="%.1f"),
            "Weighted pts": st.column_config.NumberColumn(format="%.2f"),
            "Gap": st.column_config.NumberColumn(
                format="%.2f", help="score − benchmark; 0 means this supplier leads."),
            "Evidence ✓": st.column_config.CheckboxColumn(
                help="Was the quoted evidence found verbatim in the document?"),
        },
    )

    st.markdown("**Evidence and reasoning**")
    for criterion in row["criteria"]:
        verified = "✅ verified" if criterion["evidence_verified"] else "⚠️ unverified"
        with st.expander(
            f"{criterion['criterion_name']} — {criterion['score']:g}/"
            f"{criterion['max_score']:g}  ({verified})"
        ):
            st.markdown(f"**Justification.** {criterion['justification'] or '—'}")
            st.markdown("**Evidence quoted from the document:**")
            st.info(criterion["evidence"] or "—")
            st.caption(
                f"Status `{criterion['status']}` — "
                f"{STATUS_HELP.get(criterion['status'], '')}  \n"
                f"Benchmark {criterion['benchmark']:g} · gap {criterion['gap']:g} · "
                f"relative {criterion['relative_pct']:.1f}% · "
                f"weighted {criterion['weighted_points']:.2f} pts")

    if row.get("risks"):
        st.markdown("**Risks identified**")
        for risk in row["risks"]:
            st.markdown(f"- {risk}")

    if row.get("warnings"):
        st.warning("**Validation corrections applied to this supplier:**\n\n"
                   + "\n".join(f"- {w}" for w in row["warnings"]), icon="🛠️")


# --------------------------------------------------------------------------
# tab 5 -- run details
# --------------------------------------------------------------------------
def tab_run_details() -> None:
    result = current_result()
    if not result:
        st.info("Run an evaluation first, or load one from History.", icon="🔍")
        return

    st.subheader("Run details")
    left, right = st.columns([2, 1])
    with left:
        st.markdown(
            f"**RFP_RUN_ID** `{result['rfp_run_id']}`  \n"
            f"**Status** `{result['status']}`  \n"
            f"**Provider / model** `{result['llm_provider']}` / "
            f"`{result['llm_model']}`  \n"
            f"**Base URL** `{result.get('llm_base_url') or '(provider default)'}`  \n"
            f"**Created** {result['created_at']}  \n"
            f"**Completed** {result.get('completed_at') or '—'}"
        )
        if result.get("fault_mode"):
            st.warning(f"Fault injection was active: `{result['fault_mode']}`",
                       icon="⚠️")
    with right:
        st.download_button(
            "⬇️ Download run JSON",
            data=json.dumps(result, ensure_ascii=False, indent=2),
            file_name=f"{result['rfp_run_id']}.json",
            mime="application/json",
            type="primary",
            width="stretch",
        )

    st.divider()
    st.markdown("**Tie-break decisions** — every adjacent pair on the leaderboard")
    if result.get("tie_breaks"):
        st.dataframe(
            pd.DataFrame([{
                "Above": t["above"], "Below": t["below"],
                "Rule": f"{t['rule_level']}. {t['rule']}",
                "Explanation": t["explanation"],
            } for t in result["tie_breaks"]]),
            width="stretch", hide_index=True,
            column_config={"Explanation": st.column_config.TextColumn(width="large")},
        )
    else:
        st.caption("Only one supplier — nothing to compare.")

    with st.expander("Formulas used (all computed in Python, never by the model)"):
        st.dataframe(
            pd.DataFrame(
                [{"Quantity": k, "Definition": v} for k, v in result["formulas"].items()]),
            width="stretch", hide_index=True,
            column_config={"Definition": st.column_config.TextColumn(width="large")},
        )
        st.caption(
            "The model supplies one score per criterion plus quoted evidence. "
            "Everything numeric — weighting, benchmarks, PPI, tie-breaks and "
            "ranks — is arithmetic in ranking_tool.py, so it is reproducible "
            "and auditable."
        )

    warnings = result.get("warnings", [])
    with st.expander(f"Validation warnings ({len(warnings)})",
                     expanded=bool(warnings)):
        if warnings:
            for warning in warnings:
                st.markdown(f"- {warning}")
        else:
            st.caption("No corrections were needed.")

    with st.expander(f"Agent trace ({len(result.get('agent_trace', []))} steps)"):
        st.dataframe(
            pd.DataFrame([{
                "Step": e["step"], "Status": e["status"], "Detail": e["detail"],
                "At": e["at"],
            } for e in result.get("agent_trace", [])]),
            width="stretch", hide_index=True,
            column_config={"Detail": st.column_config.TextColumn(width="large")},
        )

    with st.expander(f"Raw model output ({len(result.get('raw_llm_outputs', []))} calls)"):
        for call in result.get("raw_llm_outputs", []):
            label = f"{call['supplier_name']} — attempt {call['attempt']}"
            if call.get("faulted"):
                label += "  (fault injected)"
            st.markdown(f"**{label}**")
            st.code(call["raw"][:4000], language="json")

    with st.expander("Stored SQLite rows"):
        rows = db.supplier_rows_for_run(result["rfp_run_id"], DB_PATH)
        if rows:
            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
            st.caption(
                "Read straight back from `supplier_results`. The full run "
                "document is also stored in `rfp_runs.run_json`.")
        else:
            st.caption("No rows stored for this run.")


# --------------------------------------------------------------------------
# tab 6 -- history
# --------------------------------------------------------------------------
def tab_history() -> None:
    st.subheader("Previous runs")
    runs = db.list_runs(limit=50, path=DB_PATH)
    if not runs:
        st.info("No runs stored yet.", icon="🕓")
        return

    st.dataframe(
        pd.DataFrame([{
            "RFP_RUN_ID": r["rfp_run_id"], "Created": r["created_at"],
            "Status": r["status"], "Provider": r["llm_provider"],
            "Model": r["llm_model"], "Suppliers": r["supplier_count"],
        } for r in runs]),
        width="stretch", hide_index=True,
    )

    chosen = st.selectbox(
        "Load a run", [r["rfp_run_id"] for r in runs], key="history_choice")
    if st.button("Load this run", type="primary"):
        loaded = db.load_run(chosen, DB_PATH)
        if loaded is None:
            st.error(f"Run `{chosen}` could not be read back.", icon="🚫")
        else:
            st.session_state["result"] = loaded
            st.success(
                f"Loaded `{chosen}`. The Leaderboard, Scorecards and Run details "
                "tabs now show it.", icon="📂")


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def main() -> None:
    st.title("📋 Agentic RFP Evaluation")
    st.caption(
        "An LLM scores each supplier proposal against criteria held in SQLite. "
        "All arithmetic — weighting, peer benchmarks, PPI, tie-breaks and ranks "
        "— is done in Python, never by the model."
    )

    fault_mode = render_sidebar()

    tabs = st.tabs([
        "⚖️ Criteria", "📄 Suppliers & Evaluate", "🏆 Leaderboard",
        "🧾 Scorecards", "🔍 Run details", "🕓 History",
    ])
    with tabs[0]:
        tab_criteria()
    with tabs[1]:
        tab_evaluate(fault_mode)
    with tabs[2]:
        tab_leaderboard()
    with tabs[3]:
        tab_scorecards()
    with tabs[4]:
        tab_run_details()
    with tabs[5]:
        tab_history()


if __name__ == "__main__":
    main()
