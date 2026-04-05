"""
app.py — STOL Route Optimizer (Phase 3)
========================================
Phase 3 additions:
  POST /api/demand      → ML demand prediction for a single leg
  POST /api/full        → Optimize + assess + demand in one call

All routes:
  GET  /                → UI
  GET  /api/cities      → City list
  GET  /api/stats       → Graph stats
  GET  /api/aircraft    → Aircraft profiles
  POST /api/optimize    → Route optimization
  POST /api/assess      → STOL constraint assessment
  POST /api/demand      → ML demand prediction
  POST /api/full        → Combined: optimize + assess + demand
"""

import os
from flask import Flask, render_template, request, jsonify
from optimizer import find_optimal_route, get_all_cities, get_graph_stats
from optimizer import assess_route, AIRCRAFT_PROFILES
from optimizer import predict_demand, predict_route_demand

app = Flask(__name__)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/cities")
def cities():
    return jsonify({"cities": get_all_cities()})


@app.route("/api/stats")
def stats():
    return jsonify(get_graph_stats())


@app.route("/api/aircraft")
def aircraft():
    profiles = []
    for key, p in AIRCRAFT_PROFILES.items():
        profiles.append({
            "id": key, "name": p.name, "seats": p.seats,
            "max_payload_kg": p.max_payload_kg, "stol_todr_m": p.stol_todr_m,
            "stol_ldr_m": p.stol_ldr_m, "max_range_km": p.max_range_km,
            "cruise_speed_kmh": p.cruise_speed_kmh,
        })
    return jsonify({"aircraft": profiles})


@app.route("/api/optimize", methods=["POST"])
def optimize():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid JSON body."}), 400
    source       = data.get("source", "").strip().upper()
    destination  = data.get("destination", "").strip().upper()
    optimize_for = data.get("optimize_for", "cost")
    stol_only    = bool(data.get("stol_only", False))
    if not source or not destination:
        return jsonify({"error": "Source and destination are required."}), 400
    result = find_optimal_route(source, destination, optimize_for, stol_only)
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result)


@app.route("/api/assess", methods=["POST"])
def assess():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid JSON body."}), 400
    source       = data.get("source", "").strip().upper()
    destination  = data.get("destination", "").strip().upper()
    optimize_for = data.get("optimize_for", "cost")
    stol_only    = bool(data.get("stol_only", False))
    aircraft_id  = data.get("aircraft_id", "lat_s1")
    payload_kg   = float(data.get("payload_kg", 720))
    if not source or not destination:
        return jsonify({"error": "Source and destination are required."}), 400
    route = find_optimal_route(source, destination, optimize_for, stol_only)
    if "error" in route:
        return jsonify(route), 400
    if aircraft_id not in AIRCRAFT_PROFILES:
        return jsonify({"error": f"Unknown aircraft: {aircraft_id}"}), 400
    aircraft = AIRCRAFT_PROFILES[aircraft_id]
    payload_kg = min(payload_kg, aircraft.max_payload_kg)
    assessment = assess_route(route["path_nodes"], route["legs"], aircraft, payload_kg)
    return jsonify({"route": route, "assessment": assessment,
                    "aircraft": {"id": aircraft_id, "name": aircraft.name}})


# ---------------------------------------------------------------
# Phase 3: Demand prediction (single leg)
# ---------------------------------------------------------------
@app.route("/api/demand", methods=["POST"])
def demand():
    """
    Predicts weekly passenger demand for a single route leg.

    Body: { "src": "DEL", "dst": "SHL", "season": 3, "is_weekend": 0 }

    season: 1=Winter, 2=Spring, 3=Summer, 4=Autumn
    """
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid JSON."}), 400

    src        = data.get("src", "").strip().upper()
    dst        = data.get("dst", "").strip().upper()
    season     = int(data.get("season", 2))
    is_weekend = int(data.get("is_weekend", 0))

    if not src or not dst:
        return jsonify({"error": "src and dst are required."}), 400

    result = predict_demand(src, dst, season, is_weekend)
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result)


# ---------------------------------------------------------------
# Phase 3: Full pipeline — optimize + assess + demand in one shot
# ---------------------------------------------------------------
@app.route("/api/full", methods=["POST"])
def full_pipeline():
    """
    The main endpoint used by the Phase 3 frontend.
    Runs all three engines and returns combined results.

    Body:
    {
      "source":       "DEL",
      "destination":  "SHL",
      "optimize_for": "cost",
      "stol_only":    false,
      "aircraft_id":  "lat_s1",
      "payload_kg":   720,
      "season":       3,
      "is_weekend":   0
    }
    """
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid JSON."}), 400

    source       = data.get("source", "").strip().upper()
    destination  = data.get("destination", "").strip().upper()
    optimize_for = data.get("optimize_for", "cost")
    stol_only    = bool(data.get("stol_only", False))
    aircraft_id  = data.get("aircraft_id", "lat_s1")
    payload_kg   = float(data.get("payload_kg", 720))
    season       = int(data.get("season", 2))
    is_weekend   = int(data.get("is_weekend", 0))

    if not source or not destination:
        return jsonify({"error": "Source and destination are required."}), 400

    # Step 1: Route optimization
    route = find_optimal_route(source, destination, optimize_for, stol_only)
    if "error" in route:
        return jsonify(route), 400

    # Step 2: STOL constraint assessment
    if aircraft_id not in AIRCRAFT_PROFILES:
        return jsonify({"error": f"Unknown aircraft: {aircraft_id}"}), 400
    aircraft_obj = AIRCRAFT_PROFILES[aircraft_id]
    payload_kg   = min(payload_kg, aircraft_obj.max_payload_kg)
    assessment   = assess_route(route["path_nodes"], route["legs"],
                                aircraft_obj, payload_kg)

    # Step 3: ML demand prediction per leg
    demand_result = predict_route_demand(route["path_nodes"], route["legs"], season)

    return jsonify({
        "route":      route,
        "assessment": assessment,
        "demand":     demand_result,
        "aircraft":   {"id": aircraft_id, "name": aircraft_obj.name},
        "season":     season,
    })


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
