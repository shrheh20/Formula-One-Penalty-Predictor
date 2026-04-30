# News Intelligence System Specification

## Goal

Build a production-minded Formula One news intelligence pipeline that continuously ingests multi-source articles, stores full text for retrieval and re-summarization, clusters related stories, extracts source-cited claims, blocks low-confidence publication, and serves a professional `News` experience inside the dashboard.

This system is separate from the existing FIA document ingestion stack, but intentionally designed to interoperate with it for retrieval, verification, and strategy interpretation.

## Product Principles

- Official sources are first-class evidence, but the feed is sorted `latest first`
- Full article text is stored for retrieval, re-summarization, and auditability
- Every published summary must be grounded in citations
- Derived strategy insight is shown only after the cluster passes review
- Low-confidence or conflicting items are blocked from publication
- Review decisions are durable and auditable
- The architecture should look credible for a portfolio app and scale cleanly toward production

## Sources

### Phase 1

- Formula 1 press releases
- FIA official documents and championship pages
- Sky Sports Formula 1 news / press coverage
- Motorsport Formula 1 news

### Phase 2

- Formula 1 Instagram through compliant official access only

## High-Level Architecture

```text
Source Collectors
    -> Fetch + Parse
    -> Normalize
    -> Postgres system of record
    -> Chunk + Embed
    -> Qdrant retrieval collections
    -> Claim Extraction
    -> Story Clustering
    -> Confidence + Conflict Scoring
    -> Review Agent Gate
    -> Publishable Summaries
    -> Dashboard / API
```

## Storage Choices

### Relational system of record

- Database: `Postgres`
- Purpose:
  - ingestion run tracking
  - article metadata
  - raw and cleaned article text
  - claim extraction
  - cluster state
  - review workflow
  - publication state
  - TTL / reprocessing schedule

### Vector retrieval layer

- Vector store: `Qdrant`
- Purpose:
  - semantic retrieval over article chunks
  - hybrid retrieval over article chunks plus sparse / lexical signals
  - related-story clustering support
  - FIA cross-reference retrieval
  - cluster-summary retrieval for downstream synthesis

## Recommended Project Layout

```text
Formula-One-Penalty-Predictor/
├── news_intelligence/
│   ├── __init__.py
│   ├── api.py
│   ├── config.py
│   ├── db.py
│   ├── models.py
│   ├── schemas.py
│   ├── scheduler.py
│   ├── embeddings.py
│   ├── qdrant_client.py
│   ├── reranker.py
│   ├── summarizer.py
│   ├── review_agent.py
│   ├── clusterer.py
│   ├── pipelines/
│   │   ├── ingest.py
│   │   ├── claims.py
│   │   ├── publish.py
│   │   └── reprocess.py
│   ├── collectors/
│   │   ├── base.py
│   │   ├── formula1_press.py
│   │   ├── fia_official.py
│   │   ├── sky_sports.py
│   │   ├── motorsport.py
│   │   └── instagram_official.py
│   └── prompts/
│       ├── claim_extraction.md
│       ├── article_summary.md
│       ├── cluster_summary.md
│       └── review_resolution.md
├── data/
│   └── news_intelligence/
│       └── fixtures/
└── NEWS_INTELLIGENCE_SPEC.md
```

## Postgres Schema

Use a separate Postgres database, for example:

```bash
export NEWS_DATABASE_URL='postgresql+psycopg://postgres:password@localhost:5432/news_intelligence'
```

### `news_sources`

Tracks source configuration and health.

- `id`
- `source_key` unique
- `display_name`
- `source_type`
- `officiality_level`
- `base_url`
- `enabled`
- `poll_interval_seconds`
- `last_success_at`
- `last_error_at`
- `last_error_message`
- `created_at`
- `updated_at`

### `news_ingestion_runs`

Tracks each collector execution.

- `id`
- `source_id`
- `run_started_at`
- `run_finished_at`
- `status`
- `items_seen`
- `items_new`
- `items_updated`
- `items_failed`
- `error_message`
- `payload`

### `news_articles`

Canonical article record.

- `id`
- `source_id`
- `external_id`
- `canonical_url` unique
- `headline`
- `subheadline`
- `author`
- `published_at`
- `updated_at_source`
- `source_type`
- `officiality_level`
- `grand_prix`
- `season`
- `session_hint`
- `article_language`
- `content_hash`
- `raw_html`
- `raw_text`
- `clean_text`
- `metadata_json`
- `fetch_status`
- `parse_status`
- `chunk_status`
- `claim_status`
- `cluster_status`
- `review_status`
- `publication_status`
- `first_seen_at`
- `last_seen_at`
- `created_at`
- `updated_at`

