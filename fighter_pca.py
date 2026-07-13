"""PCA visualization of fighter statistics.

Standalone script (not part of the scraper pipeline). Reads all fighters
from data/ufc.db, standardizes their physical/performance attributes,
projects them into two principal components, clusters that projection with
KMeans, and saves/shows a scatter plot.

Usage:
    python pca_fighters.py
    python pca_fighters.py --clusters 5
    python pca_fighters.py --include-inactive --output data/all_fighters_pca.png
"""

import argparse
import logging
import sqlite3
from pathlib import Path
from typing import Tuple

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score

from ufc.config import DB_PATH, PROJECT_ROOT

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Physical + performance columns to feed into PCA. Deliberately excludes
# fighter_id/name/nickname/stance/dob/source_url/last_scraped - identifiers
# and metadata, not measurements.
FEATURE_COLUMNS = [
    "height_cm", "reach_cm", "weight_kg",
    "sig_strikes_landed_pm", "sig_strikes_accuracy", "sig_strikes_absorbed_pm",
    "sig_strikes_defended", "takedown_avg_per15m", "takedown_accuracy",
    "takedown_defence", "submission_avg_attempted_per15m",
]

# Columns where a scraped 0.0 usually means "no fight data yet" rather than
# a genuine zero - used to filter out inactive fighters by default.
ACTIVITY_COLUMNS = [c for c in FEATURE_COLUMNS if c not in ("height_cm", "reach_cm", "weight_kg")]


def load_fighters(db_path: Path) -> pd.DataFrame:
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found at {db_path}. Run the scrapers first.")
    with sqlite3.connect(db_path) as conn:
        df = pd.read_sql_query("SELECT * FROM fighters", conn)
    logger.info(f"Loaded {len(df)} fighters from {db_path}")
    return df


def preprocess(df: pd.DataFrame, drop_inactive: bool = True) -> pd.DataFrame:
    """Clean and prepare fighter data for PCA.

    - Drops fighters missing core physical measurements (height/reach/weight
      can't be meaningfully imputed - a missing value there usually means the
      scraper couldn't parse that fighter's page, not that the fighter has no
      body).
    - By default, drops fighters with zero recorded activity across every
      striking/grappling stat, since a scraped 0.0 there means "no fight
      data yet," not a genuine zero - leaving them in would falsely cluster
      every rookie at the origin regardless of their actual style.
    - Median-imputes any remaining sparse gaps in the performance stats.
    """
    before = len(df)
    df = df.dropna(subset=["height_cm", "reach_cm", "weight_kg"]).copy()
    logger.info(f"Dropped {before - len(df)} fighters missing height/reach/weight")

    if drop_inactive:
        before = len(df)
        df = df[(df[ACTIVITY_COLUMNS].fillna(0) != 0).any(axis=1)]
        logger.info(f"Dropped {before - len(df)} fighters with no recorded fight-stat activity")

    for col in ACTIVITY_COLUMNS:
        if df[col].isna().any():
            median = df[col].median()
            df[col] = df[col].fillna(median)

    df = df.reset_index(drop=True)
    logger.info(f"{len(df)} fighters remain after preprocessing")
    return df


def run_pca(df: pd.DataFrame) -> Tuple[np.ndarray, PCA]:
    """Standardize features and project onto 2 principal components.

    Standardization (mean=0, std=1 per feature) is essential here: height_cm
    ranges over ~30, sig_strikes_accuracy ranges over ~1.0, and
    takedown_avg_per15m ranges over ~10 - without scaling, PCA would just
    rediscover "which feature has the biggest raw numbers" instead of
    genuine variance structure.
    """
    X = df[FEATURE_COLUMNS].to_numpy(dtype=float)

    X_scaled = StandardScaler().fit_transform(X)

    pca = PCA(n_components=2, random_state=42)
    X_pca = pca.fit_transform(X_scaled)

    explained = pca.explained_variance_ratio_
    logger.info(
        f"Explained variance: PC1={explained[0]:.1%}, PC2={explained[1]:.1%}, "
        f"total={explained.sum():.1%}"
    )
    return X_pca, pca


def choose_k(X_pca: np.ndarray, k_min: int = 2, k_max: int = 8) -> int:
    """Auto-select a cluster count via silhouette score."""
    best_k, best_score = k_min, -1.0
    for k in range(k_min, min(k_max, len(X_pca) - 1) + 1):
        labels = KMeans(n_clusters=k, random_state=42, n_init=10).fit_predict(X_pca)
        score = silhouette_score(X_pca, labels)
        if score > best_score:
            best_k, best_score = k, score
    logger.info(f"Auto-selected k={best_k} clusters (silhouette score={best_score:.3f})")
    return best_k


def plot(df: pd.DataFrame, X_pca: np.ndarray, pca: PCA, labels: np.ndarray, output_path: Path):
    fig, ax = plt.subplots(figsize=(10, 7))
    scatter = ax.scatter(
        X_pca[:, 0], X_pca[:, 1],
        c=labels, cmap="tab10", s=25, alpha=0.75, edgecolors="none",
    )

    ax.set_xlabel(f"PC1 ({pca.explained_variance_ratio_[0]:.1%} of variance)")
    ax.set_ylabel(f"PC2 ({pca.explained_variance_ratio_[1]:.1%} of variance)")
    ax.set_title(f"UFC Fighters - PCA Projection  ({len(df)} fighters, {len(set(labels))} clusters)")

    legend = ax.legend(*scatter.legend_elements(), title="Cluster", loc="best")
    ax.add_artist(legend)

    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=150)
    logger.info(f"Saved plot to {output_path}")
    plt.show()


def main():
    parser = argparse.ArgumentParser(description="PCA visualization of fighter statistics")
    parser.add_argument("--db", type=Path, default=DB_PATH, help="Path to ufc.db")
    parser.add_argument("--clusters", type=int, default=None,
                         help="Number of KMeans clusters (auto-selected via silhouette score if omitted)")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "data" / "pca_fighters.png",
                         help="Where to save the plot image")
    parser.add_argument("--include-inactive", action="store_true",
                         help="Keep fighters with no recorded fight-stat activity (they'll cluster near the origin)")
    args = parser.parse_args()

    df = load_fighters(args.db)
    df = preprocess(df, drop_inactive=not args.include_inactive)

    if len(df) < 4:
        raise ValueError(
            f"Only {len(df)} fighters remain after preprocessing - not enough to run "
            f"PCA/clustering meaningfully. Try --include-inactive, or scrape more fighters."
        )

    X_pca, pca = run_pca(df)

    k = args.clusters or choose_k(X_pca)
    labels = KMeans(n_clusters=k, random_state=42, n_init=10).fit_predict(X_pca)

    plot(df, X_pca, pca, labels, args.output)


if __name__ == "__main__":
    main()
