#!/usr/bin/env python3
"""Record the demo video by driving the app in a real browser.

    python scripts/record_demo.py --url https://<your-app>.streamlit.app

Produces docs/demo/rfp_demo.webm covering the seven beats the brief asks for:
criteria, a successful run, leaderboard, scorecard evidence, run details and
JSON export, the fault-injection validation case, and an unreadable upload.

Pauses are deliberately generous so the finished video is readable at normal
speed and can be narrated over.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from playwright.sync_api import sync_playwright  # noqa: E402

from _browser import app_frame, creep, open_tab, set_fault_mode, settle  # noqa: E402
from rfp import config  # noqa: E402

OUT_DIR = config.PROJECT_ROOT / "docs" / "demo"
SAMPLES = config.SAMPLE_PDF_DIR
RUN_TIMEOUT_MS = 300_000
WIDTH, HEIGHT = 1600, 1000


def beat(label: str) -> None:
    print(f"  > {label}", flush=True)


def run_evaluation(page, frame) -> None:
    frame.get_by_role("button", name="Evaluate suppliers").click()
    frame.get_by_text("completed", exact=False).first.wait_for(timeout=RUN_TIMEOUT_MS)
    settle(page, 4)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:8511")
    parser.add_argument("--skip-fault", action="store_true",
                        help="skip beat 6 to save API quota")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": WIDTH, "height": HEIGHT},
            record_video_dir=str(OUT_DIR),
            record_video_size={"width": WIDTH, "height": HEIGHT},
        )
        page = context.new_page()
        page.set_default_timeout(120_000)

        print(f"recording {args.url}")
        page.goto(args.url, wait_until="domcontentloaded")
        frame = app_frame(page)
        print(f"  app frame: {frame.url}")
        settle(page, 5)                       # hold on the title and sidebar

        beat("1/7 criteria")
        open_tab(page, frame, "Criteria", 4)
        creep(page, steps=2)
        settle(page, 3)

        beat("2/7 evaluate (successful run)")
        open_tab(page, frame, "Suppliers & Evaluate", 3)
        creep(page, steps=2, dy=200)
        settle(page, 2)
        run_evaluation(page, frame)

        beat("3/7 leaderboard")
        open_tab(page, frame, "Leaderboard", 5)
        creep(page, steps=4)
        settle(page, 3)

        beat("4/7 scorecard + evidence")
        open_tab(page, frame, "Scorecards", 4)
        creep(page, steps=2)
        settle(page, 2)
        expanders = frame.locator('[data-testid="stExpander"] summary:visible')
        if expanders.count():
            expanders.first.click()
            settle(page, 6)
        creep(page, steps=2)
        settle(page, 2)

        beat("5/7 run details, tie-breaks, JSON export")
        open_tab(page, frame, "Run details", 4)
        creep(page, steps=3)
        settle(page, 3)
        try:
            with page.expect_download(timeout=45_000) as info:
                frame.get_by_role("button", name="Download run JSON").click()
            info.value.save_as(str(OUT_DIR / "downloaded_run.json"))
            settle(page, 4)
        except Exception as exc:  # noqa: BLE001
            print(f"    (download step skipped: {type(exc).__name__})")
        creep(page, steps=2)
        settle(page, 2)

        if not args.skip_fault:
            beat("6/7 fault injection -> validation warnings")
            set_fault_mode(page, frame, "malformed_values")
            open_tab(page, frame, "Suppliers & Evaluate", 3)
            run_evaluation(page, frame)
            open_tab(page, frame, "Run details", 4)
            creep(page, steps=3)
            settle(page, 7)                   # hold on the warnings list
            set_fault_mode(page, frame, "(off)")

        beat("7/7 error case: scanned PDF rejected")
        open_tab(page, frame, "Suppliers & Evaluate", 3)
        frame.get_by_text("Upload supplier PDFs", exact=False).first.click()
        settle(page, 3)
        frame.locator('input[type="file"]').last.set_input_files([
            str(SAMPLES / "nexaworks_proposal.pdf"),
            str(SAMPLES / "error_cases" / "scanned_no_text.pdf"),
        ])
        frame.get_by_text("Cannot run yet", exact=False).first.wait_for(timeout=120_000)
        settle(page, 9)                       # hold on the red error + dead button

        # The video path must be read before Playwright stops: the file is
        # only finalised on context.close(), and the handle dies with the
        # event loop.
        video = page.video
        context.close()
        raw = Path(video.path()) if video else None
        browser.close()

    final = OUT_DIR / "rfp_demo.webm"
    if raw and raw.exists():
        raw.replace(final)
        print(f"\nsaved {final}  ({final.stat().st_size / 1_048_576:.1f} MB)")
        print("convert for submission with:")
        print(f"  ffmpeg -i {final} -c:v libx264 -crf 26 -pix_fmt yuv420p "
              f"{OUT_DIR / 'rfp_demo.mp4'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
