/**
 * main.js — Phase 4 (Leaflet fixed edition)
 *
 * The blank map bug was caused by Leaflet initialising on a div
 * with zero dimensions (because it was hidden or inside a hidden parent).
 *
 * Fixes applied:
 *   1. Empty-state map: always visible, initialised on DOMContentLoaded
 *   2. Route map: created AFTER results div becomes visible, then
 *      map.invalidateSize() is called to force Leaflet to recalculate
 *      the container dimensions. This is the official Leaflet fix.
 */

"use strict";

const sourceSelect   = document.getElementById("source");
const destSelect     = document.getElementById("destination");
const stolOnly       = document.getElementById("stol-only");
const findBtn        = document.getElementById("find-route-btn");
const swapBtn        = document.getElementById("swap-btn");
const optimizeBtns   = document.querySelectorAll("#optimize-for .pill");
const seasonBtns     = document.querySelectorAll("#season-select .pill");
const aircraftSelect = document.getElementById("aircraft-select");
const payloadSlider  = document.getElementById("payload-slider");
const payloadBadge   = document.getElementById("payload-badge");
const isWeekend      = document.getElementById("is-weekend");

let optimizeFor = "cost";
let season      = 2;
let aircraftData= {};
let routeMap    = null;   // Leaflet map for results
let emptyMap    = null;   // Leaflet map for empty state
let routeLayers = [];     // Markers + polylines to clear between searches

// ── Pill toggles ──
function wirePills(btns, cb) {
  btns.forEach(b => b.addEventListener("click", () => {
    btns.forEach(x => x.classList.remove("active"));
    b.classList.add("active");
    cb(b.dataset.value);
  }));
}
wirePills(optimizeBtns, v => { optimizeFor = v; });
wirePills(seasonBtns,   v => { season = parseInt(v); });

swapBtn.addEventListener("click", () => {
  [sourceSelect.value, destSelect.value] = [destSelect.value, sourceSelect.value];
});

// ── Init ──
document.addEventListener("DOMContentLoaded", () => {
  loadCities();
  loadStats();
  loadAircraft();

  // Initialise the decorative empty-state map immediately.
  // The #empty-map div IS visible at this point so Leaflet gets real dimensions.
  emptyMap = L.map("empty-map", {
    center: [22.5, 80.5], zoom: 5,
    zoomControl: false, attributionControl: false,
    dragging: false, scrollWheelZoom: false,
    doubleClickZoom: false, keyboard: false,
  });
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    className: "map-tiles",
  }).addTo(emptyMap);
});

async function loadCities() {
  try {
    const data = await (await fetch("/api/cities")).json();
    data.cities.forEach(city => {
      const label = `${city.name} (${city.code})${city.stol ? " ✈" : ""} — ${city.state}`;
      [sourceSelect, destSelect].forEach(sel => {
        const opt = document.createElement("option");
        opt.value = city.code; opt.textContent = label;
        sel.appendChild(opt);
      });
    });
  } catch(e) { console.error(e); }
}

async function loadStats() {
  try {
    const d = await (await fetch("/api/stats")).json();
    countUp("stat-cities",      d.total_cities);
    countUp("stat-routes",      d.total_routes);
    countUp("stat-stol",        d.stol_airports);
    countUp("stat-stol-routes", d.stol_only_routes);
  } catch(e) { console.error(e); }
}

async function loadAircraft() {
  try {
    const data = await (await fetch("/api/aircraft")).json();
    aircraftSelect.innerHTML = "";
    data.aircraft.forEach((ac, i) => {
      aircraftData[ac.id] = ac;
      const opt = document.createElement("option");
      opt.value = ac.id; opt.textContent = ac.name;
      if (i === 0) opt.selected = true;
      aircraftSelect.appendChild(opt);
    });
    updateAircraftUI();
  } catch(e) { console.error(e); }
}

aircraftSelect.addEventListener("change", updateAircraftUI);

