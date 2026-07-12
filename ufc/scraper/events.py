"""Event Scraper - updated for current site + Playwright"""

import datetime
import pandas as pd

from ufc.config import EVENTS_COMPLETED_URL
from ufc.db import get_connection
from ufc.scraper.base import get_soup, sleep_randomly


class EventScraper:
    def __init__(self):
        self.curr_time = datetime.datetime.now()

    def run(self):
        print("Starting Event Scraper...")

        print("→ Fetching event URLs...")
        event_urls = self._get_individual_event_urls()

        print(f"→ Found {len(event_urls)} events.")
        self._scrape_and_store_events(event_urls)

        print("✅ Event Scraper completed.")

    def _get_individual_event_urls(self) -> list:
        soup = get_soup(EVENTS_COMPLETED_URL)
        links = soup.find_all("a", href=True)
        urls = []
        for link in links:
            href = link.get("href")
            if href and "/event-details/" in href:
                full = "http://ufcstats.com" + href if not href.startswith("http") else href
                if full not in urls:
                    urls.append(full)
        return urls

    def _scrape_and_store_events(self, event_urls: list):
        with get_connection() as conn:
            for i, url in enumerate(event_urls):
                try:
                    raw = self._get_raw_event_data(url)
                    clean = self._clean_raw_event_results(raw)
                    self._store_event_and_bouts(conn, clean)
                    print(f"  [{i+1:4d}/{len(event_urls)}] {clean['event_name'].iloc[0]} ✔️")
                except Exception as e:
                    print(f"  Error on {url}: {e}")
                sleep_randomly(2, 4)

    def _get_raw_event_data(self, event_url):
        soup = get_soup(event_url)

        event_name = soup.find("span", class_="b-content__title-highlight").text.strip()

        fight_details = soup.find_all("li", class_="b-list__box-list-item")
        event_date = fight_details[0].text.replace("\n", "").replace("Date:", "").replace(",", "").strip()
        event_location = fight_details[1].text.replace("\n", "").replace("Location:", "").strip()

        table = soup.find("table", class_="b-fight-details__table")
        df = pd.read_html(str(table))[0] if table else pd.DataFrame()
        df["event_name"] = event_name
        df["event_date"] = event_date
        df["event_location"] = event_location

        return df

    def _clean_raw_event_results(self, raw_df: pd.DataFrame):
        df = raw_df.copy()
        # More robust fighter split
        if "Fighter" in df.columns:
            df[["fighter1", "fighter2"]] = df["Fighter"].str.split(r"\s{2,}", expand=True, n=1)
        df["outcome"] = df.get("W/L", pd.Series()).map({
            "win": "fighter1",
            "draw": "Draw",
            "nc": "No contest"
        }).fillna("fighter1")
        return df

    def _store_event_and_bouts(self, conn, df: pd.DataFrame):
        cursor = conn.cursor()

        cursor.execute("""
            INSERT OR IGNORE INTO events (event_name, event_date, event_location, last_scraped)
            VALUES (?, ?, ?, ?)
        """, (df["event_name"].iloc[0], df["event_date"].iloc[0],
              df["event_location"].iloc[0], self.curr_time))

        print("    Event stored (bouts linking coming soon)")
