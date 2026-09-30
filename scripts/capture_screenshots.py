#!/usr/bin/env python3
"""Capture the six README screenshots from a running app, headlessly.

    streamlit run app.py --server.port 8511 &
    python scripts/capture_screenshots.py --url http://localhost:8511

Playwright is a development tool only. It is deliberately NOT in
requirements.txt: nothing about the deployed app depends on it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.sync_api import sync_playwright  # noqa: E402

from rfp import config  # noqa: E402

OUT_DIR = config.PROJECT_ROOT / "docs" / "screenshots"
SAMPLES = config.SAMPLE_PDF_DIR
RUN_TIMEOUT_MS = 240_000


def open_tab(page, label: str) -> None:
    page.get_by_role("tab", name=label).first.click()
    page.wait_for_timeout(1200)


def shot(page, name: str) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / name
    page.screenshot(path=str(path), full_page=True)
    print(f"  saved {path.name} ({path.stat().st_size / 1024:.0f} KB)")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:8511")
    parser.add_argument("--headed", action="store_true", help="watch it happen")
    args = parser.parse_args()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not args.headed)
        page = browser.new_page(
            viewport={"width": 1600, "height": 1150}, device_scale_factor=2
        )
        page.set_default_timeout(60_000)

        print(f"opening {args.url}")
        page.goto(args.url, wait_until="networkidle")
        page.get_by_role("tab", name="Criteria").first.wait_for(timeout=180_000)
        page.wait_for_timeout(2500)

        # 1 -- criteria
        print("1. criteria tab")
        open_tab(page, "Criteria")
        shot(page, "01_criteria.png")

        # 2 -- run in progress / just completed
        print("2. evaluate (this calls the model; may take a minute)")
        open_tab(page, "Suppliers & Evaluate")
        page.get_by_role("button", name="Evaluate suppliers").click()
        page.wait_for_selector("text=/Run .* completed/", timeout=RUN_TIMEOUT_MS)
        page.wait_for_timeout(1500)
        shot(page, "02_run.png")

        # 3 -- leaderboard
        print("3. leaderboard")
        open_tab(page, "Leaderboard")
        shot(page, "03_leaderboard.png")

        # 4 -- scorecard with one evidence expander open
        print("4. scorecard")
        open_tab(page, "Scorecards")
        # Streamlit keeps every tab panel in the DOM, so an unqualified
        # selector matches expanders on inactive tabs. Restrict to visible.
        expanders = page.locator('[data-testid="stExpander"] summary:visible')
        if expanders.count():
            expanders.first.click()
            page.wait_for_timeout(1200)
        shot(page, "04_scorecard.png")

        # 5 -- run details
        print("5. run details")
        open_tab(page, "Run details")
        shot(page, "05_run_details.png")

        # 6 -- error case: a good PDF plus an unreadable one
        print("6. error case (scanned PDF rejected)")
        open_tab(page, "Suppliers & Evaluate")
        page.locator(':text("Upload supplier PDFs"):visible').first.click()
        page.wait_for_timeout(1500)
        page.locator('input[type="file"]').last.set_input_files([
            str(SAMPLES / "nexaworks_proposal.pdf"),
            str(SAMPLES / "error_cases" / "scanned_no_text.pdf"),
        ])
        page.wait_for_selector("text=/Cannot run yet/", timeout=90_000)
        page.wait_for_timeout(1500)
        shot(page, "06_error_case.png")

        browser.close()

    print(f"\nall screenshots in {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
