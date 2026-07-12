"""Odds Scraper - Historic betting odds from betmma.tips"""

import datetime
import pandas as pd

from ufc.config import BETMMA_ODDS_URL
from ufc.db import get_connection
from ufc.scraper.base import get_soup, sleep_randomly


class OddsScraper:
    def __init__(self):
        self.curr_time = datetime.datetime.now()

    def run(self):
        print("Starting Odds Scraper...")

        print("→ Fetching odds data...")
        odds_df = self._scrape_all_event_odds()

        if odds_df.empty:
            print("No odds data retrieved.")
            return

        print(f"→ Found {len(odds_df)} odds records. Storing...")
        self._store_odds(odds_df)

        print("✅ Odds Scraper completed.")

    def _scrape_all_event_odds(self) -> pd.DataFrame:
        """Main scraper for odds"""
        try:
            soup = get_soup(BETMMA_ODDS_URL)
            # betmma.tips often uses tables - try to extract the main table
            tables = soup.find_all("table")
            if tables:
                df = pd.read_html(str(tables[0]))[0]
                print(f"    DEBUG: Extracted {len(df)} rows from odds table")
                return df
            else:
                print("    DEBUG: No tables found on odds page")
                return pd.DataFrame()
        except Exception as e:
            print(f"Error scraping odds: {e}")
            return pd.DataFrame()

    def _store_odds(self, df: pd.DataFrame):
        """Store odds in DB (basic for now)"""
        with get_connection() as conn:
            cursor = conn.cursor()
            # TODO: Improve matching with fighters/events in next iteration
            for _, row in df.iterrows():
                try:
                    cursor.execute("""
                        INSERT OR IGNORE INTO odds 
                        (bout_id, favourite_odds, underdog_odds, last_scraped)
                        VALUES (?, ?, ?, ?)
                    """, (None, row.get("Favourite Odds"), row.get("Underdog Odds"), self.curr_time))
                except:
                    pass  # skip bad rows for now
            conn.commit()
            print(f"    Stored odds for {len(df)} records (matching improved later)")
