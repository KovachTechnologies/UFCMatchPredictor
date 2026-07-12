"""Common scraping utilities - Playwright version for Cloudflare"""

import time
import random
from typing import Optional
from playwright.sync_api import sync_playwright

def get_soup(url: str, timeout: int = 30):
    """Fetch page with Playwright (bypasses JS challenges)"""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, wait_until="networkidle", timeout=timeout*1000)
        html = page.content()
        browser.close()
        from bs4 import BeautifulSoup
        return BeautifulSoup(html, "html.parser")


def sleep_randomly(min_sec: Optional[float] = None, max_sec: Optional[float] = None):
    lo = min_sec or 1.5
    hi = max_sec or 3.5
    time.sleep(random.uniform(lo, hi))
