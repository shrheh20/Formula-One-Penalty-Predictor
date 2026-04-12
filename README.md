# Formula One Penalty Predictor

A public-facing F1 dashboard and API that tracks 2026 power unit usage, flags drivers at risk of grid penalties, and highlights the circuits where taking a penalty is strategically less painful.

This project is built around official FIA race documents and turns them into a simple product:
- a web dashboard for quick race-weekend scanning
- a Flask API for structured data access
- a local FIA-backed dataset that can be refreshed as new documents are published

## What It Shows

- High-risk drivers who are at or near their component allocation limits
- A component usage overview for the full grid
- Strategic circuit analysis for penalty timing
- Driver-level car maps showing where tracked components sit on the car

## Data Source

The current dataset is built from official FIA 2026 Formula One World Championship event documents, including Technical Delegate reports covering:
- power unit elements used per driver
- new power unit elements introduced for a competition

The repo includes:
- `fia_2026_component_snapshot.csv`
- `fia_2026_document_sources.json`
- `strategic_circuit_rankings_2026.json`

These files power the live dashboard and API responses.

## Tech Stack

- Python
- Flask
- Pandas
- Tailwind CSS (via CDN)
- Static local image assets for driver photos, team badges, and side-view cars

## Quick Start

### 1. Clone the repo

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
```

### 4. Start the app

```bash
./.venv/bin/python api.py
```

Then open:

`http://localhost:5001`

The dashboard is served at the root URL, and the API is served from `/api/...`.

## API Endpoints

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

## Project Structure

```text
Formula-One-Penalty-Predictor/
├── api.py
├── component_tracker.py
├── dashboard.html
├── test_component1.py
├── requirements.txt
├── fia_2026_component_snapshot.csv
├── fia_2026_document_sources.json
├── strategic_circuit_rankings_2026.json
├── circuit_weekend_results_2026.csv
├── static/
│   ├── driver-photos/
│   ├── sidecar/
│   └── team-badges/
└── DEPLOYMENT.md
```

## Local Data Refresh

When new FIA documents are published, update the repo in three parts:

1. Add the new source URLs to `fia_2026_document_sources.json`
2. Update `fia_2026_component_snapshot.csv` with the latest component counts
3. Rebuild the circuit rankings if needed:

```bash
python3 build_strategic_circuits.py
```

Then restart the API.

## Deploying Publicly

The simplest public deployment is a single Python web service on Render.

Suggested settings:
- Build command: `pip install -r requirements.txt`
- Start command: `python api.py`

Because the app serves the dashboard from `/`, the public Render URL becomes your shareable product URL.

See [DEPLOYMENT.md](./DEPLOYMENT.md) for a more detailed launch checklist.

## Notes

- Driver and team images are stored locally under `static/` for reliability and faster loading.
- The dashboard is designed to work from the same origin as the Flask API in production.
- Predictions are based on component usage and documented allocations, not insider information or live telemetry.

## Disclaimer

This project is for informational and entertainment purposes only. It is not financial advice, betting advice, or an official Formula 1 product.

## License

MIT
