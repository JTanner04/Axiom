import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from app.core.config import Settings
from app.main import create_app


@pytest.fixture
def settings(tmp_path):
    return Settings(database_path=str(tmp_path / "test.db"), _env_file=None)


@pytest.fixture
def article():
    return {"source": "demo", "url": "https://example.com/earnings",
            "title": "Company reports earnings", "published_at": "2026-09-12T14:00:00Z",
            "tickers": ["aapl", "AAPL"]}


def test_ingestion_is_idempotent_and_persistent(settings, article):
    with TestClient(create_app(settings)) as client:
        first = client.post("/api/v1/articles", json=article)
        assert first.status_code == 201
        record = first.json()
        assert record["article"]["tickers"] == ["AAPL"]
        assert record["analysis"]["event_type"] == "earnings"
        assert record["analysis"]["action"] == "HOLD"
        assert record["analysis"]["risk_approved"] is False
        article["title"] = "Changed title"
        duplicate = client.post("/api/v1/articles", json=article)
        assert duplicate.status_code == 200
        assert duplicate.json() == record
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/v1/articles").json() == [record]
        assert client.get(f"/api/v1/articles/{record['id']}").json() == record


@pytest.mark.parametrize("field,value", [
    ("url", "not-a-url"), ("title", " "), ("published_at", "2026-09-12T14:00:00"),
    ("tickers", ["bad ticker"]),
])
def test_invalid_article(settings, article, field, value):
    article[field] = value
    with TestClient(create_app(settings)) as client:
        assert client.post("/api/v1/articles", json=article).status_code == 422
        assert client.get("/api/v1/articles").json() == []


def test_health_missing_record_and_pagination(settings):
    with TestClient(create_app(settings)) as client:
        assert client.get("/health").json()["trading_mode"] == "paper"
        assert client.get("/api/v1/articles/missing").status_code == 404
        assert client.get("/api/v1/articles?limit=101").status_code == 422
        assert client.get("/api/v1/articles?offset=-1").status_code == 422


def test_live_mode_rejected():
    with pytest.raises(ValidationError):
        Settings(trading_mode="live", _env_file=None)
