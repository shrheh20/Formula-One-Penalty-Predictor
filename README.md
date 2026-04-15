# Formula One Penalty Predictor

A professional Formula 1 analytics dashboard focused on 2026 power unit exposure, penalty risk, FIA document intelligence, and historical FastF1 weekend analysis.

The project combines two complementary application layers:

- a Flask application that serves the main dashboard and legacy `/api/...` routes
- a FastAPI backend that powers the newer `/api/v2/...` intelligence and historical weekend analysis endpoints

## Product Overview

The dashboard is designed for race-weekend monitoring and historical analysis. It currently provides:

- penalty-risk monitoring based on FIA component allocation data
- FIA steward and document intelligence summaries
- component usage views for the full driver grid
- strategic circuit guidance for penalty timing
- a `Past Races` experience for 2026 FastF1 historical weekend analysis

## Key Features

### Penalty Predictor Dashboard

- High-risk driver cards with penalty probability and recommendation context
- Component usage overview across the full field
- Team and component filtering
- Strategic circuit analysis for when penalties are less damaging
- Driver component maps with sidecar visual overlays

### FIA Intelligence

- Steward alert summaries
- Risk-delta monitoring from FIA-backed signals
- Predictor feed enrichment for the main dashboard

### Past Races (2026 Historical Explorer)

The `Past Races` tab inside the main dashboard uses FastF1 historical data for the 2026 season and supports:

- circuit-by-circuit historical weekend selection
- session switching across practice, qualifying, sprint, sprint qualifying / sprint shootout, and race where available
- top-finisher classification views with filterable depth
- gap bars relative to the fastest lap in the selected session
- tyre compound usage with real compound imagery
- grid delta / position gain views for race-like sessions
- DNF and incident panels with interpreted and raw FastF1 race-control context

## Data Sources

The project uses a combination of official FIA data and FastF1 session data.

### FIA-backed local dataset

The repository includes:

- `fia_2026_component_snapshot.csv`
- `fia_2026_document_sources.json`
- `strategic_circuit_rankings_2026.json`
- `circuit_weekend_results_2026.csv`

These files support the penalty predictor, circuit analysis, and local dashboard views.

### FastF1-backed historical analysis

The FastAPI backend uses public FastF1 session interfaces such as:

- `fastf1.get_event_schedule(...)`
- `fastf1.get_event(...)`
- `fastf1.get_session(...)`
- `Session.load(...)`
- public session properties such as `laps`, `results`, `weather_data`, and `race_control_messages`

The app does **not** import or call `fastf1.api` directly.

## Tech Stack

- Python
- Flask
- FastAPI
- Pandas
- FastF1
- Tailwind CSS via CDN
- local static media assets for drivers, teams, sidecar views, and tyre compounds

## Repository Structure

```text
Formula-One-Penalty-Predictor/
├── api.py
├── backend/
│   ├── api/
│   │   ├── dependencies.py
│   │   └── main.py
│   ├── agents/
│   ├── data_sources/
│   ├── db/
│   ├── services/
│   └── utils/
├── dashboard.html
├── live_intelligence_preview.html
├── tests/
├── test_component1.py
├── requirements.txt
├── fia_2026_component_snapshot.csv
├── fia_2026_document_sources.json
├── strategic_circuit_rankings_2026.json
├── circuit_weekend_results_2026.csv
├── static/
│   ├── driver-photos/
│   ├── sidecar/
│   ├── team-badges/
│   └── tyre-compound/
└── DEPLOYMENT.md
```

## Local Development

### 1. Clone the repository

```bash
git clone https://github.com/YOUR-USERNAME/Formula-One-Penalty-Predictor.git
cd Formula-One-Penalty-Predictor
```

### 2. Create a virtual environment and install dependencies

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
```

### 3. Run the test suite

```bash
./.venv/bin/python test_component1.py
./.venv/bin/python -m unittest tests.test_fastapi_backend
```

## Running the Application

For local development, the project can still be run with separate services.

- Flask on port `5001` for the legacy dashboard workflow
- FastAPI on port `8000` for `/api/v2/...` and the historical explorer

### Start the Flask dashboard

```bash
./.venv/bin/python api.py
```

Open:

`http://localhost:5001`

### Start the FastAPI backend

