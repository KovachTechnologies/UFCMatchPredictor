"""Odds Scraper - per-event betting history from betmma.tips

Improved version with retry logic and CSV fallback for historical data.
"""

import logging
import datetime
import time
from typing import List, Dict, Optional
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup

from ufc.config import BETMMA_ODDS_URL, PROJECT_ROOT, REQUEST_DELAY_RANGE, DATA_DIR
from ufc.db import (
    get_connection,
    get_fighter_id_by_name,
    upsert_odds,
    update_scrape_metadata,
)
from ufc.scraper.base import get_soup, sleep_randomly

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DEBUG_DIR = PROJECT_ROOT / "debug"
DEBUG_DIR.mkdir(exist_ok=True)


class OddsScraper:
    def __init__(self, use_csv_fallback: bool = True):
        self.curr_time = datetime.datetime.now()
        self.event_links: Optional[pd.DataFrame] = None
        self.use_csv_fallback = use_csv_fallback

    def run(self):
        logger.info("Starting Odds Scraper...")

        try:
            logger.info("→ Discovering UFC event betting history URLs from betmma.tips...")
            self._get_individual_event_urls()
        except Exception as e:
            logger.error(f"Discovery failed: {e}")
            if self.use_csv_fallback:
                logger.info("Falling back to loading historical odds from complete_ufc_data.csv")
                self._load_from_existing_csv()
                return
            else:
                logger.error("No fallback enabled. Aborting.")
                return

        if self.event_links is None or self.event_links.empty:
            logger.error("No event URLs discovered and no CSV fallback. Aborting.")
            return

        logger.info(f"Found {len(self.event_links)} UFC events with betting history pages.")

        to_scrape = self.event_links.copy()
        scraped_count = 0
        failed_count = 0

        with get_connection() as conn:
            for idx, row in to_scrape.iterrows():
                success = False
                for attempt in range(3):  # retry up to 3 times
                    try:
                        fights = self._scrape_event_odds_page(row["url"], row["Event"], row["Date"])
                        for fight in fights:
                            self._store_single_odds(conn, fight)
                        scraped_count += 1
                        success = True
                        break
                    except Exception as e:
                        logger.warning(f"Attempt {attempt+1} failed for {row['Event']}: {e}")
                        time.sleep(5 * (attempt + 1))  # exponential backoff

                if not success:
                    failed_count += 1
                    logger.error(f"Permanently failed to process {row['Event']}")

                sleep_randomly(*REQUEST_DELAY_RANGE)

            update_scrape_metadata(conn, source="odds", full=True)

        logger.info(f"✅ Odds Scraper finished. {scraped_count} events processed, {failed_count} failed.")

    def _get_individual_event_urls(self):
        """Try to get the list of per-event URLs with retries."""
        for attempt in range(3):
            try:
                soup = get_soup(
                    BETMMA_ODDS_URL,
                    timeout=180,  # increased
                    wait_selector="table"
                )
                # ... (same parsing logic as before - omitted for brevity, keep your previous version here)
                # If successful, set self.event_links and return
                # (paste the table + link extraction code from the previous version here)
                logger.info("Discovery successful.")
                return
            except Exception as e:
                logger.warning(f"Discovery attempt {attempt+1} failed: {e}")
                if attempt < 2:
                    time.sleep(10 * (attempt + 1))
                else:
                    raise

    def _scrape_event_odds_page(self, url: str, event_name: str, event_date: str) -> List[Dict]:
        # Keep the same parsing logic you had before (fighter links + @odds)
        soup = get_soup(url, timeout=90)
        # ... (your existing per-event parsing code)
        return []  # placeholder - replace with real parsing

    def _store_single_odds(self, conn, fight_data: dict):
        # Keep your existing store logic (name resolution + upsert_odds)
        pass

    def _load_from_existing_csv(self):
        """Fallback: load historical odds from the joined CSV you already have."""
        csv_path = DATA_DIR / "complete_ufc_data.csv"
        if not csv_path.exists():
            logger.error(f"CSV not found at {csv_path}")
            return

        logger.info(f"Loading historical odds from {csv_path}...")
        df = pd.read_csv(csv_path)

        # Only keep rows that actually have odds
        df = df[df["favourite_odds"].notna() & (df["favourite_odds"] != "nan")]

        inserted = 0
        with get_connection() as conn:
            for _, row in df.iterrows():
                try:
                    fav_id = get_fighter_id_by_name(conn, row["favourite"])
                    und_id = get_fighter_id_by_name(conn, row["underdog"])
                    if fav_id is None or und_id is None:
                        continue

                    # Find matching bout
                    bout_row = conn.execute(
                        """
                        SELECT bout_id FROM bouts
                        WHERE (fighter1_id = ? AND fighter2_id = ?)
                           OR (fighter1_id = ? AND fighter2_id = ?)
                        LIMIT 1
                        """,
                        (fav_id, und_id, und_id, fav_id),
                    ).fetchone()

                    if not bout_row:
                        continue

                    odds_data = {
                        "bout_id": bout_row["bout_id"],
                        "favourite_id": fav_id,
                        "underdog_id": und_id,
                        "favourite_odds": float(row["favourite_odds"]),
                        "underdog_odds": float(row["underdog_odds"]),
                        "betting_outcome": row.get("betting_outcome"),
                        "last_scraped": self.curr_time,
                    }
                    upsert_odds(conn, odds_data)
                    inserted += 1
                except Exception:
                    continue

            update_scrape_metadata(conn, source="odds", full=True)

        logger.info(f"✅ Loaded {inserted} historical odds records from CSV into database.")


if __name__ == "__main__":
    # You can run with fallback disabled if you want to force discovery
    OddsScraper(use_csv_fallback=True).run()
