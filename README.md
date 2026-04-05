# ✈ STOL Route Optimizer

> A full-stack web application that computes optimal flight routes across India, with a focus on **Short Takeoff and Landing (STOL)** aircraft constraints.  
> Built as a demonstration project targeting **LAT Aerospace** — an Indian startup developing next-gen STOL aircraft for underserved regional connectivity.

---

## 🔍 What It Does

- Models Indian airports as a **weighted graph** (NetworkX)
- Finds optimal routes using **Dijkstra's Shortest Path Algorithm**
- Supports three optimization targets: **Cost · Time · Distance**
- Enforces real-world **STOL runway constraints** (runway ≤ 800m)
- Clean aviation-themed dashboard UI built with vanilla JS + Flask

---

## 🧠 Tech Stack

| Layer       | Tech                          |
|-------------|-------------------------------|
| Backend     | Python 3.11, Flask 3.0        |
| Optimizer   | NetworkX (Dijkstra's algo)    |
| Frontend    | HTML5, CSS3, Vanilla JS       |
| Deployment  | Render (Gunicorn WSGI)        |
| Phase 3 (planned) | scikit-learn (demand ML) |

---

## 📁 Project Structure

```
stol-route-optimizer/
├── app.py                  # Flask entry point + API routes
├── requirements.txt
├── render.yaml             # Render deployment config
├── optimizer/
│   ├── __init__.py
│   ├── graph.py            # City/airport data + haversine distances
│   └── route.py            # NetworkX graph builder + Dijkstra optimizer
├── static/
│   ├── css/style.css       # Aviation dark theme
│   └── js/main.js          # Fetch API + dynamic DOM rendering
└── templates/
    └── index.html          # Single-page app template
```

---

## 🚀 Run Locally

```bash
# 1. Clone the repo
git clone https://github.com/YOUR_USERNAME/stol-route-optimizer.git
cd stol-route-optimizer

# 2. Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run the app
python app.py

# 5. Open in browser
# http://localhost:5000
```

---

## 🛣 Roadmap

| Phase | Feature                        | Status      |
|-------|--------------------------------|-------------|
| 1     | Flask + NetworkX route optimizer | ✅ Complete |
| 2     | STOL runway constraint engine  | ✅ Complete  |
| 3     | ML demand prediction (scikit-learn) | 🔜 Planned |
| 4     | Modern startup UI (Mapbox/Leaflet) | 🔜 Planned |
| 5     | Full deployment on Render      | 🔜 Planned  |

---

## 🔬 Algorithm Notes

The optimizer models airports as graph **nodes** and routes as weighted **edges**.  
Edge weights are computed from:
- `distance_km` (Haversine formula)
- `time_min` = `distance / 350 km/h + 15 min buffer`
- `cost_inr` = `distance × ₹8/km` (+ ₹500 penalty for non-STOL airports)

`networkx.shortest_path(G, source, target, weight=...)` runs **Dijkstra's algorithm** internally — O((V + E) log V).

---

*Built with ❤️ for LAT Aerospace's mission to connect India's underserved regions via STOL aviation.*
