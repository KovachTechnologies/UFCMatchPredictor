"""Odds Scraper - production version"""

import logging
import datetime
from typing import Dict, List, Optional

import pandas as pd

from ufc.config import BETMMA_ODDS_URL, PROJECT_ROOT
from ufc.db import get_connection, get_fighter_id_by_name, update_scrape_metadata, upsert_odds
from ufc.scraper.base import get_soup, sleep_randomly

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DEBUG_DIR = PROJECT_ROOT / "debug"
DEBUG_DIR.mkdir(exist_ok=True)


class OddsScraper:
    def __init__(self):
        self.curr_time = datetime.datetime.now()

    def run(self):
        logger.info("Starting Odds Scraper...")

        logger.info("→ Fetching odds data...")
        odds_df = self._scrape_all_event_odds()

        if odds_df.empty:
            logger.error(f"No odds data retrieved. See {DEBUG_DIR / 'debug_odds.html'} if it was written.")
            return

        logger.info(f"→ Found {len(odds_df)} odds records. Storing...")
        self._store_odds(odds_df)

        logger.info("✅ Odds Scraper completed.")

    def _scrape_all_event_odds(self) -> pd.DataFrame:
        try:
            soup = get_soup(BETMMA_ODDS_URL, timeout=150)
        except Exception as e:
            logger.error(f"Error getting data for odds: {e}")
            return pd.DataFrame()

        tables = soup.find_all("table")
        if not tables:
            logger.error("No tables found on odds page")
            with open(DEBUG_DIR / "debug_odds.html", "w", encoding="utf-8") as f:
                f.write(str(soup))
            return pd.DataFrame()

        try:
            df = pd.read_html(str(tables[0]))[0]
            logger.info(f"Extracted {len(df)} rows from odds table")
            return df
        except Exception as e:
            logger.error(f"Error parsing odds table: {e}")
            with open(DEBUG_DIR / "debug_odds.html", "w", encoding="utf-8") as f:
                f.write(str(soup))
            return pd.DataFrame()

    def _store_odds(self, df: pd.DataFrame):
        # NOTE: verify these column names against a saved debug page - guessed
        # based on the URL's apparent purpose, not confirmed against live HTML.
        required_cols = {"Fighter", "Favourite Odds", "Underdog Odds"}
        missing = required_cols - set(df.columns)
        if missing:
            logger.error(f"Odds table missing expected columns: {missing}. Columns found: {list(df.columns)}")
            return

        with get_connection() as conn:
            inserted = 0
            skipped = 0

            for _, row in df.iterrows():
                try:
                    favourite_name, underdog_name = self._parse_fighters(row.get("Fighter"))
                    if not favourite_name or not underdog_name:
                        logger.warning(f"Could not parse fighter names from row: {row.get('Fighter')}")
                        skipped += 1
                        continue

                    favourite_id = get_fighter_id_by_name(conn, favourite_name)
                    underdog_id = get_fighter_id_by_name(conn, underdog_name)
                    if favourite_id is None or underdog_id is None:
                        logger.warning(
                            f"Could not resolve fighter id(s) for '{favourite_name}' / '{underdog_name}' "
                            f"- run fighters.py first if these are new fighters."
                        )
                        skipped += 1
                        continue

                    bout_id = self._match_bout_id(conn, favourite_id, underdog_id)
                    if bout_id is None:
                        logger.warning(f"No matching bout found for {favourite_name} vs {underdog_name}")
                        skipped += 1
                        continue

                    odds_data = {
                        "bout_id": bout_id,
                        "favourite_id": favourite_id,
                        "underdog_id": underdog_id,
                        "favourite_odds": row.get("Favourite Odds"),
                        "underdog_odds": row.get("Underdog Odds"),
                        "betting_outcome": row.get("Outcome"),  # verify actual column name
                        "last_scraped": self.curr_time,
                    }
                    upsert_odds(conn, odds_data)
                    inserted += 1
                except Exception as e:
                    logger.error(f"Failed to store odds row ({row.get('Fighter')}): {e}")
                    skipped += 1

            update_scrape_metadata(conn, source="odds", full=True)
            logger.info(f"Stored {inserted} odds records ({skipped} skipped)")

    def _parse_fighters(self, fighter_field) -> (Optional[str], Optional[str]):
        """Split the betmma 'Fighter' column into favourite/underdog names.

        NOTE: verify the actual separator/format on the live page (e.g. 'A vs B',
        'A v B', or two fighters on separate lines) and adjust this parsing accordingly.
        """
        if not fighter_field or not isinstance(fighter_field, str):
            return None, None

        for sep in (" vs ", " v ", " VS ", " V "):
            if sep in fighter_field:
                parts = fighter_field.split(sep, 1)
                return parts[0].strip(), parts[1].strip()

        return None, None

    def _match_bout_id(self, conn, favourite_id: int, underdog_id: int) -> Optional[int]:
        """Look up the bout_id for a pair of fighter ids, in either order."""
        row = conn.execute(
            """
            SELECT bout_id FROM bouts
            WHERE (fighter1_id = ? AND fighter2_id = ?)
               OR (fighter1_id = ? AND fighter2_id = ?)
            LIMIT 1
            """,
            (favourite_id, underdog_id, underdog_id, favourite_id),
        ).fetchone()
        return row["bout_id"] if row else None
