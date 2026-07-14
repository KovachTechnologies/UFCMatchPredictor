"""Common scraping utilities - Playwright with stealth + retries"""

import time
import random
import json
from pathlib import Path
from typing import Optional
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

try:
    from playwright_stealth import Stealth
    _STEALTH_MODE = "class"
except ImportError:
    try:
        from playwright_stealth import stealth_sync as _stealth_sync_legacy
        _STEALTH_MODE = "legacy"
    except ImportError:
        _STEALTH_MODE = None
        print("Warning: playwright-stealth not installed.")

DEBUG_DIR = Path(__file__).resolve().parents[2] / "debug"
DEBUG_DIR.mkdir(exist_ok=True)


def get_soup(
    url: str,
    timeout: int = 90,
    wait_selector: Optional[str] = None,
    wait_until: str = "domcontentloaded",   # Changed from networkidle
    retries: int = 2,
    debug_on_failure: bool = True
):
    """Fetch page with stealth + retries. Much more reliable than before."""
    from bs4 import BeautifulSoup

    last_exception = None

    for attempt in range(retries + 1):
        playwright_cm = sync_playwright()
        if _STEALTH_MODE == "class":
            playwright_cm = Stealth().use_sync(playwright_cm)

        try:
            with playwright_cm as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    viewport={"width": 1920, "height": 1080},
                    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
                )
                page = context.new_page()
                if _STEALTH_MODE == "legacy":
                    _stealth_sync_legacy(page)

                page.goto(url, wait_until=wait_until, timeout=timeout * 1000)

                if wait_selector:
                    try:
                        page.wait_for_selector(wait_selector, timeout=timeout * 1000)
                    except Exception:
                        pass

                html = page.content()
                browser.close()
                return BeautifulSoup(html, "html.parser")

        except PlaywrightTimeout as e:
            last_exception = e
            if debug_on_failure:
                _save_debug_failure(url, attempt, str(e))
            if attempt < retries:
                sleep_time = (2 ** attempt) * 5 + random.uniform(1, 3)
                print(f"  Retry {attempt+1}/{retries} for {url} after {sleep_time:.1f}s...")
                time.sleep(sleep_time)
            continue

        except Exception as e:
            last_exception = e
            if debug_on_failure:
                _save_debug_failure(url, attempt, str(e))
            break

    raise last_exception or Exception(f"Failed to fetch {url} after {retries} retries")


def _save_debug_failure(url: str, attempt: int, error: str):
    ts = int(time.time())
    safe_name = url.split("/")[-1].replace("?", "_").replace("&", "_")[:80]
    debug_file = DEBUG_DIR / f"failure_{safe_name}_{ts}_attempt{attempt}.html"
    meta_file = DEBUG_DIR / f"failure_{safe_name}_{ts}_attempt{attempt}.json"

    try:
        # We can't easily get the HTML here without re-navigating, so we just log metadata
        with open(meta_file, "w") as f:
            json.dump({
                "url": url,
                "timestamp": ts,
                "attempt": attempt,
                "error": error,
                "note": "Run with headless=False to see the actual page"
            }, f, indent=2)
    except Exception:
        pass


def sleep_randomly(min_sec: Optional[float] = None, max_sec: Optional[float] = None):
    lo = min_sec or 2.0
    hi = max_sec or 5.0
    time.sleep(random.uniform(lo, hi))
