# Document Insights API

A FastAPI service that accepts text documents, processes them asynchronously into a
mock "insight" summary, and lets clients poll for status or fetch a user's document
history. Submission, processing, and retrieval are split across an API process and a
separate worker process, coordinated through MongoDB (durable state) and Redis
(per-user rate limiting and content-based caching).

## Overview

Clients submit a document (`user_id`, `title`, `content`) via `POST /documents`. The
document is queued in MongoDB with status `queued`. A background worker polls Mongo,
atomically claims the next eligible job, simulates processing (10–30s, per the take-home
spec) and produces a mock summary, then marks the job `completed` (or `failed` after
retries are exhausted). Clients can fetch a single document's status/result, or list a
user's documents with pagination and optional status filtering. Two cross-cutting
concerns — a per-user active-document rate limit and a content-hash based result cache
— are backed by Redis, with MongoDB as the source of truth and a fallback path if Redis
is unavailable.

## Quick Start

Zero configuration required — the Docker Compose stack ships with working defaults for
Mongo and Redis connectivity.

```bash
docker compose up --build
```

This starts four services: `mongo`, `redis`, `api`, and `worker`. Once healthy:

- API: http://localhost:8000
- Interactive docs (Swagger UI): http://localhost:8000/docs
- Health check: http://localhost:8000/health

> Do not `cp .env.example .env` before running the Docker stack — `docker-compose.yml`
> already injects the correct `MONGODB_URI`/`REDIS_URL` (pointing at the `mongo`/`redis`
> service hostnames) into the `api` and `worker` containers. A local `.env` with those
> Docker hostnames would instead break `pytest` runs on your host machine, which need
> `localhost`.

**Faster demo tip:** the worker simulates 10–30 seconds of processing per document
(per the assignment spec). To see documents complete faster while demoing, add these to
the `worker` service's `environment:` block in `docker-compose.yml` and restart:

```yaml
  worker:
    environment:
      WORKER_MIN_PROCESSING_SECONDS: "1"
      WORKER_MAX_PROCESSING_SECONDS: "2"
```

### Configuring the stack

`.env.example` documents every configurable variable (connection strings, rate-limit
thresholds, cache TTL, worker timing/retry knobs, log level) along with its meaning and
default. It is read automatically by `pydantic-settings` when running the API or worker
**locally without Docker** (copy it to `.env` and adjust as needed — the built-in
defaults already point at `localhost:27017` / `localhost:6379`). To change a setting for
the **Docker** stack instead, add it to the relevant service's `environment:` block in
`docker-compose.yml`, since Compose does not read `.env.example`/`.env` for this project.

## API Reference

### `POST /documents`

Submit a document for processing.

**Request**

```json
{
  "user_id": "user-123",
  "title": "Q3 Financial Report",
  "content": "This quarter we saw significant growth across all business units..."
}
```

**Response — `201 Created`** (new content, queued for processing)

```json
{
  "document_id": "66f1a2b3c4d5e6f7a8b9c0d1",
  "status": "queued"
}
```

**Response — `201 Created`** (content hash already has a completed summary — cache hit,
returned immediately, does not count against the rate limit)

```json
{
  "document_id": "66f1a2b3c4d5e6f7a8b9c0d2",
  "status": "completed"
}
```

**Response — `429 Too Many Requests`** (user already has `RATE_LIMIT_MAX` active —
`queued` or `processing` — documents)

```json
{
  "detail": "Rate limit exceeded: too many active documents"
}
```

**Response — `422 Unprocessable Entity`** (validation failure, e.g. empty `content` or
missing field — standard FastAPI/Pydantic error shape)

```json
{
  "detail": [
    {
      "type": "string_too_short",
      "loc": ["body", "content"],
      "msg": "String should have at least 1 character",
      "input": ""
    }
  ]
}
```

### `GET /documents/{document_id}`

Fetch a single document's current status and result.

**Response — `200 OK`**

```json
{
  "document_id": "66f1a2b3c4d5e6f7a8b9c0d1",
  "user_id": "user-123",
  "title": "Q3 Financial Report",
  "status": "completed",
  "summary": "Summary (812 words): This quarter we saw significant growth across all business units...",
  "error": null,
  "created_at": "2026-09-02T10:15:30.123456+00:00",
  "updated_at": "2026-09-02T10:15:42.987654+00:00"
}
```

A `failed` document instead has `summary: null` and `error: "simulated processing
failure"`.

**Response — `404 Not Found`** (document does not exist, or `document_id` is not a
valid MongoDB ObjectId)

```json
{
  "detail": "Document not found"
}
```

### `GET /users/{user_id}/documents`

List a user's documents, newest first, with pagination and optional status filtering.

Query parameters: `page` (default `1`, `>= 1`), `page_size` (default `20`, `1`–`100`),
`status` (optional — one of `queued`, `processing`, `completed`, `failed`).

