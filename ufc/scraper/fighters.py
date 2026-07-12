"""Fighter Scraper - fetches individual fighter stats"""

import string
import datetime
from typing import Dict

import pandas as pd

from ufc.config import FIGHTER_INDEX_URL
from ufc.db import get_connection, upsert_fighter
from ufc.scraper.base import get_soup, sleep_randomly


class FighterScraper:
    """Scrape UFC fighter stats and store in SQLite"""

    def __init__(self):
        self.curr_time = datetime.datetime.now()

    def run(self):
        """Full pipeline: fetch all fighter URLs then scrape stats"""
        print("Starting Fighter Scraper...")

        print("→ Fetching individual fighter URLs from index pages...")
        fighter_urls = self._get_all_individual_fighter_urls()

        print(f"→ Found {len(fighter_urls)} fighter pages. Now scraping stats...")
        self._scrape_and_store_fighters(fighter_urls)

        print("✅ Fighter Scraper completed.")

    def _get_all_individual_fighter_urls(self) -> list:
        """Scrape all individual fighter profile URLs from A-Z index pages"""
        letters = list(string.ascii_lowercase)
        all_urls = []

        for letter in letters:
            url = FIGHTER_INDEX_URL.format(letter=letter)
            soup = get_soup(url)
            links = soup.find_all("a", class_="b-link b-link_style_black")
            for link in links:
                href = link.get("href")
                if href and href not in all_urls:
                    all_urls.append(href)
            sleep_randomly()

        return all_urls

    def _scrape_and_store_fighters(self, fighter_urls: list):
        """Scrape stats for each fighter and upsert into DB"""
        with get_connection() as conn:
            for i, url in enumerate(fighter_urls):
                try:
                    stats = self._get_single_fighter_stats(url)
                    upsert_fighter(conn, stats)
                    print(f"  [{i+1:4d}/{len(fighter_urls)}] {stats['name']} ✔️")
                except Exception as e:
                    print(f"  Error scraping {url}: {e}")
                sleep_randomly(1.0, 2.5)

    def _get_single_fighter_stats(self, fighter_url: str) -> Dict:
        """Parse a single fighter profile page"""
        def clean_text(s):
            return s.strip().replace("\n", "").replace(" ", "").replace('\\', '') if s else None

        soup = get_soup(fighter_url)

        # Basic info
        name = soup.find("span", class_="b-content__title-highlight").text.strip()
        fight_record = (
            soup.find("span", class_="b-content__title-record")
            .text.strip()
            .replace("Record: ", "")
        )
        nickname = soup.find("p", class_="b-content__Nickname").text.strip()

        # All other stats
        stats_list = soup.find_all("li", class_="b-list__box-list-item b-list__box-list-item_type_block")
        stats_dict = {}
        for item in stats_list:
            text = clean_text(item.text)
            if text and ":" in text:
                key, value = text.split(":", 1)
                stats_dict[key.strip()] = value.strip()

        # Convert to our schema format
        fighter_data = {
            "name": name,
            "nickname": nickname,
            "height_cm": self._parse_height(stats_dict.get("Height")),
            "reach_cm": self._parse_height(stats_dict.get("Reach")),
            "weight_kg": self._parse_weight(stats_dict.get("Weight")),
            "stance": stats_dict.get("STANCE"),
            "dob": stats_dict.get("DOB"),
            "sig_strikes_landed_pm": float(stats_dict.get("SLpM", 0)),
            "sig_strikes_accuracy": float(stats_dict.get("Str.Acc.", "0%").rstrip("%")) / 100,
            "sig_strikes_absorbed_pm": float(stats_dict.get("SApM", 0)),
            "sig_strikes_defended": float(stats_dict.get("Str.Def", "0%").rstrip("%")) / 100,
            "takedown_avg_per15m": float(stats_dict.get("TDAvg.", 0)),
            "takedown_accuracy": float(stats_dict.get("TDAcc.", "0%").rstrip("%")) / 100,
            "takedown_defence": float(stats_dict.get("TDDef.", "0%").rstrip("%")) / 100,
            "submission_avg_attempted_per15m": float(stats_dict.get("Sub.Avg.", 0)),
            "last_scraped": self.curr_time,
        }

        return fighter_data

    def _parse_height(self, height_str: str) -> float:
        """Convert e.g. '5' 10"' to cm"""
        if not height_str or height_str == "--":
            return None
        try:
            if "'" in height_str:
                feet, inches = map(int, height_str.replace('"', '').split("'"))
                return feet * 30.48 + inches * 2.54
            return float(height_str) * 2.54  # fallback
        except:
            return None

    def _parse_weight(self, weight_str: str) -> float:
        """Convert lbs to kg"""
        if not weight_str or weight_str == "--":
            return None
        try:
            lbs = float(weight_str.replace("lbs.", "").strip())
            return lbs * 0.453592
        except:
            return None
