"""Odds Scraper - fetches historic betting odds from betmma.tips"""

import pandas as pd
import datetime

from ufc.config import BETMMA_ODDS_URL
from ufc.db import get_connection
from ufc.scraper.base import get_soup, sleep_randomly


class OddsScraper:
    """Scrape historic betting odds"""

    def __init__(self):
        self.curr_time = datetime.datetime.now()

    def run(self):
        print("Starting Odds Scraper...")

        print("→ Fetching event list and odds...")
        odds_df = self._scrape_all_event_odds()

        print(f"→ Found {len(odds_df)} odds records. Storing...")
        self._store_odds(odds_df)

        print("✅ Odds Scraper completed.")

    def _scrape_all_event_odds(self) -> pd.DataFrame:
        """Main scraper for odds"""
        response = get_soup(BETMMA_ODDS_URL)  # using our helper
        # Note: This is a simplified version. Full logic from old scraper can be expanded.
        # For now we stub a basic structure - we'll refine with full parsing next.
        print("    (Full odds parsing stubbed for first pass)")
        return pd.DataFrame()  # placeholder

    def _store_odds(self, df: pd.DataFrame):
        """Store odds in DB"""
        with get_connection() as conn:
            # TODO: implement full upsert once parsing is complete
            print("    (Odds storage stubbed)")