```
GET /users/user-123/documents?page=1&page_size=20&status=completed
```

**Response — `200 OK`**

```json
{
  "items": [
    {
      "document_id": "66f1a2b3c4d5e6f7a8b9c0d1",
      "title": "Q3 Financial Report",
      "status": "completed",
      "created_at": "2026-09-02T10:15:30.123456+00:00"
    }
  ],
  "page": 1,
  "page_size": 20,
  "total": 1
}
```

**Response — `422 Unprocessable Entity`** (e.g. `page_size=500`, which exceeds the cap
of `100`, or an invalid `status` value).

### `GET /health`

Reports connectivity to Mongo and Redis.

**Response — `200 OK`** (both dependencies reachable)

```json
{
  "status": "ok",
  "mongo": true,
  "redis": true
}
```

**Response — `503 Service Unavailable`** (either dependency unreachable)

```json
{
  "status": "degraded",
  "mongo": false,
  "redis": true
}
```

## Running Tests

Tests need a real MongoDB and Redis reachable at `localhost:27017` / `localhost:6379`.
The easiest way is to bring up just those two services from the Compose file:

```bash
docker compose up -d mongo redis
pip install -r requirements.txt
pytest -v
```

Tests write to the `document_insights_test` database (never `document_insights`) and
flush the Redis database between tests, so it is safe to point at the same Redis
instance used by the running stack. All 23 tests pass. Local development/testing
targets Python 3.11+ (matching the `python:3.11-slim` base image used by `Dockerfile`).

## Design Decisions

- **Separate worker with atomic claim.** Processing runs in a standalone
  `python -m app.workers.document_worker` process, so submissions return immediately. Each job is
  claimed with a single `find_one_and_update` (a due `queued` job, or a stale
  `processing` job to reclaim after a crash), so two workers can never process the
  same document — no distributed lock needed.
- **Redis for two concerns, Mongo as source of truth.** Redis backs a per-user
  rate-limit counter (`INCR`/`DECR` + safety-net TTL) and a `sha256(content)` summary
  cache. If Redis is down, both fall back to Mongo (`count_active` and
  `find_completed_by_hash`), so correctness never depends on Redis.
- **Retry with exponential backoff.** A failed attempt is requeued with
  `next_attempt_at = now + 2 ** attempts` until `MAX_ATTEMPTS` (default 3), then
  marked `failed` and its rate-limit slot released.
- **Indexes per access pattern.** Five indexes match the queries the service runs:
  `{user_id, created_at desc}`, `{user_id, status}`, `{content_hash}`, and
  `{status, next_attempt_at}` / `{status, processing_started_at}` for the two claim
  branches.

## Assumptions

- The "insight" produced is a mock summary: `f"Summary ({word_count} words): {content[:SUMMARY_CHAR_LIMIT]}"` — word count of the full document plus the first `SUMMARY_CHAR_LIMIT` characters (default 500).
- The ~10% random failure is applied **per processing attempt**, not per document. Combined with retry-with-backoff (`MAX_ATTEMPTS`, default 3), far fewer than 10% of documents end up permanently `failed` — the injected failures exist to exercise the retry and error-handling paths, which they do on most attempts.
- A syntactically invalid `document_id` (not a valid MongoDB ObjectId) is treated the same as "not found" and returns `404`, not `400`/`422`.
- A submission that resolves via the content cache (identical content already processed) returns `completed` immediately and is **not** counted against the submitter's rate limit — the rate-limit slot is only acquired on the path that actually queues a job.
- `page_size` for the user-documents listing is capped at `100` to bound response size and query cost.
- MongoDB is the system of record; Redis is purely an accelerator (rate-limit counter, content cache). Any Redis outage degrades performance/rate-limit precision but the service keeps functioning via Mongo fallbacks, and `/health` reports Redis status separately so this is observable.

## What I'd Improve With More Time

- **Replace worker polling with an event-driven trigger** (MongoDB change streams or a real queue like Redis Streams/SQS) to cut pickup latency and the constant poll load on Mongo as workers scale out.
- **Make the rate-limit acquire atomic** with a small Redis Lua script (or `INCR` + conditional), closing the brief window where concurrent submits can momentarily admit past the limit.
- **Add authentication/authorization** — `user_id` is currently trusted from the client, so any caller can submit or list documents as any user.
- **Emit metrics and traces** (Prometheus/OpenTelemetry): queue depth, processing latency, and failure rate. Today observability is structured logs plus `/health` only.
- **Fair scheduling** so one heavy user can't monopolize the global FIFO claim order (e.g. per-user round-robin or weighted queues).
- **CI pipeline** running lint + tests on every push, and a self-contained test harness (ephemeral Mongo/Redis containers) so the suite needs no manually started services.