function updateAircraftUI() {
  const ac = aircraftData[aircraftSelect.value];
  if (!ac) return;
  payloadSlider.max   = ac.max_payload_kg;
  payloadSlider.value = Math.min(parseInt(payloadSlider.value), ac.max_payload_kg);
  document.getElementById("payload-max-label").textContent = ac.max_payload_kg + " kg";
  document.getElementById("ac-seats").textContent = ac.seats + " pax";
  document.getElementById("ac-todr").textContent  = ac.stol_todr_m + " m";
  document.getElementById("ac-range").textContent = ac.max_range_km + " km";
  document.getElementById("ac-speed").textContent = ac.cruise_speed_kmh + " km/h";
  document.getElementById("aircraft-card").classList.remove("hidden");
  updatePayload(ac);
}

payloadSlider.addEventListener("input", () => {
  const ac = aircraftData[aircraftSelect.value];
  if (ac) updatePayload(ac);
});

function updatePayload(ac) {
  const kg = parseInt(payloadSlider.value);
  payloadBadge.textContent = `${kg} kg · ~${Math.min(Math.round(kg/80), ac.seats)} pax`;
}

// ── Main button ──
findBtn.addEventListener("click", async () => {
  const source = sourceSelect.value, dest = destSelect.value, acId = aircraftSelect.value;
  if (!source) { alert("Please select an origin."); return; }
  if (!dest)   { alert("Please select a destination."); return; }
  if (!acId)   { alert("Please select an aircraft."); return; }
  if (source === dest) { alert("Origin and destination must differ."); return; }

  showState("loading");
  animateLoadSteps();

  try {
    const res = await fetch("/api/full", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        source, destination: dest,
        optimize_for: optimizeFor, stol_only: stolOnly.checked,
        aircraft_id: acId, payload_kg: parseInt(payloadSlider.value),
        season, is_weekend: isWeekend.checked ? 1 : 0,
      }),
    });
    const data = await res.json();
    if (!res.ok || data.error) { showError(data.error || "Failed."); return; }
    renderAll(data);
    showState("results");

    // ── KEY FIX: After results div becomes visible, tell Leaflet
    // to recalculate the map container size. Without this, Leaflet
    // renders into a 0×0 box and shows a grey blank tile.
    setTimeout(() => { if (routeMap) routeMap.invalidateSize(); }, 50);

  } catch(e) { showError("Network error."); console.error(e); }
});

function animateLoadSteps() {
  ["ls1","ls2","ls3"].forEach(id => document.getElementById(id)?.classList.remove("active"));
  let i = 0; const ids = ["ls1","ls2","ls3"];
  const iv = setInterval(() => {
    if (i < ids.length) { document.getElementById(ids[i])?.classList.add("active"); i++; }
    else clearInterval(iv);
  }, 700);
}

// ================================================================
// RENDER
// ================================================================

function renderAll(data) {
  const { route, assessment, demand } = data;
  const t = route.totals;

  document.getElementById("rb-from").textContent = route.path_nodes[0].name;
  document.getElementById("rb-to").textContent   = route.path_nodes[route.path_nodes.length-1].name;
  document.getElementById("rb-meta").textContent =
    `Optimized for ${route.optimize_for} · ${route.path_nodes.length-1} leg(s) · ${["","Winter","Spring","Summer","Autumn"][demand.season]} season`;

  const score = assessment.overall_score;
  document.getElementById("dial-val").textContent = score;
  setTimeout(() => {
    const c = document.getElementById("dial-circle");
    c.style.strokeDashoffset = 213.6 - (score/100)*213.6;
    c.style.stroke = score>=70 ? "var(--green)" : score>=40 ? "var(--amber)" : "var(--red)";
  }, 100);

  if (assessment.critical_issues.length) {
    document.getElementById("issues-list").innerHTML = assessment.critical_issues.map(i=>`<li>${i}</li>`).join("");
    show("issues-banner"); hide("clear-banner");
  } else { hide("issues-banner"); show("clear-banner"); }

  if (route.stol_warning) { document.getElementById("stol-warning-text").textContent = route.stol_warning; show("stol-warning"); }
  else hide("stol-warning");

  document.getElementById("total-cost").textContent     = `₹${t.cost_inr.toLocaleString("en-IN")}`;
  document.getElementById("total-time").textContent     = t.time_formatted;
  document.getElementById("total-distance").textContent = `${t.distance_km} km`;
  document.getElementById("total-stops").textContent    = t.stops===0 ? "Direct" : `${t.stops} stop${t.stops>1?"s":""}`;

  renderLeafletMap(route.path_nodes);
  renderDemand(demand);
  renderFeasibility(route.path_nodes, assessment.airport_checks);
  renderRange(assessment);
  renderLegsTable(route.legs);
}

