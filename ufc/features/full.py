"""
Full Features

Basic fighter attributes and simple derived comparisons.
Uses db helpers for DOB and win rate (computed from bouts).
"""

import logging
import os
import pandas as pd
import numpy as np

from ufc.config import DATA_DIR
from ufc.db import get_connection, get_fighter_dob, get_fighter_win_rate
from ufc.features.base import FeatureEngineer

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# queries
performance_query = """
    select
        fighter_id as fighter1_id,
        sig_strikes_landed_pm as fighter1_sig_strikes_landed_pm,
        sig_strikes_accuracy as fighter1_sig_strikes_accuracy,
        sig_strikes_absorbed_pm as fighter1_sig_strikes_absorbed_pm,
        sig_strikes_defended as fighter1_sig_strikes_defended,
        takedown_avg_per15m as fighter1_takedown_avg_per15m,
        takedown_accuracy as fighter1_takedown_accuracy,
        takedown_defence as fighter1_takedown_defence,
        submission_avg_attempted_per15m as fighter1_submission_avg_attempted_per15m
    from fighters
"""

recency_query = """
    select 
        a.event_id, 
        a.fighter1_id, 
        a.fighter2_id, 
        a.outcome, 
        b.event_date 
    from 
        bouts as a 
    inner join 
        events as b 
    on 
        a.event_id=b.event_id
"""

odds_query = """
    select
        bout_id,
        favourite_id
    from odds
"""

class FullFeatures(FeatureEngineer):
    """Full fighter attributes and simple comparisons."""

    def compute(self, df, conn=None):
        logger.info("Computing Full Features...")
        df = df.copy()

        df_performance = pd.read_sql_query( performance_query, conn )
        df_merged_left = df.merge( df_performance, on="fighter1_id", how="left" )
        df_performance.columns = [ i.replace( "fighter1", "fighter2" ) for i in df_performance.columns ]
        df_merged = df_merged_left.merge( df_performance, on="fighter2_id", how="left" )

        df_odds = pd.read_sql_query( odds_query, conn )
        df_merged = df.merged( df_odds, on="bout_id", how="left" )
        df_merged[ "fighter1_favourite" ] = df_merged[ "fighter1_id" ] == df_merged[ "favourite_id" ]
        df_merged[ "fighter2_favourite" ] = df_merged[ "fighter2_id" ] == df_merged[ "favourite_id" ]

        logger.info("Full Features computation complete.")
        return df_merged


if __name__ == "__main__":
    logger.info("Running FullFeatures standalone test...")
    input_filepath = DATA_DIR / "features_core.csv"
    if not os.path.exists( input_filepath ) :
        raise( f"{input_filepath} does not exist!  Run ufc.ml.core first" )
    output_filepath = DATA_DIR / "features_full.csv"
    df = pd.read_csv( input_filepath )
    full = FullFeatures()
    with get_connection() as conn:
        df_with_features = full.compute( df, conn=conn )
    df_with_features.to_csv( output_filepath, index=False )
