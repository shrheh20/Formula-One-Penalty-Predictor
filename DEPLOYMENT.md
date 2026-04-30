# Deployment Guide

## Recommended Architecture

Deploy a single FastAPI web service:

- app entrypoint: `backend.api.main:app`
- public dashboard: `/dashboard.html`
- dashboard APIs: `/api/...` and `/api/v2/...`
- embedded FIA documents service: `/fia-documents/...`

This avoids port conflicts and keeps local development and Render aligned.

## Render Settings

Use these Render settings for the web service:

- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn backend.api.main:app --host 0.0.0.0 --port $PORT`

## Required Environment Variables

```bash
DATABASE_URL=postgresql+psycopg://postgres:3520@<host>:5432/fia_documents
FIA_DOCS_DIR=data/fia_docs
LOG_LEVEL=INFO

LLM_API_URL=http://localhost:11434
LLM_API_KEY=dummy
LLM_MODEL=qwen3.5:2b

# FIA dashboard summary model override
SUMMARY_LLM_API_URL=https://api.mistral.ai
SUMMARY_LLM_API_KEY=<your-mistral-api-key>
SUMMARY_LLM_MODEL=mistral-small-2603

FIA_MONITOR_ENABLED=true
SCRAPE_INTERVAL_SECONDS=1800
FIA_MONITOR_WEEKEND_ONLY=true
FIA_MONITOR_TIMEZONE=America/Chicago
FIA_MONITOR_ACTIVE_DAYS=4,5,6
```

Notes:

- `F1_FIA_DOCUMENTS_BASE_URL` is optional. Do not set it unless you intentionally move FIA ingestion to a second service.
- If `F1_FIA_DOCUMENTS_BASE_URL` is unset, the backend defaults to its own mounted FIA routes under `/fia-documents`.
- `SUMMARY_LLM_*` only affects FIA race-impact summarization. Classification and extraction continue to use `LLM_*` unless you also change those variables.

## Local Development

Run one service:

```bash
cd Formula-One-Penalty-Predictor
../.venv/bin/uvicorn backend.api.main:app --port 8000
```

Then ingest FIA documents:

```bash
curl -X POST 'http://localhost:8000/fia-documents/documents/ingest?apply_processing=true'
```

Open:

- `http://localhost:8000/dashboard.html`

## Health Checks

```bash
curl http://localhost:8000/api/health
curl http://localhost:8000/fia-documents/health
curl "http://localhost:8000/api/v2/intelligence/fia-updates?limit=6"
```

## Optional Split-Service Mode

If you want FIA ingestion on a separate service:

1. Run `main.py` separately on `8001`
2. Set `F1_FIA_DOCUMENTS_BASE_URL=http://localhost:8001`
3. Start `backend.api.main:app` on `8000`

This is optional and not required for Render.