### `news_article_entities`

Entity extraction output per article.

- `id`
- `article_id`
- `entity_type`
- `entity_value`
- `entity_role`
- `normalized_value`
- `confidence`
- `payload`
- `created_at`

### `news_article_chunks`

Chunk registry for retrieval and citation spans.

- `id`
- `article_id`
- `chunk_index`
- `char_start`
- `char_end`
- `token_count`
- `chunk_text`
- `embedding_provider`
- `embedding_model`
- `embedding_version`
- `qdrant_point_id` unique
- `created_at`
- `updated_at`

### `news_claims`

Atomic extracted claims.

- `id`
- `article_id`
- `claim_type`
- `claim_text`
- `normalized_claim_key`
- `claim_scope`
- `strategy_priority`
- `confidence`
- `is_conflicting`
- `needs_review`
- `citation_article_chunk_id`
- `citation_char_start`
- `citation_char_end`
- `evidence_text`
- `affected_driver`
- `affected_team`
- `affected_session`
- `grand_prix`
- `published_at`
- `payload`
- `created_at`
- `updated_at`

### `news_clusters`

Represents one story across one or more sources.

- `id`
- `cluster_key` unique
- `cluster_title`
- `cluster_type`
- `grand_prix`
- `season`
- `strategy_priority_score`
- `freshness_score`
- `confidence_score`
- `conflict_score`
- `official_evidence_count`
- `secondary_evidence_count`
- `latest_published_at`
- `review_status`
- `publication_status`
- `primary_article_id`
- `created_at`
- `updated_at`

### `news_cluster_members`

Maps articles to clusters.

- `id`
- `cluster_id`
- `article_id`
- `membership_score`
- `is_primary`
- `created_at`

### `news_summaries`

Stores published and draft summaries at article and cluster level.

- `id`
- `target_type`
- `target_id`
- `summary_kind`
- `factual_summary`
- `strategy_impact_summary`
- `derived_insight`
- `citations_json`
- `model_provider`
- `model_name`
- `prompt_version`
- `status`
- `created_at`
- `updated_at`

### `news_review_tasks`

Review queue for blocked items.

- `id`
- `target_type`
- `target_id`
- `reason_type`
- `reason_summary`
- `priority`
- `status`
- `attempt_count`
- `last_attempt_at`
- `resolution`
- `resolution_notes`
- `agent_payload`
- `created_at`
- `updated_at`

### `news_reprocess_jobs`

TTL and refresh scheduling.

- `id`
- `job_type`
- `target_type`
- `target_id`
- `run_after`
- `status`
- `attempt_count`
- `last_error`
- `payload`
- `created_at`
- `updated_at`

## Qdrant Collections

### Collection: `news_article_chunks`

Vector payload fields:

- `article_id`
- `chunk_index`
- `source_key`
- `source_type`
- `officiality_level`
- `grand_prix`
- `season`
- `published_at`
- `drivers`
- `teams`
- `claim_types`
- `review_status`
- `publication_status`

Purpose:

- article retrieval
- evidence retrieval for claim review
- related-article matching
- context for article and cluster summaries

### Collection: `news_cluster_summaries`

Payload fields:

- `cluster_id`
- `cluster_type`
- `grand_prix`
- `season`
- `latest_published_at`
- `strategy_priority_score`
- `publication_status`

Purpose:

- story-level retrieval
- deduplication support
- “related stories” UI

### Collection: `fia_context_chunks`

Payload fields:

- `document_id`
- `document_type`
- `grand_prix`
- `session`
- `drivers`
- `teams`
- `signal_types`

Purpose:

- retrieve official FIA context while summarizing or reviewing news stories

## Ingestion Pipeline

### Step 1: Collect

Each source collector should:

- discover the latest items
- canonicalize URLs
- fetch page HTML or API payload
- extract headline, byline, publish time, and article body
- compute a content hash
- upsert the article

Rules:

- full text is stored
- articles are never silently discarded
- updates to an existing article trigger re-chunking and reprocessing

### Step 2: Normalize

Normalize source-specific output into a shared schema:

- source metadata
- article text
- event / weekend hints
- driver / team / session mentions
- strategy topic candidates

### Step 3: Chunk and embed

Recommended chunking:

- paragraph-aware splitting
- target `350-700` tokens per chunk
- overlap `60-100` tokens

Store chunk metadata in Postgres and embeddings in Qdrant.

### Step 4: Claim extraction

