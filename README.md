# UFC Match Predictor

Data-driven system to predict UFC bout outcomes and identify value bets by combining official match history, fighter statistics, and historic betting odds.

## Project Goals
- Build a reliable, incrementally updatable data pipeline for UFC events, fighters, and odds.
- Develop robust machine learning models with proper time-series cross-validation.
- Identify positive expected value bets by comparing model probabilities against market odds.

## Current Status
**Phase 1: Data Scraper** (in progress)

We are building a clean, maintainable scraper that stores data in SQLite and supports independent updates via CLI flags.

## Quick Start
```bash
poetry install
python cli.py --help
