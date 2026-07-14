"""SQLite database layer - schema creation and common helpers

SCHEMA CHANGES vs. previous version:
  - fighters: added `source_url` (fighter profile URL) for reliable joining
    from events/bouts instead of fragile name matching.
  - events:   added `source_url` (event page URL) for traceability.
  - bouts:    added `fighter1_name` / `fighter2_name` raw-text audit columns
              (kept even when ID resolution succeeds/fails, for debugging).
  - odds:     added UNIQUE(bout_id) so odds can be upserted (latest line per
              bout) instead of accumulating duplicate rows.

MIGRATING AN EXISTING DB:
  New columns (source_url, fighter1_name, fighter2_name) can be added to an
  existing data/ufc.db via `migrate_db()` below (idempotent, safe to re-run).
  The new UNIQUE(bout_id) constraint on `odds` CANNOT be added via ALTER TABLE
  in SQLite. Since this is still early-stage data, the simplest path is to
  delete data/ufc.db* and let `init_db()` recreate everything from scratch.
  If you need to preserve existing odds data, recreate the table manually
  (CREATE new table with the constraint, copy rows, drop old, rename) -
  ask if you want that migration written out.
"""

import sqlite3
import datetime
import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

from ufc.config import DB_PATH

logger = logging.getLogger(__name__)


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
                source_url TEXT,
                last_scraped TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(name, dob)
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_fighters_source_url ON fighters(source_url)")

        # Events
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_name TEXT NOT NULL,
                event_date TEXT NOT NULL,
                event_location TEXT,
                source_url TEXT,
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
                fighter1_name TEXT,
                fighter2_name TEXT,
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
                FOREIGN KEY(underdog_id) REFERENCES fighters(fighter_id),
                UNIQUE(bout_id)
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


def migrate_db():
    """Best-effort, idempotent migration for existing databases.

    Adds new columns that ALTER TABLE can handle. Does NOT add the new
    UNIQUE(bout_id) constraint on `odds` - see module docstring.
    """
    statements = [
        "ALTER TABLE fighters ADD COLUMN source_url TEXT",
        "ALTER TABLE events ADD COLUMN source_url TEXT",
        "ALTER TABLE bouts ADD COLUMN fighter1_name TEXT",
        "ALTER TABLE bouts ADD COLUMN fighter2_name TEXT",
    ]
    with get_connection() as conn:
        for stmt in statements:
            try:
                conn.execute(stmt)
                logger.info(f"Migration applied: {stmt}")
            except sqlite3.OperationalError as e:
                if "duplicate column name" in str(e).lower():
                    logger.debug(f"Migration already applied, skipping: {stmt}")
                else:
                    raise
        conn.execute("CREATE INDEX IF NOT EXISTS idx_fighters_source_url ON fighters(source_url)")
        conn.commit()
    print("✅ Migration complete (odds.UNIQUE(bout_id) still requires a manual rebuild - see db.py docstring).")


# ---------------------------------------------------------------------------
# Fighters
# ---------------------------------------------------------------------------

def upsert_fighter(conn, fighter_data: dict) -> int:
    """Insert or update a fighter. Returns fighter_id reliably (not lastrowid,
    which is not updated by SQLite when the ON CONFLICT UPDATE path fires)."""
    conn.execute("""
        INSERT INTO fighters (
            name, nickname, height_cm, reach_cm, weight_kg, stance, dob,
            sig_strikes_landed_pm, sig_strikes_accuracy, sig_strikes_absorbed_pm,
            sig_strikes_defended, takedown_avg_per15m, takedown_accuracy,
            takedown_defence, submission_avg_attempted_per15m, source_url, last_scraped
        ) VALUES (
            :name, :nickname, :height_cm, :reach_cm, :weight_kg, :stance, :dob,
            :sig_strikes_landed_pm, :sig_strikes_accuracy, :sig_strikes_absorbed_pm,
            :sig_strikes_defended, :takedown_avg_per15m, :takedown_accuracy,
            :takedown_defence, :submission_avg_attempted_per15m, :source_url, :last_scraped
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
            source_url = excluded.source_url,
            last_scraped = excluded.last_scraped
    """, fighter_data)
    conn.commit()

    row = conn.execute(
        "SELECT fighter_id FROM fighters WHERE name = ? AND dob IS ?",
        (fighter_data["name"], fighter_data.get("dob")),
    ).fetchone()
    return row["fighter_id"] if row else None


