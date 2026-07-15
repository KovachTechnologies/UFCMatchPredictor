"""
Light ML model for UFC fight outcome prediction using core features.

This is a baseline model using XGBoost + Optuna hyperparameter tuning + sklearn Pipeline.
It demonstrates:
- Data loading and filtering for completed bouts
- Preprocessing Pipeline (impute + scale numeric/binary, impute + OHE categorical)
- Time-aware? simple split + Stratified CV
- Optuna tuning for XGB params (light: 15 trials)
- Evaluation with Accuracy and F1 (primary metrics)
- Basic feature importance (XGB) + placeholder for SHAP

Note on data: In the provided features_core.csv, historical bouts have been prepared
such that 'outcome' == 'fighter1' for nearly all decisive fights (winner's stats placed in fighter1_* slots).
This leads to a highly imbalanced (near-constant) target. The model serves as pipeline baseline;
future data prep should preserve original bout ordering from events to have both fighter1/fighter2 win examples.

Run with: python -m ufc.models.core
"""

import warnings
warnings.filterwarnings("ignore")

from pathlib import Path
import pandas as pd
import numpy as np

from sklearn.model_selection import train_test_split, StratifiedKFold, cross_val_score
from sklearn.pipeline import Pipeline
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.metrics import (
    accuracy_score, f1_score, classification_report, confusion_matrix
)

import xgboost as xgb
import optuna
import joblib

# Resolve data path relative to project root when running as module
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_PATH = PROJECT_ROOT / "data" / "features_full.csv"


def get_core_feature_lists():
    """Define features exactly as specified in features_core.txt"""
    numeric_features = [
        "fighter1_height",
        "fighter1_reach",
        "fighter2_height",
        "fighter2_reach",
        "fighter1_age",
        "fighter2_age",
        "delta_age",
        "delta_height",
        "ratio_height",
        "delta_reach",
        "ratio_reach",
        "fighter1_win_rate",
        "fighter2_win_rate",
        "fighter1_sig_strikes_landed_pm",
        "fighter1_sig_strikes_accuracy",
        "fighter1_sig_strikes_absorbed_pm",
        "fighter1_sig_strikes_defended",
        "fighter1_takedown_avg_per15m",
        "fighter1_takedown_accuracy",
        "fighter1_takedown_defence",
        "fighter2_sig_strikes_landed_pm",
        "fighter2_sig_strikes_accuracy",
        "fighter2_sig_strikes_absorbed_pm",
        "fighter2_sig_strikes_defended",
        "fighter2_takedown_avg_per15m",
        "fighter2_takedown_accuracy",
        "fighter2_takedown_defence",
        "sig_strikes_landed_pm_ratio",
        "sig_strikes_accuracy_ratio",
        "sig_strikes_absorbed_pm_ratio",
        "sig_strikes_defended_ratio",
        "takedown_avg_per15m_ratio",
        "takedown_accuracy_ratio",
        "takedown_defence_ratio",
    ]

    binary_features = [
        "fighter1_stance_Orthodox",
        "fighter2_stance_Orthodox",
        "fighter1_stance_Southpaw",
        "fighter2_stance_Southpaw",
        "fighter1_stance_Switch",
        "fighter2_stance_Switch",
        "same_stance",
    ]

    categorical_features = [
        "fighter1_stance",
        "fighter2_stance",
    ]

    all_model_features = numeric_features + binary_features + categorical_features
    return numeric_features, binary_features, categorical_features, all_model_features

