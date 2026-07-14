"""
Core Features

Basic fighter attributes and simple derived comparisons.
Uses db helpers for DOB and win rate (computed from bouts).
"""

import logging
from typing import List, Optional
import pandas as pd
import numpy as np

from ufc.config import DATA_DIR
from ufc.db import get_connection, get_fighter_dob, get_fighter_win_rate
from ufc.features.base import FeatureEngineer

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class CoreFeatures(FeatureEngineer):
    """Core / basic fighter attributes and simple comparisons."""

    def compute(self, df: pd.DataFrame, conn=None) -> pd.DataFrame:
        logger.info("Computing Core Features...")

        df = df.copy()

        fighter_format_string = "%b%d,%Y"
        event_format_string = "%Y-%m-%d"
        if "fighter1_dob" in df.columns :
            df['fighter1_dob'] = pd.to_datetime(df['fighter1_dob'], format=fighter_format_string, errors="coerce")
        if "fighter2_dob" in df.columns :
            df['fighter2_dob'] = pd.to_datetime(df['fighter2_dob'], format=fighter_format_string, errors="coerce")
        if "event_date" in df.columns :
            df['event_date'] = pd.to_datetime(df['event_date'], format=event_format_string, errors="coerce")

        # --- Robust datetime handling ---
        for col in ["event_date", "fighter1_dob", "fighter2_dob"]:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors="coerce", format="mixed")

        # --- Age ---
        if "event_date" in df.columns:
            if "fighter1_dob" in df.columns:
                df["fighter1_age"] = df["event_date"].dt.year - df["fighter1_dob"].dt.year
            if "fighter2_dob" in df.columns:
                df["fighter2_age"] = df["event_date"].dt.year - df["fighter2_dob"].dt.year
            if "fighter1_age" in df.columns and "fighter2_age" in df.columns:
                df["delta_age"] = df["fighter1_age"] - df["fighter2_age"]

        # --- Height & Reach deltas ---
        if "fighter1_height" in df.columns and "fighter2_height" in df.columns:
            df["delta_height"] = df["fighter1_height"] - df["fighter2_height"]
            df["ratio_height"] = df["fighter1_height"] / df["fighter2_height"].replace(0, np.nan)

        if "fighter1_reach" in df.columns and "fighter2_reach" in df.columns:
            df["delta_reach"] = df["fighter1_reach"] - df["fighter2_reach"]
            df["ratio_reach"] = df["fighter1_reach"] / df["fighter2_reach"].replace(0, np.nan)

        # --- Stance ---
        if "fighter1_stance" in df.columns and "fighter2_stance" in df.columns:
            for stance in ["Orthodox", "Southpaw", "Switch"]:
                df[f"fighter1_stance_{stance}"] = (df["fighter1_stance"] == stance).astype(int)
                df[f"fighter2_stance_{stance}"] = (df["fighter2_stance"] == stance).astype(int)
            df["same_stance"] = (df["fighter1_stance"] == df["fighter2_stance"]).astype(int)

        # --- Weight class ---
        if "weight_class" in df.columns:
            df["weight_class"] = df["weight_class"].astype("category")

        # --- Win rate (computed via db helper) ---
        if conn is not None:
            for fighter_prefix, id_col in [("fighter1", "fighter1_id"), ("fighter2", "fighter2_id")]:
                if id_col in df.columns:
                    win_rates = []
                    missing_count = 0
                    for fid in df[id_col]:
                        record = get_fighter_win_rate(conn, fid)
                        win_rates.append(record.get("win_rate"))
                        if record.get("win_rate") is None:
                            missing_count += 1
                    df[f"{fighter_prefix}_win_rate"] = win_rates
                    logger.info(f"{fighter_prefix} win_rate: {missing_count}/{len(df)} rows have NaN")

        logger.info("Core Features computation complete.")
        return df

    @property
    def feature_names(self) -> List[str]:
        return [
            "fighter1_age", "fighter2_age", "delta_age",
            "delta_height", "ratio_height",
            "delta_reach", "ratio_reach",
            "fighter1_stance_Orthodox", "fighter1_stance_Southpaw", "fighter1_stance_Switch",
            "fighter2_stance_Orthodox", "fighter2_stance_Southpaw", "fighter2_stance_Switch",
            "same_stance",
            "fighter1_win_rate", "fighter2_win_rate",
        ]


if __name__ == "__main__":
    logger.info("Running CoreFeatures standalone test...")

    output_path = DATA_DIR / "features_core.csv"

    with get_connection() as conn:
        # Load base bout + event data
        query = """
            SELECT 
                b.bout_id, b.event_id, b.fighter1_id, b.fighter2_id, b.weight_class,
                b.outcome, b.method, b.round, b.time,
                e.event_name, e.event_date,
                f1.name as fighter1_name, f1.height_cm as fighter1_height,
                f1.reach_cm as fighter1_reach, f1.stance as fighter1_stance,
                f2.name as fighter2_name, f2.height_cm as fighter2_height,
                f2.reach_cm as fighter2_reach, f2.stance as fighter2_stance
            FROM bouts b
            JOIN events e ON b.event_id = e.event_id
            LEFT JOIN fighters f1 ON b.fighter1_id = f1.fighter_id
            LEFT JOIN fighters f2 ON b.fighter2_id = f2.fighter_id
        """
        df = pd.read_sql(query, conn)

        # Enrich with DOBs (from fighters table)
        df["fighter1_dob"] = df["fighter1_id"].apply(lambda x: get_fighter_dob(conn, x))
        df["fighter2_dob"] = df["fighter2_id"].apply(lambda x: get_fighter_dob(conn, x))

        df.to_csv( "debug.csv" )

        core = CoreFeatures()
        df_with_features = core.compute(df, conn=conn)

    print("\n=== Core Features Head ===")
    print(df_with_features[core.feature_names].head(10).to_string())

    df_with_features.to_csv(output_path, index=False)
    logger.info(f"Saved full feature dataframe → {output_path}")
    logger.info(f"Total columns: {df_with_features.shape[1]}")
