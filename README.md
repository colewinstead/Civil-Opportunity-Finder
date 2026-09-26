# Mississippi Civil Opportunity Finder

A local business-development workspace for a small Mississippi civil engineering firm. Collectors feed a reusable normalization, classification, relevance-scoring, and deduplication pipeline; a FastAPI/Jinja dashboard supports discovery and pursuit review.

**Phase 2 adds one live source: Mississippi’s public statewide procurement portal.** New checkouts start with an empty database; run collection to populate it. The verified local Phase 2 database contains live records. Demo opportunities are fictional, marked `DEMO`, and never included in daily collection. No credentials or external AI services are required.

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

`requirements.lock.txt` records the exact verified environment; `requirements.txt` specifies direct compatible dependency ranges for future updates. Do not start multiple web workers or multiple scheduled app instances. Do not bind this unauthenticated local application to an office network or public interface.

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
│   ├── scrapers/        base.py, registry.py, fixture.py,
│   │                    mississippi_procurement.py, fixtures/demo.html
│   ├── services/        classifier.py, scoring.py, normalizer.py,
│   │                    deduplicator.py, query.py, collection.py, lock.py
│   ├── routes/          api.py, web.py
│   ├── templates/       base.html, dashboard.html, detail.html, sources.html
│   └── static/          app.css, app.js, favicon.svg, vendor/
├── scripts/             scrape.py, load_demo.py
├── tests/               conftest.py, test_api_web.py, test_collection.py,
│                        test_classifier_scoring.py, test_deduplicator.py,
│                        test_normalizer.py, test_scraper_http.py,
│                        test_mississippi_procurement.py, fixtures/
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
- `scripts/` provides collection and explicit demo loading. `tests/` uses saved HTML/JSON and mocked HTTP, never live websites.

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
# All active, non-demo sources (currently Mississippi procurement only):
.\.venv\Scripts\python.exe -m scripts.scrape
# Only the live Mississippi source:
.\.venv\Scripts\python.exe -m scripts.scrape --source mississippi-procurement
# Explicit fictional source:
.\.venv\Scripts\python.exe -m scripts.load_demo
```

CLI output includes the durable run ID and counts; failed or partial runs exit with code 1. API collection is accepted asynchronously and returns a run ID. A process lock plus local OS file lock prevents concurrent web/CLI collection for the same database. OS locks release on exit or crash; startup marks orphaned runs `INTERRUPTED` only when no collection holds the lock. Locks are local-computer safeguards, not distributed PostgreSQL locks.

**Scheduling remains disabled by default and was not enabled in Phase 2.** For a later, explicitly approved unattended phase, daily collection can be enabled using `ENABLE_SCHEDULER=true`. APScheduler runs in the FastAPI lifespan, coalesces missed executions, and limits the job to one instance. It does not collect immediately at startup. Disabled sources and the demo source are excluded from scheduled/all-source runs. Selecting a real source explicitly runs it even when its automatic-collection flag is disabled. Source activation is registry/database configuration in Phase 1; no source-edit API is implemented.

Each source gets a separate transaction. A failed source rolls back its opportunities and successful-write counters; later sources continue. A scraper may report individual record errors: valid records commit with a `PARTIAL` outcome, error details remain visible, and `last_successful` is not advanced. All candidate records failing produces `FAILED`. Run outcomes are `RUNNING`, `SUCCEEDED`, `PARTIAL`, `FAILED`, or `INTERRUPTED`. JSON logs report source, start/finish, discoveries, additions, updates, and errors. The live scraper also logs pages fetched, detail requests, parsed/normalized counts, and malformed/skipped records. Discovered means all open listing rows before relevance filtering; updated means matched/refreshed, including unchanged content. Persistent run history appears at `/sources` and through the API. An updated count means an existing record was observed and refreshed, even if its content was unchanged.

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

Detail pages show all supplied fields, discovery timestamps, contact information, raw text, and the original link. Workflow states are `NEW`, `REVIEWING`, `INTERESTED`, `NOT_INTERESTED`, `SUBMITTED`, and `ARCHIVED`. Deadlines are date-only. Source-provided closing times remain available in raw text; the portal does not state a closing timezone. Always check the original notice for the exact submission requirements.

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

Tests use temporary databases, saved HTML/JSON, and mocked network responses. The test app uses an isolated fixture-only registry, and an automatic guard rejects real HTTP transports. They cover every classification category, configurable relevance factors and bounds, normalization, duplicate identities/fuzzy constraints, status preservation, source rollback/failure isolation, overlapping runs, API validation/pagination, rendering/escaping, CSRF/origin checks, and scheduler lifecycle. No live site needs to be available. The locked Starlette/httpx test client currently emits one upstream deprecation warning; it does not affect application HTTP collection or test results.

Phase 1 verification on September 25, 2026 (America/Chicago): **88 tests passed**, and `pip check` found no dependency conflicts. Live local-server checks confirmed health/API startup, SQLite initialization, empty dashboard rendering, and the OpenAPI schema. Browser checks confirmed populated desktop/mobile layouts, light-mode persistence, keyword filtering, pursuit-status submission, and collection status polling. An isolated verification database loaded three demo records; repeated ingestion added zero duplicates and preserved an `INTERESTED` status. The default database remained empty.

Phase 2 verification on September 26, 2026: **137 tests passed, zero failed**,
including all 88 original cases; dependency checks passed. Using the existing
manual CLI against the default database, run one fetched two listing pages and
89 detail responses, discovered 129 open listings, parsed/normalized 12 relevant
records, and inserted 12 with no errors. Run two fetched the same coverage,
inserted zero and refreshed all 12 with no errors. Direct SQLite checks found no
duplicate URL or agency/solicitation groups. Record IDs and `first_seen` values
were unchanged, all `last_seen` timestamps advanced, and an API-selected
`INTERESTED` status was preserved. Improved explicit issuer extraction refreshed
six agency fields in place on the second run. Changed-deadline updates are also
covered by offline integration tests.

Health/API startup, live desktop/mobile dashboard and detail rendering, all
filter types, four sort modes, source history, and run polling were checked.
Original detail pages loaded successfully and their submission dates/times
matched the stored date/raw-text values. The dashboard contains live data in
`data/opportunities.db`; databases and verification logs remain ignored by Git.
**The scheduler remains disabled.** Source counts are a dated verification
snapshot, not a promise about future portal coverage.

## Adding another scraper

1. Inspect the site's robots policy and terms, HTML, legitimate public APIs/network traffic, pagination, detail URLs, and date semantics before coding. Prefer public JSON endpoints where suitable; never bypass authentication or access controls.
2. Add an isolated module under `app/scrapers/` extending `BaseScraper`. Set `slug`, `source_name`, `source_url`, source metadata, and `default_active`. Keep URLs centralized in that module.
3. Implement `parse(content)` to return ingestion dictionaries. Use `self.http.get(url)` or `self.http.post_form(url, data)` for public listing/detail requests, including every page. Validate expected structure; an empty valid results container differs from a changed/error page.
4. Leave absent fields null, preserve raw text, resolve relative links, and let the pipeline normalize/classify/score/persist. Do not put these services in the scraper or API routes.
5. Register the class in `SCRAPERS`, add representative saved fixtures and mocked HTTP tests, then run that source manually before enabling daily collection.
6. Document data coverage, source policies, pagination, and known limitations. For inaccessible sources, register a disabled stub with explanatory notes and move on.

`PoliteHTTPClient` provides timeouts, host delays, robots checks, safe GET/form-POST redirect checks, 429/5xx/network retries, exponential backoff, and `Retry-After` support. It respects robots crawl-delay/request-rate directives. If robots cannot be verified (including 404 or an HTML error page), collection fails visibly rather than assuming permission. Retry delays over 120 seconds defer the source to another run. A future scraper must still assess site terms separately. JavaScript browser automation is not installed or required by the application; add it only when a real source needs rendering.

## Supported sources and limitations

| Slug | Coverage | All-source manual collection |
| --- | --- | --- |
| `mississippi-procurement` | Open engineering services and civil infrastructure notices in the Mississippi public procurement portal | Enabled |
| `demo-fixture` | Three fictional notices from saved local HTML | Always excluded |

### Live source: Mississippi Procurement Opportunity and Public Notification Search

**Source:** [Mississippi procurement search](https://www.ms.gov/dfa/contract_bid_search/bid).
This statewide portal includes agency and local-government notices, engineering
RFQs/RFPs, sewer/water construction, bridges, roadway projects, and other civil
work. It supplies a useful statewide mix rather than a commodity-only feed.

Access investigation on September 26, 2026 found public access without login,
account, CAPTCHA, or observed access-control bypass. The [robots policy](https://www.ms.gov/robots.txt)
permits these paths; the client checks it on each run. The linked
[privacy policy](https://www.ms.gov/privacy-policy) and
[linking policy](https://www.ms.gov/linking-policy) were reviewed; no automation
prohibition was found there. This is not a guarantee of continued permission;
reassess policies if the portal changes. MDOT was considered but its investigated
data endpoint returned 403, so no workaround or MDOT scraper was added.

**Delivery:** the source page's own public JSON endpoints, without browser
rendering. `POST /dfa/contract_bid_search/Bid/BidData?AppId=1&Status=Open` accepts
its legacy DataTables form. The scraper requests 100 rows per page, ascending
`BidID`, with `iDisplayStart` offsets until `iTotalDisplayRecords` is exhausted.
It fails visibly on duplicate IDs, changing totals, inconsistent counts, no
progress, or a 100-page safety limit, rather than silently truncating coverage.
The reviewed response contained 129 open listings across two pages.

**Details:** all open rows except explicit noncompetitive notification types are fetched from
`GET /dfa/contract_bid_search/Bid/BidDetailData/{BidID}`. Major categories are checked only after detail retrieval, because a utility
construction notice was incorrectly labeled COMMODITIES. Notification subtypes
13–15 remain excluded before details. Final relevance uses the existing
classifier, descriptions/instructions, attachment names, engineering codes and
verified civil service codes. Unrelated IT and commodity records still require
explicit civil-service evidence to qualify. This prioritizes
engineering and civil construction; it does not retain every statewide purchase.
Some engineering records remain `OTHER` when their specific discipline is absent
from the source's short text. Scores remain transparent internal rankings.

**Identity:** numeric `BidID` supplies the stable original link
`https://www.ms.gov/dfa/contract_bid_search/Bid/Details/{BidID}`. The portal's RFx
`ObjectID` is the solicitation number, falling back to its smart number and then
the source-prefixed BidID. All available identifiers remain in raw text. Existing
agency-scoped solicitation/URL deduplication handles repeat and changed records.
An explicit issuer such as “Lee County requests proposals” replaces generic
publisher `MPTAP` as the agency; otherwise the supplied agency is retained.
Explicit bid-receiving entities are also extracted from construction notices.
Publisher addresses are not treated as project locations. Only explicit county
names and City/Town issuer names populate location fields; unknown locations
and estimated values remain null. Explicit
notice contacts are preferred over generic BID BANK contacts when supplied.