def get_fighter_id_by_url(conn, source_url: str) -> Optional[int]:
    """Resolve a fighter_id from a fighter profile URL. This is the preferred
    join key for bouts/odds since fighter names are not reliably unique or
    reliably parseable from event pages."""
    if not source_url:
        return None
    row = conn.execute(
        "SELECT fighter_id FROM fighters WHERE source_url = ? LIMIT 1", (source_url,)
    ).fetchone()
    return row["fighter_id"] if row else None


def get_fighter_id_by_name(conn, name: str) -> Optional[int]:
    """Fallback lookup by name only, for cases where no URL is available.
    Logs a warning if the name matches more than one fighter, since name
    alone is not guaranteed unique (the fighters table's real key is
    name+dob)."""
    if not name:
        return None
    rows = conn.execute(
        "SELECT fighter_id FROM fighters WHERE name = ? LIMIT 2", (name,)
    ).fetchall()
    if not rows:
        return None
    if len(rows) > 1:
        logger.warning(f"Ambiguous fighter name match for '{name}' - using first result")
    return rows[0]["fighter_id"]


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

def upsert_event(conn, event_data: dict) -> int:
    """Insert or update an event. Returns event_id."""
    conn.execute("""
        INSERT INTO events (event_name, event_date, event_location, source_url, last_scraped)
        VALUES (:event_name, :event_date, :event_location, :source_url, :last_scraped)
        ON CONFLICT(event_name, event_date) DO UPDATE SET
            event_location = excluded.event_location,
            source_url = excluded.source_url,
            last_scraped = excluded.last_scraped
    """, event_data)
    conn.commit()

    row = conn.execute(
        "SELECT event_id FROM events WHERE event_name = ? AND event_date = ?",
        (event_data["event_name"], event_data["event_date"]),
    ).fetchone()
    return row["event_id"] if row else None


# ---------------------------------------------------------------------------
# Bouts
# ---------------------------------------------------------------------------

def upsert_bout(conn, bout_data: dict) -> int:
    """Insert or update a bout. Returns bout_id.

    Expects fighter1_id / fighter2_id to already be resolved (may be None if
    the fighter couldn't be matched - fighter1_name/fighter2_name are stored
    regardless, as an audit trail for later reconciliation).

    NOTE: because SQLite treats NULL as distinct from every other NULL in a
    UNIQUE constraint, two bouts that both fail to resolve fighter IDs will
    NOT be recognized as duplicates and will insert separately on repeat
    scrapes. This is a known limitation until every fighter has been scraped
    at least once (run fighters.py before events.py, or re-run events.py
    after a fighter backfill).
    """
    conn.execute("""
        INSERT INTO bouts (
            event_id, fighter1_id, fighter2_id, fighter1_name, fighter2_name,
            weight_class, outcome, method, round, time, last_scraped
        ) VALUES (
            :event_id, :fighter1_id, :fighter2_id, :fighter1_name, :fighter2_name,
            :weight_class, :outcome, :method, :round, :time, :last_scraped
        )
        ON CONFLICT(event_id, fighter1_id, fighter2_id) DO UPDATE SET
            fighter1_name = excluded.fighter1_name,
            fighter2_name = excluded.fighter2_name,
            weight_class = excluded.weight_class,
            outcome = excluded.outcome,
            method = excluded.method,
            round = excluded.round,
            time = excluded.time,
            last_scraped = excluded.last_scraped
    """, bout_data)
    conn.commit()

    row = conn.execute(
        """SELECT bout_id FROM bouts
           WHERE event_id = ? AND fighter1_id IS ? AND fighter2_id IS ?
           ORDER BY bout_id DESC LIMIT 1""",
        (bout_data["event_id"], bout_data.get("fighter1_id"), bout_data.get("fighter2_id")),
    ).fetchone()
    return row["bout_id"] if row else None


# ---------------------------------------------------------------------------
# Odds
# ---------------------------------------------------------------------------

