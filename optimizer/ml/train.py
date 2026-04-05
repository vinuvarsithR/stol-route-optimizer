"""
optimizer/ml/train.py
======================
Synthetic Data Generation + Model Training

WHY SYNTHETIC DATA?
  Real DGCA passenger data is not publicly available at the route level.
  Instead, we generate synthetic demand figures using a carefully designed
  formula that mirrors real aviation demand patterns:

  Demand drivers (grounded in aviation economics):
    1. Metro connectivity: DEL-BOM >> DEL-SHL in absolute volume
    2. Tourism gravity: remote scenic areas have high demand relative to population
    3. STOL advantage: routes with NO road alternative have captive demand
    4. Distance decay: demand drops sharply beyond 800km (rail competes)
    5. Seasonality: Leh/Manali peaks in summer; Lakshadweep in winter
    6. NE India: extremely high STOL demand due to terrain

MODEL CHOICE: Random Forest Regressor
  - Handles non-linear feature interactions well (tourism × altitude)
  - Robust to outliers in demand data
  - Built-in feature importance (explainable to recruiter)
  - No scaling required (unlike SVM / neural nets)
  - Fast train + inference — suitable for a Flask API

ALTERNATIVE CONSIDERED: Gradient Boosting (XGBoost)
  - More accurate but heavier dependency
  - RF is simpler to explain in an interview

OUTPUT:
  Saves trained model as optimizer/ml/demand_model.pkl
  This file is loaded at runtime by predict.py — training runs once.
"""

import os
import math
import pickle
import random
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split, cross_val_score
from sklearn.metrics import mean_absolute_error, r2_score

from optimizer.graph import CITIES, ROUTES
from optimizer.graph import haversine_km
from optimizer.ml.features import (
    extract_features, FEATURE_NAMES,
    POPULATION_SCORES, TOURISM_SCORES,
    MOUNTAIN_AIRPORTS, ISLAND_AIRPORTS, NORTHEAST_AIRPORTS,
)

# Path to save the trained model
MODEL_PATH = os.path.join(os.path.dirname(__file__), "demand_model.pkl")
META_PATH  = os.path.join(os.path.dirname(__file__), "model_meta.pkl")


# ================================================================
# SYNTHETIC DEMAND FORMULA
# ================================================================
# Generates realistic weekly passenger demand for a route.
# Formula design decisions explained inline.
# ================================================================

def synthetic_demand(src: str, dst: str, season: int, is_weekend: int) -> float:
    """
    Generates a realistic weekly demand estimate (passengers per week)
    for a given route, season, and day type.

    This is the "ground truth" our model will learn to approximate.
    In production, this would be replaced with real DGCA / airline data.
    """

    src_d = CITIES[src]
    dst_d = CITIES[dst]
    dist  = haversine_km(src, dst)

    # --- Base demand from population gravity model ---
    # Gravity model: demand ∝ (pop_A × pop_B) / distance²
    # Standard in transport economics (Zipf / gravity law)
    pop_a  = POPULATION_SCORES.get(src, 0.05)
    pop_b  = POPULATION_SCORES.get(dst, 0.05)
    gravity = (pop_a * pop_b) / max(dist ** 0.8, 1)  # 0.8 exponent = distance decay
    base_demand = gravity * 8000   # Scale to realistic pax/week range

    # --- Tourism demand bonus ---
    tour_a = TOURISM_SCORES.get(src, 0.1)
    tour_b = TOURISM_SCORES.get(dst, 0.1)
    tourism_bonus = max(tour_a, tour_b) * 200  # Up to 200 pax/week bonus

    # --- Seasonal multipliers ---
    # Summer (3): Mountain routes peak — Leh, Manali, Kashmir
    # Winter (1): Island routes peak — Lakshadweep
    seasonal_mult = 1.0
    is_mountain = src in MOUNTAIN_AIRPORTS or dst in MOUNTAIN_AIRPORTS
    is_island   = src in ISLAND_AIRPORTS   or dst in ISLAND_AIRPORTS
    is_ne       = src in NORTHEAST_AIRPORTS or dst in NORTHEAST_AIRPORTS

    if season == 3 and is_mountain:   seasonal_mult = 2.2   # Summer peak
    elif season == 2 and is_mountain: seasonal_mult = 1.6   # Spring rising
    elif season == 4 and is_mountain: seasonal_mult = 1.3   # Autumn shoulder
    elif season == 1 and is_mountain: seasonal_mult = 0.5   # Winter trough

    if season == 1 and is_island:     seasonal_mult = 2.0   # Winter island peak
    elif season == 2 and is_island:   seasonal_mult = 1.4
    elif season == 3 and is_island:   seasonal_mult = 0.7   # Monsoon dip

    # NE India demand is year-round (no alternative transport)
    if is_ne: seasonal_mult = max(seasonal_mult, 1.2)

    # --- STOL captive demand ---
    # Routes where both airports are STOL have NO road alternative —
    # everyone who travels MUST fly. This dramatically increases demand
    # relative to what the gravity model predicts.
    stol_mult = 1.0
    if src_d["stol"] and dst_d["stol"]:
        stol_mult = 2.5   # Fully captive market
    elif src_d["stol"] or dst_d["stol"]:
        stol_mult = 1.4   # Partially captive

    # --- Distance decay: rail/road competition ---
    # Below 300km: trains compete hard → less demand for flight
    # 300–700km: sweet spot for short haul
    # Above 700km: rail loses, flight wins
    if dist < 200:
        dist_mult = 0.6   # Road is preferred
    elif dist < 400:
        dist_mult = 1.0
    elif dist < 700:
        dist_mult = 1.2   # Flight advantage zone
    else:
        dist_mult = 1.4   # Long haul: only option

    # --- Weekend boost ---
    weekend_mult = 1.3 if is_weekend else 1.0

    # Combine all factors
    demand = (
        (base_demand + tourism_bonus)
        * seasonal_mult
        * stol_mult
        * dist_mult
        * weekend_mult
    )

    # Add realistic noise (~10%) to simulate market variability
    noise = random.gauss(1.0, 0.10)
    demand *= max(noise, 0.7)  # Prevent negative demand

    return max(round(demand, 1), 5.0)   # Minimum 5 pax/week


