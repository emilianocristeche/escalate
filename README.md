# Escalate

**Support-ticket triage & SLA early-warning API.** Ingest tickets, auto-classify
severity + category, and surface which ones are about to breach their SLA —
before they do.

Built by a Tier 2 support engineer who watched SLA breaches happen because
nobody could see them coming. So this is the tool that predicts them.

---

## Stack

FastAPI · SQLAlchemy 2.0 · PostgreSQL (SQLite for local/CI) · React + Vite · pytest · Docker Compose · GitHub Actions

## Quickstart

### Local (SQLite, zero infra)

```bash
python -m venv .venv && source .venv/Scripts/activate   # Windows Git Bash
#                                    source .venv/bin/activate   # macOS/Linux
pip install -r requirements-dev.txt
python -m app.seed                 # 10 synthetic tickets
uvicorn app.main:app --reload      # http://localhost:8000/docs
```

### Docker (Postgres, production-like)

```bash
docker compose up --build          # API on :8000, Postgres on :5432
```

## API

| Method | Path | What |
|--------|------|------|
| `POST` | `/tickets` | Ingest a ticket; severity + category are auto-classified |
| `GET` | `/tickets` | List tickets (filter: `resolved`, `severity`, `category`) |
| `POST` | `/tickets/{id}/resolve` | Mark resolved (stops the SLA clock) |
| `GET` | `/tickets/at-risk` | Open tickets breaching within `?window_min` (default 30) |
| `GET` | `/metrics` | Queue health: volume, breach rate, MTTR, breakdowns |
| `GET` | `/health` | Liveness probe |

Interactive docs (Swagger) at `/docs`.

### Example: `/metrics` after seeding

Real output of `python -m app.seed` followed by `curl -s localhost:8000/metrics | python -m json.tool`:

```json
{
    "total": 10,
    "open": 10,
    "resolved": 0,
    "breached_open": 1,
    "at_risk": 2,
    "breach_rate": 0.1,
    "by_category": {
        "billing": 3,
        "general": 2,
        "connectivity": 2,
        "api": 2,
        "account": 1
    },
    "by_severity": {
        "P1": 2,
        "P3": 4,
        "P2": 2,
        "P4": 2
    },
    "mttr_minutes": null
}
```

### Example: `/tickets/at-risk`

Real output of `curl -s localhost:8000/tickets/at-risk | python -m json.tool`, taken
a few seconds after seeding (so `minutes_to_breach` depends on when you call it):

```json
[
    {
        "id": 1,
        "subject": "Payments API returning 500 for all customers",
        "body": "Every charge fails since 10am",
        "customer": "acme-co",
        "severity": "P1",
        "category": "billing",
        "resolved": false,
        "created_at": "2026-10-15T22:19:43.028163",
        "resolved_at": null,
        "minutes_to_breach": 4.8,
        "deadline": "2026-10-15T23:19:43.028163Z"
    },
    {
        "id": 2,
        "subject": "Cannot pay \u2014 card reader offline",
        "body": "Terminal shows outage",
        "customer": "bluebird-cafe",
        "severity": "P1",
        "category": "general",
        "resolved": false,
        "created_at": "2026-10-15T22:34:43.028163",
        "resolved_at": null,
        "minutes_to_breach": 19.8,
        "deadline": "2026-10-15T23:34:43.028163Z"
    }
]
```

`created_at` is always set by the server. `POST /tickets` rejects it (and any
other unknown field) with a `422`, so a client cannot backdate a ticket to fake
or hide an SLA breach.

## Dashboard

A React + Vite dashboard (`web/`) shows live metrics, an at-risk list, and the
queue, with inline resolve and ticket creation. Polls the API every 10s.

```bash
cd web
npm install
npm run dev            # http://localhost:5173 (expects the API on :8000)
```

For production, set `VITE_API_URL` to your deployed API URL at build time.

## Classification: rules vs LLM

**v1 — rule-based** ([`app/classifier.py`](app/classifier.py)): keyword heuristics
map text → severity (P1–P4) + category. Keywords match on word boundaries with an
optional plural (`outage` matches "outages" but `down` does not match "download").
Instant, free, deterministic, fully tested.

**v2 — LLM classifier** ([`app/llm_classifier.py`](app/llm_classifier.py), optional):
handles ambiguous / mixed-language tickets the rules miss. Requires
`ANTHROPIC_API_KEY` + `pip install anthropic`. If a call fails (API error, timeout,
non-JSON or truncated reply), the failure is logged as a warning with its traceback
and the ticket falls back to the rules; the benchmark reports how many calls did.

**Hybrid** routes only *low-confidence* tickets to the LLM. Confidence proxy: the
rules are "confident" when a keyword actually matched, "guessing" when they fell
through to a default. Most of the accuracy lift, a fraction of the cost.

### Benchmark

```bash
python -m app.benchmark              # rules real; LLM+hybrid if ANTHROPIC_API_KEY set
python -m app.benchmark --mock-llm   # verify the harness with a stubbed oracle
```

On the bundled 30-ticket labeled set (deliberately mixes English, Spanish,
sarcasm, and no-keyword phrasing):

| Classifier | Both-axis acc | LLM calls | Est. cost |
|---|---|---|---|
| rules-only | 40% | 0/30 | $0.0000 |
| hybrid (upper bound via `--mock-llm`) | 90% | 21/30 | $0.0040 |

The rules keep 9/30 confident tickets for free; only the 21 they're unsure about
cost an LLM call. Real LLM numbers land once you run it with a key — the mock row
shows the routing mechanics and the accuracy ceiling.

## SLA logic

Per-severity resolution budgets ([`app/sla.py`](app/sla.py)):

| Severity | Budget |
|----------|--------|
| P1 | 1 hour |
| P2 | 4 hours |
| P3 | 1 day |
| P4 | 2 days |

A ticket is **at risk** when it's unresolved and within `window_min` of its
deadline; **breached** once past it. All math is on timezone-aware UTC.

## Tests

```bash
pytest -q                 # 28 tests
python app/classifier.py  # zero-dependency self-check
python app/sla.py         # zero-dependency self-check
```

CI runs all three on every push ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)).

## Structure

```
app/
  classifier.py       rule-based severity + category (pure, self-checking)
  llm_classifier.py   optional LLM classifier (Anthropic)
  benchmark.py        rules vs LLM vs hybrid, markdown table
  eval_data.py        30 labeled tickets for the benchmark
  sla.py              deadline + breach-risk math (pure, self-checking)
  metrics.py          aggregation over a ticket list (pure)
  models.py           SQLAlchemy Ticket
  schemas.py          Pydantic request/response
  db.py               engine/session (Postgres or SQLite)
  main.py             FastAPI routes + CORS
  seed.py             synthetic seed data
tests/                classifier / sla / api
web/                  React + Vite dashboard
```

## Deploy

- **API → Render:** `render.yaml` blueprint provisions the Docker web service +
  a free Postgres. New → Blueprint → point at this repo. After it's live, set
  `CORS_ORIGINS` to your dashboard URL.
- **Dashboard → Vercel:** import the repo, set root directory to `web/`, add env
  `VITE_API_URL=<your Render API URL>`. `web/vercel.json` handles the build.

## Roadmap

- [x] v2 LLM classifier + rules-vs-LLM-vs-hybrid benchmark
- [x] React dashboard (queue + at-risk + live metrics)
- [x] Deploy configs (Render blueprint + Vercel)
- [ ] Push live + record a 2-min demo video

## What I Learned

_TODO: section to be written by the author._

## Note

All seed/demo data is **synthetic**. No real customer or employer data is used.