def load_and_prepare_data():
    """Load core features, filter valid completed bouts, create binary target."""
    print(f"Loading data from {DATA_PATH} ...")
    df = pd.read_csv(DATA_PATH)

    # Filter to completed bouts with decisive outcome (ignore future NaN, draws, NC)
    # Note: in current data prep, outcome is almost always 'fighter1' (see module docstring)
    valid_outcomes = ["fighter1", "fighter2"]
    df = df[df["outcome"].isin(valid_outcomes)].copy()

    shuffled = df.sample(frac=1)
    result = np.array_split(shuffled, 5)  
    df1 = result[ 0 ]
    df2 = result[ 1 ]

    # handle fighter 1 bias
    df1["outcome"] = "fighter2"
    df1_columns = []
    for colname in df1.columns :
        if "fighter1" in colname :
            df1_columns.append( colname.replace( "fighter1", "fighter2" ) )
        elif "fighter2" in colname :
            df1_columns.append( colname.replace( "fighter2", "fighter1" ) )
        else :
            df1_columns.append( colname )
    df1.columns = df1_columns

    # handle ratios and deltas from core
    df1[ "delta_age" ] = df1[ "fighter1_age" ] - df1[ "fighter2_age" ]
    df1[ "delta_height" ] = df1[ "fighter1_height" ] - df1[ "fighter2_height" ]
    df1[ "ratio_height" ] = df1[ "fighter1_height" ].divide( df1[ "fighter2_height" ] ) 
    df1[ "delta_reach" ] = df1[ "fighter1_reach" ] - df1[ "fighter2_reach" ]
    df1[ "ratio_reach" ] = df1[ "fighter1_reach" ].divide( df1[ "fighter2_reach" ] )

    df = pd.concat( [ df1, df2 ], axis=0 )

    # handle deltas from full
    df[ "sig_strikes_landed_pm_ratio" ] = ( df[ "fighter1_sig_strikes_landed_pm" ] + 1 ).divide( df[ "fighter2_sig_strikes_landed_pm" ] + 1 )
    df[ "sig_strikes_accuracy_ratio" ] = ( df[ "fighter1_sig_strikes_accuracy" ] + 1 ).divide( df[ "fighter2_sig_strikes_accuracy" ] + 1 )
    df[ "sig_strikes_absorbed_pm_ratio" ] = ( df[ "fighter1_sig_strikes_absorbed_pm" ] + 1 ).divide( df[ "fighter2_sig_strikes_absorbed_pm" ] + 1 )
    df[ "sig_strikes_defended_ratio" ] = ( df[ "fighter1_sig_strikes_defended" ] + 1 ).divide( df[ "fighter2_sig_strikes_defended" ] + 1 )
    df[ "takedown_avg_per15m_ratio" ] = ( df[ "fighter1_takedown_avg_per15m" ] + 1 ).divide( df[ "fighter2_takedown_avg_per15m" ] + 1 )
    df[ "takedown_accuracy_ratio" ] = ( df[ "fighter1_takedown_accuracy" ] + 1 ).divide( df[ "fighter2_takedown_accuracy" ] + 1 )
    df[ "takedown_defence_ratio" ] = ( df[ "fighter1_takedown_defence" ] + 1 ).divide( df[ "fighter2_takedown_defence" ] + 1 )

    df.to_csv( "debug_full.csv", index=False )

    if len(df) == 0:
        raise ValueError("No valid training samples after filtering!")

    # Binary target: 1 if fighter1 wins (as labeled in data)
    y = (df["outcome"] == "fighter1").astype(int)

    numeric_features, binary_features, categorical_features, all_features = get_core_feature_lists()

    # Ensure all expected columns exist
    missing = [c for c in all_features if c not in df.columns]
    if missing:
        raise ValueError(f"Missing expected feature columns in CSV: {missing}")

    X = df[all_features].copy()

    print(f"Prepared {len(X)} samples for modeling.")
    print(f"Target distribution:\n{y.value_counts(normalize=True).round(4)}")
    return X, y, numeric_features, binary_features, categorical_features


