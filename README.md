# Mississippi Civil Opportunity Finder

A local business-development workspace for a small Mississippi civil engineering firm. Collectors feed a reusable normalization, classification, relevance-scoring, and deduplication pipeline; a FastAPI/Jinja dashboard supports discovery and pursuit review.

**Phase 1 is a working foundation with an offline synthetic scraper. It has no live Mississippi procurement coverage.** The initial database is empty. Demo opportunities are fictional, marked `DEMO`, and never included in daily collection. No credentials or external AI services are required.

## Quick start — Windows PowerShell

Python 3.12+ is required. This implementation was verified with Python 3.14.4 on Windows. From a new checkout:

```powershell
Set-Location "C:\Python Projects\Civil-Opportunity-Finder"
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000>. Stop the server with `Ctrl+C`. Explicit interpreter paths avoid PowerShell activation-policy issues. Optional activation:

```powershell
.\.venv\Scripts\Activate.ps1
```

`requirements.lock.txt` records the exact verified environment; `requirements.txt` specifies direct compatible dependency ranges for future updates. Do not start multiple web workers or multiple scheduled app instances. Do not bind this unauthenticated Phase 1 application to an office network or public interface.

### Optional demo data

In a second PowerShell window, using the same project directory:

```powershell
.\.venv\Scripts\python.exe -m scripts.load_demo
```

Reload the dashboard. Three fictional opportunities demonstrate professional-services relevance, unrelated-commodity penalties, and missing fields. Repeating the command updates existing records. The sample dates are fixed fixture dates; they are not current notices. Demo original links use the reserved, non-resolving `example.invalid` domain.

## Architecture

Project layout (package marker files omitted):

```text
Civil-Opportunity-Finder/
├── app/
│   ├── main.py, config.py, database.py, security.py, logging_config.py
│   ├── models/          opportunity.py, source.py, collection_run.py
│   ├── schemas/         opportunity.py
│   ├── scrapers/        base.py, registry.py, fixture.py, fixtures/demo.html
│   ├── services/        classifier.py, scoring.py, normalizer.py,
│   │                    deduplicator.py, query.py, collection.py, lock.py
│   ├── routes/          api.py, web.py
│   ├── templates/       base.html, dashboard.html, detail.html, sources.html
│   └── static/          app.css, app.js, favicon.svg, vendor/
├── scripts/             scrape.py, load_demo.py
├── tests/               conftest.py, test_api_web.py, test_collection.py,
│                        test_classifier_scoring.py, test_deduplicator.py,
│                        test_normalizer.py, test_scraper_http.py, fixtures/
├── data/                .gitkeep (runtime databases/locks ignored)
├── requirements.txt
├── requirements.lock.txt
├── .env.example
├── .gitignore
├── LICENSE
└── README.md
```

```text
Source module → BaseScraper.fetch/parse/normalize/run
              → validated OpportunityInput
              → CollectionService
              → deduplication + merged-field classification/scoring
              → SQLAlchemy transaction → SQLite
              → shared query service → REST API / Jinja dashboard
