"""Fighter Scraper - production version"""

import logging
import string
import datetime
from pathlib import Path
from typing import Dict, List, Optional

from ufc.config import FIGHTER_INDEX_URL, REQUEST_DELAY_RANGE, PROJECT_ROOT
from ufc.db import get_connection, upsert_fighter, update_scrape_metadata
from ufc.scraper.base import get_soup, sleep_randomly

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DEBUG_DIR = PROJECT_ROOT / "debug"
DEBUG_DIR.mkdir(exist_ok=True)

# Phrases commonly used by JS-challenge / anti-bot interstitials (Cloudflare
# and similar). If a page's visible text matches one of these, it's not that
# the site's structure changed - it's that we got a challenge shell instead
# of real content.
CHALLENGE_MARKERS = ("checking your browser", "requires javascript", "just a moment", "attention required")

MAX_DEBUG_SAVES = 3  # cap how many debug files we write per run, to avoid spamming 26 near-identical files


def _looks_like_challenge_page(soup) -> bool:
    text = soup.get_text(" ", strip=True).lower()
    return any(marker in text for marker in CHALLENGE_MARKERS) or len(text) < 200


class FighterScraper:
    def __init__(self):
        self.curr_time = datetime.datetime.now()
        self._debug_saves = 0

    def run(self):
        logger.info("Starting Fighter Scraper (full refresh)...")
        fighter_urls = self._get_all_individual_fighter_urls()

        if not fighter_urls:
            logger.error("No fighter URLs found at all - aborting before touching the DB. "
                         f"Check {DEBUG_DIR} for saved raw HTML from the failing pages - if it "
                         f"shows a 'checking your browser' / JS-challenge message, the site is "
                         f"blocking the scraper rather than having changed its page structure.")
            return

        logger.info(f"Found {len(fighter_urls)} fighter pages. Scraping...")

        succeeded = 0
        failed = 0
        with get_connection() as conn:
            for i, url in enumerate(fighter_urls):
                try:
                    stats = self._get_single_fighter_stats(url)
                    fighter_id = upsert_fighter(conn, stats)
                    succeeded += 1
                    if (i + 1) % 100 == 0 or i < 5:
                        logger.info(f"  [{i+1:5d}/{len(fighter_urls)}] {stats['name']} (id={fighter_id})")
                except Exception as e:
                    failed += 1
                    logger.error(f"Failed to process {url}: {e}")
                sleep_randomly(*REQUEST_DELAY_RANGE)

            update_scrape_metadata(conn, source="fighters", full=True)

        logger.info(f"✅ Fighter Scraper completed. {succeeded} succeeded, {failed} failed.")

    def _get_all_individual_fighter_urls(self) -> List[str]:
        letters = list(string.ascii_lowercase)
        all_urls: List[str] = []
        failed_letters: List[str] = []

        for letter in letters:
            url = FIGHTER_INDEX_URL.format(letter=letter)
            try:
                soup = get_soup(url, wait_selector="a[href*='fighter-details']")
                links = soup.find_all("a", href=True)
                found_this_letter = 0
                for link in links:
                    href = link.get("href", "")
                    if "/fighter-details/" in href:
                        full_url = "http://ufcstats.com" + href if not href.startswith("http") else href
                        if full_url not in all_urls:
                            all_urls.append(full_url)
                            found_this_letter += 1

                if found_this_letter == 0:
                    if _looks_like_challenge_page(soup):
                        logger.error(
                            f"Letter '{letter}' returned what looks like a JS challenge / "
                            f"anti-bot interstitial, not real content - this is not a page "
                            f"structure change."
                        )
                    else:
                        logger.warning(f"No fighter links found for letter '{letter}' - page may have changed")

                    if self._debug_saves < MAX_DEBUG_SAVES:
                        debug_path = DEBUG_DIR / f"fighters_index_failure_{letter}.html"
                        with open(debug_path, "w", encoding="utf-8") as f:
                            f.write(str(soup))
                        self._debug_saves += 1
                        logger.info(f"Saved raw page HTML to {debug_path}")

            except Exception as e:
                logger.warning(f"Could not scrape index for letter '{letter}': {e}")
                failed_letters.append(letter)
            sleep_randomly(*REQUEST_DELAY_RANGE)

        if failed_letters:
            logger.error(f"Failed to fetch index pages for letters: {failed_letters}")

        return list(dict.fromkeys(all_urls))

    def _get_single_fighter_stats(self, fighter_url: str) -> Dict:
        def clean_text(s):
            return s.strip().replace("\n", "").replace(" ", "").replace('\\', '') if s else None

        soup = get_soup(fighter_url, wait_selector="span.b-content__title-highlight")

        name_el = soup.find("span", class_="b-content__title-highlight")
        if not name_el:
            raise ValueError(f"Could not find fighter name on page: {fighter_url}")
        name = name_el.text.strip()

        record_el = soup.find("span", class_="b-content__title-record")
        fight_record = record_el.text.strip().replace("Record: ", "") if record_el else None

        nickname_el = soup.find("p", class_="b-content__Nickname")
        nickname = nickname_el.text.strip() if nickname_el else None

        stats_list = soup.find_all("li", class_="b-list__box-list-item b-list__box-list-item_type_block")
        stats_dict = {}
        for item in stats_list:
            text = clean_text(item.text)
            if text and ":" in text:
                key, value = text.split(":", 1)
                stats_dict[key.strip()] = value.strip()

        return {
            "name": name,
            "nickname": nickname,
            "height_cm": self._parse_height(stats_dict.get("Height")),
            "reach_cm": self._parse_height(stats_dict.get("Reach")),
            "weight_kg": self._parse_weight(stats_dict.get("Weight")),
            "stance": stats_dict.get("STANCE"),
            "dob": stats_dict.get("DOB"),
            "sig_strikes_landed_pm": self._safe_float(stats_dict.get("SLpM")),
            "sig_strikes_accuracy": self._safe_pct(stats_dict.get("Str.Acc.")),
            "sig_strikes_absorbed_pm": self._safe_float(stats_dict.get("SApM")),
            "sig_strikes_defended": self._safe_pct(stats_dict.get("Str.Def")),
            "takedown_avg_per15m": self._safe_float(stats_dict.get("TDAvg.")),
            "takedown_accuracy": self._safe_pct(stats_dict.get("TDAcc.")),
            "takedown_defence": self._safe_pct(stats_dict.get("TDDef.")),
            "submission_avg_attempted_per15m": self._safe_float(stats_dict.get("Sub.Avg.")),
            "source_url": fighter_url,
            "last_scraped": self.curr_time,
        }

    def _safe_float(self, value: Optional[str]) -> float:
        """Parse a numeric stat, tolerating '--', empty strings, and other
        placeholder values ufcstats.com uses for unknown data."""
        if not value or value in ("--", "-"):
            return 0.0
        try:
            return float(value)
        except (ValueError, TypeError):
            logger.warning(f"Could not parse numeric value: {value!r}")
            return 0.0

    def _safe_pct(self, value: Optional[str]) -> float:
        """Parse a percentage stat like '54%' -> 0.54, tolerating missing/bad data."""
        if not value or value in ("--", "-"):
            return 0.0
        try:
            return float(value.rstrip("%")) / 100
        except (ValueError, TypeError):
            logger.warning(f"Could not parse percentage value: {value!r}")
            return 0.0

    def _parse_height(self, height_str: Optional[str]):
        if not height_str or height_str == "--":
            return None
        try:
            if "'" in height_str:
                feet, inches = map(int, height_str.replace('"', '').split("'"))
                return feet * 30.48 + inches * 2.54
            return float(height_str.replace('"', '')) * 2.54
        except Exception:
            return None

    def _parse_weight(self, weight_str: Optional[str]):
        if not weight_str or weight_str == "--":
            return None
        try:
            lbs = float(weight_str.replace("lbs.", "").strip())
            return lbs * 0.453592
        except Exception:
            return None
