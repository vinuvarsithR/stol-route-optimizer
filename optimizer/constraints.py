"""
optimizer/constraints.py
=========================
STOL Constraint Engine — Phase 2

Models the real physics that determine whether a STOL aircraft
can safely operate at a given airport on a given leg.

Physics modules:
  1. ISA Atmosphere    — Standard temperature at any altitude
  2. Density Altitude  — Effective altitude the aircraft "feels"
  3. Runway Correction — How much runway the aircraft actually needs
  4. Wind Component    — Headwind helps, tailwind hurts
  5. Payload-Range     — Heavier load = shorter safe range
  6. Feasibility Score — Composite 0–100 score per airport/leg

References:
  FAA Pilot's Handbook of Aeronautical Knowledge, Ch. 11
  ICAO Doc 9157 Aerodrome Design Manual
  Standard Atmosphere (ISA) model
"""

import math
from dataclasses import dataclass


# ================================================================
# AIRCRAFT PROFILE DATACLASS
# ================================================================
# Based on realistic twin-engine STOL commuter specs.
# Think: RUAG Dornier 228 class, or a hypothetical LAT-S1 concept.
# ================================================================

@dataclass
class AircraftProfile:
    """
    All runway figures are at sea level, ISA conditions,
    MTOW, zero wind, dry paved runway.
    """
    name:                str   = "LAT-S1 Concept"
    seats:               int   = 9          # Passenger capacity
    mtow_kg:             float = 3600.0     # Max Takeoff Weight (kg)
    oew_kg:              float = 2050.0     # Operating Empty Weight (kg)
    max_payload_kg:      float = 900.0      # Max payload: pax + baggage (kg)
    fuel_capacity_l:     float = 800.0      # Total fuel (litres)
    fuel_burn_lph:       float = 130.0      # Fuel burn at cruise (L/hr)
    cruise_speed_kmh:    float = 350.0      # Cruise speed
    stol_todr_m:         float = 400.0      # Takeoff distance required at SL, ISA, MTOW
    stol_ldr_m:          float = 380.0      # Landing distance required at SL, ISA, MTOW
    max_range_km:        float = 1200.0     # Max range at MTOW
    service_ceiling_ft:  float = 25000.0    # Service ceiling
    max_tailwind_kt:     float = 10.0       # Max demonstrated tailwind component


# Pre-defined aircraft options users can choose from
AIRCRAFT_PROFILES = {
    "lat_s1": AircraftProfile(
        name="LAT-S1 Concept",
        seats=9, mtow_kg=3600, oew_kg=2050, max_payload_kg=900,
        fuel_capacity_l=800, fuel_burn_lph=130, cruise_speed_kmh=350,
        stol_todr_m=400, stol_ldr_m=380, max_range_km=1200,
        service_ceiling_ft=25000, max_tailwind_kt=10,
    ),
    "dornier_228": AircraftProfile(
        name="Dornier 228-212",
        seats=19, mtow_kg=6400, oew_kg=3739, max_payload_kg=2000,
        fuel_capacity_l=1935, fuel_burn_lph=290, cruise_speed_kmh=428,
        stol_todr_m=780, stol_ldr_m=690, max_range_km=1100,
        service_ceiling_ft=28000, max_tailwind_kt=10,
    ),
    "cessna_208": AircraftProfile(
        name="Cessna 208B Grand Caravan",
        seats=13, mtow_kg=3969, oew_kg=2145, max_payload_kg=1360,
        fuel_capacity_l=1053, fuel_burn_lph=115, cruise_speed_kmh=341,
        stol_todr_m=520, stol_ldr_m=490, max_range_km=1982,
        service_ceiling_ft=25000, max_tailwind_kt=10,
    ),
}


# ================================================================
# MODULE 1: ISA (International Standard Atmosphere)
# ================================================================
# The ISA defines how temperature drops with altitude.
# This is the baseline all aircraft performance data is measured against.
#
# Formula: T_ISA (°C) = 15 - 1.98 × (altitude_ft / 1000)
# Valid up to 36,089 ft (tropopause)
# ================================================================

def isa_temperature_c(altitude_ft: float) -> float:
    """
    Returns the ISA standard temperature at a given altitude.
    At sea level: 15°C. Drops ~2°C per 1000 ft.
    """
    return 15.0 - (1.98 * altitude_ft / 1000.0)


