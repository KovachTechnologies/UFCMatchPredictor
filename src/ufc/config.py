"""Central configuration for URLs, paths, and constants"""

from pathlib import Path

# Project root
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "ufc.db"

# Ensure data dir exists
DATA_DIR.mkdir(exist_ok=True)

# Scraping targets
UFCSTATS_BASE = "http://ufcstats.com"
EVENTS_COMPLETED_URL = f"{UFCSTATS_BASE}/statistics/events/completed?page=all"
FIGHTER_INDEX_URL = f"{UFCSTATS_BASE}/statistics/fighters?char={{letter}}&page=all"

BETMMA_ODDS_URL = "https://www.betmma.tips/past_mma_handicapper_performance_all.php?Org=1"

# Scraping politeness
REQUEST_DELAY_RANGE = (1.5, 3.5)  # seconds
USER_AGENT = "UFC-Predictor-Research/0.1 (academic use; respectful scraper)"

# Weight classes (for later validation)
WEIGHT_CLASSES = [
    "Women's Strawweight", "Women's Flyweight", "Women's Bantamweight",
    "Women's Featherweight", "Flyweight", "Bantamweight", "Featherweight",
    "Lightweight", "Welterweight", "Middleweight", "Light Heavyweight",
    "Heavyweight", "Catch Weight", "Open Weight",
]