# ================================================================
# GENERATE TRAINING DATASET
# ================================================================

def generate_dataset(n_samples_per_route: int = 80) -> pd.DataFrame:
    """
    Generates a synthetic dataset of (features, demand) pairs.

    For each route in our network, we generate samples across:
      - All 4 seasons
      - Both weekday and weekend
      - Multiple repetitions with noise

    Returns a pandas DataFrame ready for model training.
    """

    random.seed(42)   # Reproducibility
    np.random.seed(42)

    records = []

    for src, dst in ROUTES:
        dist = haversine_km(src, dst)

        for _ in range(n_samples_per_route):
            season     = random.randint(1, 4)
            is_weekend = random.randint(0, 1)

            # Feature vector
            X = extract_features(src, dst, dist, season, is_weekend)

            # Target: weekly demand
            y = synthetic_demand(src, dst, season, is_weekend)

            records.append({
                "src": src, "dst": dst,
                **{FEATURE_NAMES[i]: float(X[i]) for i in range(len(FEATURE_NAMES))},
                "demand_pax_week": y,
            })

            # Also add reverse direction (A→B ≠ B→A in real life due to tourism asymmetry)
            X_rev = extract_features(dst, src, dist, season, is_weekend)
            y_rev = synthetic_demand(dst, src, season, is_weekend)

            records.append({
                "src": dst, "dst": src,
                **{FEATURE_NAMES[i]: float(X_rev[i]) for i in range(len(FEATURE_NAMES))},
                "demand_pax_week": y_rev,
            })

    return pd.DataFrame(records)


# ================================================================
# TRAIN MODEL
# ================================================================

def train_model() -> dict:
    """
    Full training pipeline:
      1. Generate synthetic dataset
      2. Split train/test
      3. Train Random Forest
      4. Evaluate with cross-validation
      5. Save model + metadata to disk

    Returns evaluation metrics dict.
    """

    print("Generating synthetic training data...")
    df = generate_dataset(n_samples_per_route=80)
    print(f"  Dataset: {len(df)} rows, {len(df.columns)} columns")
    print(f"  Demand range: {df['demand_pax_week'].min():.0f} – {df['demand_pax_week'].max():.0f} pax/week")

    # Feature matrix X and target y
    X = df[FEATURE_NAMES].values.astype(np.float32)
    y = df["demand_pax_week"].values.astype(np.float32)

    # Train / test split (80/20)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42
    )
    print(f"  Train: {len(X_train)} | Test: {len(X_test)}")

    # Random Forest — key hyperparameters explained:
    #   n_estimators=200  : 200 decision trees (more = better, diminishing returns)
    #   max_depth=12      : prevents overfitting (unlimited depth memorises noise)
    #   min_samples_leaf=3: each leaf needs ≥3 samples (regularisation)
    #   max_features='sqrt': each split considers √n_features (prevents correlation)
    model = RandomForestRegressor(
        n_estimators   = 200,
        max_depth      = 12,
        min_samples_leaf= 3,
        max_features   = "sqrt",
        random_state   = 42,
        n_jobs         = -1,   # Use all CPU cores
    )

    print("Training Random Forest...")
    model.fit(X_train, y_train)

    # Evaluation
    y_pred = model.predict(X_test)
    mae  = mean_absolute_error(y_test, y_pred)
    r2   = r2_score(y_test, y_pred)

    # Cross-validation for more reliable estimate
    cv_scores = cross_val_score(model, X, y, cv=5, scoring="r2")
    print(f"  MAE (test): {mae:.1f} pax/week")
    print(f"  R² (test) : {r2:.4f}")
    print(f"  R² (5-fold CV): {cv_scores.mean():.4f} ± {cv_scores.std():.4f}")

    # Feature importances — these tell us which factors drive demand most
    importances = model.feature_importances_
    feat_imp = sorted(
        zip(FEATURE_NAMES, importances),
        key=lambda x: x[1], reverse=True
    )
    print("\nTop 5 demand drivers:")
    for name, imp in feat_imp[:5]:
        print(f"  {name}: {imp:.4f}")

    # Save model and metadata
    meta = {
        "mae"           : float(mae),
        "r2"            : float(r2),
        "cv_r2_mean"    : float(cv_scores.mean()),
        "cv_r2_std"     : float(cv_scores.std()),
        "n_features"    : len(FEATURE_NAMES),
        "feature_names" : FEATURE_NAMES,
        "feature_importances": {
            name: float(imp) for name, imp in feat_imp
        },
        "training_samples": len(X_train),
    }

    with open(MODEL_PATH, "wb") as f:
        pickle.dump(model, f)

    with open(META_PATH, "wb") as f:
        pickle.dump(meta, f)

    print(f"\nModel saved to {MODEL_PATH}")
    return meta


if __name__ == "__main__":
    train_model()
