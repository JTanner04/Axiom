"""Provider boundary for future timestamped price/volume ingestion."""
from datetime import datetime
from typing import Protocol
from pydantic import AwareDatetime, BaseModel, Field


class MarketBar(BaseModel):
    ticker: str
    timestamp: AwareDatetime
    close: float = Field(gt=0, allow_inf_nan=False)
    volume: int = Field(ge=0)


class MarketDataProvider(Protocol):
    def bars(self, ticker: str, start: datetime, end: datetime) -> list[MarketBar]: ...
