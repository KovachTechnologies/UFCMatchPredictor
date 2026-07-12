"""Fighter Scraper - production version"""

import logging
import string
import datetime
from typing import Dict, List

from ufc.config import FIGHTER_INDEX_URL
from ufc.db import get_connection, upsert_fighter
from ufc.scraper.base import get_soup, sleep_randomly

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class FighterScraper:
    def __init__(self):
        self.curr_time = datetime.datetime.now()

    def run(self):
        logger.info("Starting Fighter Scraper (full refresh)...")
        fighter_urls = self._get_all_individual_fighter_urls()
        logger.info(f"Found {len(fighter_urls)} fighter pages. Scraping...")

        with get_connection() as conn:
            for i, url in enumerate(fighter_urls):
                try:
                    stats = self._get_single_fighter_stats(url)
                    fighter_id = upsert_fighter(conn, stats)
                    if (i + 1) % 100 == 0 or i < 5:
                        logger.info(f"  [{i+1:5d}/{len(fighter_urls)}] {stats['name']} (id={fighter_id})")
                except Exception as e:
                    logger.error(f"Failed to process {url}: {e}")
                sleep_randomly()

        logger.info("✅ Fighter Scraper completed.")

    def _get_all_individual_fighter_urls(self) -> List[str]:
        letters = list(string.ascii_lowercase)
        all_urls: List[str] = []

        for letter in letters:
            url = FIGHTER_INDEX_URL.format(letter=letter)
            try:
                soup = get_soup(url)
                links = soup.find_all("a", href=True)
                for link in links:
                    href = link.get("href", "")
                    if "/fighter-details/" in href:
                        full_url = "http://ufcstats.com" + href if not href.startswith("http") else href
                        if full_url not in all_urls:
                            all_urls.append(full_url)
            except Exception as e:
                logger.warning(f"Could not scrape index for letter '{letter}': {e}")
            sleep_randomly(1.0, 2.0)

        return list(dict.fromkeys(all_urls))

    def _get_single_fighter_stats(self, fighter_url: str) -> Dict:
        def clean_text(s):
            return s.strip().replace("\n", "").replace(" ", "").replace('\\', '') if s else None

        soup = get_soup(fighter_url)

        name = soup.find("span", class_="b-content__title-highlight").text.strip()
        fight_record = soup.find("span", class_="b-content__title-record").text.strip().replace("Record: ", "")
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
            "sig_strikes_landed_pm": float(stats_dict.get("SLpM", 0) or 0),
            "sig_strikes_accuracy": float(stats_dict.get("Str.Acc.", "0%").rstrip("%")) / 100 if stats_dict.get("Str.Acc.") else 0.0,
            "sig_strikes_absorbed_pm": float(stats_dict.get("SApM", 0) or 0),
            "sig_strikes_defended": float(stats_dict.get("Str.Def", "0%").rstrip("%")) / 100 if stats_dict.get("Str.Def") else 0.0,
            "takedown_avg_per15m": float(stats_dict.get("TDAvg.", 0) or 0),
            "takedown_accuracy": float(stats_dict.get("TDAcc.", "0%").rstrip("%")) / 100 if stats_dict.get("TDAcc.") else 0.0,
            "takedown_defence": float(stats_dict.get("TDDef.", "0%").rstrip("%")) / 100 if stats_dict.get("TDDef.") else 0.0,
            "submission_avg_attempted_per15m": float(stats_dict.get("Sub.Avg.", 0) or 0),
            "last_scraped": self.curr_time,
        }

    def _parse_height(self, height_str: str):
        if not height_str or height_str == "--":
            return None
        try:
            if "'" in height_str:
                feet, inches = map(int, height_str.replace('"', '').split("'"))
                return feet * 30.48 + inches * 2.54
            return float(height_str) * 2.54
        except Exception:
            return None

    def _parse_weight(self, weight_str: str):
        if not weight_str or weight_str == "--":
            return None
        try:
            lbs = float(weight_str.replace("lbs.", "").strip())
            return lbs * 0.453592
        except Exception:
            return None
