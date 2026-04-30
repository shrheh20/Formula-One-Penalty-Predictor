# Formula One Penalty Predictor

For the current local runbook and operator workflow, see [OPERATIONS.md](/Users/shrheh/Documents/F1-PenaltyPredictor/Formula-One-Penalty-Predictor/OPERATIONS.md).

A professional Formula 1 analytics dashboard focused on 2026 power unit exposure, penalty risk, FIA document intelligence, and precomputed historical weekend analysis.

The project combines two complementary application layers:

- a dedicated FIA documents ingestion service that scrapes, downloads, parses, classifies, and stores FIA PDFs
- a FastAPI dashboard backend that serves `dashboard.html`, historical analysis, and the `/api/v2/...` intelligence endpoints

A third layer is now in active development and documented in [NEWS_INTELLIGENCE_SPEC.md](/Users/shrheh/Documents/F1-PenaltyPredictor/Formula-One-Penalty-Predictor/NEWS_INTELLIGENCE_SPEC.md): a source-grounded multi-source news intelligence system for clustered, citation-backed F1 story monitoring.

## Product Overview

The dashboard is designed for race-weekend monitoring and historical analysis. It currently provides:

- penalty-risk monitoring based on FIA component allocation data
- FIA steward and document intelligence summaries
- a review-gated `News` tab with approved F1 article and cluster summaries
- component usage views for the full driver grid
- strategic circuit guidance for penalty timing
- a `Past Races` experience for precomputed 2026 historical weekend analysis

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
- LLM-backed FIA document insight cards for the `FIA Updates` tab
- Review queue and targeted reprocessing for failed or unknown FIA documents

### Past Races (2026 Historical Explorer)

The `Past Races` tab inside the main dashboard uses a precomputed 2026 dataset generated from FastF1 and supports:

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

### Precomputed historical analysis

The historical dataset generator uses public FastF1 session interfaces such as:

- `fastf1.get_event_schedule(...)`
- `fastf1.get_event(...)`
- `fastf1.get_session(...)`
- `Session.load(...)`
- public session properties such as `laps`, `results`, `weather_data`, and `race_control_messages`

The app does **not** import or call `fastf1.api` directly.

Generated JSON files are stored in `data/historical/2026/` and are served directly by the FastAPI backend in production.

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
├── build_historical_2026_dataset.py
├── live_intelligence_preview.html
├── tests/
├── test_component1.py
├── requirements.txt
├── fia_2026_component_snapshot.csv
├── fia_2026_document_sources.json
├── strategic_circuit_rankings_2026.json
├── circuit_weekend_results_2026.csv
├── data/
│   └── historical/
│       └── 2026/
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

For local development, the recommended setup is one FastAPI service on port `8000`.

Do not open `dashboard.html` through a separate static file server such as Live Server on port `5500` unless the dashboard backend is also running on `8000`. The dashboard API calls are designed to target the FastAPI backend on `8000`.

### Start the unified dashboard + FIA service

From the `Formula-One-Penalty-Predictor/` directory:

```bash
export DATABASE_URL='postgresql+psycopg://postgres:3520@localhost:5432/fia_documents'
export FIA_DOCS_DIR='data/fia_docs'
export LOG_LEVEL='INFO'

# Local LLM classification / extraction
export LLM_API_URL='http://localhost:11434'
export LLM_API_KEY='dummy'
export LLM_MODEL='qwen3.5:2b'

# Mistral Small 4 for FIA race-impact summarization only
export SUMMARY_LLM_API_URL='https://api.mistral.ai'
export SUMMARY_LLM_API_KEY='YOUR_MISTRAL_API_KEY'
export SUMMARY_LLM_MODEL='mistral-small-2603'

# News intelligence subsystem
export NEWS_DATABASE_URL='postgresql+psycopg://postgres:password@localhost:5432/news_intelligence'
export NEWS_QDRANT_URL='http://127.0.0.1:6333'
export NEWS_QDRANT_API_KEY=''

# 30-minute FIA monitor
export FIA_MONITOR_ENABLED=true
export SCRAPE_INTERVAL_SECONDS=1800
export FIA_MONITOR_WEEKEND_ONLY=true
export FIA_MONITOR_TIMEZONE='America/Chicago'
export FIA_MONITOR_ACTIVE_DAYS='4,5,6'

../.venv/bin/uvicorn backend.api.main:app --port 8000
```