// ── LEAFLET MAP ──
function renderLeafletMap(nodes) {
  // Clear previous layers
  routeLayers.forEach(l => l.remove());
  routeLayers = [];

  if (!routeMap) {
    // Create map for the first time
    routeMap = L.map("route-map", { zoomControl: true, attributionControl: false });
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      className: "map-tiles",
    }).addTo(routeMap);
  }

  const latlngs = nodes.map(n => [n.lat, n.lon]);

  // Dashed route line
  const line = L.polyline(latlngs, {
    color: "#f59e0b", weight: 2.5, opacity: 0.9, dashArray: "8 5",
  }).addTo(routeMap);
  routeLayers.push(line);

  // Markers
  nodes.forEach((node, i) => {
    const isEndpoint = i===0 || i===nodes.length-1;
    const color = node.stol ? "#34d399" : "#f59e0b";
    const size  = isEndpoint ? 14 : 10;
    const role  = i===0 ? "Origin" : i===nodes.length-1 ? "Destination" : "Transit";

    const icon = L.divIcon({
      className: "",
      html: `<div style="
        width:${size}px;height:${size}px;border-radius:50%;
        background:${color};
        border:${isEndpoint ? "2px solid #fff" : `1px solid ${color}`};
        box-shadow:0 0 0 3px ${color}44,0 2px 6px rgba(0,0,0,0.5);
        cursor:pointer;
      "></div>`,
      iconSize: [size,size], iconAnchor: [size/2,size/2],
    });

    const marker = L.marker([node.lat, node.lon], { icon })
      .addTo(routeMap)
      .bindPopup(`
        <div style="font-family:'Exo 2',sans-serif;min-width:160px">
          <div style="font-size:15px;font-weight:800;margin-bottom:2px">${node.code} — ${node.name}</div>
          <div style="font-size:11px;color:#7a93b8;margin-bottom:7px">${node.state} · ${role}</div>
          <div style="font-size:11px;line-height:1.8">
            Runway: <strong style="color:${color}">${node.runway_m}m${node.stol?" · STOL ✓":""}</strong><br/>
            Elevation: <strong>${node.altitude_ft.toLocaleString()} ft</strong>
          </div>
        </div>`, { maxWidth: 220 });

    routeLayers.push(marker);
  });

  const bounds = L.latLngBounds(latlngs).pad(0.25);
  routeMap.fitBounds(bounds);
}

