# Axiom

**Market intelligence → explainable signals → risk checks → paper execution.**

A complete local research workbench built with FastAPI, SQLite and a self-hosted
responsive dashboard. Starts with a clearly labeled simulation; optionally reads
Alpaca news and market data. It never connects to a brokerage or trades real money.

## Start in three minutes

Requires Python 3.11+ (tested with 3.12).

```bash
python -m venv .venv
source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.lock
pip install --no-deps -e .
cp .env.example .env
# Windows PowerShell: Copy-Item .env.example .env
python -m app
```

Open **http://127.0.0.1:8000**. API docs: **http://127.0.0.1:8000/docs**.
No API keys are needed for simulation. The first boot creates a $100,000 paper
account, 45 days of synthetic hourly prices and synthetic company events. No
profits or trades are preloaded. Portfolio charts show actual recorded snapshots.

For dependency development, `pip install -e '.[dev]'` uses supported version ranges.
`requirements.lock` pins the environment used for validation, including test tools.

## Try the full workflow

1. **Overview:** click **Run pipeline** to append synthetic prices, ingest an event,
   freeze its features, generate a signal and record an equity snapshot.
2. **Intelligence:** open a headline to inspect its source, timestamps, sentiment,
   event type and numeric features. Add an article or search/filter the feed.
3. **Paper portfolio:** review a BUY signal with **Trade**, optionally choose whole
   shares, and submit. The engine checks risk and records either a fill or a
   rejection. Sell signals can close owned shares; shorting is disabled.
4. **Model lab:** click **Train & evaluate**. Review a chronological holdout against
   a majority-class baseline. Explicitly activate a model for future events or
   return to the rule baseline. Download the event/outcome CSV.
5. **Settings:** tune position/exposure limits, default size, strength, drawdown,
   fees and slippage. Enable scheduled ingestion and/or automatic paper execution.
   Pause blocks all orders. Automation is off initially.
6. **Activity:** inspect ingestion, policy changes, training and order attempts.

## Connect live-source data

Set these server-side values in `.env`, restart, and select **Alpaca** in Settings:

```dotenv
AXIOM_ALPACA_KEY=your-key
AXIOM_ALPACA_SECRET=your-secret
AXIOM_ALPACA_FEED=iex
# Optional: make Alpaca the mode selected after restart
AXIOM_DATA_MODE=alpaca
```

The read-only connector uses Alpaca's [news endpoint](https://docs.alpaca.markets/us/reference/news-3)
and [latest minute bars endpoint](https://docs.alpaca.markets/us/reference/stocklatestbars-1).
Access depends on your account/feed permissions. HTTP failures are reported in the
UI; transient failures receive bounded retries. A cycle fetches up to 200 news
items from the previous two days and records if catch-up is capped. It does not
claim an exhaustive archive. Invalid records are counted and skipped.

Demo and Alpaca have separate cash, positions, events, signals, policies and models.
The account balance setting applies only when an account is first created.
Selecting a mode affects the running single-user server; after restart the
`AXIOM_DATA_MODE` setting is used. Keys are never returned to the browser.

Prices older than 15 minutes or signals older than 24 hours cannot fill orders.
A delayed feed or closed market can therefore produce risk rejections. This is
intentional. The app stores only observed minute bars in live-source mode, so
outcome labeling needs time and regular polling; historical backfill is not included.

## What the model actually does

- The default rule baseline classifies event phrases and scores sentiment. Its
  strength is **not** a probability. It does not understand all negation or context.
- Five frozen features: sentiment, event importance, prior-price momentum,
  volatility and volume ratio. Prices used for features must precede receipt.
- Labels use the first observed price at/after receipt and the first observation
  at least 24 hours after that. Each observation can lag its target by up to the
  documented four-day lookup window; this is an elapsed-time outcome, not exactly
  one trading session. Receipt time, not original publication time, controls entry.
- Training requires 60 completed outcomes. A standardized logistic regression
  uses the earliest 75% for development and holds out later timestamps. Training
  labels overlapping the holdout boundary are purged. Scaling fits training only.
- The report shows accuracy, majority baseline, Brier score, split counts and
  synthetic status. It is **not a profitability backtest**. Demo data is randomly
  generated and is not evidence of predictive ability. Repeated tuning against
  the same holdout will invalidate its independence.
- Saved coefficients are JSON, not executable pickle. Promotion is manual and
  predictions already made are immutable. Scores remain uncalibrated.

## Execution and persistence

SQLite uses WAL and immediate transactions for ledger writes. Cash and aggregate
cost basis use integer cents. Each order applies configured adverse slippage and
fees. Request keys are idempotent; each signal can fill at most once, including
under concurrent requests. Long-only, whole-share orders pass a separate risk
module. Drawdown blocks purchases; sales can still reduce positions.

The simulator assumes immediate full fills at a stored price. It does not model
order books, liquidity, settlement, corporate actions, taxes or market-session
execution rules. No external trade API exists. Automation uses deterministic
request keys, so a rejected automatic attempt is not silently retried every cycle;
you can review it and submit a new manual attempt.

Tables are versioned separately from the original raw-article API. Your initial
`/api/v1/articles` endpoints remain available as the V0 compatibility ingestion
store. Use `/api/v1/workbench/events` for the integrated signal pipeline. Existing
V0 articles are preserved and are not implicitly imported into a data mode.

## Run with Docker

```bash
cp .env.example .env
docker compose up --build
```

The port is bound to localhost and the SQLite database lives in a named volume.
Docker configuration is included but was not runtime-tested here because Docker
is unavailable in the build environment. The Python wheel was built and inspected
for packaged frontend assets. Use one server worker so scheduled cycles do
not duplicate. The Python process must remain running for scheduled ingestion.

## API and tests

```bash
pytest -q
```

Main routes are under `/api/v1/workbench`: `state`, `events`, `cycle`, `orders`,
`settings`, `mode`, `models/train`, `models/{id}/activate`, and `dataset`.
The original `/health` is retained. Interactive OpenAPI docs describe payloads.

The 28 Python tests pass. The browser smoke test also passed on desktop and a
390px mobile viewport, with no JavaScript errors. To run it against a disposable
demo server, install Playwright, install its Chromium browser, then run
`node tests/browser-smoke.cjs`. It mutates the demo account.

Tests cover validation, persistence, idempotency/concurrency, order accounting,
risk gates, data isolation, point-in-time features, purged model evaluation,
provider contract/retry behavior, and optional token/origin checks. The Alpaca
adapter is tested with mocked responses; real credentials are needed to validate
access and responses on your account.

## Deployment boundary and remaining work

This is a **single-user V1 research application**, not a production investment
service. Bind to localhost. Optional `AXIOM_API_TOKEN` protects API routes; the
browser asks for it and stores it only for the tab session. Before remote use,
add HTTPS, proper identity/session management, monitoring, backups and a reverse
proxy with request limits. Same-origin writes are enforced; no third-party scripts,
fonts or browser data providers are loaded.

Not yet implemented: SEC/earnings-specific adapters, measured earnings surprise,
sector/benchmark features, robust entity resolution beyond supplied symbols and a
small company-name dictionary, transaction-cost-aware strategy backtesting,
walk-forward model selection, calibration, periodic model retraining, and real
broker integration. The implemented workflow is runnable end to end; those are
further research/product milestones, not hidden placeholders.

See [architecture](docs/architecture.md) for module boundaries and invariants.