**Dates:** .NET `/Date(milliseconds)/` fields encode local calendar dates; the
parser converts the epoch through `America/Chicago` and stores the date only.
This was checked against the portal's rendered date fields. Separate
`SubmissionTime`/`AdvertiseTime` values are preserved verbatim in raw text.
`SubmissionDate` supplies the due date; an opening date never substitutes for a
missing submission date. ISO and conventional date formats are also supported.
Malformed dates/records and isolated detail failures are reported, with valid
records retained as a partial run. Access denials, exhausted HTTP 429 retries,
and three consecutive detail failures stop further requests and fail the source. Unknown closing timezone is not invented.

**Limitations:** source descriptions can be truncated to approximately 250
characters even in the detail response. The best available description and
additional instructions are stored; full scopes require opening the original
notice and its documents. Attachment descriptions/URLs remain in raw text, but
no PDF downloads, extraction, attachment model, or addenda tracking is added.
“Open” is the portal's status and may include stale or already expired deadlines;
user pursuit status is independent and never reset by collection. Public endpoints
are not a documented API contract. Relevance filtering may miss poorly described
civil work, and keyword classification/deduplication remain conservative and
imperfect. This is one source, not exhaustive Mississippi coverage.

No accounts, cloud hosting, exports, alerts, AI, GIS, CRM, document downloads,
time-of-day deadline schema, or additional live sources were added. Scheduling
requires the application to stay running and remains disabled. Future features
can extend the existing registry, ingestion service, models, and query layer.
Add authentication, proper migrations, a durable worker/distributed lock, and
deployment controls before multi-user or hosted operation.

## Focused coverage verification

A [coverage audit](docs/mississippi-procurement-coverage-audit.md), with a
[row-by-row CSV](docs/mississippi-procurement-coverage-audit.csv), reconstructed
the original 129 → 12 reduction: 40 major-category/notification exclusions before
details and 77 relevance exclusions after details. All 129 live detail JSON
responses were reviewed. Genuine keyword, truncated-description/service-code,
and mislabeled-major-category gaps were corrected within the existing scraper
and shared classifier. No new architecture, dependencies, or scheduler changes.

The corrected snapshot retained 40 relevant or potentially relevant notices and
excluded 89 (9 noncompetitive notices, 80 after detail review). Parsing and
normalization errors were zero. All 161 tests passed. Captured live responses
were replayed twice through the existing collection service: 28 added/12
refreshed, then zero added/40 refreshed, with existing status and identities
preserved. The local database now contains 40 records. This replay did not make
two additional live network collections.

New source log counters report `records_excluded_listing` and
`records_excluded_relevance`. Generic titles receive detail review; opaque JSON
whose civil scope exists only in a PDF can still be missed. Daily collection
should be treated as best effort with periodic exclusion audits. **The scheduler
remains disabled, and Phase 3 has not begun.**