# ================================================================
# MODULE 2: Density Altitude
# ================================================================
# Density altitude = the altitude the aircraft "feels" in terms of
# air density. Hot + high = very high density altitude = poor performance.
#
# DA = PA + 120 × (OAT − T_ISA)
# Where:
#   PA     = Pressure Altitude (we approximate as airport elevation)
#   OAT    = Outside Air Temperature (actual)
#   T_ISA  = ISA standard temperature at that altitude
#
# Rule of thumb: every +1000 ft of DA adds ~10% to takeoff distance.
# ================================================================

def density_altitude_ft(elevation_ft: float, oat_c: float) -> float:
    """
    Computes density altitude given airport elevation and temperature.
    
    Args:
        elevation_ft : Airport elevation above MSL in feet
        oat_c        : Outside Air Temperature in Celsius
    
    Returns:
        Density altitude in feet
    """
    t_isa = isa_temperature_c(elevation_ft)
    da = elevation_ft + 120.0 * (oat_c - t_isa)
    return round(da, 0)


# ================================================================
# MODULE 3: Runway Requirement Correction
# ================================================================
# Aircraft performance charts give TODR/LDR at sea level, ISA.
# We correct for actual density altitude using the standard factor:
#
#   Corrected_distance = Base_distance × (1 + 0.10 × DA_thousands)
#
# i.e., 10% more runway per 1000 ft of density altitude.
# This is a conservative but standard approximation from FAA guidance.
#
# Additionally:
#   - Tailwind: adds 10% per 2 kt of tailwind (very penalising)
#   - Headwind: reduces by 10% per 9 kt headwind
#   - Uphill slope: adds ~7% per 1% slope (not modelled here yet)
# ================================================================

def corrected_runway_required_m(
    base_distance_m: float,
    da_ft: float,
    wind_kt: float = 0.0,   # Positive = headwind, negative = tailwind
) -> float:
    """
    Corrects base TODR or LDR for actual density altitude and wind.

    Args:
        base_distance_m : Aircraft's published SL/ISA distance (m)
        da_ft           : Density altitude in feet
        wind_kt         : Wind component along runway.
                          Positive = headwind (beneficial)
                          Negative = tailwind (penalising)
    
    Returns:
        Actual runway distance required (metres)
    """

    # Density altitude correction: +10% per 1000 ft
    da_thousands = da_ft / 1000.0
    da_factor = 1.0 + (0.10 * da_thousands)

    # Wind correction
    if wind_kt >= 0:
        # Headwind: reduce by 10% per 9 kt (FAA formula approximation)
        wind_factor = 1.0 - (0.10 * wind_kt / 9.0)
        wind_factor = max(wind_factor, 0.5)   # Cap at 50% reduction
    else:
        # Tailwind: add 10% per 2 kt — very penalising
        wind_factor = 1.0 + (0.10 * abs(wind_kt) / 2.0)

    corrected = base_distance_m * da_factor * wind_factor
    return round(corrected, 1)


# ================================================================
# MODULE 4: Payload-Range Analysis
# ================================================================
# A heavier aircraft burns more fuel per km and has less range.
# We compute the effective range given a payload.
#
# Simplified linear model:
#   fuel_available = fuel_capacity - fuel_reserve (45min)
#   endurance_hr   = fuel_available / fuel_burn_lph
#   max_range_km   = endurance_hr × cruise_speed_kmh
#
# Payload penalty: each extra 100 kg above half payload reduces
# range by ~5% (approximation; real model uses drag polar).
# ================================================================

FUEL_DENSITY_KG_L = 0.803   # Jet A-1 fuel: ~0.8 kg/litre
FUEL_RESERVE_MIN  = 45       # FAA/DGCA minimum reserve: 45 minutes


def effective_range_km(
    aircraft: AircraftProfile,
    payload_kg: float,
) -> float:
    """
    Estimates effective range given current payload.
    
    Args:
        aircraft   : AircraftProfile instance
        payload_kg : Current payload (passengers + baggage) in kg
    
    Returns:
        Effective range in km (with 45-min fuel reserve)
    """
    # Clamp payload to aircraft limits
    payload_kg = min(payload_kg, aircraft.max_payload_kg)

    # Available fuel after holding reserve
    reserve_l = aircraft.fuel_burn_lph * (FUEL_RESERVE_MIN / 60.0)
    usable_fuel_l = aircraft.fuel_capacity_l - reserve_l

    # Endurance and base range
    endurance_hr = usable_fuel_l / aircraft.fuel_burn_lph
    base_range_km = endurance_hr * aircraft.cruise_speed_kmh

    # Payload penalty: payload above 50% of max reduces range slightly
    half_payload = aircraft.max_payload_kg / 2.0
    if payload_kg > half_payload:
        excess_ratio = (payload_kg - half_payload) / half_payload
        penalty = 1.0 - (0.08 * excess_ratio)   # Up to 8% range reduction
    else:
        penalty = 1.0

    return round(base_range_km * penalty, 1)