def build_preprocessor(numeric_features, binary_features, categorical_features):
    """sklearn Pipeline + ColumnTransformer for preprocessing."""
    numeric_pipeline = Pipeline(steps=[
        ("imputer", SimpleImputer(strategy="median")),
        ("scaler", StandardScaler()),  # Helps convergence; XGB is robust but consistent
    ])

    categorical_pipeline = Pipeline(steps=[
        ("imputer", SimpleImputer(strategy="most_frequent")),
        ("onehot", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
    ])

    preprocessor = ColumnTransformer(
        transformers=[
            ("num", numeric_pipeline, numeric_features + binary_features),
            ("cat", categorical_pipeline, categorical_features),
        ],
        remainder="drop",
        verbose_feature_names_out=False,
    )
    return preprocessor


def objective(trial, X, y, preprocessor):
    """Optuna objective: inner CV to maximize F1."""
    params = {
        "objective": "binary:logistic",
        "eval_metric": "logloss",
        "n_estimators": trial.suggest_int("n_estimators", 100, 400, step=50),
        "max_depth": trial.suggest_int("max_depth", 3, 7),
        "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.2, log=True),
        "subsample": trial.suggest_float("subsample", 0.7, 1.0),
        "colsample_bytree": trial.suggest_float("colsample_bytree", 0.7, 1.0),
        "gamma": trial.suggest_float("gamma", 0.0, 4.0),
        "reg_alpha": trial.suggest_float("reg_alpha", 0.0, 1.0),
        "reg_lambda": trial.suggest_float("reg_lambda", 0.5, 2.0),
        "min_child_weight": trial.suggest_int("min_child_weight", 1, 8),
        "scale_pos_weight": trial.suggest_float("scale_pos_weight", 0.8, 1.5),  # handles any residual imbalance
        "random_state": 42,
        "n_jobs": 1,  # avoid nested parallelism issues with CV
        "verbosity": 0,
    }

    model = xgb.XGBClassifier(**params)

    clf_pipeline = Pipeline(steps=[
        ("preprocessor", preprocessor),
        ("classifier", model),
    ])

    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    scores = cross_val_score(
        clf_pipeline, X, y, cv=cv, scoring="f1", n_jobs=1
    )
    return np.mean(scores)


def train_model_and_save():
    print("=" * 60)
    print("UFC Light ML Model (XGBoost + Optuna + sklearn Pipeline)")
    print("=" * 60)

    X, y, num_feats, bin_feats, cat_feats = load_and_prepare_data()
    preprocessor = build_preprocessor(num_feats, bin_feats, cat_feats)

    # Holdout test set (stratified)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.20, stratify=y, random_state=42
    )
    print(f"Train: {len(X_train)} | Test: {len(X_test)}")

    # Optuna tuning (light config)
    print("\nRunning Optuna hyperparameter search (15 trials, ~few minutes)...")
    study = optuna.create_study(direction="maximize", study_name="ufc_xgb_light")
    study.optimize(
        lambda trial: objective(trial, X_train, y_train, preprocessor),
        n_trials=15,
        timeout=180,
        show_progress_bar=False,
    )

    print(f"\nBest trial F1 (inner CV): {study.best_value:.4f}")
    print(f"Best hyperparameters: {study.best_params}")

    # Final model with best params
    best_params = study.best_params
    best_params.update({
        "objective": "binary:logistic",
        "eval_metric": "logloss",
        "random_state": 42,
        "n_jobs": -1,
        "verbosity": 0,
    })

    final_model = xgb.XGBClassifier(**best_params)
    final_pipeline = Pipeline(steps=[
        ("preprocessor", preprocessor),
        ("classifier", final_model),
    ])

    final_pipeline.fit(X_train, y_train)

    # Evaluation on holdout
    y_pred = final_pipeline.predict(X_test)
    y_proba = final_pipeline.predict_proba(X_test)[:, 1]

    acc = accuracy_score(y_test, y_pred)
    f1 = f1_score(y_test, y_pred, average="binary")

    print("\n" + "=" * 40)
    print("HOLD-OUT TEST SET PERFORMANCE (Light Baseline)")
    print("=" * 40)
    print(f"Accuracy : {acc:.4f}")
    print(f"F1-score : {f1:.4f}   <-- primary metric")
    print("\nClassification Report:")
    print(classification_report(y_test, y_pred, target_names=["fighter2 wins", "fighter1 wins"]))
    print("Confusion Matrix:")
    print(confusion_matrix(y_test, y_pred))

    # Robustness: 5-fold CV on full data
    print("\n5-Fold Stratified CV on full data (F1):")
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    cv_scores = cross_val_score(final_pipeline, X, y, cv=cv, scoring="f1", n_jobs=-1)
    print(f"  Mean F1: {cv_scores.mean():.4f}  |  Std: {cv_scores.std():.4f}")

    # Feature importance (from fitted XGB)
    try:
        importances = final_pipeline.named_steps["classifier"].feature_importances_
        # Get feature names after preprocessing (approximate)
        ohe = final_pipeline.named_steps["preprocessor"].named_transformers_["cat"].named_steps["onehot"]
        cat_feature_names = ohe.get_feature_names_out(cat_feats) if hasattr(ohe, "get_feature_names_out") else []
        feature_names = num_feats + bin_feats + list(cat_feature_names)
        feat_imp = pd.DataFrame({
            "feature": feature_names[:len(importances)],
            "importance": importances
        }).sort_values("importance", ascending=False)
        print("\nTop 10 features by XGBoost importance:")
        print(feat_imp.head(10).to_string(index=False))
    except Exception as e:
        print(f"Could not extract feature importances: {e}")

    # SHAP placeholder (full analysis in notebooks or future version)
    print("\n[SHAP] TreeExplainer ready for post-hoc analysis on fitted model.")
    print("       Example usage (in notebook):")
    print("       explainer = shap.TreeExplainer(final_pipeline.named_steps['classifier'])")
    print("       X_trans = final_pipeline.named_steps['preprocessor'].transform(X_test)")
    print("       shap_values = explainer.shap_values(X_trans)")

    # Persist model
    model_out = PROJECT_ROOT / "data" / "ufc_xgb_full_pipeline.joblib"
    joblib.dump(final_pipeline, model_out)
    print(f"\nModel pipeline saved to: {model_out}")

    print("\nLight baseline complete. Use this as starting point to beat with richer features / better labeling.")


