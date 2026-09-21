import hashlib
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from app.schemas.news import Analysis, ArticleInput, ArticleRecord


class ArticleRepository:
    def __init__(self, path: str):
        self.path = path

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS articles (
                id TEXT PRIMARY KEY,
                received_at TEXT NOT NULL,
                record TEXT NOT NULL
            )""")

    def save(self, article: ArticleInput, analysis: Analysis) -> tuple[ArticleRecord, bool]:
        # Exact normalized URL identity; first-seen content is immutable.
        article_id = hashlib.sha256(str(article.url).encode()).hexdigest()
        record = ArticleRecord(id=article_id, article=article,
                               received_at=datetime.now(timezone.utc), analysis=analysis)
        with self.connect() as db:
            cursor = db.execute("INSERT OR IGNORE INTO articles VALUES (?, ?, ?)",
                                (article_id, record.received_at.isoformat(), record.model_dump_json()))
            created = cursor.rowcount == 1
            saved = db.execute("SELECT record FROM articles WHERE id = ?", (article_id,)).fetchone()
        return ArticleRecord.model_validate_json(saved[0]), created

    def list(self, limit: int, offset: int) -> list[ArticleRecord]:
        with self.connect() as db:
            rows = db.execute("SELECT record FROM articles ORDER BY received_at DESC, id LIMIT ? OFFSET ?",
                              (limit, offset)).fetchall()
        return [ArticleRecord.model_validate_json(row[0]) for row in rows]

    def get(self, article_id: str) -> ArticleRecord | None:
        with self.connect() as db:
            row = db.execute("SELECT record FROM articles WHERE id = ?", (article_id,)).fetchone()
        return ArticleRecord.model_validate_json(row[0]) if row else None
