# UFC Match Predictor

Data-driven system to predict UFC bout outcomes and identify value bets by combining official match history, fighter statistics, and historic betting odds.

## Running

### Data Scraping
```bash
python3 -m ufc.scraper.fighters
python3 -m ufc.scraper.events
python3 -m ufc.scraper.odds
```

or 
```bash
./run.sh
```

### Feature/Training Set Generation
Core features
```bash
python3 -m ufc.features.core
```

All features
```bash
python3 -m ufc.features.full
```

### Machine Learning Model 
Core features
```bash
python3 -m ufc.ml.core --train   # train
python3 -m ufc.ml.core --predict # predict
```

All features
```bash
python3 -m ufc.ml.full --train   # train
python3 -m ufc.ml.full --predict # predict

```

## Project Goals
- Build a reliable, incrementally updatable data pipeline for UFC events, fighters, and odds.
- Develop robust machine learning models with proper time-series cross-validation.
- Identify positive expected value bets by comparing model probabilities against market odds.

## Current Status
**Phase 1: Data Scraper** (in progress)
**Phase 2: Feature Generation** (in progress)
**Phase 3: ML Predictor** (in progress)

## Training Set Features

### Core Fighter Attributes (static or slowly changing)

- Age at fight time (calculated from dob + event_date)
- Height (cm)
- Reach (cm)
- Stance (Orthodox / Southpaw / Switch) — one-hot or target-encoded
- Weight class (category) — important because styles differ dramatically
- Current weight / weight class history

### Derived Comparative Features (very high signal — fighter1 minus / ratio fighter2)

- Delta age, height, reach
- Delta SLpM, accuracy, SApM, defense, takedown stats, submission avg
- Ratio versions of the above (often works better than raw deltas)
- Stance matchup (e.g., Orthodox vs Southpaw)

### Career / Performance Stats (from fighters table, at time of scrape or latest available)

- Significant strikes landed per 15 min (SLpM)
- Significant strikes accuracy
- Significant strikes absorbed per 15 min (SApM)
- Significant strikes defended
- Takedown average per 15 min
- Takedown accuracy
- Takedown defense
- Submission average attempted per 15 min
- Professional record win rate: wins / (wins + losses + draws + NC) (normalized)
- Career finish rate (KO/TKO + SUB wins / total wins) — derived from bouts table

### Recency / Form Features (require joining bouts + events)

- Days since last fight
- Number of fights in last 12/24 months
- Win streak (current)
- Recent win rate (last 3 / 5 fights)
- Recent finish rate
- Performance in last fight (e.g., significant strikes landed, takedowns, etc.)

### Contextual / Fight-level Features

- Is title fight? (derived from event_name or weight_class + main event status)
- Main card / prelim status (if available)
- Weight class (already listed)
- Event location / time zone effects (minor)
- Round & method of previous fights (aggressiveness profile)

### Betting / Market Features (from odds table)

- Is betting favorite? (binary)
- Decimal odds of the fighter (or implied probability)
- Historical betting favorite win rate (how often favorites win in this weight class / era)
- Average / recent betting odds movement (if we scrape multiple books later)
- “Value” signal: model probability vs implied probability from odds (this is the target for +EV betting)

### Interaction & Advanced Features (for later)

- Fighter style clustering (wrestler / striker / grappler) — derived or clustered from stats
- Experience gap (difference in number of UFC fights)
- Age vs experience interaction
- Reach advantage in striking-heavy weight classes
