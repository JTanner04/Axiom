import re
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class RiskSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    paused: bool = False
    auto_execute: bool = False
    polling: bool = False
    max_position: float = Field(.2, ge=.01, le=.5, allow_inf_nan=False)
    max_gross: float = Field(.7, ge=.05, le=1, allow_inf_nan=False)
    trade_fraction: float = Field(.05, ge=.001, le=.2, allow_inf_nan=False)
    min_strength: float = Field(.6, ge=.5, le=1, allow_inf_nan=False)
    max_drawdown: float = Field(.1, ge=.01, le=.5, allow_inf_nan=False)
    slippage_bps: float = Field(5, ge=0, le=100, allow_inf_nan=False)
    fee_bps: float = Field(1, ge=0, le=100, allow_inf_nan=False)
    watchlist: list[str] = Field(default_factory=lambda: ["NVDA", "AAPL", "MSFT", "AMZN", "GOOGL", "META", "TSLA", "SPY"], min_length=1, max_length=20)

    @field_validator("watchlist")
    @classmethod
    def symbols(cls, values):
        values = sorted(set(v.strip().upper() for v in values))
        if any(not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}", v) for v in values):
            raise ValueError("Invalid ticker")
        return values


class ExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    signal_id: str = Field(min_length=1, max_length=100)
    request_key: str = Field(min_length=8, max_length=100)
    quantity: int | None = Field(None, ge=1, le=1000000)


class ModeRequest(BaseModel):
    mode: Literal["demo", "alpaca"]
