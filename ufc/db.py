"""SQLite database layer - schema creation and common helpers"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from ufc.config import DB_PATH


@contextmanager
def get_connection(db_path: Path = DB_PATH):
    """Context manager for SQLite connection with sensible defaults."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    """Create all tables if they do not exist. Idempotent."""
    with get_connection() as conn:
        cursor = conn.cursor()

        # Fighters
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS fighters (
                fighter_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                nickname TEXT,
                height_cm REAL,
                reach_cm REAL,
                weight_kg REAL,
                stance TEXT,
                dob TEXT,
                sig_strikes_landed_pm REAL,
                sig_strikes_accuracy REAL,
                sig_strikes_absorbed_pm REAL,
                sig_strikes_defended REAL,
                takedown_avg_per15m REAL,
                takedown_accuracy REAL,
                takedown_defence REAL,
                submission_avg_attempted_per15m REAL,
                last_scraped TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(name, dob)
            )
        """)

        # Events
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_name TEXT NOT NULL,
                event_date TEXT NOT NULL,
                event_location TEXT,
                last_scraped TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(event_name, event_date)
            )
        """)

        # Bouts
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bouts (
                bout_id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id INTEGER NOT NULL,
                fighter1_id INTEGER,
                fighter2_id INTEGER,
                weight_class TEXT,
                outcome TEXT,
                method TEXT,
                round INTEGER,
                time TEXT,
                last_scraped TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(event_id) REFERENCES events(event_id),
                FOREIGN KEY(fighter1_id) REFERENCES fighters(fighter_id),
                FOREIGN KEY(fighter2_id) REFERENCES fighters(fighter_id),
                UNIQUE(event_id, fighter1_id, fighter2_id)
            )
        """)

        # Odds
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS odds (
                odds_id INTEGER PRIMARY KEY AUTOINCREMENT,
                bout_id INTEGER NOT NULL,
                favourite_id INTEGER,
                underdog_id INTEGER,
                favourite_odds REAL,
                underdog_odds REAL,
                betting_outcome TEXT,
                last_scraped TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(bout_id) REFERENCES bouts(bout_id),
                FOREIGN KEY(favourite_id) REFERENCES fighters(fighter_id),
                FOREIGN KEY(underdog_id) REFERENCES fighters(fighter_id)
            )
        """)

        # Metadata
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS scrape_metadata (
                source TEXT PRIMARY KEY,
                last_full_scrape TIMESTAMP,
                last_incremental_scrape TIMESTAMP
            )
        """)

        print("✅ Database schema initialized.")


def upsert_fighter(conn, fighter_data: dict):
    """Insert or update a fighter. Returns fighter_id."""
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO fighters (
            name, nickname, height_cm, reach_cm, weight_kg, stance, dob,
            sig_strikes_landed_pm, sig_strikes_accuracy, sig_strikes_absorbed_pm,
            sig_strikes_defended, takedown_avg_per15m, takedown_accuracy,
            takedown_defence, submission_avg_attempted_per15m, last_scraped
        ) VALUES (
            :name, :nickname, :height_cm, :reach_cm, :weight_kg, :stance, :dob,
            :sig_strikes_landed_pm, :sig_strikes_accuracy, :sig_strikes_absorbed_pm,
            :sig_strikes_defended, :takedown_avg_per15m, :takedown_accuracy,
            :takedown_defence, :submission_avg_attempted_per15m, :last_scraped
        )
        ON CONFLICT(name, dob) DO UPDATE SET
            nickname = excluded.nickname,
            height_cm = excluded.height_cm,
            reach_cm = excluded.reach_cm,
            weight_kg = excluded.weight_kg,
            stance = excluded.stance,
            sig_strikes_landed_pm = excluded.sig_strikes_landed_pm,
            sig_strikes_accuracy = excluded.sig_strikes_accuracy,
            sig_strikes_absorbed_pm = excluded.sig_strikes_absorbed_pm,
            sig_strikes_defended = excluded.sig_strikes_defended,
            takedown_avg_per15m = excluded.takedown_avg_per15m,
            takedown_accuracy = excluded.takedown_accuracy,
            takedown_defence = excluded.takedown_defence,
            submission_avg_attempted_per15m = excluded.submission_avg_attempted_per15m,
            last_scraped = excluded.last_scraped
    """, fighter_data)
    conn.commit()
    return cursor.lastrowid
