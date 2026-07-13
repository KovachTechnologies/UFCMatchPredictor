"""Common scraping utilities - Playwright with stealth"""

import time
import random
from typing import Optional
from playwright.sync_api import sync_playwright

# playwright-stealth's API changed in 2.x: the old `stealth_sync(page)` /
# `stealth_async(page)` functions were removed in favour of a `Stealth`
# class that wraps the *playwright instance itself* (not individual pages),
# e.g. `with Stealth().use_sync(sync_playwright()) as p: ...`.
# We detect whichever version is installed and use it accordingly.
_STEALTH_MODE = None
_stealth_sync_legacy = None

try:
    from playwright_stealth import Stealth
    _STEALTH_MODE = "class"
except ImportError:
    try:
        from playwright_stealth import stealth_sync as _stealth_sync_legacy
        _STEALTH_MODE = "legacy"
    except ImportError:
        print("Warning: playwright-stealth not installed. Running without stealth.")


def get_soup(url: str, timeout: int = 90, wait_selector: Optional[str] = None):
    """Fetch page with stealth.

    If `wait_selector` is given, waits (up to `timeout`) for that CSS
    selector to appear before reading the page content. This matters for
    sites that serve a JS-driven interstitial/challenge shell first
    ("Checking your browser...", "Just a moment...", etc.) - domcontentloaded
    alone fires as soon as that shell loads, before any real content exists.
    If the selector never appears, we still return whatever HTML is there so
    the caller can inspect/log it rather than silently getting nothing.
    """
    from bs4 import BeautifulSoup

    playwright_cm = sync_playwright()
    if _STEALTH_MODE == "class":
        playwright_cm = Stealth().use_sync(playwright_cm)

    with playwright_cm as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        if _STEALTH_MODE == "legacy":
            _stealth_sync_legacy(page)
        page.goto(url, wait_until="networkidle", timeout=timeout*1000)
        if wait_selector:
            try:
                page.wait_for_selector(wait_selector, timeout=timeout*1000)
            except Exception:
                pass  # let the caller inspect the HTML and decide what happened
        html = page.content()
        browser.close()
        return BeautifulSoup(html, "html.parser")


def sleep_randomly(min_sec: Optional[float] = None, max_sec: Optional[float] = None):
    lo = min_sec or 2.0
    hi = max_sec or 5.0
    time.sleep(random.uniform(lo, hi))
