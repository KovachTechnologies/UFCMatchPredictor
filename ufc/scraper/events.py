"""Event Scraper - Incremental (only new events) with full bout storage"""

import logging
import datetime
from typing import List, Dict

import pandas as pd

from ufc.config import EVENTS_COMPLETED_URL
from ufc.db import get_connection, upsert_event, upsert_bout
from ufc.scraper.base import get_soup, sleep_randomly

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class EventScraper:
    def __init__(self):
        self.curr_time = datetime.datetime.now()

    def run(self):
        logger.info("Starting Event Scraper (incremental)...")

        logger.info("→ Fetching event URLs from ufcstats.com...")
        event_urls = self._get_individual_event_urls()
        logger.info(f"Found {len(event_urls)} total events on site.")

        new_events = self._filter_new_events(event_urls)
        logger.info(f"→ {len(new_events)} new events to scrape.")

        if not new_events:
            logger.info("No new events found. Exiting.")
            return

        self._scrape_and_store_events(new_events)
        logger.info("✅ Event Scraper completed successfully.")

    def _get_individual_event_urls(self) -> List[str]:
        """Scrape the completed events index page for individual event URLs."""
        soup = get_soup(EVENTS_COMPLETED_URL)
        links = soup.find_all("a", href=True)
        urls = []
        for link in links:
            href = link.get("href", "")
            if "/event-details/" in href:
                full = "http://ufcstats.com" + href if not href.startswith("http") else href
                if full not in urls:
                    urls.append(full)
        return urls

    def _filter_new_events(self, event_urls: List[str]) -> List[str]:
        """Return only events that are not already in the database (by name + date)."""
        new_urls = []
        with get_connection() as conn:
            cursor = conn.cursor()
            for url in event_urls:
                try:
                    temp_soup = get_soup(url)
                    event_name = temp_soup.find("span", class_="b-content__title-highlight").text.strip()
                    fight_details = temp_soup.find_all("li", class_="b-list__box-list-item")
                    event_date_raw = fight_details[0].text.replace("\n", "").replace("Date:", "").replace(",", "").strip()
                    event_date = self._parse_event_date(event_date_raw)

                    cursor.execute(
                        "SELECT 1 FROM events WHERE event_name = ? AND event_date = ? LIMIT 1",
                        (event_name, event_date)
                    )
                    if not cursor.fetchone():
                        new_urls.append(url)
                except Exception as e:
                    logger.warning(f"Could not pre-check event {url}: {e}")
        return new_urls

    def _scrape_and_store_events(self, event_urls: List[str]):
        with get_connection() as conn:
            for i, url in enumerate(event_urls):
                try:
                    raw = self._get_raw_event_data(url)
                    event_id = self._store_event(conn, raw)

                    bouts = self._parse_bouts(raw, event_id)
                    for bout in bouts:
                        upsert_bout(conn, bout)

                    event_name = raw["event_name"].iloc[0]
                    logger.info(f"  [{i+1:4d}/{len(event_urls)}] {event_name} ✔️ ({len(bouts)} bouts)")

                except Exception as e:
                    logger.error(f"Failed to process event {url}: {e}")
                sleep_randomly(2, 4)

    def _get_raw_event_data(self, event_url: str) -> pd.DataFrame:
        soup = get_soup(event_url)

        event_name = soup.find("span", class_="b-content__title-highlight").text.strip()

        fight_details = soup.find_all("li", class_="b-list__box-list-item")
        event_date_raw = fight_details[0].text.replace("\n", "").replace("Date:", "").replace(",", "").strip()
        event_location = fight_details[1].text.replace("\n", "").replace("Location:", "").strip()

        table = soup.find("table", class_="b-fight-details__table")
        if table:
            df = pd.read_html(str(table))[0]
        else:
            df = pd.DataFrame()

        df["event_name"] = event_name
        df["event_date"] = self._parse_event_date(event_date_raw)
        df["event_location"] = event_location
        df["event_url"] = event_url

        return df

    def _parse_event_date(self, date_str: str) -> str:
        """Convert various date formats to YYYY-MM-DD"""
        try:
            for fmt in ("%B %d %Y", "%b %d %Y", "%d %B %Y"):
                try:
                    return datetime.datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
                except ValueError:
                    continue
            return date_str
        except Exception:
            return date_str

    def _store_event(self, conn, raw_df: pd.DataFrame) -> int:
        event_data = {
            "event_name": raw_df["event_name"].iloc[0],
            "event_date": raw_df["event_date"].iloc[0],
            "event_location": raw_df["event_location"].iloc[0],
            "last_scraped": self.curr_time,
        }
        return upsert_event(conn, event_data)

    def _parse_bouts(self, raw_df: pd.DataFrame, event_id: int) -> List[Dict]:
        """Convert the raw event table into clean bout records for the bouts table."""
        bouts = []
        for _, row in raw_df.iterrows():
            try:
                fighters = str(row.get("Fighter", "")).split()
                if len(fighters) < 2:
                    continue

                fighter1 = fighters[0]
                fighter2 = " ".join(fighters[1:])

                outcome_raw = str(row.get("W/L", "")).lower()
                if "win" in outcome_raw:
                    outcome = "fighter1"
                elif "draw" in outcome_raw:
                    outcome = "Draw"
                elif "nc" in outcome_raw:
                    outcome = "No contest"
                else:
                    outcome = None

                bout = {
                    "event_id": event_id,
                    "fighter1": fighter1,
                    "fighter2": fighter2,
                    "weight_class": row.get("Weight class"),
                    "outcome": outcome,
                    "method": row.get("Method"),
                    "round": int(row.get("Round")) if pd.notna(row.get("Round")) else None,
                    "time": row.get("Time"),
                    "last_scraped": self.curr_time,
                }
                bouts.append(bout)
            except Exception as e:
                logger.warning(f"Skipping one bout: {e}")
        return bouts