Or use the included launcher so the working directory and venv are always correct:

```bash
./scripts/start_dashboard_server.sh
```

From the parent workspace directory `/Users/shrheh/Documents/F1-PenaltyPredictor`, you can also run:

```bash
./start_f1_dashboard.sh
```

Open:

- `http://localhost:8000/dashboard.html`
- `http://localhost:8000/docs`

This single service serves:

- `/` -> main dashboard
- `/dashboard` -> main dashboard
- `/dashboard.html` -> main dashboard
- `/live-preview` -> standalone historical preview
- `/fia-documents/health`
- `/fia-documents/documents/ingest`
- `/fia-documents/documents/review-queue`
- `/fia-documents/documents/reprocess`
- `/fia-documents/insights/latest`
- `/news-intelligence/health`
- `/news-intelligence/sources`
- `/news-intelligence/articles/ingest`
- `/news-intelligence/articles/latest`

### Local news review CLI

Use the local CLI when you want to review or publish news stories without exposing any admin surface in the public dashboard.

From `Formula-One-Penalty-Predictor/`:

```bash
./.venv/bin/python -m news_intelligence.review_cli stats
./.venv/bin/python -m news_intelligence.review_cli queue --limit 15
./.venv/bin/python -m news_intelligence.review_cli show cluster 1
./.venv/bin/python -m news_intelligence.review_cli approve cluster 1 --notes "Verified and ready to publish."
./.venv/bin/python -m news_intelligence.review_cli reject article 4 --notes "Filtered or not useful for the public strategy feed."
```

If you just want the queue without remembering paths:

```bash
./scripts/review_news_queue.sh --limit 15
```

From the parent workspace directory:

```bash
./review_f1_news_queue.sh --limit 15
```

Recommended workflow:

1. Run `queue` to inspect open review tasks.
2. Run `show cluster <id>` to inspect the cluster summary and member articles.
3. Approve or reject at the `cluster` level whenever possible so article states stay aligned automatically.

### First-time refresh after startup

Once the app is running, ingest the latest FIA documents:

```bash
curl -X POST 'http://localhost:8000/fia-documents/documents/ingest?apply_processing=true'
```

Then refresh `http://localhost:8000/dashboard.html`.

### Restart sequence from scratch

If you have stopped everything, restart in this order:

1. Start Ollama if you are using local LLM classification.
2. Start the FastAPI app on `8000`.
3. Run one manual ingest.
4. Open the dashboard and check the `FIA Updates` tab.

If you want Mistral Small 4 only for the stored FIA document summaries, leave `LLM_*` pointing at your current local model and set `SUMMARY_LLM_*` to the Mistral API values above.
Local runs also load [/Users/shrheh/Documents/F1-PenaltyPredictor/Formula-One-Penalty-Predictor/.env](</Users/shrheh/Documents/F1-PenaltyPredictor/Formula-One-Penalty-Predictor/.env>) automatically when present, while Render should keep using its own environment-variable settings.

### Optional standalone FIA documents service

If you explicitly want FIA ingestion on a second process, you can still run:

```bash
export PORT=8001
../.venv/bin/python main.py
```

and point the dashboard backend at it with:

```bash
export F1_FIA_DOCUMENTS_BASE_URL='http://localhost:8001'
../.venv/bin/uvicorn backend.api.main:app --port 8000
```

That override is optional. The default local and Render setup does not need it.

### Historical dataset workflow

Generate the deployable 2026 historical JSON files locally before starting the backend:

```bash
./.venv/bin/python build_historical_2026_dataset.py --year 2026 --force
```

This writes the schedule and weekend payloads into `data/historical/2026/`.

### FastF1 behavior

FastF1 live loading is enabled by default when the package is installed.

Force FastF1 mode explicitly:

```bash
F1_ENABLE_FASTF1_LIVE=true F1_FIA_DOCUMENTS_BASE_URL='http://localhost:8001' ../.venv/bin/uvicorn backend.api.main:app --port 8000
```