// ── DEMAND ──
function renderDemand(demand) {
  document.getElementById("demand-kpis").innerHTML = `
    <div class="dkpi"><div class="dkpi-val">${Math.round(demand.total_pax_week)}</div><div class="dkpi-key">Total pax/week</div></div>
    <div class="dkpi"><div class="dkpi-val">${Math.round(demand.avg_pax_week)}</div><div class="dkpi-key">Avg per leg</div></div>
    <div class="dkpi"><div class="dkpi-val">${demand.recommended_flights_per_week}×</div><div class="dkpi-key">Flights/week</div></div>
    <div class="dkpi"><div class="dkpi-val" style="font-size:12px;line-height:1.4">${demand.bottleneck_leg}</div><div class="dkpi-key">Bottleneck</div></div>
  `;

  const legsEl = document.getElementById("demand-legs");
  legsEl.innerHTML = "";
  let firstLeg = null;

  demand.legs.forEach((leg, i) => {
    const pred = leg.demand.prediction, cat = leg.demand.category;
    if (i===0) firstLeg = leg.demand;
    const maxV  = pred.ci_high * 1.1;
    const lowP  = (pred.ci_low  / maxV * 100).toFixed(1);
    const highP = (pred.ci_high / maxV * 100).toFixed(1);
    const ptP   = (pred.pax_per_week / maxV * 100).toFixed(1);
    const card  = document.createElement("div");
    card.className = "dleg";
    card.innerHTML = `
      <div class="dleg-top">
        <div><span class="dleg-route">${leg.from_code} → ${leg.to_code}</span><span class="dleg-dist">${leg.distance_km} km</span></div>
        <span class="dleg-cat" style="background:${cat.color}22;color:${cat.color};border:1px solid ${cat.color}44">${cat.label}</span>
      </div>
      <div class="dleg-stats">
        <div><div class="dleg-stat-val">${Math.round(pred.pax_per_week)}</div><div class="dleg-stat-key">pax/week</div></div>
        <div><div class="dleg-stat-val">${Math.round(pred.pax_per_day)}</div><div class="dleg-stat-key">pax/day</div></div>
        <div><div class="dleg-stat-val">${Math.round(pred.ci_low)}–${Math.round(pred.ci_high)}</div><div class="dleg-stat-key">90% CI</div></div>
      </div>
      <div class="ci-bar">
        <div class="ci-fill" style="width:${highP}%;margin-left:${lowP}%"></div>
        <div class="ci-point" style="left:${ptP}%"></div>
      </div>
      <div style="font-size:10px;color:var(--text-3);margin-top:5px;font-style:italic">${cat.description}</div>
    `;
    legsEl.appendChild(card);
  });

  if (firstLeg) { renderSeasonBars(firstLeg.seasonal_forecast); renderFiList(firstLeg.top_drivers); }
}

function renderSeasonBars(seasonal) {
  const el = document.getElementById("season-bars");
  const names=Object.keys(seasonal), vals=Object.values(seasonal), maxV=Math.max(...vals);
  const colors=["#38bdf8","#34d399","#f59e0b","#a78bfa"], emojis=["❄️","🌸","☀️","🍂"];
  el.innerHTML="";
  names.forEach((name,i) => {
    const pct=Math.max((vals[i]/maxV)*65,3);
    const col=document.createElement("div"); col.className="sbar-col";
    col.innerHTML=`<div class="sbar-val">${Math.round(vals[i])}</div><div class="sbar" style="height:${pct}px;background:${colors[i]};opacity:.85"></div><div class="sbar-label">${emojis[i]} ${name.slice(0,3)}</div>`;
    el.appendChild(col);
  });
}

function renderFiList(drivers) {
  const el=document.getElementById("fi-list"); el.innerHTML="";
  const maxI=Math.max(...drivers.map(d=>d.importance));
  drivers.forEach(d => {
    const pct=(d.importance/maxI*100).toFixed(1);
    const row=document.createElement("div"); row.className="fi-row";
    row.innerHTML=`<div class="fi-name">${d.feature}</div><div class="fi-track"><div class="fi-fill" style="width:${pct}%"></div></div><div class="fi-pct">${(d.importance*100).toFixed(1)}%</div>`;
    el.appendChild(row);
  });
}

function renderFeasibility(nodes, checks) {
  const grid=document.getElementById("feas-grid"); grid.innerHTML="";
  const nm={}; nodes.forEach(n=>{nm[n.code]=n;});
  checks.forEach(c => {
    const node=nm[c.airport_code]||{};
    const sc=c.score>=70?"high":c.score>=40?"mid":"low";
    const cc=c.feasible?(c.score>=70?"pass":"warn"):"fail";
    const ratio=Math.min(Math.max(c.todr_required_m,c.ldr_required_m)/c.runway_available_m,1);
    const bc=c.feasible?(ratio>.85?"warn":"ok"):"bad";
    const mc=c.todr_margin_m>=0?"var(--green)":"var(--red)";
    const w=c.warnings.slice(0,2).map(w=>`<div class="fcard-warn-text">${w}</div>`).join("");
    const card=document.createElement("div"); card.className=`fcard ${cc}`;
    card.innerHTML=`
      <div class="fcard-header"><div><div class="fcard-code">${c.airport_code}</div><div class="fcard-name">${node.name||""}</div></div><div class="score-ring ${sc}">${c.score}</div></div>
      <div class="fcard-rows">
        <div class="fcard-row"><span>Elevation</span><span>${c.elevation_ft.toLocaleString()} ft</span></div>
        <div class="fcard-row"><span>Density Alt.</span><span>${c.density_altitude_ft.toLocaleString()} ft</span></div>
        <div class="fcard-row"><span>TODR Req.</span><span>${c.todr_required_m} m</span></div>
        <div class="fcard-row"><span>Runway</span><span>${c.runway_available_m} m</span></div>
        <div class="fcard-row"><span>Margin</span><span style="color:${mc}">${c.todr_margin_m>=0?"+":""}${c.todr_margin_m} m</span></div>
      </div>
      <div class="rw-bar-wrap"><div class="rw-bar-label">Runway utilisation</div><div class="rw-bar-track"><div class="rw-bar-fill ${bc}" style="width:${(ratio*100).toFixed(1)}%"></div></div></div>${w}`;
    grid.appendChild(card);
  });
}

