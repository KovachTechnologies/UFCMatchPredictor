"""Common scraping utilities - Playwright with stealth"""

import time
import random
from typing import Optional
from playwright.sync_api import sync_playwright

try:
    from playwright_stealth import stealth_sync
except ImportError:
    stealth_sync = None
    print("Warning: playwright-stealth not installed. Running without stealth.")


def get_soup(url: str, timeout: int = 90):
    """Fetch page with stealth"""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        if stealth_sync:
            stealth_sync(page)
        page.goto(url, wait_until="domcontentloaded", timeout=timeout*1000)
        html = page.content()
        browser.close()
        from bs4 import BeautifulSoup
        return BeautifulSoup(html, "html.parser")


def sleep_randomly(min_sec: Optional[float] = None, max_sec: Optional[float] = None):
    lo = min_sec or 2.0
    hi = max_sec or 5.0
    time.sleep(random.uniform(lo, hi))
