"""Event Scraper - Incremental (only new events) with full bout storage"""

import logging
import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple

import pandas as pd
from bs4 import BeautifulSoup

from ufc.config import EVENTS_COMPLETED_URL, REQUEST_DELAY_RANGE, PROJECT_ROOT
from ufc.db import (
    get_connection,
    upsert_event,
    upsert_bout,
    get_fighter_id_by_url,
    get_fighter_id_by_name,
    update_scrape_metadata,
)
from ufc.scraper.base import get_soup, sleep_randomly

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DEBUG_DIR = PROJECT_ROOT / "debug"
DEBUG_DIR.mkdir(exist_ok=True)

BASE_URL = "http://ufcstats.com"

# NOTE: these column indices reflect ufcstats.com's b-fight-details__table
# layout as of writing (W/L, Fighter, Str, Td, Sub, Pass, Weight class,
# Method, Round, Time). Sites re-skin without notice - if bouts start coming
# back with empty weight_class/method/round/time, check
# debug/event_bad_row.html (written automatically below) against the live
# page and adjust these indices.
COL_OUTCOME = 0
COL_FIGHTER = 1
COL_WEIGHT_CLASS = 6
COL_METHOD = 7
COL_ROUND = 8
COL_TIME = 9


class EventScraper:
    def __init__(self):
        self.curr_time = datetime.datetime.now()

    def run(self):
        logger.info("Starting Event Scraper (incremental)...")

        logger.info("→ Fetching event URLs from ufcstats.com...")
        event_urls = self._get_individual_event_urls()

        if not event_urls:
            logger.error("No event URLs found - aborting before touching the DB.")
            return

        logger.info(f"Found {len(event_urls)} total events on site.")

        new_count = 0
        skipped_count = 0
        failed_count = 0

        with get_connection() as conn:
            for i, url in enumerate(event_urls):
                try:
                    soup = get_soup(url)
                    header = self._parse_event_header(soup, url)
                    if header is None:
                        failed_count += 1
                        sleep_randomly(*REQUEST_DELAY_RANGE)
                        continue

                    event_name, event_date, event_location = header

                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT 1 FROM events WHERE event_name = ? AND event_date = ? LIMIT 1",
                        (event_name, event_date),
                    )
                    if cursor.fetchone():
                        skipped_count += 1
                        sleep_randomly(*REQUEST_DELAY_RANGE)
                        continue

                    event_id = upsert_event(conn, {
                        "event_name": event_name,
                        "event_date": event_date,
                        "event_location": event_location,
                        "source_url": url,
                        "last_scraped": self.curr_time,
                    })

                    bouts = self._parse_bouts(conn, soup, event_id)
                    for bout in bouts:
                        upsert_bout(conn, bout)

                    new_count += 1
                    logger.info(f"  [{i+1:4d}/{len(event_urls)}] {event_name} ✔️ ({len(bouts)} bouts)")

                except Exception as e:
                    failed_count += 1
                    logger.error(f"Failed to process event {url}: {e}")

                sleep_randomly(*REQUEST_DELAY_RANGE)

            update_scrape_metadata(conn, source="events", full=False)

        logger.info(
            f"✅ Event Scraper completed. {new_count} new, {skipped_count} already known, "
            f"{failed_count} failed."
        )

    def _get_individual_event_urls(self) -> List[str]:
        """Scrape the completed events index page for individual event URLs."""
        try:
            soup = get_soup(EVENTS_COMPLETED_URL)
        except Exception as e:
            logger.error(f"Error fetching events index: {e}")
            return []

        links = soup.find_all("a", href=True)
        urls = []
        for link in links:
            href = link.get("href", "")
            if "/event-details/" in href:
                full = self._normalize_url(href)
                if full not in urls:
                    urls.append(full)

        if not urls:
            with open(DEBUG_DIR / "events_index_failure.html", "w", encoding="utf-8") as f:
                f.write(str(soup))
            logger.error(f"No event links found on index page. Saved {DEBUG_DIR / 'events_index_failure.html'}")

        return urls

    def _normalize_url(self, href: str) -> str:
        return href if href.startswith("http") else BASE_URL + href

    def _parse_event_header(self, soup: BeautifulSoup, url: str) -> Optional[Tuple[str, str, str]]:
        """Extract (event_name, event_date_iso, event_location) from an event page."""
        try:
            name_el = soup.find("span", class_="b-content__title-highlight")
            if not name_el:
                raise ValueError("title element not found")
            event_name = name_el.text.strip()

            fight_details = soup.find_all("li", class_="b-list__box-list-item")
            event_date_raw = fight_details[0].text.replace("\n", "").replace("Date:", "").replace(",", "").strip()
            event_location = fight_details[1].text.replace("\n", "").replace("Location:", "").strip()
            event_date = self._parse_event_date(event_date_raw)

            return event_name, event_date, event_location
        except Exception as e:
            logger.warning(f"Could not parse event header for {url}: {e}")
            with open(DEBUG_DIR / "event_header_failure.html", "w", encoding="utf-8") as f:
                f.write(str(soup))
            return None

    def _parse_event_date(self, date_str: str) -> str:
        """Convert various date formats to YYYY-MM-DD"""
        for fmt in ("%B %d %Y", "%b %d %Y", "%d %B %Y"):
            try:
                return datetime.datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue
        logger.warning(f"Could not parse event date '{date_str}' with known formats - storing raw")
        return date_str

    def _parse_bouts(self, conn, soup: BeautifulSoup, event_id: int) -> List[Dict]:
        """Extract bouts directly from the fight table HTML.

        Deliberately does NOT use pd.read_html for the Fighter column: that
        column holds two separate <a> links (one per fighter) which
        read_html flattens into a single text blob with no reliable
        separator. Splitting that text on whitespace breaks for any
        multi-word name (i.e. almost every fighter), so fighter identity is
        resolved here from the actual <a href> profile URLs instead.
        """
        bouts = []
        rows = soup.find_all("tr", class_="b-fight-details__table-row")

        for row in rows:
            try:
                cells = row.find_all("td", class_="b-fight-details__table-col")
                if len(cells) <= max(COL_OUTCOME, COL_FIGHTER, COL_WEIGHT_CLASS, COL_METHOD, COL_ROUND, COL_TIME):
                    logger.warning(f"Bout row has fewer columns than expected ({len(cells)}) - skipping")
                    with open(DEBUG_DIR / "event_bad_row.html", "w", encoding="utf-8") as f:
                        f.write(str(row))
                    continue

                fighter_links = cells[COL_FIGHTER].find_all("a", href=True)
                if len(fighter_links) < 2:
                    logger.warning("Could not find two fighter links in bout row - skipping")
                    continue

                fighter1_url = self._normalize_url(fighter_links[0]["href"])
                fighter2_url = self._normalize_url(fighter_links[1]["href"])
                fighter1_name = fighter_links[0].get_text(strip=True)
                fighter2_name = fighter_links[1].get_text(strip=True)

                fighter1_id = get_fighter_id_by_url(conn, fighter1_url) or get_fighter_id_by_name(conn, fighter1_name)
                fighter2_id = get_fighter_id_by_url(conn, fighter2_url) or get_fighter_id_by_name(conn, fighter2_name)
                if fighter1_id is None or fighter2_id is None:
                    logger.warning(
                        f"Could not resolve fighter id(s) for bout '{fighter1_name}' vs "
                        f"'{fighter2_name}' (event_id={event_id}) - run fighters.py first "
                        f"if these are new fighters. Storing bout with raw names only."
                    )

                outcome_paras = cells[COL_OUTCOME].find_all("p")
                outcome_raw = outcome_paras[0].get_text(strip=True).lower() if outcome_paras else ""
                if "win" in outcome_raw:
                    outcome = "fighter1"
                elif "draw" in outcome_raw:
                    outcome = "Draw"
                elif "nc" in outcome_raw:
                    outcome = "No contest"
                else:
                    outcome = None

                weight_class = cells[COL_WEIGHT_CLASS].get_text(strip=True) or None
                method = cells[COL_METHOD].get_text(strip=True) or None
                round_text = cells[COL_ROUND].get_text(strip=True)
                round_val = int(round_text) if round_text.isdigit() else None
                time_val = cells[COL_TIME].get_text(strip=True) or None

                bouts.append({
                    "event_id": event_id,
                    "fighter1_id": fighter1_id,
                    "fighter2_id": fighter2_id,
                    "fighter1_name": fighter1_name,
                    "fighter2_name": fighter2_name,
                    "weight_class": weight_class,
                    "outcome": outcome,
                    "method": method,
                    "round": round_val,
                    "time": time_val,
                    "last_scraped": self.curr_time,
                })
            except Exception as e:
                logger.warning(f"Skipping one bout row: {e}")

        return bouts