```

- `app/config.py` loads validated environment settings. Paths resolve relative to the repository using `pathlib`.
- `app/database.py` creates engines and sessions, configures SQLite, and restores UTC-aware timestamps after database reads.
- `app/models/` defines opportunities, source metadata, and durable collection runs.
- `app/schemas/` separates ingestion fields from API output and status updates.
- `app/scrapers/` isolates parsing by source. The registry maps stable slugs to classes.
- `app/services/` handles normalization, classification, relevance, deduplication, querying, orchestration, and local collection locking.
- `app/routes/` contains thin web/API routes. Templates autoescape source content; local Bootstrap assets avoid CDN dependencies.
- `scripts/` provides collection and explicit demo loading. `tests/` uses saved HTML and mocked HTTP, never live websites.

Startup creates missing tables and inserts registry source metadata. It does **not** migrate existing schemas; add explicit migrations before changing a populated production schema. SQLite is the initial backend; ORM models, portable queries, JSON lists, decimal values, and `DATABASE_URL` allow a future PostgreSQL migration. PostgreSQL driver installation and data migration are not implemented in Phase 1.

## Configuration

Copy `.env.example` to `.env`; environment variables override the file. `.env` and databases are ignored by Git.

| Variable | Default / behavior |
| --- | --- |
| `DATABASE_URL` | `sqlite:///./data/opportunities.db`; relative SQLite paths resolve under the project |
| `SCRAPER_USER_AGENT` | Descriptive tool name; add a real contact before live collection |
| `SCRAPER_TIMEOUT` | 20 seconds per HTTP operation |
| `SCRAPER_DELAY` | At least 2 seconds between requests to a host |
| `SCRAPER_RETRIES` | 3 retries after the first attempt; exponential backoff |
| `ENABLE_SCHEDULER` | `false`; scheduler exists only while the server is running |
| `SCRAPE_HOUR` / `SCRAPE_MINUTE` | Daily at 07:00 |
| `SCHEDULER_TIMEZONE` | `America/Chicago`; `tzdata` supplies Windows timezone data |
| `DUE_SOON_DAYS` | 7 calendar days, inclusive of today |
| `SCORING_WEIGHTS` | JSON object; partial overrides merge with default factors |

To use a separate database for experimentation:

```powershell
$env:DATABASE_URL = 'sqlite:///./data/sandbox.db'
.\.venv\Scripts\python.exe -m scripts.load_demo
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001
# After stopping the server:
Remove-Item Env:DATABASE_URL
```

## Manual collection and scheduler

```powershell
# All active, non-demo sources (currently an intentional zero-record run):
.\.venv\Scripts\python.exe -m scripts.scrape
# Once a real source slug is registered:
.\.venv\Scripts\python.exe -m scripts.scrape --source your-source-slug
# Explicit fictional source:
.\.venv\Scripts\python.exe -m scripts.load_demo
```

CLI output includes the durable run ID and counts; failed or partial runs exit with code 1. API collection is accepted asynchronously and returns a run ID. A process lock plus local OS file lock prevents concurrent web/CLI collection for the same database. OS locks release on exit or crash; startup marks orphaned runs `INTERRUPTED` only when no collection holds the lock. Locks are local-computer safeguards, not distributed PostgreSQL locks.

Enable daily collection using `ENABLE_SCHEDULER=true`. APScheduler runs in the FastAPI lifespan, coalesces missed executions, and limits the job to one instance. It does not collect immediately at startup. Disabled sources and the demo source are excluded from scheduled/all-source runs. Selecting a real source explicitly runs it even when its automatic-collection flag is disabled. Source activation is registry/database configuration in Phase 1; no source-edit API is implemented.

Each source gets a separate transaction. A failed source rolls back its opportunities and successful-write counters; later sources continue. Run outcomes are `RUNNING`, `SUCCEEDED`, `PARTIAL`, `FAILED`, or `INTERRUPTED`. JSON logs report source, start/finish, discoveries, additions, updates, and errors. Persistent run history appears at `/sources` and through the API. An updated count means an existing record was observed and refreshed, even if its content was unchanged.

## Classification, scoring, and deduplication

The classifier counts distinct matching phrases across title, description, and raw text. The category with the most phrases wins; dictionary insertion order breaks ties. Additional category matches become subcategories. Keyword dictionaries are separate from scrapers and can be supplied to the classifier. Category values match the requested list, including `SITE DEVELOPMENT` with a space. Phrase boundaries avoid matches inside unrelated words. `OTHER` is the fallback.

Scoring counts each factor once, sums configured weights, and clamps the result to 0–100:

| Factor | Default |
| --- | ---: |
| Civil engineering | +20 |
| Recognized civil discipline | +25 |
| Professional services | +20 |
| Explicit Mississippi location | +10 |
| RFQ/RFP | +10 |
| Consulting | +10 |
| Design | +15 |
| Unrelated supplies/equipment/janitorial/IT/medical signals | −65 |

This is an internal relevance score, **not** an objective probability, bid eligibility judgment, project value, or chance of winning. Boolean engineering/professional-service fields remain null unless a source provides evidence for them; scoring can independently recognize text signals. Review original notices before making business decisions.