# ================================================================
# MODULE 5: Per-Airport Feasibility Assessment
# ================================================================

@dataclass
class AirportFeasibility:
    """Result of a single airport feasibility check."""
    airport_code:        str
    elevation_ft:        float
    oat_c:               float
    density_altitude_ft: float
    runway_available_m:  float
    todr_required_m:     float    # Takeoff distance required
    ldr_required_m:      float    # Landing distance required
    todr_margin_m:       float    # Positive = safe, negative = UNSAFE
    ldr_margin_m:        float
    can_takeoff:         bool
    can_land:            bool
    feasible:            bool
    score:               int      # 0–100 composite score
    warnings:            list
    notes:               str


def assess_airport(
    airport_code:  str,
    elevation_ft:  float,
    runway_m:      float,
    aircraft:      AircraftProfile,
    payload_kg:    float,
    oat_c:         float   = None,   # If None, use ISA standard
    wind_kt:       float   = 0.0,
) -> AirportFeasibility:
    """
    Full feasibility assessment for one aircraft at one airport.

    Args:
        airport_code : IATA code (for reference)
        elevation_ft : Airport elevation in feet
        runway_m     : Available runway length in metres
        aircraft     : AircraftProfile
        payload_kg   : Current payload in kg
        oat_c        : Actual temperature (default: ISA standard)
        wind_kt      : Runway wind component (+headwind / -tailwind)

    Returns:
        AirportFeasibility dataclass with full breakdown
    """

    warnings = []

    # Use ISA temperature if none provided
    if oat_c is None:
        oat_c = isa_temperature_c(elevation_ft)

    # Step 1: Compute density altitude
    da_ft = density_altitude_ft(elevation_ft, oat_c)

    # Step 2: Check service ceiling (airport must be below ceiling)
    if elevation_ft >= aircraft.service_ceiling_ft:
        warnings.append(f"Airport elevation exceeds aircraft service ceiling!")

    # Step 3: Payload-adjusted performance factor
    # Heavier = more runway needed. Linear interpolation.
    payload_ratio = min(payload_kg / aircraft.max_payload_kg, 1.0)

    # Scale the base runway requirement by payload (up to 15% increase at MTOW)
    payload_factor = 1.0 + (0.15 * payload_ratio)

    # Step 4: Corrected TODR and LDR
    todr_req = corrected_runway_required_m(
        aircraft.stol_todr_m * payload_factor, da_ft, wind_kt
    )
    ldr_req = corrected_runway_required_m(
        aircraft.stol_ldr_m * payload_factor, da_ft, wind_kt
    )

    # Step 5: Margins
    todr_margin = runway_m - todr_req
    ldr_margin  = runway_m - ldr_req

    can_takeoff = todr_margin >= 0
    can_land    = ldr_margin  >= 0
    feasible    = can_takeoff and can_land

    # Step 6: Warnings
    if da_ft > 8000:
        warnings.append(f"High density altitude ({int(da_ft):,} ft) — significant performance degradation.")
    if da_ft > 5000:
        warnings.append(f"Elevated density altitude ({int(da_ft):,} ft) — verify weight limits.")
    if wind_kt < -5:
        warnings.append(f"Tailwind component ({abs(wind_kt)} kt) increases runway requirement.")
    if not can_takeoff:
        warnings.append(f"Runway too short for takeoff! Need {todr_req:.0f}m, available {runway_m:.0f}m.")
    if not can_land:
        warnings.append(f"Runway too short for landing! Need {ldr_req:.0f}m, available {runway_m:.0f}m.")
    if todr_margin >= 0 and todr_margin < 100:
        warnings.append(f"Takeoff margin is very tight ({todr_margin:.0f}m). Consider reducing payload.")
    if ldr_margin >= 0 and ldr_margin < 100:
        warnings.append(f"Landing margin is very tight ({ldr_margin:.0f}m). Consider reducing payload.")

    # Step 7: Composite feasibility score (0–100)
    # Based on: runway margin, density altitude, tailwind penalty
    if not feasible:
        score = 0
    else:
        # Runway margin score: 40 points
        worst_margin = min(todr_margin, ldr_margin)
        margin_score = min(40, int(40 * (worst_margin / 300)))  # Full marks at 300m+ margin

        # Density altitude score: 40 points (penalise high DA)
        da_score = max(0, int(40 * (1 - da_ft / 12000)))

        # Wind score: 20 points
        if wind_kt >= 0:
            wind_score = 20
        else:
            wind_score = max(0, int(20 * (1 + wind_kt / aircraft.max_tailwind_kt)))

        score = margin_score + da_score + wind_score

    # Human-readable notes
    notes = (
        f"DA={int(da_ft):,}ft | "
        f"TODR={todr_req:.0f}m (margin {todr_margin:+.0f}m) | "
        f"LDR={ldr_req:.0f}m (margin {ldr_margin:+.0f}m)"
    )

    return AirportFeasibility(
        airport_code        = airport_code,
        elevation_ft        = elevation_ft,
        oat_c               = oat_c,
        density_altitude_ft = da_ft,
        runway_available_m  = runway_m,
        todr_required_m     = todr_req,
        ldr_required_m      = ldr_req,
        todr_margin_m       = round(todr_margin, 1),
        ldr_margin_m        = round(ldr_margin, 1),
        can_takeoff         = can_takeoff,
        can_land            = can_land,
        feasible            = feasible,
        score               = score,
        warnings            = warnings,
        notes               = notes,
    )


