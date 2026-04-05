"""
optimizer/ml/features.py
========================
Feature Engineering for Route Demand Prediction

This module converts raw airport/route data into a numerical
feature vector that the ML model can learn from.

Features designed:
  1.  distance_km          — shorter routes = more regional demand
  2.  log_distance          — log-scaled distance (diminishing effect)
  3.  is_stol_both          — both airports STOL? (underserved market)
  4.  is_stol_either        — at least one STOL endpoint
  5.  src_population_score  — proxy for city size (0–1 scaled)
  6.  dst_population_score
  7.  src_tourism_score     — hill stations, islands, pilgrimage sites
  8.  dst_tourism_score
  9.  src_connectivity      — number of direct routes from city (hub score)
  10. dst_connectivity
  11. route_elevation_diff  — high altitude difference = tougher route
  12. src_altitude_ft       — high altitude airports serve remote areas
  13. dst_altitude_ft
  14. is_mountain_route     — either endpoint > 3000 ft
  15. is_island_route       — Lakshadweep / island airports
  16. is_northeast_route    — NE India has high STOL demand (poor road connectivity)
  17. season                — 1=winter, 2=spring, 3=summer, 4=autumn (tourism peaks)
  18. is_weekend            — weekends see more leisure travel

Design rationale:
  - STOL routes in mountains / NE India / islands serve markets with
    NO alternative transport. These have inelastic, high demand.
  - Metro-to-metro routes (DEL-BOM) have high volume but face rail/road competition.
  - Regional STOL routes have lower absolute volume but higher growth potential.
"""

import math
import numpy as np
from optimizer.graph import CITIES, ROUTES


# ================================================================
# DOMAIN KNOWLEDGE SCORES
# ================================================================
# These are informed estimates based on:
#   - Census 2011 / 2021 urban agglomeration data
#   - Ministry of Tourism annual visitor data
#   - DGCA route statistics
# Scaled 0.0 – 1.0 for model compatibility
# ================================================================

# Population score: proxy for travel demand generation
# Large metros score high; small hill/island airports score low
POPULATION_SCORES = {
    "DEL": 1.00,   # NCT ~32M
    "BOM": 0.95,   # MMR ~21M
    "BLR": 0.85,   # Bengaluru ~13M
    "CCU": 0.80,   # Kolkata ~15M
    "HYD": 0.78,   # Hyderabad ~10M
    "MAA": 0.75,   # Chennai ~11M
    "IXC": 0.45,   # Chandigarh ~1.1M
    "IXU": 0.30,   # Aurangabad ~1.2M
    "JLR": 0.28,   # Jabalpur ~1.4M
    "SXR": 0.35,   # Srinagar ~1.6M
    "LEN": 0.10,   # Leh ~0.3M
    "SHL": 0.15,   # Shimla ~0.2M
    "KUU": 0.08,   # Kullu ~0.1M
    "DHM": 0.12,   # Dharamsala ~0.15M
    "PYB": 0.10,   # Jeypore ~0.1M
    "COH": 0.08,   # Cooch Behar ~0.1M
    "IXH": 0.06,   # Kailashahar ~0.05M
    "AGX": 0.04,   # Agatti ~0.01M (island)
}

# Tourism score: leisure + pilgrimage + adventure travel potential
# High for Leh, Manali, Dharamsala, Lakshadweep; low for industrial cities
TOURISM_SCORES = {
    "DEL":  0.55,  # Gateway hub, some tourism
    "BOM":  0.50,  # Business + Bollywood tourism
    "BLR":  0.40,  # Tech hub, some tourism
    "CCU":  0.45,  # Cultural tourism, gateway to NE
    "HYD":  0.45,  # Heritage, tech
    "MAA":  0.40,  # Gateway south
    "IXC":  0.35,  # Chandigarh gardens, gateway HP
    "IXU":  0.50,  # Ajanta & Ellora caves
    "JLR":  0.30,  # Marble rocks, limited
    "SXR":  0.85,  # Kashmir tourism (high season)
    "LEN":  0.95,  # Leh-Ladakh: peak adventure tourism
    "SHL":  0.80,  # Shimla heritage + snow tourism
    "KUU":  0.90,  # Manali: highest leisure demand in HP
    "DHM":  0.85,  # McLeodganj, Dalai Lama temple, trekking
    "PYB":  0.35,  # Koraput tribal tourism
    "COH":  0.25,  # Limited tourism
    "IXH":  0.20,  # Limited tourism
    "AGX":  0.90,  # Lakshadweep: exclusive island tourism
}

# Is this airport in Northeast India? (High STOL demand due to terrain)
NORTHEAST_AIRPORTS = {"IXH", "COH"}

# Is this an island airport?
ISLAND_AIRPORTS = {"AGX"}

# Mountain airports (elevation > 3000 ft)
MOUNTAIN_AIRPORTS = {c for c, d in CITIES.items() if d["altitude_ft"] > 3000}


def compute_connectivity(city_code: str) -> int:
    """
    Returns how many direct routes a city has in the network.
    High connectivity = hub airport = high base demand.
    """
    count = 0
    for a, b in ROUTES:
        if a == city_code or b == city_code:
            count += 1
    return count