Duplicate matching uses agency-scoped solicitation numbers first, then canonical detail URLs, content hashes, and normalized titles with agency and compatible dates. Conflicting solicitation numbers prevent URL/title-based merging. Fuzzy matching requires a matching agency, the same known due date, titles at least 20 characters long, and similarity of at least 95%. Exact title/agency matching permits both dates to be missing. Tracking URL parameters are removed; identifier parameters are preserved. Hashes deterministically cover source content, excluding workflow and discovery fields.

Repeated records refresh `last_seen`, non-null source fields, classification, and score. They preserve `first_seen`, your status, and existing values when the new source omits them. Due-date expiry or disappearance never changes pursuit status. Deduplication scans records conservatively in Phase 1; indexed identity keys and per-source provenance/history are future improvements for larger datasets. Cross-source merges retain the latest source attribution.

## Dashboard and workflow

The responsive dashboard starts in dark mode; the light-mode preference stays in the browser. Search title, agency, description, solicitation number, and raw text. Filter category, agency, county, city, source, minimum score, due-date range, and status. Sort by score, nearest due date, latest posted date, or newest discovery. Undated opportunities sort last for date sorts. Pagination preserves filters.

Detail pages show all supplied fields, discovery timestamps, contact information, raw text, and the original link. Workflow states are `NEW`, `REVIEWING`, `INTERESTED`, `NOT_INTERESTED`, `SUBMITTED`, and `ARCHIVED`. Deadlines are date-only because Phase 1 cannot safely infer source-specific closing times.

## REST API

| Method | Endpoint | Behavior |
| --- | --- | --- |
| GET | `/api/health` | Database readiness, scheduler flag, CSRF token |
| GET | `/api/opportunities` | Paginated filtered results |
| GET | `/api/opportunities/{id}` | Full record |
| PATCH | `/api/opportunities/{id}` | JSON `{ "status": "INTERESTED" }`; other changes rejected |
| GET | `/api/sources` | Registered source metadata |
| POST | `/api/scrape` | All active non-demo sources; HTTP 202 + run ID |
| POST | `/api/scrape/{source}` | One real registered source slug |
| GET | `/api/scrape-runs/{id}` | Batch and per-source results/errors |
| GET | `/openapi.json` | Machine-readable API schema |

Query parameters: `q`, `category`, `agency`, `county`, `city`, `source` (source display name), `min_score`, `due_from`, `due_to`, `status`, `sort`, `page`, and `page_size`. Dates use `YYYY-MM-DD`; sort values are `match_score`, `due_date`, `posted_date`, and `newest`; page size is 1–100. Responses contain `items`, `total`, `page`, and `page_size`. Invalid values return 422, missing objects/slugs return 404, and overlapping collection returns 409. Demo collection through normal scrape endpoints is intentionally blocked; use `scripts.load_demo`.

```powershell
Invoke-RestMethod 'http://127.0.0.1:8000/api/opportunities?category=ROADWAY&min_score=70'

# Preserve the CSRF cookie in a session and supply its matching token:
$health = Invoke-RestMethod 'http://127.0.0.1:8000/api/health' -SessionVariable finderSession
$headers = @{ 'X-CSRF-Token' = $health.csrf_token }
$run = Invoke-RestMethod 'http://127.0.0.1:8000/api/scrape' -Method Post -WebSession $finderSession -Headers $headers
Invoke-RestMethod "http://127.0.0.1:8000$($run.status_url)" -WebSession $finderSession

# With a valid opportunity ID:
Invoke-RestMethod 'http://127.0.0.1:8000/api/opportunities/1' -Method Patch -WebSession $finderSession -Headers $headers -ContentType 'application/json' -Body '{"status":"INTERESTED"}'
```

Interactive CDN-backed API documentation is disabled to keep the local content security policy strict; `/openapi.json` remains available. Browser mutation forms include CSRF tokens; REST mutations require the matching cookie/header. Cross-origin mutations are rejected, allowed hosts are localhost/loopback, and no CORS policy is enabled. These protections do not replace authentication for future shared deployment.

