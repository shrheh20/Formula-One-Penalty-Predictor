# Operations Runbook

This document captures the current operational state of the project as of `2026-04-29` and explains how to run, review, and demo the app locally.

## Current State

The project currently includes three main layers:

1. `Dashboard + FIA intelligence backend`
2. `FIA documents ingestion and review pipeline`
3. `News intelligence pipeline` for multi-source F1 article ingestion, clustering, claim extraction, review gating, and dashboard publishing

### Live checkpoint

Current live store status from the local review CLI:

- `11` stored news articles
- `8` news clusters
- `13` open review tasks
- `1` approved article
- `1` approved cluster

These numbers will move over time as new stories are ingested and approved.

## What Works Today

### Dashboard

- `High Risk` tab for penalty-risk monitoring
- `FIA Updates` tab for FIA document intelligence
- `News` tab for approved article and cluster summaries
- `Components`, `Circuits`, and `Past Races` views

### News intelligence

Implemented and working:

- source collectors
  - `Formula 1 Latest`
  - `Sky Sports F1`
  - `The Race`
  - `RacingNews365`
- separate Postgres-backed news store
- embedded local Qdrant vector storage
- article chunking and indexing
- first-pass clustering with F1-specific story typing
- deterministic claim extraction
- review-task creation
- deterministic draft summarization
- approval workflow
- local CLI review tool

### Review model

Public dashboard content is intentionally restricted to `approved` items only.

That means:

- newly ingested stories are stored first
- claims and summaries are generated
- stories remain `blocked` until approved
- approved items appear in the `News` tab automatically

## Local Runbook

### Recommended working directory

The safest place to run commands is the parent workspace:

`/Users/shrheh/Documents/F1-PenaltyPredictor`

This avoids confusion between the parent `.venv` and the app-specific `.venv`.

### Important environment layout

The application code, app venv, `.env`, backend, and news subsystem are all under:

`/Users/shrheh/Documents/F1-PenaltyPredictor/Formula-One-Penalty-Predictor`

Use the provided wrapper scripts so the correct directory and interpreter are always used.

### Start Postgres first

The backend requires the local PostgreSQL server to be running because both:

- `fia_documents`
- `news_intelligence`

are configured as Postgres databases.

Expected local credentials from `.env`:

- host: `localhost`
- port: `5432`
- username: `postgres`
- password: `3520`

### Start the dashboard/backend

From the parent workspace:

```bash
cd /Users/shrheh/Documents/F1-PenaltyPredictor
./start_f1_dashboard.sh
```

Open:

- `http://localhost:8000/dashboard.html`
- `http://localhost:8000/docs`

### Review the news queue

From the parent workspace:

```bash
cd /Users/shrheh/Documents/F1-PenaltyPredictor
./review_f1_news_queue.sh --limit 15
```

### Inspect a cluster

From the app directory:

```bash
cd /Users/shrheh/Documents/F1-PenaltyPredictor/Formula-One-Penalty-Predictor
./.venv/bin/python -m news_intelligence.review_cli show cluster 1
```

### Approve a cluster

```bash
cd /Users/shrheh/Documents/F1-PenaltyPredictor/Formula-One-Penalty-Predictor
./.venv/bin/python -m news_intelligence.review_cli approve cluster 1 --notes "Verified and ready to publish."
```

### Reject a cluster

```bash
cd /Users/shrheh/Documents/F1-PenaltyPredictor/Formula-One-Penalty-Predictor
./.venv/bin/python -m news_intelligence.review_cli reject cluster 8 --notes "Not ready for public feed."
```

### Ingest fresh news

With the backend running:

```bash
curl -X POST http://localhost:8000/news-intelligence/articles/ingest \
  -H "Content-Type: application/json" \
  -d '{"sources":["formula1_press","sky_sports_f1","the_race_f1","racingnews365_f1"],"limit_per_source":3}'
```

Then review again:

```bash
./review_f1_news_queue.sh --limit 20
```

## Daily Operator Flow

1. Start Postgres
2. Start backend with `./start_f1_dashboard.sh`
3. Ingest fresh news if needed
4. Run `./review_f1_news_queue.sh --limit 15`
5. Inspect clusters with `show cluster <id>`
6. Approve or reject clusters
7. Refresh `http://localhost:8000/dashboard.html`

## Known Constraints

### Public dashboard intentionally hides unapproved content

If the `News` tab looks empty, that usually means:

- the backend is not running, or
- no stories have been approved yet

This is expected behavior, not a rendering bug.

### Two virtual environments exist

There is:

- a parent workspace `.venv`
- an app-specific `.venv`

Only the app-specific venv contains the full dashboard/news dependencies such as `qdrant-client`.

Use:

- `./start_f1_dashboard.sh`
- `./review_f1_news_queue.sh`

to avoid accidentally using the wrong interpreter.

### Embedded local Qdrant uses a file lock

The local vector store is embedded and file-based. If multiple processes try to grab the same local Qdrant storage folder, one of them can fail with a lock error.

Current code is safer than before because Qdrant is initialized lazily, but you should still avoid launching multiple conflicting ingest/server processes against the same local store at once.

## GitHub Readiness

The repo is now in a good state to push publicly as an active work-in-progress project because it already demonstrates:

- real multi-source ingestion
- database-backed pipelines
- F1-specific clustering logic
- review-gated publication
- dashboard integration
- operator tooling

## Suggested Next Milestones

1. Improve CLI ergonomics
   - `approve-next`
   - better `show task` context
2. Refine clustering and duplicate suppression
3. Upgrade the summarizer from deterministic to approved-evidence LLM synthesis
4. Add related FIA evidence to News stories
5. Harden production scheduling and source-health monitoring
