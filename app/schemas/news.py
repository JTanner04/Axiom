from datetime import datetime
from typing import Literal
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, HttpUrl, field_validator


class ArticleInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    source: str = Field(min_length=1, max_length=100)
    url: HttpUrl
    title: str = Field(min_length=1, max_length=500)
    body: str = Field(default="", max_length=100000)
    published_at: AwareDatetime
    tickers: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("tickers")
    @classmethod
    def normalize_tickers(cls, values: list[str]) -> list[str]:
        import re
        result = sorted({value.strip().upper() for value in values})
        if any(not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}", value) for value in result):
            raise ValueError("Invalid ticker symbol")
        return result


class Analysis(BaseModel):
    event_type: str
    sentiment: Literal["positive", "negative", "neutral"]
    model_version: str = "keyword-baseline-v1"
    action: Literal["HOLD"] = "HOLD"
    confidence: float | None = None
    risk_approved: Literal[False] = False
    reason: str = "Research baseline only; no validated trading model or execution adapter."


class ArticleRecord(BaseModel):
    id: str
    article: ArticleInput
    received_at: datetime
    analysis: Analysis
