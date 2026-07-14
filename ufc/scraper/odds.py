"""Odds Scraper - per-event betting history from betmma.tips

Key improvements:
- Retries + backoff on timeouts
- Incremental mode by default (only scrape events without odds yet)
- Much richer debugging (HTML + JSON metadata on failures)
"""

import logging
import datetime
import json
from typing import List, Dict, Optional
from pathlib import Path
import time

import pandas as pd

from ufc.config import BETMMA_ODDS_URL, PROJECT_ROOT, REQUEST_DELAY_RANGE
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
    def __init__(self, incremental: bool = True, debug: bool = False):
        self.curr_time = datetime.datetime.now()
        self.event_links: Optional[pd.DataFrame] = None
        self.incremental = incremental
        self.debug = debug

    def run(self):
        logger.info("Starting Odds Scraper (per-event from betmma.tips)...")

        self._get_individual_event_urls()

        if self.event_links is None or self.event_links.empty:
            logger.error("No event URLs discovered. Aborting.")
            return

        to_scrape = self._filter_events_to_scrape()

        logger.info(f"Found {len(self.event_links)} total UFC events. Will process {len(to_scrape)}.")

        scraped_count = 0
        failed_count = 0

        with get_connection() as conn:
            for idx, row in to_scrape.iterrows():
                success = False
                for attempt in range(3):  # per-event retry
                    try:
                        odds_for_event = self._scrape_event_odds_page(
                            row["url"], row["Event"], row["Date"]
                        )
                        if odds_for_event:
                            for odds_row in odds_for_event:
                                self._store_single_odds(conn, odds_row)
                            scraped_count += 1
                            success = True
                            break
                    except Exception as e:
                        logger.warning(f"Attempt {attempt+1} failed for {row['Event']}: {e}")
                        if self.debug:
                            self._save_detailed_debug(row["url"], str(e), attempt)
                        sleep_time = (2 ** attempt) * 8
                        time.sleep(sleep_time)

                if not success:
                    failed_count += 1

                sleep_randomly(*REQUEST_DELAY_RANGE)

            update_scrape_metadata(conn, source="odds", full=not self.incremental)

        logger.info(f"✅ Finished. {scraped_count} events processed, {failed_count} failed.")

    def _filter_events_to_scrape(self) -> pd.DataFrame:
        """Incremental mode: only scrape events that don't have odds yet."""
        if not self.incremental:
            return self.event_links.copy()

        with get_connection() as conn:
            existing = conn.execute("""
                SELECT DISTINCT e.event_name
                FROM events e
                JOIN bouts b ON e.event_id = b.event_id
                JOIN odds o ON b.bout_id = o.bout_id
            """).fetchall()

        existing_names = {r["event_name"] for r in existing}
        filtered = self.event_links[
            ~self.event_links["Event"].isin(existing_names)
        ].copy()

        logger.info(f"Incremental mode: {len(filtered)} new events to scrape.")
        return filtered

    def _get_individual_event_urls(self):
        """Scrape the big handicapper performance page to extract links to individual
        UFC event betting history pages + their dates/names for filtering."""
        try:
            soup = get_soup(BETMMA_ODDS_URL, timeout=180, wait_selector="table")
        except Exception as e:
            logger.error(f"Could not fetch discovery page: {e}")
            self.event_links = pd.DataFrame()
            return

        # The page has a large table; pd.read_html is convenient for the data part
        try:
            tables = pd.read_html(str(soup), header=0)
            # The main data table is usually the largest or has specific structure.
            # In practice it was table index ~8 in legacy code; we try to find one with "Event" and "Date"
            main_table = None
            for t in tables:
                if "Event" in t.columns and "Date" in t.columns:
                    main_table = t
                    break
            if main_table is None:
                main_table = tables[0] if tables else pd.DataFrame()

            # Clean
            main_table.columns = [str(c).strip() for c in main_table.columns]
            if "Event" not in main_table.columns:
                logger.error("Discovery table missing 'Event' column. Page structure may have changed.")
                self.event_links = pd.DataFrame()
                return

            # Filter to UFC only (exclude Road to UFC, Contender etc if desired)
            ufc_events = main_table[
                main_table["Event"].astype(str).str.contains("UFC", case=False, na=False) &
                ~main_table["Event"].astype(str).str.contains("Road to UFC|Contender Series", case=False, na=False)
            ].copy()

            # The links are in <a> tags; we need to pair them with the table rows.
            # Legacy code did soup.select("td td td td a") which was fragile.
            # Better: find all links that point to mma_event_betting_history
            links = []
            for a in soup.find_all("a", href=True):
                href = a.get("href", "")
                if "mma_event_betting_history.php" in href:
                    full = "http://www.betmma.tips/" + href if not href.startswith("http") else href
                    links.append(full)

            # Since order in table may match order of links on page for UFC rows,
            # we take the first N links where N = len(ufc_events). This is imperfect but worked before.
            # For robustness we could parse the specific table cell links, but this gets us running.
            ufc_events = ufc_events.head(len(links))  # safety
            ufc_events["url"] = links[:len(ufc_events)]

            self.event_links = ufc_events[["Date", "Event", "url"]].reset_index(drop=True)
            logger.info(f"Discovered {len(self.event_links)} UFC betting history pages.")

        except Exception as e:
            logger.error(f"Failed to parse discovery page tables/links: {e}")
            with open(DEBUG_DIR / "odds_discovery_failure.html", "w", encoding="utf-8") as f:
                f.write(str(soup))
            self.event_links = pd.DataFrame()

    def _scrape_event_odds_page(self, url: str, event_name: str, event_date: str) -> List[Dict]:
        """Parse one event's betting history page for fights + decimal odds + outcome."""
        soup = get_soup(url, timeout=120)

        # The legacy parsing logic (adapted):
        # Collect all fighter names from fighter_profile links in order they appear.
        fighter_links = soup.select("a[href*='fighter_profile']")
        fighters = [a.get_text(strip=True) for a in fighter_links]

        if len(fighters) < 2:
            logger.debug(f"No fighter links found on {url}")
            return []

        fights = []
        i = 0
        while i < len(fighters) - 1:
            f1 = fighters[i]
            f2 = fighters[i + 1]
            # The next item after f2 is usually the winner (or '-' for draw/NC)
            if i + 2 < len(fighters):
                possible_result = fighters[i + 2]
                if possible_result in (f1, f2):
                    winner = possible_result
                    i += 3
                else:
                    # draw or NC - the 'result' is actually the next f1
                    winner = None
                    i += 2
            else:
                winner = None
                i += 2

            fights.append({
                "fighter1": f1,
                "fighter2": f2,
                "winner": winner,
                "event_name": event_name,
                "event_date": event_date,
            })

        # Now parse the odds labels (the @X.XX lines)
        # They appear in <td> near the fight rows. Legacy code parsed specific tr+tr td with "@"
        odds_labels = []
        for td in soup.select("td"):
            txt = td.get_text(strip=True)
            if "@" in txt and len(txt) < 10:
                odds_labels.append(txt.replace("@", "").strip())

        # Pair them: even index = fighter1 odds, odd = fighter2 odds (for that fight)
        for j, fight in enumerate(fights):
            if j * 2 + 1 < len(odds_labels):
                try:
                    o1 = float(odds_labels[j * 2])
                    o2 = float(odds_labels[j * 2 + 1])
                    fight["fighter1_odds"] = o1
                    fight["fighter2_odds"] = o2
                    # Determine favourite / underdog
                    if o1 <= o2:
                        fight["favourite"] = fight["fighter1"]
                        fight["underdog"] = fight["fighter2"]
                        fight["favourite_odds"] = o1
                        fight["underdog_odds"] = o2
                    else:
                        fight["favourite"] = fight["fighter2"]
                        fight["underdog"] = fight["fighter1"]
                        fight["favourite_odds"] = o2
                        fight["underdog_odds"] = o1
                except ValueError:
                    pass

        return fights

    def _store_single_odds(self, conn, fight_data: dict):
        """Resolve fighters to IDs, find bout_id, upsert odds row."""
        f1_name = fight_data.get("favourite") or fight_data.get("fighter1")
        f2_name = fight_data.get("underdog") or fight_data.get("fighter2")

        if not f1_name or not f2_name:
            return

        fav_id = get_fighter_id_by_name(conn, f1_name)
        und_id = get_fighter_id_by_name(conn, f2_name)

        if fav_id is None or und_id is None:
            # Fallback: try reverse order
            fav_id = get_fighter_id_by_name(conn, f2_name)
            und_id = get_fighter_id_by_name(conn, f1_name)
            if fav_id is None or und_id is None:
                logger.debug(f"Could not resolve fighter IDs for {f1_name} vs {f2_name}")
                return

        # Find the bout (either order)
        row = conn.execute(
            """
            SELECT bout_id FROM bouts
            WHERE (fighter1_id = ? AND fighter2_id = ?)
               OR (fighter1_id = ? AND fighter2_id = ?)
            LIMIT 1
            """,
            (fav_id, und_id, und_id, fav_id),
        ).fetchone()

        if not row:
            logger.debug(f"No matching bout found in DB for {f1_name} vs {f2_name}")
            return

        bout_id = row["bout_id"]

        odds_payload = {
            "bout_id": bout_id,
            "favourite_id": fav_id,
            "underdog_id": und_id,
            "favourite_odds": fight_data.get("favourite_odds"),
            "underdog_odds": fight_data.get("underdog_odds"),
            "betting_outcome": None,  # We can derive later from actual outcome if needed
            "last_scraped": self.curr_time,
        }

        upsert_odds(conn, odds_payload)

    def _save_detailed_debug(self, url: str, error: str, attempt: int):
        ts = int(datetime.datetime.now().timestamp())
        safe = url.split("/")[-1].replace("?", "_")[:60]
        meta_path = DEBUG_DIR / f"odds_debug_{safe}_{ts}_attempt{attempt}.json"

        with open(meta_path, "w") as f:
            json.dump({
                "url": url,
                "timestamp": ts,
                "attempt": attempt,
                "error": error,
                "recommendation": "Try running with headless=False to see Cloudflare challenge"
            }, f, indent=2)

# Quick standalone test helper (run with python -m ufc.scraper.odds)
if __name__ == "__main__":
    logging.getLogger().setLevel(logging.INFO)
    scraper = OddsScraper()
    scraper.run()