Each article is processed to extract atomic claims with citations.

Target claim classes:

- `grid_penalty`
- `power_unit_change`
- `upgrade`
- `tyre_compound`
- `weather_forecast`
- `reliability_concern`
- `parc_ferme_or_setup`
- `steward_action`
- `driver_quote`
- `team_statement`
- `schedule_or_session_change`
- `other_strategy_relevant`

Each claim must include:

- exact supporting citation location
- confidence score
- affected entities
- one strategy-priority label

### Step 5: Cluster

Cluster on a rolling basis using:

- embedding similarity
- exact entity overlap
- same grand prix / weekend
- lexical overlap on key terms
- temporal proximity

Preferred logic:

- start with retrieval candidates from Qdrant
- rerank cluster candidates with lexical + metadata features
- assign to existing cluster when above threshold
- otherwise create new cluster

### Step 6: Score confidence and conflict

Cluster scoring inputs:

- number of sources
- presence of official evidence
- source agreement
- claim consistency
- extraction confidence
- article freshness

Conflict examples:

- one article says a penalty is confirmed and another says it is only under consideration
- two sources name different upgrade packages
- weather stories disagree materially on qualifying conditions

### Step 7: Review gate

Publication is blocked until review status is `approved`.

Automatic review triggers:

- cluster confidence below threshold
- any conflicting material claim
- high strategy priority with weak evidence
- ambiguous entity resolution
- insufficient citations for summary generation

### Step 8: Summarize

Generate:

- article-level summary
- cluster-level summary

Each published cluster should have:

- `factual_summary`
- `strategy_impact_summary`
- `derived_insight`

Derived insight is allowed only after review approval, even though it may be more interpretive than the factual summary.

## Review Agent

The review agent is an automated gatekeeper, not a free-form chat assistant.

### Inputs

- blocked article or cluster
- extracted claims
- citations
- retrieved related chunks
- retrieved FIA context
- conflict metadata

### Responsibilities

- verify whether claims are actually supported by cited evidence
- compare conflicting claims across sources
- retrieve additional official context where possible
- downgrade, merge, or reject weak stories
- approve only when a publishable evidence package exists

### Allowed outcomes

- `approved`
- `rejected`
- `needs_more_evidence`
- `superseded`

### Review agent rules

- no uncited summary sentence may be published
- no cluster with unresolved factual conflict may be published
- official evidence outranks secondary evidence
- latest source does not automatically outrank official source

## Summary Contracts

### Article summary

- 2 lines maximum for `factual_summary`
- 2 lines maximum for `strategy_impact_summary`
- each sentence backed by citations

### Cluster summary

- `factual_summary`
  - what happened across sources
- `strategy_impact_summary`
  - effect on race strategy
- `derived_insight`
  - what this means for the race and for teams

### Summary style requirements

- explicit and concrete
- no invented certainty
- no unlabeled speculation
- concise enough for dashboard cards
- strategy lens ordered by:
  - grid penalties
  - upgrades
  - tyre compounds
  - weather
  - reliability
  - parc ferme / setup
  - steward trends

## Ranking Logic

The feed is sorted `latest first`, then weighted within that window by strategy relevance.

Recommended cluster score inputs:

- recency
- grid penalty relevance
- upgrade relevance
- tyre relevance
- weather relevance
- reliability relevance
- parc ferme / setup relevance
- steward trend relevance
- official evidence presence
- cluster confidence

## TTL and Reprocessing

### Keep permanently

- article metadata
- raw text
- clean text
- claims
- citations
- review decisions
- publication audit trail

### Rebuildable

- embeddings
- draft summaries
- cluster memberships
- derived insight

### Suggested reprocessing policy

- newly seen article:
  - immediate full pipeline
- updated article body:
  - re-chunk, re-embed, re-extract claims, recluster, resummarize
- published cluster during active race weekend:
  - refresh every `6 hours`
- non-weekend cluster:
  - refresh every `24 hours`
- blocked cluster with `needs_more_evidence`:
  - retry every `2 hours` for `24 hours`
- stale cluster older than `14 days`:
  - no scheduled refresh unless linked to new evidence

## API Design

Mount a separate app similarly to the FIA documents service:

```python
app.mount("/news-intelligence", news_intelligence_app)
```

### Health and admin

- `GET /news-intelligence/health`
- `POST /news-intelligence/articles/ingest`
- `POST /news-intelligence/articles/reprocess`
- `GET /news-intelligence/review-queue`

### Feed

- `GET /news-intelligence/feed/latest`
  - latest approved article cards
