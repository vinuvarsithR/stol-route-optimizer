"""
optimizer/graph.py
==================
Defines the city network graph for STOL route optimization.

Phase 2 additions:
  - altitude_ft  : airport elevation (used for density altitude calc)
  - avg_temp_c   : average annual temperature (used if no live weather)
"""

import math

CITIES = {
    "DEL": {
        "name": "Delhi", "state": "Delhi",
        "lat": 28.5665, "lon": 77.1031,
        "stol": False, "runway_m": 4430,
        "altitude_ft": 777, "avg_temp_c": 25.0,
    },
    "BOM": {
        "name": "Mumbai", "state": "Maharashtra",
        "lat": 19.0896, "lon": 72.8656,
        "stol": False, "runway_m": 3660,
        "altitude_ft": 11, "avg_temp_c": 27.0,
    },
    "BLR": {
        "name": "Bengaluru", "state": "Karnataka",
        "lat": 13.1986, "lon": 77.7066,
        "stol": False, "runway_m": 4000,
        "altitude_ft": 3008, "avg_temp_c": 24.0,
    },
    "SHL": {
        "name": "Shimla", "state": "Himachal Pradesh",
        "lat": 31.0818, "lon": 77.0674,
        "stol": True, "runway_m": 1200,
        "altitude_ft": 5072, "avg_temp_c": 13.0,
    },
    "KUU": {
        "name": "Kullu-Manali", "state": "Himachal Pradesh",
        "lat": 31.8787, "lon": 77.1544,
        "stol": True, "runway_m": 1372,
        "altitude_ft": 3800, "avg_temp_c": 14.0,
    },
    "DHM": {
        "name": "Dharamsala (Gaggal)", "state": "Himachal Pradesh",
        "lat": 32.1651, "lon": 76.2635,
        "stol": True, "runway_m": 1372,
        "altitude_ft": 2525, "avg_temp_c": 18.0,
    },
    "IXC": {
        "name": "Chandigarh", "state": "Punjab",
        "lat": 30.6735, "lon": 76.7885,
        "stol": False, "runway_m": 2900,
        "altitude_ft": 1012, "avg_temp_c": 23.0,
    },
    "JLR": {
        "name": "Jabalpur", "state": "Madhya Pradesh",
        "lat": 23.1778, "lon": 80.0520,
        "stol": True, "runway_m": 1800,
        "altitude_ft": 1624, "avg_temp_c": 26.0,
    },
    "AGX": {
        "name": "Agatti Island", "state": "Lakshadweep",
        "lat": 10.8237, "lon": 72.1760,
        "stol": True, "runway_m": 1204,
        "altitude_ft": 14, "avg_temp_c": 29.0,
    },
    "COH": {
        "name": "Cooch Behar", "state": "West Bengal",
        "lat": 26.3303, "lon": 89.4672,
        "stol": True, "runway_m": 1372,
        "altitude_ft": 138, "avg_temp_c": 24.0,
    },
    "IXH": {
        "name": "Kailashahar", "state": "Tripura",
        "lat": 24.3082, "lon": 92.0072,
        "stol": True, "runway_m": 1500,
        "altitude_ft": 98, "avg_temp_c": 24.0,
    },
    "LEN": {
        "name": "Leh", "state": "Ladakh",
        "lat": 34.1359, "lon": 77.5465,
        "stol": False, "runway_m": 3658,
        "altitude_ft": 10682, "avg_temp_c": 7.0,
    },
    "SXR": {
        "name": "Srinagar", "state": "J&K",
        "lat": 33.9871, "lon": 74.7742,
        "stol": False, "runway_m": 2900,
        "altitude_ft": 5199, "avg_temp_c": 13.0,
    },
    "PYB": {
        "name": "Jeypore", "state": "Odisha",
        "lat": 18.8799, "lon": 82.5520,
        "stol": True, "runway_m": 1530,
        "altitude_ft": 1952, "avg_temp_c": 26.0,
    },
    "HYD": {
        "name": "Hyderabad", "state": "Telangana",
        "lat": 17.2403, "lon": 78.4294,
        "stol": False, "runway_m": 4260,
        "altitude_ft": 2024, "avg_temp_c": 27.0,
    },
    "CCU": {
        "name": "Kolkata", "state": "West Bengal",
        "lat": 22.6547, "lon": 88.4467,
        "stol": False, "runway_m": 3627,
        "altitude_ft": 16, "avg_temp_c": 26.0,
    },
    "MAA": {
        "name": "Chennai", "state": "Tamil Nadu",
        "lat": 12.9941, "lon": 80.1709,
        "stol": False, "runway_m": 3658,
        "altitude_ft": 52, "avg_temp_c": 29.0,
    },
    "IXU": {
        "name": "Aurangabad", "state": "Maharashtra",
        "lat": 19.8627, "lon": 75.3981,
        "stol": True, "runway_m": 2745,
        "altitude_ft": 1911, "avg_temp_c": 25.0,
    },
}

ROUTES = [
    ("DEL", "IXC"), ("DEL", "SHL"), ("DEL", "KUU"), ("DEL", "DHM"),
    ("DEL", "LEN"), ("DEL", "SXR"), ("DEL", "JLR"), ("DEL", "HYD"),
    ("DEL", "BOM"), ("DEL", "BLR"), ("DEL", "MAA"), ("DEL", "CCU"),
    ("BOM", "HYD"), ("BOM", "BLR"), ("BOM", "IXU"), ("BOM", "MAA"),
    ("BLR", "MAA"), ("BLR", "HYD"), ("BLR", "AGX"),
    ("MAA", "HYD"),
    ("CCU", "COH"), ("CCU", "IXH"), ("CCU", "PYB"),
    ("IXC", "SHL"), ("IXC", "KUU"), ("IXC", "DHM"), ("IXC", "SXR"),
    ("SHL", "KUU"), ("SHL", "DHM"),
    ("SXR", "LEN"),
    ("HYD", "JLR"), ("BOM", "JLR"),
    ("BOM", "AGX"), ("MAA", "AGX"),
    ("CCU", "IXH"),
]

def haversine_km(city1_code: str, city2_code: str) -> float:
    R = 6371
    lat1 = math.radians(CITIES[city1_code]["lat"])
    lat2 = math.radians(CITIES[city2_code]["lat"])
    dlat = lat2 - lat1
    dlon = math.radians(CITIES[city2_code]["lon"] - CITIES[city1_code]["lon"])
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return round(6371 * 2 * math.asin(math.sqrt(a)), 1)

STOL_CRUISE_SPEED_KMH    = 350
COST_PER_KM_INR          = 8
STOL_INCOMPATIBILITY_FEE = 500

def compute_edge_weights(city_a: str, city_b: str) -> dict:
    dist      = haversine_km(city_a, city_b)
    time_min  = round((dist / STOL_CRUISE_SPEED_KMH) * 60 + 15, 1)
    cost      = dist * COST_PER_KM_INR
    both_stol = CITIES[city_a]["stol"] and CITIES[city_b]["stol"]
    if not both_stol:
        cost += STOL_INCOMPATIBILITY_FEE
    return {
        "distance_km":     dist,
        "time_min":        time_min,
        "cost_inr":        round(cost),
        "stol_compatible": both_stol,
    }
