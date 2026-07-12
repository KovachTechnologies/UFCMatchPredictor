"""Odds Scraper - with debug HTML save"""

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
            print("No odds data retrieved. Check debug_odds.html")
            return

        print(f"→ Found {len(odds_df)} odds records. Storing...")
        self._store_odds(odds_df)

        print("✅ Odds Scraper completed.")

    def _scrape_all_event_odds(self) -> pd.DataFrame:
        try:
            soup = get_soup(BETMMA_ODDS_URL, timeout=150)  # even longer timeout
        except Exception as e:
            print(f"Error getting data for odds: {e}")
            return pd.DataFrame()

        try :
            with open("debug_odds.html", "w", encoding="utf-8") as f:
                f.write(str(soup))
            print("DEBUG: Saved debug_odds.html in project root")

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
            print(f"    Stored {inserted} odds records")