# Pre-compute connectivity for all cities (done once at import)
CONNECTIVITY = {code: compute_connectivity(code) for code in CITIES}
MAX_CONNECTIVITY = max(CONNECTIVITY.values())  # For normalisation


def extract_features(
    src: str,
    dst: str,
    distance_km: float,
    season: int = 2,      # 1=Winter, 2=Spring, 3=Summer, 4=Autumn
    is_weekend: int = 0,  # 0 or 1
) -> np.ndarray:
    """
    Converts a route (src → dst) into a feature vector for the ML model.

    Args:
        src         : IATA source code
        dst         : IATA destination code
        distance_km : Haversine distance of the direct route
        season      : 1–4 (affects tourism demand)
        is_weekend  : 0/1 flag

    Returns:
        numpy array of shape (18,) ready for model.predict()
    """

    src_data = CITIES[src]
    dst_data = CITIES[dst]

    # --- Feature 1-2: Distance ---
    # We include both raw and log-scaled distance.
    # Log handles the diminishing effect: going from 100→200km matters
    # more than 900→1000km for demand.
    f_distance     = distance_km
    f_log_distance = math.log1p(distance_km)   # log(1 + x) avoids log(0)

    # --- Feature 3-4: STOL flags ---
    f_stol_both   = int(src_data["stol"] and dst_data["stol"])
    f_stol_either = int(src_data["stol"] or  dst_data["stol"])

    # --- Feature 5-6: Population scores ---
    f_src_pop = POPULATION_SCORES.get(src, 0.1)
    f_dst_pop = POPULATION_SCORES.get(dst, 0.1)

    # --- Feature 7-8: Tourism scores ---
    # Season modifier: summer (3) boosts mountain/hill routes
    #                  winter (1) boosts island routes
    season_boost = 1.0
    src_tourism = TOURISM_SCORES.get(src, 0.2)
    dst_tourism = TOURISM_SCORES.get(dst, 0.2)

    if season == 3:  # Summer: mountains peak
        if src in MOUNTAIN_AIRPORTS: src_tourism *= 1.3
        if dst in MOUNTAIN_AIRPORTS: dst_tourism *= 1.3
    elif season == 1:  # Winter: islands peak
        if src in ISLAND_AIRPORTS: src_tourism *= 1.4
        if dst in ISLAND_AIRPORTS: dst_tourism *= 1.4

    f_src_tourism = min(src_tourism, 1.0)
    f_dst_tourism = min(dst_tourism, 1.0)

    # --- Feature 9-10: Connectivity (hub score, normalised 0–1) ---
    f_src_conn = CONNECTIVITY.get(src, 1) / MAX_CONNECTIVITY
    f_dst_conn = CONNECTIVITY.get(dst, 1) / MAX_CONNECTIVITY

    # --- Feature 11: Elevation difference ---
    # High diff = challenging route = fewer alternatives = captive demand
    elev_diff = abs(src_data["altitude_ft"] - dst_data["altitude_ft"])
    f_elev_diff = elev_diff / 12000   # Normalise by max possible (~12000ft)

    # --- Feature 12-13: Individual altitudes ---
    f_src_alt = src_data["altitude_ft"] / 12000
    f_dst_alt = dst_data["altitude_ft"] / 12000

    # --- Feature 14: Mountain route flag ---
    f_mountain = int(src in MOUNTAIN_AIRPORTS or dst in MOUNTAIN_AIRPORTS)

    # --- Feature 15: Island route flag ---
    f_island = int(src in ISLAND_AIRPORTS or dst in ISLAND_AIRPORTS)

    # --- Feature 16: Northeast India route ---
    f_northeast = int(src in NORTHEAST_AIRPORTS or dst in NORTHEAST_AIRPORTS)

    # --- Feature 17: Season (1–4) ---
    # Encoded as a float; the model will learn seasonal patterns
    f_season = season / 4.0   # Normalise to 0–1

    # --- Feature 18: Weekend flag ---
    f_weekend = is_weekend

    return np.array([
        f_distance,       # 0
        f_log_distance,   # 1
        f_stol_both,      # 2
        f_stol_either,    # 3
        f_src_pop,        # 4
        f_dst_pop,        # 5
        f_src_tourism,    # 6
        f_dst_tourism,    # 7
        f_src_conn,       # 8
        f_dst_conn,       # 9
        f_elev_diff,      # 10
        f_src_alt,        # 11
        f_dst_alt,        # 12
        f_mountain,       # 13
        f_island,         # 14
        f_northeast,      # 15
        f_season,         # 16
        f_weekend,        # 17
    ], dtype=np.float32)


# Human-readable feature names (used for feature importance display)
FEATURE_NAMES = [
    "Distance (km)",
    "Log Distance",
    "Both STOL airports",
    "At least one STOL",
    "Origin population",
    "Destination population",
    "Origin tourism score",
    "Destination tourism score",
    "Origin hub connectivity",
    "Destination hub connectivity",
    "Elevation difference",
    "Origin altitude",
    "Destination altitude",
    "Mountain route",
    "Island route",
    "Northeast India route",
    "Season",
    "Weekend",
]
