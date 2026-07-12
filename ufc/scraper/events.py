"""Event Scraper - fetches historic UFC event results (incremental)"""

import datetime
import pandas as pd

from ufc.config import EVENTS_COMPLETED_URL
from ufc.db import get_connection
from ufc.scraper.base import get_soup, sleep_randomly


class EventScraper:
    """Scrape UFC event results and store in SQLite"""

    def __init__(self):
        self.curr_time = datetime.datetime.now()

    def run(self):
        """Run event scraping (incremental)"""
        print("Starting Event Scraper...")

        print("→ Fetching all event URLs...")
        event_urls = self._get_individual_event_urls()

        print(f"→ Found {len(event_urls)} events. Scraping results...")
        self._scrape_and_store_events(event_urls)

        print("✅ Event Scraper completed.")

    def _get_individual_event_urls(self) -> list:
        """Scrape index page for all completed event URLs"""
        soup = get_soup(EVENTS_COMPLETED_URL)
        link_elements = soup.find_all("a", class_="b-link b-link_style_black")
        return [link["href"] for link in link_elements]

    def _scrape_and_store_events(self, event_urls: list):
        """Scrape each event and store bouts"""
        with get_connection() as conn:
            cursor = conn.cursor()

            for i, url in enumerate(event_urls):
                try:
                    raw = self._get_raw_event_data(url)
                    clean = self._clean_raw_event_results(raw)
                    self._store_event_and_bouts(conn, clean)
                    print(f"  [{i+1:4d}/{len(event_urls)}] {clean['event_name'][0]} ✔️")
                except Exception as e:
                    print(f"  Error on {url}: {e}")
                sleep_randomly(1.5, 3.0)

    def _get_raw_event_data(self, event_url):
        """Parse one event page"""
        soup = get_soup(event_url)

        event_name = soup.find("span", class_="b-content__title-highlight").text.strip()

        fight_details = soup.find_all("li", class_="b-list__box-list-item")
        event_date = fight_details[0].text.replace("\n", "").replace("Date:", "").replace(",", "").strip()
        event_location = fight_details[1].text.replace("\n", "").replace("Location:", "").strip()

        table = soup.find("table", "b-fight-details__table")
        # (simplified parsing - using pandas for speed)
        df = pd.read_html(str(table))[0]
        df["event_name"] = event_name
        df["event_date"] = event_date
        df["event_location"] = event_location

        return df

    def _clean_raw_event_results(self, raw_df: pd.DataFrame):
        """Clean event results"""
        df = raw_df.copy()
        df[["fighter1", "fighter2"]] = df["Fighter"].str.split("                          ", expand=True)
        df["outcome"] = df["W/L"].map({
            "win": "fighter1",
            "draw": "Draw",
            "nc": "No contest"
        }).fillna("fighter1")
        return df[["event_name", "event_date", "event_location", "Weight class",
                   "fighter1", "fighter2", "outcome", "Method", "Round", "Time"]]

    def _store_event_and_bouts(self, conn, df: pd.DataFrame):
        """Store event + bouts (simple upsert for now)"""
        cursor = conn.cursor()

        # Store event
        cursor.execute("""
            INSERT OR IGNORE INTO events (event_name, event_date, event_location, last_scraped)
            VALUES (?, ?, ?, ?)
        """, (df["event_name"].iloc[0], df["event_date"].iloc[0],
              df["event_location"].iloc[0], self.curr_time))

        # For bouts we would need fighter IDs - simplified for first pass
        # TODO: join with fighters table using name matching in future increment
        print("    (Bout storage stubbed - coming in next refinement)")