# ================================================================
# MODULE 6: Full Route Feasibility Assessment
# ================================================================

def assess_route(
    path_nodes:  list,      # From find_optimal_route()["path_nodes"]
    legs:        list,      # From find_optimal_route()["legs"]
    aircraft:    AircraftProfile,
    payload_kg:  float,
) -> dict:
    """
    Runs feasibility checks on every airport and leg in a route.

    Returns:
        {
          "route_feasible"  : bool,
          "payload_kg"      : float,
          "effective_range" : float,
          "airport_checks"  : [ AirportFeasibility dict per node ],
          "leg_checks"      : [ per-leg feasibility dict ],
          "overall_score"   : int (0–100, average of airport scores),
          "critical_issues" : [ list of blocking problems ],
        }
    """

    airport_checks = []
    critical_issues = []

    # Assess each airport in the path
    for node in path_nodes:
        check = assess_airport(
            airport_code = node["code"],
            elevation_ft = node["altitude_ft"],
            runway_m     = node["runway_m"],
            aircraft     = aircraft,
            payload_kg   = payload_kg,
        )
        airport_checks.append(check)

        if not check.feasible:
            critical_issues.append(
                f"{node['name']} ({node['code']}): Aircraft cannot operate — "
                f"runway too short after density altitude correction."
            )

    # Assess each leg for range feasibility
    leg_checks = []
    eff_range = effective_range_km(aircraft, payload_kg)

    for leg in legs:
        dist = leg["distance_km"]
        within_range = dist <= eff_range
        range_margin_km = round(eff_range - dist, 1)

        if not within_range:
            critical_issues.append(
                f"Leg {leg['from_code']} → {leg['to_code']}: "
                f"{dist} km exceeds effective range ({eff_range} km) at current payload."
            )

        leg_checks.append({
            "from_code"       : leg["from_code"],
            "to_code"         : leg["to_code"],
            "distance_km"     : dist,
            "effective_range" : eff_range,
            "within_range"    : within_range,
            "range_margin_km" : range_margin_km,
        })

    # Overall score = average of airport scores
    scores = [c.score for c in airport_checks]
    overall_score = round(sum(scores) / len(scores)) if scores else 0

    route_feasible = len(critical_issues) == 0

    # Convert dataclasses to dicts for JSON serialisation
    def check_to_dict(c: AirportFeasibility) -> dict:
        return {
            "airport_code"        : c.airport_code,
            "elevation_ft"        : c.elevation_ft,
            "oat_c"               : c.oat_c,
            "density_altitude_ft" : c.density_altitude_ft,
            "runway_available_m"  : c.runway_available_m,
            "todr_required_m"     : c.todr_required_m,
            "ldr_required_m"      : c.ldr_required_m,
            "todr_margin_m"       : c.todr_margin_m,
            "ldr_margin_m"        : c.ldr_margin_m,
            "can_takeoff"         : c.can_takeoff,
            "can_land"            : c.can_land,
            "feasible"            : c.feasible,
            "score"               : c.score,
            "warnings"            : c.warnings,
            "notes"               : c.notes,
        }

    return {
        "route_feasible"  : route_feasible,
        "payload_kg"      : payload_kg,
        "effective_range" : eff_range,
        "airport_checks"  : [check_to_dict(c) for c in airport_checks],
        "leg_checks"      : leg_checks,
        "overall_score"   : overall_score,
        "critical_issues" : critical_issues,
    }
