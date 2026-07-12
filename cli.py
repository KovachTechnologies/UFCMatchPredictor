"""Command-line interface for the UFC data pipeline"""

import argparse
from ufc.db import init_db
from ufc.scraper.fighters import FighterScraper
from ufc.scraper.events import EventScraper
from ufc.scraper.odds import OddsScraper


def main():
    parser = argparse.ArgumentParser(
        description="UFC Match Predictor Data Pipeline"
    )
    parser.add_argument(
        "--init-db", action="store_true",
        help="Initialize / update the SQLite schema"
    )
    parser.add_argument(
        "--fighters", action="store_true",
        help="Run fighter scraper"
    )
    parser.add_argument(
        "--events", action="store_true",
        help="Run event scraper (incremental)"
    )
    parser.add_argument(
        "--odds", action="store_true",
        help="Run odds scraper"
    )
    parser.add_argument(
        "--all", action="store_true",
        help="Run all scrapers in recommended order"
    )

    args = parser.parse_args()

    if args.init_db or args.all:
        print("Initializing database schema...")
        init_db()

    if args.fighters or args.all:
        print("\n=== Running Fighter Scraper ===")
        FighterScraper().run()

    if args.events or args.all:
        print("\n=== Running Event Scraper ===")
        EventScraper().run()

    if args.odds or args.all:
        print("\n=== Running Odds Scraper ===")
        OddsScraper().run()

    if not any([args.init_db, args.fighters, args.events, args.odds, args.all]):
        parser.print_help()


if __name__ == "__main__":
    main()