- `GET /news-intelligence/clusters/latest`
  - latest approved story clusters
- `GET /news-intelligence/clusters/{cluster_id}`
  - cluster summary, member articles, citations, related FIA context

### Search

- `GET /news-intelligence/search`
  - query over articles and clusters
- `GET /news-intelligence/articles/{article_id}/related`
  - similar articles and relevant FIA documents

### Dashboard-specific contract

- `GET /api/v2/news/briefing`
- `GET /api/v2/news/feed`
- `GET /api/v2/news/clusters/{cluster_id}`

## Dashboard News Tab

Add a `News` tab to `dashboard.html` with three layers.

### 1. Strategy briefing rail

Displays highest-priority approved clusters with:

- cluster title
- `factual_summary`
- `strategy_impact_summary`
- verification badge
- source count
- related FIA links

### 2. Latest stories list

Displays approved article cards sorted latest first with:

- headline
- source badge
- published time
- 2-line factual summary
- 2-line strategy impact summary
- direct source link
- cluster link

### 3. Cluster detail panel

Displays:

- cross-source story timeline
- strategy themes
- affected drivers / teams
- source list
- citation-backed insight
- related FIA documents

### Verification badges

- `Official`
- `Corroborated`
- `Single-source`

No low-confidence or conflicting item should receive a dashboard card before approval.

## Environment Variables

```bash
export NEWS_DATABASE_URL='postgresql+psycopg://postgres:password@localhost:5432/news_intelligence'
export NEWS_QDRANT_URL='http://localhost:6333'
export NEWS_QDRANT_API_KEY=''
export NEWS_EMBEDDING_PROVIDER='openai-compatible'
export NEWS_EMBEDDING_MODEL='text-embedding-3-large'
export NEWS_LLM_API_URL='https://api.mistral.ai'
export NEWS_LLM_API_KEY='YOUR_MISTRAL_API_KEY'
export NEWS_LLM_MODEL='mistral-small-3.2'
export NEWS_REVIEW_LLM_MODEL='mistral-medium-latest'
export NEWS_POLL_INTERVAL_SECONDS='1800'
export NEWS_ENABLE_INSTAGRAM='false'
export NEWS_ACTIVE_TIMEZONE='America/Chicago'
```

Notes:

- the exact embedding model may change later, but one consistent general-purpose embedding model should be used across all article chunks
- review should use a stronger model than first-pass summarization when practical

## MVP Build Order

### Milestone 1: Core ingestion and storage

- create `news_intelligence` package
- add Postgres schema
- add four collectors for phase-1 sources
- store full text and run metadata

### Milestone 2: Retrieval and clustering

- add chunking
- add Qdrant sync
- add article similarity search
- add first-pass cluster assignment

### Milestone 3: Claims and review gate

- add citation-backed claim extraction
- add review task creation
- add review agent resolution loop
- block publication until approval

### Milestone 4: Summaries and dashboard feed

- add article and cluster summaries
- add dashboard endpoints
- add `News` tab UI

### Milestone 5: FIA cross-linking and search

- retrieve FIA context during review and summarization
- add related-FIA references on cluster detail
- add search endpoint

### Milestone 6: Instagram official access

- integrate only when compliant official access is available

## Testing Strategy

### Unit tests

- collectors parse representative HTML correctly
- canonicalization and dedup logic
- chunk boundary logic
- claim extraction schema validation
- cluster assignment rules
- review state transitions

### Integration tests

- ingest a mixed-source article set
- verify cluster formation
- verify blocked publication for conflict
- verify approved publication after review resolution
- verify dashboard feed excludes blocked items

### Evaluation set

Create a small gold dataset of real F1 stories:

- confirmed grid penalty
- upgrade weekend
- tyre allocation / compound story
- changing weather forecast
- FIA steward action story
- conflicting rumor that should be blocked

Track:

- clustering accuracy
- citation validity
- false-positive publication rate
- review resolution rate

## Portfolio Positioning

This feature should be described as:

`A source-grounded Formula One news intelligence system that unifies official and media reporting, stores full text for retrieval, clusters overlapping stories, extracts citation-backed claims, and blocks low-confidence publication through an automated review gate before surfacing strategy-focused race insight on the dashboard.`

## Immediate Next Build Tasks

1. Scaffold `news_intelligence/` package and DB models
2. Add `Postgres + Qdrant` config and client wrappers
3. Implement the `Formula 1 press release` collector first
4. Add chunking and Qdrant indexing
5. Add article-level storage and manual ingest endpoint
6. Add initial dashboard `News` tab with mocked approved payloads

