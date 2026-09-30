"""Shared browser helpers for the Playwright-driven scripts.

The one non-obvious thing in here: Streamlit Community Cloud serves the app
inside an iframe (`/~/+/`), while a local `streamlit run` does not. Locators
bound to the page therefore find nothing against a deployed URL even though
screenshots look perfectly normal. Everything here resolves the frame that
actually contains the app and works against both.
"""

from __future__ import annotations

import time


def app_frame(page, timeout: float = 180.0):
    """Return the frame containing the app, waiting for it to appear.

    Local Streamlit has no iframe, so this returns the main frame. On
    Streamlit Cloud it returns the inner `/~/+/` frame.
    """
    deadline = time.time() + timeout
    last_error: Exception | None = None
    while time.time() < deadline:
        for frame in page.frames:
            try:
                if frame.get_by_role("tab", name="Criteria").count():
                    return frame
            except Exception as exc:  # frame detached mid-navigation
                last_error = exc
        page.wait_for_timeout(1000)
    raise TimeoutError(
        f"No frame containing the app appeared within {timeout:.0f}s "
        f"(frames: {[f.url for f in page.frames]}; last error: {last_error})"
    )


def settle(page, seconds: float) -> None:
    page.wait_for_timeout(int(seconds * 1000))


def open_tab(page, frame, label: str, pause: float = 2.5) -> None:
    frame.get_by_role("tab", name=label).first.click()
    settle(page, pause)


def creep(page, steps: int = 4, dy: int = 260, pause: float = 1.1) -> None:
    """Scroll in small steps so a viewer can read on the way down.

    The mouse is parked over the middle of the viewport first: wheel events go
    to whatever is under the cursor, and an unpositioned cursor scrolls the
    wrapper page rather than the app inside the iframe.
    """
    box = page.viewport_size or {"width": 1600, "height": 1000}
    page.mouse.move(box["width"] // 2, box["height"] // 2)
    for _ in range(steps):
        page.mouse.wheel(0, dy)
        settle(page, pause)


def scroll_top(page, frame) -> None:
    try:
        frame.evaluate("window.scrollTo(0, 0)")
    except Exception:
        pass
    page.wait_for_timeout(400)


def set_fault_mode(page, frame, label: str) -> None:
    """Choose a value in the sidebar's fault-injection selectbox.

    Scoped to the sidebar by test-id rather than by `data-baseweb`, which is
    an internal attribute this Streamlit build does not emit.
    """
    select = frame.locator('[data-testid="stSidebar"] [data-testid="stSelectbox"]')
    select.first.click()
    settle(page, 1.8)
    frame.get_by_role("option", name=label, exact=True).first.click()
    settle(page, 2.5)
