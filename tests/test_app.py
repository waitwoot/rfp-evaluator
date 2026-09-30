"""Streamlit UI tests via Streamlit's own app-test harness.

These run the real app.py end to end with no browser. They exist because a
UI fault (a missing optional dependency, a tab that throws on empty state)
is invisible to unit tests and only shows up as a blank screen in front of
whoever is marking the work.
"""

from __future__ import annotations

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from rfp import config

APP = str(config.PROJECT_ROOT / "app.py")

requires_samples = pytest.mark.skipif(
    not (config.SAMPLE_PDF_DIR / "nexaworks_proposal.pdf").exists(),
    reason="run scripts/generate_sample_pdfs.py first",
)


@pytest.fixture
def app(tmp_path, monkeypatch):
    """A fresh app pointed at a throwaway database, on the offline provider."""
    monkeypatch.setenv("RFP_DB_PATH", str(tmp_path / "app.db"))
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    st.cache_resource.clear()
    return AppTest.from_file(APP, default_timeout=120)


def evaluate_button(at: AppTest):
    return next(b for b in at.button if b.label == "Evaluate suppliers")


def test_app_starts_without_error(app):
    at = app.run()
    assert not at.exception
    assert at.title[0].value.endswith("Agentic RFP Evaluation")
    assert len(at.tabs) == 6


def test_sidebar_reports_detected_secrets_by_name_only(app):
    at = app.run()
    captions = " ".join(c.value for c in at.sidebar.caption)
    assert "secrets detected:" in captions
    # The caption must never contain a value, only names.
    assert "gsk_" not in captions and "sk-" not in captions


def test_criteria_tab_shows_the_seeded_criteria(app):
    at = app.run()
    assert any("Active weights total 100%" in s.value for s in at.success)
    assert any(m.label == "Active criteria" and m.value == "5" for m in at.metric)


def test_mock_provider_needs_no_api_key(app):
    at = app.run()
    assert not any("No API key" in e.value for e in at.error)
    assert any("mock provider" in i.value for i in at.info)


@requires_samples
def test_bundled_proposals_pass_validation_and_enable_the_button(app):
    at = app.run()
    assert not at.error
    assert any("readable documents" in s.value for s in at.success)
    assert evaluate_button(at).disabled is False


@requires_samples
def test_full_run_through_the_ui_populates_every_tab(app):
    at = evaluate_button(app.run()).click().run()

    assert not at.exception
    assert any("completed" in s.value for s in at.success)

    # leaderboard
    assert any(m.label.startswith("#1") for m in at.metric)
    # scorecards
    assert any(s.label == "Supplier" for s in at.selectbox)
    assert any(m.label == "PPI" for m in at.metric)
    # run details
    assert [d.label for d in at.download_button]
    # history
    assert any(s.label == "Load a run" for s in at.selectbox)


@requires_samples
def test_run_is_written_to_the_database_and_listed_in_history(app, tmp_path):
    from rfp import db

    at = evaluate_button(app.run()).click().run()
    assert not at.exception

    runs = db.list_runs(path=str(tmp_path / "app.db"))
    assert len(runs) == 1
    assert runs[0]["status"] == "COMPLETED"
    assert runs[0]["supplier_count"] == 4


@requires_samples
def test_fault_injection_surfaces_warnings_in_the_ui(app):
    at = app.run()
    fault = next(s for s in at.sidebar.selectbox if s.label == "Fault injection")
    at = fault.set_value("malformed_values").run()
    at = evaluate_button(at).click().run()

    assert not at.exception
    assert any("warning(s)" in s.value for s in at.success)
    assert any("Fault injection active" in w.value for w in at.sidebar.warning)


def test_tabs_are_safe_before_any_run_has_happened(app):
    """Every tab must render on a cold start with no result in session state."""
    at = app.run()
    assert not at.exception
    info_messages = " ".join(i.value for i in at.info)
    assert "Run an evaluation first" in info_messages
