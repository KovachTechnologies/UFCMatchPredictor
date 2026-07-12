"""Common scraping utilities"""

import time
import random
from typing import Optional

import requests
from bs4 import BeautifulSoup

from ufc.config import USER_AGENT, REQUEST_DELAY_RANGE


def get_soup(url: str, timeout: int = 15) -> BeautifulSoup:
    """Fetch URL and return BeautifulSoup object."""
    headers = {"User-Agent": USER_AGENT}
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


def sleep_randomly(min_sec: Optional[float] = None, max_sec: Optional[float] = None):
    """Sleep randomly to be polite to websites."""
    lo = min_sec or REQUEST_DELAY_RANGE[0]
    hi = max_sec or REQUEST_DELAY_RANGE[1]
    time.sleep(random.uniform(lo, hi))
