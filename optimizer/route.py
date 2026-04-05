"""
optimizer/route.py
==================
The core optimization engine.

Uses NetworkX to build a weighted graph of Indian cities and
finds the optimal path between source and destination.

We support THREE optimization modes:
  1. "cost"     → Dijkstra on cost_inr weight
  2. "time"     → Dijkstra on time_min weight
  3. "distance" → Dijkstra on distance_km weight

NetworkX's shortest_path algorithm uses Dijkstra internally
when given a weight parameter — O((V + E) log V) complexity.
"""

import networkx as nx
from .graph import CITIES, ROUTES, compute_edge_weights


# ------------------------------------------------------------------
# BUILD THE GRAPH (called once at app startup)
# ------------------------------------------------------------------

def build_graph() -> nx.Graph:
    """
    Constructs a weighted undirected graph.
    
    Nodes = city codes (e.g., "DEL", "BOM")
    Edges = valid flight routes, each carrying distance/time/cost attributes
    """

    G = nx.Graph()  # Undirected: DEL→BOM same as BOM→DEL

    # Add all cities as nodes with their metadata attached
    for code, info in CITIES.items():
        G.add_node(code, **info)   # **info unpacks the dict as node attributes

    # Add all route edges with computed weights
    for city_a, city_b in ROUTES:
        weights = compute_edge_weights(city_a, city_b)

        G.add_edge(
            city_a, city_b,
            distance_km    = weights["distance_km"],
            time_min       = weights["time_min"],
            cost_inr       = weights["cost_inr"],
            stol_compatible= weights["stol_compatible"],
        )

    return G


# Instantiate the graph once (module-level singleton)
# This avoids rebuilding it on every API request
FLIGHT_GRAPH = build_graph()


# ------------------------------------------------------------------
# MAIN OPTIMIZER FUNCTION
# ------------------------------------------------------------------