def load_data_to_predict() :
    """Load core features, filter valid completed bouts, create binary target."""
    print(f"Loading data from {DATA_PATH} ...")
    df = pd.read_csv(DATA_PATH)

    # Filter to completed bouts with decisive outcome (ignore future NaN, draws, NC)
    # Note: in current data prep, outcome is almost always 'fighter1' (see module docstring)
    df = df[df["outcome"].isna()].copy()

    if len(df) == 0:
        raise ValueError("No valid application data!")

    # handle deltas from full
    df[ "sig_strikes_landed_pm_ratio" ] = ( df[ "fighter1_sig_strikes_landed_pm" ] + 1 ).divide( df[ "fighter2_sig_strikes_landed_pm" ] + 1 )
    df[ "sig_strikes_accuracy_ratio" ] = ( df[ "fighter1_sig_strikes_accuracy" ] + 1 ).divide( df[ "fighter2_sig_strikes_accuracy" ] + 1 )
    df[ "sig_strikes_absorbed_pm_ratio" ] = ( df[ "fighter1_sig_strikes_absorbed_pm" ] + 1 ).divide( df[ "fighter2_sig_strikes_absorbed_pm" ] + 1 )
    df[ "sig_strikes_defended_ratio" ] = ( df[ "fighter1_sig_strikes_defended" ] + 1 ).divide( df[ "fighter2_sig_strikes_defended" ] + 1 )
    df[ "takedown_avg_per15m_ratio" ] = ( df[ "fighter1_takedown_avg_per15m" ] + 1 ).divide( df[ "fighter2_takedown_avg_per15m" ] + 1 )
    df[ "takedown_accuracy_ratio" ] = ( df[ "fighter1_takedown_accuracy" ] + 1 ).divide( df[ "fighter2_takedown_accuracy" ] + 1 )
    df[ "takedown_defence_ratio" ] = ( df[ "fighter1_takedown_defence" ] + 1 ).divide( df[ "fighter2_takedown_defence" ] + 1 )

    return df


def apply_model() :
    import datetime

    model_file = PROJECT_ROOT / "data" / "ufc_xgb_full_pipeline.joblib"
    model = joblib.load(model_file)

    df = load_data_to_predict()

    numeric_features, binary_features, categorical_features, all_features = get_core_feature_lists()

    # Ensure all expected columns exist
    missing = [c for c in all_features if c not in df.columns]
    if missing:
        raise ValueError(f"Missing expected feature columns in CSV: {missing}")

    X = df[all_features].copy()
    readable_columns = [ "fighter1_name", "fighter2_name" ]
    readable_df = df[ readable_columns ].copy()

    print(f"Prepared {len(X)} samples for model application.")

    y = model.predict(X)
    yp = model.predict_proba(X)
    readable_df[ "prediction_numeric" ] = y
    df_dict = readable_df.to_dict('records')
    for i, row in enumerate( df_dict ) :
        if row[ "prediction_numeric" ] == 0 :
            row[ "prediction_name" ] = row[ "fighter1_name" ]
        else :
            row[ "prediction_name" ] = row[ "fighter2_name" ]
        row[ "probability" ] = yp[ i ][ row[ "prediction_numeric" ] ]

    dt_string = df[ "event_date" ][ 0 ]
    output_filename = f"{dt_string}_predictions_full.csv"
    output_filepath = PROJECT_ROOT / "predictions" / output_filename
    print( f"Model output for event at {dt_string} output to {output_filepath}" )
    df_output = pd.DataFrame( df_dict )
    df_output.to_csv( output_filepath, index=False )


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="UFC Match Predictor Data Pipeline"
    )
    parser.add_argument(
        "--train", action="store_true",
        help="Train model"
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="Apply model"
    )

    args = parser.parse_args()

    if args.train:
        train_model_and_save()

    if args.apply:
        apply_model()

if __name__ == "__main__":
    main()