Disable FastF1 and stay in snapshot mode:

```bash
F1_ENABLE_FASTF1_LIVE=false F1_FIA_DOCUMENTS_BASE_URL='http://localhost:8001' ../.venv/bin/uvicorn backend.api.main:app --port 8000
```

FastF1 responses are cached under `.cache/fastf1/`.

Historical weekend serving reads from `data/historical/2026/` by default. Runtime historical generation is disabled by default so production does not fetch 2026 weekends on demand.

## Using the Dashboard

### Main dashboard tabs

- `High Risk`: drivers at elevated grid-penalty risk
- `FIA Updates`: steward summaries, risk deltas, latest alerts, and LLM FIA document insight cards
- `Components`: full-grid power unit usage view
- `Circuits`: strategic penalty timing by circuit
- `Past Races`: 2026 historical weekend explorer

### Past Races workflow

1. Generate the 2026 historical dataset.
2. Start the FastAPI backend.
3. Open the dashboard at `http://localhost:8000/dashboard.html`.
4. Select the `Past Races` tab.
5. Choose a 2026 circuit.
6. Switch between available sessions.
7. Use the classification dropdown to change how many drivers are shown.

The following visuals update with the selected session:

- session focus summary
- classification
- gap bars
- tyre compound usage
- position gain/loss
- DNF and incidents

## API Surface

### Dashboard backend routes

```text
GET /api/health
GET /api/predictions?race=4
GET /api/drivers
GET /api/circuits
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
GET /api/v2/intelligence/fia-updates
POST /api/v2/webhooks/fia-document
```

### Mounted FIA documents routes

```text
GET /fia-documents/health
GET /fia-documents/documents/latest
GET /fia-documents/documents/grand-prix/{name}
GET /fia-documents/documents/review-queue
GET /fia-documents/insights/latest
POST /fia-documents/documents/ingest
POST /fia-documents/documents/reprocess
POST /fia-documents/documents/debug/parse-url
```

## Verifying the Backends

### Dashboard backend health

```bash
curl http://localhost:8000/api/health
```

### Mounted FIA documents health

```bash
curl http://localhost:8000/fia-documents/health
```

### Dashboard FIA updates feed

```bash
curl "http://localhost:8000/api/v2/intelligence/fia-updates?limit=6"
```

### FIA insights feed

```bash
curl "http://localhost:8000/fia-documents/insights/latest?limit=6"
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

The FIA monitor can pick up new documents automatically every 30 minutes inside the same FastAPI app. You can also run it manually:

```bash
curl -X POST 'http://localhost:8000/fia-documents/documents/ingest?apply_processing=true'
```

Useful review/recovery endpoints:

```bash
curl 'http://localhost:8000/fia-documents/documents/review-queue?needs_review_only=true'
curl 'http://localhost:8000/fia-documents/documents/review-queue?failed_only=true'
curl -X POST 'http://localhost:8000/fia-documents/documents/reprocess' \
  -H 'Content-Type: application/json' \
  -d '{"include_needs_review":true,"run_ingestion":true}'
```

## Render Deployment Guidance

The simplest production path is to deploy the FastAPI dashboard app as the public web service. In that setup, the same service can host:

- the dashboard at `/`
- static assets under `/static/...`
- the modern `/api/v2/...` API
- the legacy `/api/...` routes that the dashboard still uses
- the FIA documents subsystem under `/fia-documents/...`

Before deploying, generate and commit the contents of `data/historical/2026/` so the `Past Races` tab serves historical weekends without runtime FastF1 work.

The FIA ingestion subsystem needs:

- Postgres
- write access to `data/fia_docs/`
- an LLM endpoint if you want local classification / extraction assistance

Suggested Render settings:

- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn backend.api.main:app --host 0.0.0.0 --port $PORT`

### Recommended production setup

- deploy `backend.api.main:app` as the public web service
- let the mounted FIA documents routes run inside that same service
- only set `F1_FIA_DOCUMENTS_BASE_URL` if you intentionally move FIA ingestion to a second service
- keep the old Flask process out of the local default path unless you explicitly need legacy compatibility

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