def upsert_odds(conn, odds_data: dict) -> int:
    """Insert or update odds for a bout (one row per bout - latest line
    wins). Returns odds_id."""
    conn.execute("""
        INSERT INTO odds (
            bout_id, favourite_id, underdog_id, favourite_odds, underdog_odds,
            betting_outcome, last_scraped
        ) VALUES (
            :bout_id, :favourite_id, :underdog_id, :favourite_odds, :underdog_odds,
            :betting_outcome, :last_scraped
        )
        ON CONFLICT(bout_id) DO UPDATE SET
            favourite_id = excluded.favourite_id,
            underdog_id = excluded.underdog_id,
            favourite_odds = excluded.favourite_odds,
            underdog_odds = excluded.underdog_odds,
            betting_outcome = excluded.betting_outcome,
            last_scraped = excluded.last_scraped
    """, odds_data)
    conn.commit()

    row = conn.execute(
        "SELECT odds_id FROM odds WHERE bout_id = ?", (odds_data["bout_id"],)
    ).fetchone()
    return row["odds_id"] if row else None


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

def update_scrape_metadata(conn, source: str, full: bool):
    """Record when a scraper last ran. `source` should be one of
    'fighters', 'events', 'odds'."""
    now = datetime.datetime.now()
    if full:
        conn.execute("""
            INSERT INTO scrape_metadata (source, last_full_scrape, last_incremental_scrape)
            VALUES (:source, :ts, :ts)
            ON CONFLICT(source) DO UPDATE SET
                last_full_scrape = excluded.last_full_scrape,
                last_incremental_scrape = excluded.last_incremental_scrape
        """, {"source": source, "ts": now})
    else:
        conn.execute("""
            INSERT INTO scrape_metadata (source, last_full_scrape, last_incremental_scrape)
            VALUES (:source, NULL, :ts)
            ON CONFLICT(source) DO UPDATE SET
                last_incremental_scrape = excluded.last_incremental_scrape
        """, {"source": source, "ts": now})
    conn.commit()


def get_fighter_dob(conn, fighter_id: int) -> Optional[str]:
    """Return DOB for a fighter (or None)."""
    row = conn.execute(
        "SELECT dob FROM fighters WHERE fighter_id = ?", (fighter_id,)
    ).fetchone()
    dob = row["dob"] if row else None
    if not dob:
        logger.debug(f"No DOB found for fighter_id {fighter_id}")
    return dob


def get_fighter_win_rate(conn, fighter_id: int) -> dict:
    """
    Calculate win rate for a fighter. More robust outcome matching.
    """
    if fighter_id is None:
        return {"wins": 0, "losses": 0, "draws": 0, "nc": 0, "total": 0, "win_rate": None}

    query = """
        SELECT 
            SUM(CASE WHEN outcome IN ('fighter1', 'Fighter1', '1') THEN 1 ELSE 0 END) as wins_f1,
            SUM(CASE WHEN outcome IN ('fighter2', 'Fighter2', '2') THEN 1 ELSE 0 END) as losses_f1,
            SUM(CASE WHEN outcome IN ('Draw', 'draw', 'DRAW') THEN 1 ELSE 0 END) as draws_f1,
            SUM(CASE WHEN outcome IN ('No Contest', 'NC', 'no contest', 'No contest') THEN 1 ELSE 0 END) as nc_f1
        FROM bouts 
        WHERE fighter1_id = ?
    """
    row1 = conn.execute(query, (fighter_id,)).fetchone()

    query2 = """
        SELECT 
            SUM(CASE WHEN outcome IN ('fighter2', 'Fighter2', '2') THEN 1 ELSE 0 END) as wins_f2,
            SUM(CASE WHEN outcome IN ('fighter1', 'Fighter1', '1') THEN 1 ELSE 0 END) as losses_f2,
            SUM(CASE WHEN outcome IN ('Draw', 'draw', 'DRAW') THEN 1 ELSE 0 END) as draws_f2,
            SUM(CASE WHEN outcome IN ('No Contest', 'NC', 'no contest', 'No contest') THEN 1 ELSE 0 END) as nc_f2
        FROM bouts 
        WHERE fighter2_id = ?
    """
    row2 = conn.execute(query2, (fighter_id,)).fetchone()

    wins = (row1["wins_f1"] or 0) + (row2["wins_f2"] or 0)
    losses = (row1["losses_f1"] or 0) + (row2["losses_f2"] or 0)
    draws = (row1["draws_f1"] or 0) + (row2["draws_f2"] or 0)
    nc = (row1["nc_f1"] or 0) + (row2["nc_f2"] or 0)

    total = wins + losses + draws + nc
    win_rate = round(wins / total, 4) if total > 0 else None

    if total == 0:
        logger.debug(f"Fighter {fighter_id} has no recorded bouts → win_rate=None")

    return {
        "wins": wins,
        "losses": losses,
        "draws": draws,
        "nc": nc,
        "total": total,
        "win_rate": win_rate
    }
