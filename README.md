# Axiom: Autonomous Market Intelligence System

A Python/FastAPI foundation for collecting market events and eventually evaluating
signals through a separate risk layer and paper broker.

## Run locally (Python 3.11+)

```bash
python -m venv .venv
source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -e '.[dev]'
cp .env.example .env
uvicorn app.main:app --reload --host 127.0.0.1
```

Open http://127.0.0.1:8000/docs for interactive API documentation.
Configuration is read from `.env` or `AXIOM_` environment variables. The SQLite
file is created automatically at `data/axiom.db` on startup. Only `paper` mode
is accepted. No credentials are needed for this initial offline scaffold.

```bash
curl -X POST http://127.0.0.1:8000/api/v1/articles \
  -H 'Content-Type: application/json' --data-binary @examples/article.json
curl http://127.0.0.1:8000/api/v1/articles
pytest
```

## Implemented

- `/health` retains the original health route and reports paper mode.
- `POST /api/v1/articles` validates and persists an article plus its analysis.
  New URLs return 201; duplicate normalized URLs return the original record (200).
- `GET /api/v1/articles?limit=50&offset=0` lists newest received records first.
- `GET /api/v1/articles/{id}` retrieves the persisted article and analysis.
- Timezone-aware publication timestamps, server receipt times, normalized supplied
  tickers, bounded request fields, and versioned baseline outputs.
- Keyword event classification; neutral sentiment and HOLD-only signals with no
  estimated confidence and no risk approval. These are explicit placeholders.
- A typed market-data provider interface for future adapters.

The API accepts submitted JSON; it does not fetch URLs or poll live news yet.
Ticker extraction, trained ML, feature generation, order execution, and portfolio
accounting are not implemented. There is no simulated fill or real broker connection.
This unauthenticated local development API should stay bound to localhost.

## Structure

| Package | Responsibility |
| --- | --- |
| `app/api` | HTTP routes |
| `app/core` | Configuration |
| `app/db`, `app/schemas` | SQLite persistence and validated contracts |
| `app/ingestion` | Ingestion orchestration |
| `app/intelligence` | Replaceable baseline analysis |
| `app/market_data` | Price/volume provider interface |
| `app/models`, `app/evaluation` | Reserved for model training and offline evaluation |

## Next milestones

1. Add a news/SEC provider with timeouts, retries, source IDs, and scheduled ingestion.
2. Resolve company tickers and store point-in-time market bars and feature versions.
3. Label subsequent returns using information available after receipt time; evaluate
   with chronological splits, transaction costs, and leakage checks.
4. Add independently tested position limits and persistent paper cash, positions,
   orders, and fills; execution must depend on explicit risk approval.
5. Train and version models offline; promote only after out-of-sample evaluation.

SQLite bootstrapping is for V1 development. Add migrations before changing the
schema; move to PostgreSQL when concurrent worker requirements warrant it. URL
identity currently preserves query strings and does not merge syndicated articles.
