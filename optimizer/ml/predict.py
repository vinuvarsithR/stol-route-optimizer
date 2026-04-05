"""
optimizer/ml/predict.py
========================
Demand Prediction API

Loads the trained Random Forest model from disk and provides:
  1. predict_demand()      — demand for a single route + conditions
  2. predict_route_demand()— demand for every leg in an optimized route
  3. demand_category()     — classifies demand as Low/Medium/High/Very High
  4. confidence_interval() — bootstrap uncertainty estimate

The model is loaded ONCE at module import (not per request) for performance.
If the model file doesn't exist, it's trained automatically.
"""

import os
import pickle
import numpy as np
from typing import Optional

from optimizer.ml.features import extract_features, FEATURE_NAMES
from optimizer.graph import haversine_km, CITIES

MODEL_PATH = os.path.join(os.path.dirname(__file__), "demand_model.pkl")
META_PATH  = os.path.join(os.path.dirname(__file__), "model_meta.pkl")


# ================================================================
# MODEL LOADER
# ================================================================
# We load the model once at module import time.
# This is cached in memory for the lifetime of the Flask process.
# Typical load time: < 1 second. Prediction time: ~2ms per request.
# ================================================================

def _load_or_train():
    """Loads model from disk, training it first if it doesn't exist."""
    if not os.path.exists(MODEL_PATH):
        print("[ML] No trained model found. Training now...")
        from optimizer.ml.train import train_model
        train_model()
        print("[ML] Training complete.")

    with open(MODEL_PATH, "rb") as f:
        model = pickle.load(f)

    with open(META_PATH, "rb") as f:
        meta = pickle.load(f)

    return model, meta


# Load model at import time
_MODEL, _META = _load_or_train()


# ================================================================
# DEMAND CATEGORY THRESHOLDS
# ================================================================
# Based on typical Indian regional aviation market sizes.
# Small STOL routes: 50–300 pax/week is commercially viable.
# ================================================================

DEMAND_THRESHOLDS = {
    "Very High": 600,   # Metro corridors
    "High":      300,   # Popular tourist/regional routes
    "Medium":    100,   # Developing STOL routes
    "Low":       0,     # Very thin markets
}


def demand_category(pax_per_week: float) -> dict:
    """
    Classifies demand and returns category + colour for UI display.
    
    Returns: { "label": str, "color": str, "description": str }
    """
    if pax_per_week >= DEMAND_THRESHOLDS["Very High"]:
        return {
            "label": "Very High",
            "color": "#3d9bff",
            "description": "High-density corridor. Frequent service viable."
        }
    elif pax_per_week >= DEMAND_THRESHOLDS["High"]:
        return {
            "label": "High",
            "color": "#00e5a0",
            "description": "Strong demand. Daily service recommended."
        }
    elif pax_per_week >= DEMAND_THRESHOLDS["Medium"]:
        return {
            "label": "Medium",
            "color": "#f4a523",
            "description": "Moderate demand. 3–4 flights per week viable."
        }
    else:
        return {
            "label": "Low",
            "color": "#ff5757",
            "description": "Thin market. Subsidy or bundling may be needed."
        }


# ================================================================
# MAIN PREDICTION FUNCTION
# ================================================================

