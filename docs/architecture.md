# Architecture

The FastAPI app serves the static UI and owns a single optional polling worker.
The worker and the Run pipeline button call the same `Engine.run_cycle` function.
A process lock prevents overlapping cycles. Do not run multiple Uvicorn workers.

| Module | Responsibility |
| --- | --- |
| `app/providers/alpaca.py` | Read-only bounded news and price fetches, retries |
| `app/trading/engine.py` | Data-mode orchestration, paper ledger, snapshots, audit |
| `app/intelligence/research.py` | Classification, frozen features, inference |
| `app/trading/risk.py` | Pure execution approval checks |
| `app/evaluation/training.py` | Outcome labels, chronological split, model registry |
| `app/db/store.py` | WAL connections, schema, transaction boundaries |
| `app/api/workbench.py` | Validated workbench HTTP operations |
| `app/static` | Dependency-free dashboard, charts, forms, event inspection |
| `app/db/repository.py` | Preserved V0 article store |

## Invariants

1. `trading_mode` only accepts `paper`; providers have no order-submission method.
2. Every data row and account belongs to `demo` or `alpaca`; models cannot activate
   across these boundaries.
3. News is deduplicated by normalized URL, ticker and mode. Existing raw events and
   predictions are immutable. Query strings and syndicated URLs remain distinct.
4. Features use bars at or before receipt. Labels start at or after receipt. Training
   outcome windows must end strictly before the holdout begins.
5. Risk runs inside the same immediate database transaction as a fill. Failed
   decisions persist a rejected attempt but do not mutate cash or holdings.
6. An order request key is unique per mode. A partial unique index permits at most
   one filled order for each signal. Database serialization protects concurrency.
7. No UI user-supplied text is injected as HTML; text is escaped. Article URLs are
   validated HTTP(S) URLs. API secrets are server-side Pydantic SecretStr fields.
8. Environment settings configure the process. Risk preferences persist per mode.
   Scheduled polling and automatic order submission are independent opt-in flags.

## Simulation

Historical demo bars and events use a fixed random seed. Their receipt timestamps
are simulated historical times. Subsequent Run pipeline clicks generate fresh
synthetic prices/events. Demo prices are illustrative, not current market quotes.
Paper account performance starts flat and changes only from actual simulated fills
and recorded marks. No equity curve is invented for appearance.

## Operational limits

SQLite and the process scheduler target one user and one server process. A stopped
server does not ingest data; a failed API call cannot magically backfill an entire
gap. Add durable queues, historical backfill, schema migrations beyond V1 and
PostgreSQL before scaling workers. Account snapshots are recorded on cycles/fills;
drawdown peaks therefore reflect observed snapshots, not every market tick.
