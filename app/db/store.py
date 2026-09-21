"""Versioned application tables. Every ledger mutation takes an immediate write lock."""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class Store:
    def __init__(self, path):
        self.path = path

    @contextmanager
    def connection(self, write=False):
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db
            if write:
                db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def initialize(self):
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript('''
CREATE TABLE IF NOT EXISTS schema_versions(version INTEGER PRIMARY KEY);
CREATE TABLE IF NOT EXISTS preferences(scope TEXT PRIMARY KEY, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS bars(scope TEXT, ticker TEXT, ts REAL, price REAL NOT NULL,
 volume INTEGER NOT NULL, PRIMARY KEY(scope,ticker,ts));
CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY, scope TEXT NOT NULL, ticker TEXT NOT NULL,
 received REAL NOT NULL, payload TEXT NOT NULL, UNIQUE(scope,ticker,id));
CREATE TABLE IF NOT EXISTS signals(id TEXT PRIMARY KEY, event_id TEXT NOT NULL REFERENCES events(id),
 scope TEXT NOT NULL, ticker TEXT NOT NULL, created REAL NOT NULL, action TEXT NOT NULL,
 strength REAL NOT NULL, model TEXT NOT NULL, reason TEXT NOT NULL, features TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'pending', UNIQUE(event_id,model));
CREATE TABLE IF NOT EXISTS accounts(scope TEXT PRIMARY KEY, cash_cents INTEGER NOT NULL,
 initial_cents INTEGER NOT NULL, realized_cents INTEGER NOT NULL DEFAULT 0, peak_cents INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS positions(scope TEXT, ticker TEXT, quantity INTEGER NOT NULL,
 cost_cents INTEGER NOT NULL, PRIMARY KEY(scope,ticker));
CREATE TABLE IF NOT EXISTS orders(id TEXT PRIMARY KEY, scope TEXT NOT NULL, request_key TEXT NOT NULL,
 signal_id TEXT NOT NULL, ticker TEXT NOT NULL, side TEXT NOT NULL, quantity INTEGER NOT NULL,
 price_cents INTEGER NOT NULL, fee_cents INTEGER NOT NULL, status TEXT NOT NULL,
 reason TEXT NOT NULL, created REAL NOT NULL, UNIQUE(scope,request_key));
CREATE UNIQUE INDEX IF NOT EXISTS one_fill_per_signal ON orders(signal_id) WHERE status='filled';
CREATE TABLE IF NOT EXISTS equity(id INTEGER PRIMARY KEY, scope TEXT NOT NULL, ts REAL NOT NULL,
 value_cents INTEGER NOT NULL, cash_cents INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, scope TEXT NOT NULL, ts REAL NOT NULL,
 kind TEXT NOT NULL, message TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS models(id TEXT PRIMARY KEY, scope TEXT NOT NULL, created REAL NOT NULL,
 payload TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS events_scope_time ON events(scope,received);
CREATE INDEX IF NOT EXISTS signals_scope_time ON signals(scope,created);
CREATE INDEX IF NOT EXISTS bars_lookup ON bars(scope,ticker,ts);
INSERT OR IGNORE INTO schema_versions VALUES (1);
''')

    @staticmethod
    def preferences(db, scope):
        row = db.execute("SELECT payload FROM preferences WHERE scope=?", (scope,)).fetchone()
        return json.loads(row[0]) if row else None