## Database structure

- `opportunities`: all requested identity, source, description, classification, location, dates, contact, procurement, value, engineering flags, raw content, discovery timestamps, workflow, score, and content-hash fields. Subcategories are JSON; values use `Numeric(18,2)`; unknown fields are null. Status and score have database constraints.
- `sources`: requested fields plus a unique stable `slug` for registry/API selection. Startup preserves activation choices for existing rows.
- `collection_runs`: UUID identity, optional parent batch ID, source slug, UTC start/finish, outcome, discovered/added/updated counts, and errors. Each batch has per-source child rows.

Timestamps are UTC-aware in the application/API. Procurement dates are date-only. SQLite files, logs, fixture verification artifacts, environments, and `.env` are excluded from source control. To back up SQLite reliably, stop the server and CLI processes before copying the database.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pip check
```

Tests use temporary databases, saved HTML, and mocked network responses. They cover every classification category, configurable relevance factors and bounds, normalization, duplicate identities/fuzzy constraints, status preservation, source rollback/failure isolation, overlapping runs, API validation/pagination, rendering/escaping, CSRF/origin checks, and scheduler lifecycle. No live site needs to be available. The locked Starlette/httpx test client currently emits one upstream deprecation warning; it does not affect application HTTP collection or test results.

Phase 1 verification on September 25, 2026 (America/Chicago): **88 tests passed**, and `pip check` found no dependency conflicts. Live local-server checks confirmed health/API startup, SQLite initialization, empty dashboard rendering, and the OpenAPI schema. Browser checks confirmed populated desktop/mobile layouts, light-mode persistence, keyword filtering, pursuit-status submission, and collection status polling. An isolated verification database loaded three demo records; repeated ingestion added zero duplicates and preserved an `INTERESTED` status. The default database remained empty.

## Adding a real scraper — Phase 2

1. Inspect the site's robots policy and terms, HTML, legitimate public APIs/network traffic, pagination, detail URLs, and date semantics before coding. Prefer public JSON endpoints where suitable; never bypass authentication or access controls.
2. Add an isolated module under `app/scrapers/` extending `BaseScraper`. Set `slug`, `source_name`, `source_url`, source metadata, and `default_active`. Keep URLs centralized in that module.
3. Implement `parse(content)` to return ingestion dictionaries. Use `self.http.get(url)` for listing/detail requests, including any pagination. Validate expected structure; an empty valid results container differs from a changed/error page.
4. Leave absent fields null, preserve raw text, resolve relative links, and let the pipeline normalize/classify/score/persist. Do not put these services in the scraper or API routes.
5. Register the class in `SCRAPERS`, add representative saved fixtures and mocked HTTP tests, then run that source manually before enabling daily collection.
6. Document data coverage, source policies, pagination, and known limitations. For inaccessible sources, register a disabled stub with explanatory notes and move on.

`PoliteHTTPClient` provides timeouts, host delays, robots checks, redirect checks, 429/5xx/network retries, exponential backoff, and `Retry-After` support. It respects robots crawl-delay/request-rate directives. If robots cannot be verified (including 404 or an HTML error page), collection fails visibly rather than assuming permission. Retry delays over 120 seconds defer the source to another run. A future scraper must still assess site terms separately. JavaScript browser automation is not installed or required by the application; add it only when a real source needs rendering.

## Supported sources and limitations

| Slug | Coverage | Automatic collection |
| --- | --- | --- |
| `demo-fixture` | Three fictional notices from saved local HTML | Always excluded |

There are no real state, MDOT, municipal, county, university, utility, airport, or portal scrapers yet. This is the explicit Phase 1 boundary. Source permissions, real procurement semantics, and live-source reliability have not been validated. Keyword classification can misread context; deduplication is conservative but imperfect. No PDF/document downloads, addenda detection, time-of-day deadlines, export, alerts, accounts, CRM, maps, or hosted deployment are implemented. Scheduling requires the application to stay running.

Future features can extend the source registry, ingestion service, database models, and query layer independently. Add authentication, proper migrations, a durable worker/distributed lock, and deployment controls before multi-user or hosted operation.