```bash
./.venv/bin/uvicorn backend.api.main:app --reload --port 8000
```

Open:

`http://localhost:8000/docs`

The FastAPI service also serves:

- `/` -> main dashboard
- `/dashboard` -> main dashboard
- `/dashboard.html` -> main dashboard
- `/live-preview` -> standalone historical preview

### FastF1 behavior

FastF1 live loading is enabled by default when the package is installed.

Force FastF1 mode explicitly:

```bash
F1_ENABLE_FASTF1_LIVE=true ./.venv/bin/uvicorn backend.api.main:app --reload --port 8000
```

Disable FastF1 and stay in snapshot mode:

```bash
F1_ENABLE_FASTF1_LIVE=false ./.venv/bin/uvicorn backend.api.main:app --reload --port 8000
```

FastF1 responses are cached under `.cache/fastf1/`.

## Using the Dashboard

### Main dashboard tabs

- `High Risk`: drivers at elevated grid-penalty risk
- `FIA Updates`: steward and FIA signal summaries
- `Components`: full-grid power unit usage view
- `Circuits`: strategic penalty timing by circuit
- `Past Races`: 2026 historical weekend explorer

### Past Races workflow

1. Start the FastAPI backend.
2. Open the Flask dashboard.
3. Select the `Past Races` tab.
4. Choose a 2026 circuit.
5. Switch between available sessions.
6. Use the classification dropdown to change how many drivers are shown.

The following visuals update with the selected session:

- session focus summary
- classification
- gap bars
- tyre compound usage
- position gain/loss
- DNF and incidents

## API Surface

### Flask routes

```text
GET /api
GET /api/health
GET /api/predictions?race=4
GET /api/drivers
GET /api/driver/<code>
GET /api/circuits
GET /api/report/<race_number>
GET /api/betting-insights?race=4
GET /api/sources
```

### FastAPI routes

```text
GET /api/v2/health
GET /api/v2/live/race-state
GET /api/v2/live/reliability-alerts
GET /api/v2/preview/{race_name}
GET /api/v2/component-allocations
GET /api/v2/sources
GET /api/v2/reference/events
GET /api/v2/history/weekend
GET /api/v2/stream/commentary
GET /api/v2/intelligence/steward-alerts
GET /api/v2/intelligence/predictor-feed
POST /api/v2/webhooks/fia-document
```

## Verifying the Backends

### Flask health

```bash
curl http://localhost:5001/api/health
```

### FastAPI health

```bash
curl http://localhost:8000/api/v2/health
```

### Historical event schedule

```bash
curl "http://localhost:8000/api/v2/reference/events?year=2026"
```

### Historical weekend payload

```bash
curl "http://localhost:8000/api/v2/history/weekend?year=2026&gp_name=Japanese%20Grand%20Prix"
```

## Updating FIA-backed Data

When new FIA documents are published:

1. add the new source URLs to `fia_2026_document_sources.json`
2. update `fia_2026_component_snapshot.csv`
3. rebuild strategic circuit rankings if required

```bash
python3 build_strategic_circuits.py
```

Then restart the application services.

## Render Deployment Guidance

The simplest production path is to deploy the FastAPI app as the public web service. In that setup, the same Render service can host:

- the dashboard at `/`
- static assets under `/static/...`
- the modern `/api/v2/...` API
- the legacy `/api/...` routes that the dashboard still uses

Suggested Render settings:

- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn backend.api.main:app --host 0.0.0.0 --port $PORT`

### Recommended production setup

- deploy `backend.api.main:app` as the Render web service
- let Render assign the public URL
- use that single public URL for both the website and API
- keep the Flask process for local compatibility only, unless you explicitly want a second legacy deployment

See [DEPLOYMENT.md](./DEPLOYMENT.md) for a broader deployment checklist.

## Notes

- Driver, team, and tyre assets are stored locally under `static/` for reliability and consistent rendering.
- The `Past Races` tab is designed for 2026 historical weekend data.
- Incident cards now include both interpreted and raw FastF1-derived race-control context so fields can be refined further over time.
- Predictions are based on documented component usage, FIA sources, and public session data.

## Disclaimer

This project is for informational and entertainment purposes only. It is not financial advice, betting advice, or an official Formula 1 product.

## License

MIT