def predict_demand(
    src: str,
    dst: str,
    season: int      = 2,   # 1=Winter, 2=Spring, 3=Summer, 4=Autumn
    is_weekend: int  = 0,
) -> dict:
    """
    Predicts weekly passenger demand for a route.

    Uses a Random Forest ensemble — each tree gives one prediction,
    and we use the variance across trees as a confidence interval.

    Args:
        src        : IATA code for origin
        dst        : IATA code for destination
        season     : 1–4
        is_weekend : 0 or 1

    Returns a rich prediction dict for the API response.
    """

    # Validate city codes
    if src not in CITIES or dst not in CITIES:
        return {"error": f"Unknown city: {src} or {dst}"}

    dist = haversine_km(src, dst)

    # Build feature vector
    X = extract_features(src, dst, dist, season, is_weekend).reshape(1, -1)

    # --- Point prediction ---
    point_pred = float(_MODEL.predict(X)[0])
    point_pred = max(point_pred, 1.0)   # Clamp to positive

    # --- Confidence interval via individual tree predictions ---
    # Random Forests expose each tree's prediction via estimators_.
    # The spread of these predictions gives us a natural uncertainty measure.
    tree_preds = np.array([tree.predict(X)[0] for tree in _MODEL.estimators_])
    ci_low  = float(np.percentile(tree_preds, 10))   # 10th percentile
    ci_high = float(np.percentile(tree_preds, 90))   # 90th percentile
    ci_low  = max(ci_low, 1.0)

    # --- Seasonal breakdown: predict all 4 seasons for the chart ---
    season_names = {1: "Winter", 2: "Spring", 3: "Summer", 4: "Autumn"}
    seasonal = {}
    for s in range(1, 5):
        X_s = extract_features(src, dst, dist, s, is_weekend).reshape(1, -1)
        seasonal[season_names[s]] = round(float(_MODEL.predict(X_s)[0]), 1)

    # --- Feature contributions (top 5 drivers for this prediction) ---
    # We use feature importances × feature values as a proxy for SHAP values.
    # Real SHAP would require the shap library; this is a simpler explainability method.
    X_flat = X.flatten()
    importances = _MODEL.feature_importances_

    contributions = []
    for i, (name, imp) in enumerate(zip(FEATURE_NAMES, importances)):
        raw_val = X_flat[i]
        # Contribution = importance × normalised feature value
        contrib_score = imp * raw_val
        contributions.append({
            "feature":      name,
            "importance":   round(float(imp), 4),
            "value":        round(float(raw_val), 4),
            "contribution": round(float(contrib_score), 5),
        })

    # Sort by contribution magnitude
    contributions.sort(key=lambda x: abs(x["contribution"]), reverse=True)
    top_drivers = contributions[:5]

    category = demand_category(point_pred)

    return {
        "src":              src,
        "dst":              dst,
        "distance_km":      dist,
        "season":           season,
        "season_name":      season_names.get(season, "Unknown"),
        "is_weekend":       bool(is_weekend),
        "prediction": {
            "pax_per_week":  round(point_pred, 1),
            "pax_per_day":   round(point_pred / 7, 1),
            "ci_low":        round(ci_low, 1),
            "ci_high":       round(ci_high, 1),
        },
        "category":         category,
        "seasonal_forecast": seasonal,
        "top_drivers":      top_drivers,
        "model_info": {
            "type":         "Random Forest (200 trees)",
            "r2_score":     round(_META["r2"], 4),
            "mae_pax_week": round(_META["mae"], 1),
        },
    }


# ================================================================
# ROUTE-LEVEL DEMAND PREDICTION
# ================================================================

def predict_route_demand(path_nodes: list, legs: list, season: int = 2) -> dict:
    """
    Predicts demand for every leg in an optimized route.

    Args:
        path_nodes : from find_optimal_route()["path_nodes"]
        legs       : from find_optimal_route()["legs"]
        season     : 1–4

    Returns per-leg demand predictions + route-level summary.
    """

    leg_predictions = []
    total_pax_week  = 0

    for leg in legs:
        pred = predict_demand(
            src        = leg["from_code"],
            dst        = leg["to_code"],
            season     = season,
            is_weekend = 0,  # Weekday baseline
        )

        leg_predictions.append({
            "from_code":   leg["from_code"],
            "to_code":     leg["to_code"],
            "from_name":   leg["from_name"],
            "to_name":     leg["to_name"],
            "distance_km": leg["distance_km"],
            "demand":      pred,
        })

        total_pax_week += pred["prediction"]["pax_per_week"]

    # Bottleneck leg = lowest demand (determines aircraft sizing)
    bottleneck = min(leg_predictions, key=lambda x: x["demand"]["prediction"]["pax_per_week"])

    # Recommended flights per week based on average demand + 9-seat STOL aircraft
    avg_demand = total_pax_week / max(len(leg_predictions), 1)
    flights_per_week = math.ceil(avg_demand / 9)   # 9-seat aircraft
    flights_per_week = max(flights_per_week, 3)     # Minimum viable frequency

    return {
        "legs":              leg_predictions,
        "total_pax_week":    round(total_pax_week, 1),
        "avg_pax_week":      round(avg_demand, 1),
        "bottleneck_leg":    f"{bottleneck['from_code']} → {bottleneck['to_code']}",
        "recommended_flights_per_week": flights_per_week,
        "season":            season,
    }


import math  # needed for math.ceil in predict_route_demand
