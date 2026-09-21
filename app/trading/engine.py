import hashlib
import json
import math
import random
import re
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from threading import Lock

from app.db.store import Store
from app.intelligence.research import NAMES, classify, extract, predict
from app.providers.alpaca import AlpacaProvider, ProviderError
from app.schemas.news import ArticleInput
from app.schemas.workbench import RiskSettings
from app.trading.risk import assess


def cents(value):
    return int((Decimal(str(value)) * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def stamp(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()


class Engine:
    def __init__(self, settings):
        self.settings = settings
        self.store = Store(settings.database_path)
        self.cycle_lock = Lock()
        self.scope = settings.data_mode

    def initialize(self):
        self.store.initialize()
        with self.store.connection(True) as db:
            for scope in ('demo', 'alpaca'):
                initial = cents(self.settings.initial_cash)
                db.execute('INSERT OR IGNORE INTO accounts(scope,cash_cents,initial_cents,peak_cents) VALUES (?,?,?,?)', (scope, initial, initial, initial))
                db.execute('INSERT OR IGNORE INTO preferences VALUES (?,?)', (scope, RiskSettings().model_dump_json()))
            if self.settings.bootstrap_demo and not db.execute("SELECT 1 FROM events WHERE scope='demo' LIMIT 1").fetchone():
                self.seed(db)

    def audit(self, db, scope, kind, message):
        db.execute('INSERT INTO audit(scope,ts,kind,message) VALUES (?,?,?,?)', (scope, time.time(), kind, message))

    def price(self, db, scope, ticker):
        return db.execute('SELECT price,ts FROM bars WHERE scope=? AND ticker=? AND ts<=? ORDER BY ts DESC LIMIT 1', (scope, ticker, time.time())).fetchone()

    def portfolio(self, db, scope):
        account = dict(db.execute('SELECT * FROM accounts WHERE scope=?', (scope,)).fetchone())
        positions, gross = [], 0
        for row in db.execute('SELECT * FROM positions WHERE scope=? AND quantity>0', (scope,)):
            quote = self.price(db, scope, row['ticker'])
            value = row['quantity'] * cents(quote['price']) if quote else row['cost_cents']
            gross += value
            positions.append({**dict(row), 'price': quote['price'] if quote else None,
                              'quote_time': quote['ts'] if quote else None,
                              'value': value / 100, 'average_cost': row['cost_cents'] / row['quantity'] / 100,
                              'unrealized': (value-row['cost_cents'])/100})
        equity = account['cash_cents'] + gross
        peak = max(account['peak_cents'], equity)
        return {**account, 'positions': positions, 'equity': equity / 100, 'cash': account['cash_cents']/100,
                'gross': gross/100, 'unrealized': sum(p['unrealized'] for p in positions),
                'realized': account['realized_cents']/100, 'pnl': (equity-account['initial_cents'])/100,
                'return_pct': (equity/account['initial_cents']-1)*100,
                'drawdown': (peak-equity)/peak if peak else 0}

    def snapshot(self, db, scope):
        p = self.portfolio(db, scope)
        value = cents(p['equity'])
        db.execute('UPDATE accounts SET peak_cents=MAX(peak_cents,?) WHERE scope=?', (value, scope))
        db.execute('INSERT INTO equity(scope,ts,value_cents,cash_cents) VALUES (?,?,?,?)', (scope, time.time(), value, p['cash_cents']))

    def add_bar(self, db, scope, ticker, timestamp, price, volume):
        if not (math.isfinite(price) and price > 0 and math.isfinite(timestamp) and timestamp <= time.time()+5 and volume >= 0):
            raise ValueError('Invalid or future-dated market bar')
        db.execute('INSERT OR IGNORE INTO bars VALUES (?,?,?,?,?)', (scope, ticker, timestamp, price, volume))

    def ingest(self, db, scope, article, received=None):
        received = received or time.time()
        if article.published_at.timestamp() > received+300:
            raise ValueError('Article publication time is in the future')
        tickers = article.tickers or [symbol for symbol, name in NAMES.items()
                                     if re.search(r'\b'+re.escape(name)+r'\b', article.title+' '+article.body, re.I)]
        if not tickers:
            tickers = ['UNRESOLVED']
        count = 0
        active = db.execute('SELECT id,payload FROM models WHERE scope=? AND active=1 ORDER BY created DESC LIMIT 1', (scope,)).fetchone()
        model_id = active['id'] if active else 'rules-v2'
        model = json.loads(active['payload']) if active else None
        for ticker in tickers:
            event_id = hashlib.sha256(f'{scope}|{ticker}|{article.url}'.encode()).hexdigest()[:24]
            if db.execute('SELECT 1 FROM events WHERE id=?', (event_id,)).fetchone():
                continue
            event, sentiment, importance = classify(article.title, article.body)
            features = extract(db, scope, ticker, received, sentiment, importance)
            action, strength, reason = predict(features, model)
            if ticker == 'UNRESOLVED':
                action, reason = 'HOLD', 'No ticker resolved; review the article before using it.'
            payload = {**article.model_dump(mode='json'), 'event_type': event, 'sentiment': sentiment,
                       'importance': importance, 'horizon_hours': 24, 'surprise': None,
                       'features': features, 'feature_version': 'v1', 'synthetic': scope == 'demo'}
            db.execute('INSERT INTO events VALUES (?,?,?,?,?)', (event_id, scope, ticker, received, json.dumps(payload)))
            signal_id = uuid.uuid4().hex
            db.execute('INSERT INTO signals(id,event_id,scope,ticker,created,action,strength,model,reason,features) VALUES (?,?,?,?,?,?,?,?,?,?)',
                       (signal_id, event_id, scope, ticker, received, action, strength, model_id, reason, json.dumps(features)))
            count += 1
        return count

    def seed(self, db):
        """Synthetic history is explicit and never shared with the live-source account."""
        rng = random.Random(42)
        now = time.time()
        base = {'NVDA': 126., 'AAPL': 218., 'MSFT': 422., 'AMZN': 186., 'GOOGL': 164., 'META': 526., 'TSLA': 238., 'SPY': 554.}
        for ticker, start in base.items():
            price = start
            for hour in range(24*45+1):
                ts = now-(24*45-hour)*3600
                price *= math.exp(rng.gauss(.00001, .003))
                self.add_bar(db, 'demo', ticker, ts, round(price, 4), rng.randint(30000, 500000))
            for day in range(40, 0, -1):
                received = now-day*86400+1800
                positive = rng.random() > .5
                title = f'{NAMES[ticker]} '+('beats earnings estimates; raises guidance' if positive else 'misses earnings estimates; cuts guidance')
                article = ArticleInput(source='Synthetic simulation', url=f'https://example.com/axiom/{ticker}/{day}',
                                       title=title, body='Generated test event. Not real market news.',
                                       published_at=datetime.fromtimestamp(received-60, timezone.utc), tickers=[ticker])
                self.ingest(db, 'demo', article, received)
        # Only recent events are executable; historical records are for offline evaluation.
        for i, ticker in enumerate(base):
            article = ArticleInput(source='Synthetic simulation', url=f'https://example.com/axiom/current/{ticker}',
                                   title=f'{NAMES[ticker]} '+('beats earnings estimates; raises guidance' if i%3 != 2 else 'faces lawsuit following product recall'),
                                   body='Generated scenario for paper-trading research. Not real news.',
                                   published_at=datetime.fromtimestamp(now-120-i*90, timezone.utc), tickers=[ticker])
            self.ingest(db, 'demo', article, now-i*90)
        self.snapshot(db, 'demo')
        self.audit(db, 'demo', 'system', 'Simulation initialized: 45 days of synthetic prices and labeled-as-synthetic news. No trades preloaded.')

    def execute(self, request, scope=None):
        scope = scope or self.scope
        with self.store.connection(True) as db:
            existing = db.execute('SELECT * FROM orders WHERE scope=? AND request_key=?', (scope, request.request_key)).fetchone()
            if existing:
                if existing['signal_id'] != request.signal_id or (request.quantity is not None and existing['quantity'] != request.quantity):
                    raise ValueError('Idempotency key was already used for a different order')
                return dict(existing)
            signal = db.execute('SELECT * FROM signals WHERE id=? AND scope=?', (request.signal_id, scope)).fetchone()
            if not signal:
                raise LookupError('Signal not found')
            filled = db.execute("SELECT * FROM orders WHERE signal_id=? AND status='filled'", (request.signal_id,)).fetchone()
            if filled:
                return dict(filled)
            prefs = Store.preferences(db, scope)
            p = self.portfolio(db, scope)
            quote = self.price(db, scope, signal['ticker'])
            raw_price = quote['price'] if quote else 0
            slip = 1 + (1 if signal['action']=='BUY' else -1)*prefs['slippage_bps']/10000
            price = max(1, cents(raw_price*slip)) if quote else 0
            pos = db.execute('SELECT * FROM positions WHERE scope=? AND ticker=?', (scope, signal['ticker'])).fetchone()
            held = pos['quantity'] if pos else 0
            qty = request.quantity if request.quantity is not None else (int(p['equity']*100*prefs['trade_fraction']/price) if price else 0)
            if request.quantity is None and signal['action']=='SELL':
                qty = min(held, qty)
            fee = int((Decimal(qty*price)*Decimal(str(prefs['fee_bps']))/10000).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
            decision = assess(side=signal['action'], quantity=qty, price_cents=price, fee_cents=fee,
                              cash=p['cash_cents'], equity=cents(p['equity']), gross=cents(p['gross']), held=held,
                              strength=signal['strength'], quote_age=time.time()-quote['ts'] if quote else 1e10,
                              signal_age=time.time()-signal['created'], paused=prefs['paused'],
                              max_position=prefs['max_position'], max_gross=prefs['max_gross'],
                              min_strength=prefs['min_strength'], drawdown=p['drawdown'], max_drawdown=prefs['max_drawdown'])
            order = {'id': uuid.uuid4().hex, 'scope': scope, 'request_key': request.request_key,
                     'signal_id': signal['id'], 'ticker': signal['ticker'], 'side': signal['action'],
                     'quantity': qty, 'price_cents': price, 'fee_cents': fee,
                     'status': 'filled' if decision.approved else 'rejected', 'reason': decision.reason, 'created': time.time()}
            db.execute('INSERT INTO orders VALUES (:id,:scope,:request_key,:signal_id,:ticker,:side,:quantity,:price_cents,:fee_cents,:status,:reason,:created)', order)
            if decision.approved:
                total = qty*price
                if signal['action']=='BUY':
                    db.execute('UPDATE accounts SET cash_cents=cash_cents-? WHERE scope=?', (total+fee, scope))
                    db.execute('INSERT INTO positions VALUES (?,?,?,?) ON CONFLICT(scope,ticker) DO UPDATE SET quantity=quantity+excluded.quantity,cost_cents=cost_cents+excluded.cost_cents',
                               (scope, signal['ticker'], qty, total+fee))
                else:
                    cost = pos['cost_cents'] if qty==held else round(pos['cost_cents']*qty/held)
                    db.execute('UPDATE accounts SET cash_cents=cash_cents+?,realized_cents=realized_cents+? WHERE scope=?', (total-fee, total-fee-cost, scope))
                    db.execute('UPDATE positions SET quantity=quantity-?,cost_cents=cost_cents-? WHERE scope=? AND ticker=?', (qty, cost, scope, signal['ticker']))
                db.execute("UPDATE signals SET status='filled' WHERE id=?", (signal['id'],))
            self.audit(db, scope, 'trade' if decision.approved else 'risk', f"{signal['action']} {qty} {signal['ticker']}: {order['status']}. {decision.reason}")
            self.snapshot(db, scope)
            return order

    def run_cycle(self):
        if not self.cycle_lock.acquire(blocking=False):
            raise ValueError('A pipeline cycle is already running')
        scope = self.scope
        try:
            with self.store.connection() as db:
                prefs = Store.preferences(db, scope)
            added, skipped, truncated = 0, 0, False
            if scope=='alpaca':
                news, bars, truncated = AlpacaProvider(self.settings).fetch(prefs['watchlist'])
                with self.store.connection(True) as db:
                    for ticker, bar in bars.items():
                        try:
                            self.add_bar(db, scope, ticker, stamp(bar['t']), float(bar['c']), int(bar['v']))
                        except (ValueError, KeyError, TypeError):
                            skipped += 1
                    for item in news:
                        try:
                            article = ArticleInput(source=item.get('source', 'Alpaca'), url=item['url'], title=item['headline'],
                                                   body=re.sub('<[^>]+>', ' ', item.get('content') or item.get('summary') or '')[:100000],
                                                   published_at=item['created_at'], tickers=item.get('symbols', []))
                            added += self.ingest(db, scope, article)
                        except (ValueError, KeyError, TypeError):
                            skipped += 1
            else:
                now = time.time()
                rng = random.Random()
                with self.store.connection(True) as db:
                    for ticker in prefs['watchlist']:
                        previous = self.price(db, scope, ticker)
                        price = previous['price'] if previous else 100
                        self.add_bar(db, scope, ticker, now, round(price*(1+rng.uniform(-.008,.008)), 4), rng.randint(30000,500000))
                    ticker = rng.choice(prefs['watchlist'])
                    title = f'{NAMES.get(ticker,ticker)} '+rng.choice(['beats earnings estimates; raises guidance', 'receives analyst upgrade on growth outlook', 'cuts guidance following revenue decline', 'announces product launch'])
                    article = ArticleInput(source='Synthetic simulation', url=f'https://example.com/axiom/cycle/{uuid.uuid4().hex}', title=title,
                                           body='Generated scenario. Prices and news are synthetic.', published_at=datetime.now(timezone.utc), tickers=[ticker])
                    added = self.ingest(db, scope, article)
            with self.store.connection(True) as db:
                self.snapshot(db, scope)
                self.audit(db, scope, 'ingestion', f'Cycle complete: {added} events added, {skipped} invalid records skipped.'+(' News catch-up capped at 200 records.' if truncated else ''))
                pending = [r['id'] for r in db.execute("SELECT id FROM signals WHERE scope=? AND status='pending' AND action!='HOLD' AND created>=? ORDER BY created DESC LIMIT 20", (scope, time.time()-86400))]
            if prefs['auto_execute'] and not prefs['paused']:
                from app.schemas.workbench import ExecuteRequest
                for signal_id in pending:
                    self.execute(ExecuteRequest(signal_id=signal_id, request_key='auto-'+signal_id), scope)
            return {'added': added, 'skipped': skipped, 'truncated': truncated, 'mode': scope}
        except ProviderError as exc:
            with self.store.connection(True) as db:
                self.audit(db, scope, 'error', str(exc))
            raise
        finally:
            self.cycle_lock.release()

    def set_preferences(self, settings):
        with self.store.connection(True) as db:
            db.execute('UPDATE preferences SET payload=? WHERE scope=?', (settings.model_dump_json(), self.scope))
            self.audit(db, self.scope, 'settings', 'Risk policy and pipeline preferences updated.')
        return settings.model_dump()

    def state(self):
        scope = self.scope
        with self.store.connection() as db:
            p = self.portfolio(db, scope)
            prefs = Store.preferences(db, scope)
            market = []
            for ticker in prefs['watchlist']:
                rows = db.execute('SELECT price,ts FROM bars WHERE scope=? AND ticker=? ORDER BY ts DESC LIMIT 48', (scope,ticker)).fetchall()[::-1]
                market.append({'ticker': ticker, 'name': NAMES.get(ticker, ticker), 'price': rows[-1][0] if rows else None,
                               'as_of': rows[-1][1] if rows else None, 'history': [r[0] for r in rows],
                               'change': (rows[-1][0]/rows[0][0]-1)*100 if len(rows)>1 else 0})
            events = [{**dict(r), 'payload': json.loads(r['payload'])} for r in db.execute('SELECT * FROM events WHERE scope=? ORDER BY received DESC LIMIT 100', (scope,))]
            signals = [dict(r) for r in db.execute('SELECT s.*,e.payload FROM signals s JOIN events e ON e.id=s.event_id WHERE s.scope=? ORDER BY s.created DESC LIMIT 100', (scope,))]
            for s in signals:
                s['features'] = json.loads(s['features'])
                s['title'] = json.loads(s.pop('payload'))['title']
            orders = [dict(r) for r in db.execute('SELECT * FROM orders WHERE scope=? ORDER BY created DESC LIMIT 100', (scope,))]
            history = [dict(r) for r in db.execute('SELECT ts,value_cents,cash_cents FROM equity WHERE scope=? ORDER BY id DESC LIMIT 500', (scope,))][::-1]
            activity = [dict(r) for r in db.execute('SELECT * FROM audit WHERE scope=? ORDER BY id DESC LIMIT 60', (scope,))]
            models = [{**dict(r), 'payload': json.loads(r['payload'])} for r in db.execute('SELECT * FROM models WHERE scope=? ORDER BY created DESC LIMIT 10', (scope,))]
            count = db.execute('SELECT COUNT(*) FROM events WHERE scope=?', (scope,)).fetchone()[0]
            return {'mode': scope, 'trading_mode': 'paper', 'connected': bool(self.settings.alpaca_key.get_secret_value() and self.settings.alpaca_secret.get_secret_value()),
                    'portfolio': p, 'settings': prefs, 'market': market, 'events': events, 'signals': signals,
                    'orders': orders, 'equity': history, 'activity': activity, 'models': models, 'event_count': count,
                    'poll_seconds': self.settings.poll_seconds, 'server_time': time.time()}
