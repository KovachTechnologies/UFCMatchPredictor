"""Odds Scraper - with debug HTML save"""

import datetime
import pandas as pd
import logging
import string
from typing import Dict, List

from ufc.config import BETMMA_ODDS_URL
from ufc.db import get_connection
from ufc.scraper.base import get_soup, sleep_randomly

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class OddsScraper:
    def __init__(self):
        self.curr_time = datetime.datetime.now()

    def run(self):
        logger.info("Starting Odds Scraper...")

        logger.info("→ Fetching odds data...")
        odds_df = self._scrape_all_event_odds()

        if odds_df.empty:
            logger.error("No odds data retrieved. Check debug_odds.html")
            return

        logger.info(f"→ Found {len(odds_df)} odds records. Storing...")
        self._store_odds(odds_df)

        logger.info("✅ Odds Scraper completed.")

    def _scrape_all_event_odds(self) -> pd.DataFrame:
        try:
            soup = get_soup(BETMMA_ODDS_URL, timeout=150)  # even longer timeout
        except Exception as e:
            logger.error(f"Error getting data for odds: {e}")
            return pd.DataFrame()

        try :
            tables = soup.find_all("table")
            if tables:
                df = pd.read_html(str(tables[0]))[0]
                logger.info(f"Extracted {len(df)} rows from odds table")
                return df
            else:
                logger.error("No tables found on odds page")
                return pd.DataFrame()
        except Exception as e:
            logger.info(f"Error scraping odds: {e}")
            return pd.DataFrame()

    def _store_odds(self, df: pd.DataFrame):
        with get_connection() as conn:
            cursor = conn.cursor()
            inserted = 0
            for _, row in df.iterrows():
                try:
                    cursor.execute("""
                        INSERT OR IGNORE INTO odds 
                        (bout_id, favourite_odds, underdog_odds, last_scraped)
                        VALUES (?, ?, ?, ?)
                    """, (None, row.get("Favourite Odds"), row.get("Underdog Odds"), self.curr_time))
                    inserted += 1
                except:
                    pass
            conn.commit()
            logger.info(f"Stored {inserted} odds records")