def find_optimal_route(
    source: str,
    destination: str,
    optimize_for: str = "cost",  # "cost" | "time" | "distance"
    stol_only: bool = False,      # If True, only allow STOL-compatible edges
) -> dict:
    """
    Finds the optimal route between source and destination.

    Parameters:
        source       : IATA code of origin city (e.g. "DEL")
        destination  : IATA code of destination city (e.g. "SHL")
        optimize_for : Weight to minimize ("cost", "time", or "distance")
        stol_only    : If True, exclude non-STOL edges from the graph

    Returns a dict with:
        path         : list of city codes along the route
        legs         : detailed info for each segment
        totals       : aggregated cost, time, distance
        stol_warning : message if route has non-STOL hops
    """

    # Validate inputs
    if source not in CITIES:
        return {"error": f"Unknown city code: {source}"}
    if destination not in CITIES:
        return {"error": f"Unknown city code: {destination}"}
    if source == destination:
        return {"error": "Source and destination cannot be the same."}

    # Map friendly names to graph weight keys
    weight_map = {
        "cost":     "cost_inr",
        "time":     "time_min",
        "distance": "distance_km",
    }
    if optimize_for not in weight_map:
        optimize_for = "cost"

    weight_key = weight_map[optimize_for]

    # Optionally build a filtered subgraph (STOL-only mode)
    if stol_only:
        # Build a brand new graph containing only STOL-compatible edges
        # (nx.edge_subgraph is read-only and has node membership issues)
        working_graph = nx.Graph()
        working_graph.add_nodes_from(FLIGHT_GRAPH.nodes(data=True))
        for u, v, d in FLIGHT_GRAPH.edges(data=True):
            if d.get("stol_compatible", False):
                working_graph.add_edge(u, v, **d)
    else:
        working_graph = FLIGHT_GRAPH

    # Run Dijkstra's shortest path algorithm
    try:
        path = nx.shortest_path(
            working_graph,
            source=source,
            target=destination,
            weight=weight_key,   # minimize this attribute
        )
    except nx.NetworkXNoPath:
        return {
            "error": f"No route found from {CITIES[source]['name']} "
                     f"to {CITIES[destination]['name']}. "
                     f"Try disabling STOL-only mode."
        }
    except nx.NodeNotFound:
        return {"error": "One or more cities not found in graph."}

    # ------------------------------------------------------------------
    # Build detailed leg-by-leg breakdown
    # ------------------------------------------------------------------
    legs = []
    total_cost     = 0
    total_time     = 0
    total_distance = 0
    has_non_stol   = False

    for i in range(len(path) - 1):
        city_a = path[i]
        city_b = path[i + 1]

        # Fetch edge attributes (the data we stored when building the graph)
        edge_data = FLIGHT_GRAPH[city_a][city_b]

        leg = {
            "from_code" : city_a,
            "to_code"   : city_b,
            "from_name" : CITIES[city_a]["name"],
            "to_name"   : CITIES[city_b]["name"],
            "distance_km"     : edge_data["distance_km"],
            "time_min"        : edge_data["time_min"],
            "cost_inr"        : edge_data["cost_inr"],
            "stol_compatible" : edge_data["stol_compatible"],
            "from_runway_m"   : CITIES[city_a]["runway_m"],
            "to_runway_m"     : CITIES[city_b]["runway_m"],
        }

        total_cost     += edge_data["cost_inr"]
        total_time     += edge_data["time_min"]
        total_distance += edge_data["distance_km"]

        if not edge_data["stol_compatible"]:
            has_non_stol = True

        legs.append(leg)

    # Format time as "Xhr Ymin"
    hours   = int(total_time // 60)
    minutes = int(total_time % 60)
    time_formatted = f"{hours}h {minutes}m" if hours else f"{minutes}m"

    # Compute path node details (for map rendering and constraint checks)
    path_nodes = [
        {
            "code"        : code,
            "name"        : CITIES[code]["name"],
            "state"       : CITIES[code]["state"],
            "lat"         : CITIES[code]["lat"],
            "lon"         : CITIES[code]["lon"],
            "stol"        : CITIES[code]["stol"],
            "runway_m"    : CITIES[code]["runway_m"],
            "altitude_ft" : CITIES[code]["altitude_ft"],   # Phase 2
            "avg_temp_c"  : CITIES[code]["avg_temp_c"],    # Phase 2
        }
        for code in path
    ]

    return {
        "path"          : path,
        "path_nodes"    : path_nodes,
        "legs"          : legs,
        "optimize_for"  : optimize_for,
        "totals": {
            "cost_inr"      : total_cost,
            "time_min"      : round(total_time, 1),
            "time_formatted": time_formatted,
            "distance_km"   : round(total_distance, 1),
            "stops"         : len(path) - 2,  # intermediate stops
        },
        "stol_warning"  : (
            "⚠️ Some legs use non-STOL airports (runway > 800m). "
            "Enable STOL-only mode for a fully STOL-compatible route."
            if has_non_stol else None
        ),
    }


# ------------------------------------------------------------------
# UTILITY: All cities list (for frontend dropdowns)
# ------------------------------------------------------------------

def get_all_cities() -> list:
    """Returns sorted list of city dicts for dropdown menus."""
    return sorted(
        [
            {
                "code"     : code,
                "name"     : info["name"],
                "state"    : info["state"],
                "stol"     : info["stol"],
                "runway_m" : info["runway_m"],
            }
            for code, info in CITIES.items()
        ],
        key=lambda x: x["name"],  # Alphabetical by city name
    )


# ------------------------------------------------------------------
# UTILITY: Graph stats (for the dashboard panel)
# ------------------------------------------------------------------

def get_graph_stats() -> dict:
    """Returns summary statistics about the flight network."""
    stol_cities  = sum(1 for c in CITIES.values() if c["stol"])
    stol_edges   = sum(
        1 for _, _, d in FLIGHT_GRAPH.edges(data=True)
        if d.get("stol_compatible")
    )

    return {
        "total_cities"      : FLIGHT_GRAPH.number_of_nodes(),
        "total_routes"      : FLIGHT_GRAPH.number_of_edges(),
        "stol_airports"     : stol_cities,
        "stol_only_routes"  : stol_edges,
    }