function renderRange(a) {
  document.getElementById("range-summary").innerHTML=`
    <div class="rstat"><div class="rstat-val">${a.effective_range} km</div><div class="rstat-key">Effective Range</div></div>
    <div class="rstat"><div class="rstat-val">${a.payload_kg} kg</div><div class="rstat-key">Payload</div></div>
    <div class="rstat"><div class="rstat-val" style="color:${a.route_feasible?"var(--green)":"var(--red)"}">${a.route_feasible?"FEASIBLE":"ISSUES"}</div><div class="rstat-key">Status</div></div>`;
  const bEl=document.getElementById("range-bars"); bEl.innerHTML="";
  a.leg_checks.forEach(leg => {
    const ratio=Math.min(leg.distance_km/leg.effective_range,1), ok=leg.within_range;
    const txt=ok?`+${leg.range_margin_km} km margin`:`${Math.abs(leg.range_margin_km)} km OVER`;
    const row=document.createElement("div"); row.className="rbar-row";
    row.innerHTML=`<div class="rbar-label">${leg.from_code}→${leg.to_code} <span style="color:var(--text-3)">(${leg.distance_km}km)</span></div><div class="rbar-track-wrap"><div class="rbar-track"><div class="rbar-fill ${ok?"ok":"over"}" style="width:${(ratio*100).toFixed(1)}%"></div></div></div><div class="rbar-status ${ok?"ok":"over"}">${txt}</div>`;
    bEl.appendChild(row);
  });
}

function renderLegsTable(legs) {
  const tbody=document.getElementById("legs-body"); tbody.innerHTML="";
  legs.forEach(leg => {
    const b=leg.stol_compatible
      ?`<span class="stol-yes"><i class="ph ph-check-circle"></i>Yes</span>`
      :`<span class="stol-no"><i class="ph ph-x-circle"></i>No</span>`;
    const row=document.createElement("tr");
    row.innerHTML=`<td><strong>${leg.from_name}</strong><br/><small>${leg.from_code}</small></td><td><strong>${leg.to_name}</strong><br/><small>${leg.to_code}</small></td><td>${leg.distance_km}km</td><td>${fmtTime(leg.time_min)}</td><td>₹${leg.cost_inr.toLocaleString("en-IN")}</td><td>${b}</td>`;
    tbody.appendChild(row);
  });
}

// ── UTILS ──
function fmtTime(m) { const h=Math.floor(m/60),mn=Math.round(m%60); return h>0?`${h}h ${mn}m`:`${mn}m`; }
function countUp(id, target) {
  const el=document.getElementById(id); if(!el)return;
  let n=0; const iv=setInterval(()=>{ n+=target/20; if(n>=target){el.textContent=target;clearInterval(iv);}else el.textContent=Math.floor(n); },30);
}
function show(id){document.getElementById(id)?.classList.remove("hidden");}
function hide(id){document.getElementById(id)?.classList.add("hidden");}
function showState(state){
  ["empty-state","loading-state","error-state","results"].forEach(hide);
  show(state==="empty"?"empty-state":state==="loading"?"loading-state":state==="error"?"error-state":"results");
}
function showError(msg){document.getElementById("error-message").textContent=msg;showState("error");}
