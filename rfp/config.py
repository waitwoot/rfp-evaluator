"""Runtime configuration for the RFP evaluator.

Design rule: every getter reads ``os.environ`` at CALL time, never at import
time. Streamlit Community Cloud injects ``st.secrets`` into the process only
after the module graph is imported, so module-level constants like
``PROVIDER = os.getenv("LLM_PROVIDER")`` freeze the placeholder value and the
deployed app reports "No API key found" forever. Functions dodge that entirely.
"""

from __future__ import annotations

import os
from pathlib import Path

# --- paths ---------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = PROJECT_ROOT / "sql" / "schema.sql"
SAMPLE_PDF_DIR = PROJECT_ROOT / "sample_pdfs"
SAMPLE_OUTPUT_DIR = PROJECT_ROOT / "sample_output"
DEFAULT_DB_FILENAME = "rfp_eval.db"

# --- secrets we are willing to import from st.secrets into os.environ ----
SECRET_KEYS = (
    "LLM_PROVIDER",
    "LLM_MODEL",
    "LLM_BASE_URL",
    "LLM_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
)

# --- document extraction limits ------------------------------------------
MIN_DOC_CHARS = 200          # below this we treat the PDF as scanned/imageonly
MAX_DOC_CHARS = 40_000       # truncate beyond this, and flag that we did
MAX_UPLOAD_BYTES = 10 * 1024 * 1024

# --- evaluation / ranking invariants -------------------------------------
MIN_SUPPLIERS = 2
WEIGHT_TOTAL = 100.0
WEIGHT_TOLERANCE = 0.01      # float slack when checking "weights sum to 100"
PPI_SORT_DECIMALS = 4        # round PPI before sorting so float noise cannot
                             # flip a deterministic tie-break

# --- LLM client behaviour -------------------------------------------------
LLM_CLIENT_MAX_RETRIES = 6   # Groq free tier throws 429 around the 4th supplier
LLM_TEMPERATURE = 0.0
GRAPH_RECURSION_LIMIT = 500  # LangGraph default of 25 is far too low for
                             # 4 suppliers x (extract, evaluate, validate, retry)

DEFAULT_PROVIDER = "mock"
DEFAULT_MOCK_MODEL = "mock-keyword-scorer"


def db_path() -> Path:
    """SQLite file location. Override with RFP_DB_PATH (tests use a tmp file)."""
    override = os.getenv("RFP_DB_PATH", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return PROJECT_ROOT / DEFAULT_DB_FILENAME


def get_provider() -> str:
    """openai | anthropic | mock."""
    return (os.getenv("LLM_PROVIDER") or DEFAULT_PROVIDER).strip().lower()


def get_model(provider: str | None = None) -> str:
    """Configured model name.

    ``provider`` must be passed when the caller has its own provider: the mock
    model name is only a sensible default for the mock provider, and silently
    handing it to a real endpoint produces a baffling 404.
    """
    model = (os.getenv("LLM_MODEL") or "").strip()
    if model:
        return model
    provider = (provider or get_provider()).lower()
    return DEFAULT_MOCK_MODEL if provider == "mock" else ""


def get_base_url() -> str | None:
    """Set for Groq/OpenRouter, unset for OpenAI proper."""
    base = (os.getenv("LLM_BASE_URL") or "").strip()
    return base or None


def get_api_key(provider: str | None = None) -> str | None:
    """LLM_API_KEY wins; fall back to the provider's conventional variable."""
    provider = (provider or get_provider()).lower()
    generic = (os.getenv("LLM_API_KEY") or "").strip()
    if generic:
        return generic
    specific = "ANTHROPIC_API_KEY" if provider == "anthropic" else "OPENAI_API_KEY"
    return (os.getenv(specific) or "").strip() or None


def detected_secret_names() -> list[str]:
    """Names (never values) of the secrets actually present in the process.

    Rendered in the Streamlit sidebar so a broken deployment can be diagnosed
    without guessing whether the Secrets blob was saved.
    """
    return [k for k in SECRET_KEYS if (os.getenv(k) or "").strip()]


def llm_config() -> dict:
    """Snapshot of the active LLM settings, safe to log or store in the DB."""
    provider = get_provider()
    return {
        "provider": provider,
        "model": get_model(),
        "base_url": get_base_url(),
        "has_api_key": bool(get_api_key(provider)) or provider == "mock",
    }
