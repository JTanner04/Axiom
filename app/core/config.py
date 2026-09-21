from typing import Literal
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AXIOM_", env_file=".env", extra="ignore")
    database_path: str = "data/axiom.db"
    trading_mode: Literal["paper"] = "paper"
    data_mode: Literal["demo", "alpaca"] = "demo"
    initial_cash: float = Field(default=100000, ge=1000, le=100000000)
    alpaca_key: SecretStr = SecretStr("")
    alpaca_secret: SecretStr = SecretStr("")
    alpaca_feed: Literal["iex", "sip", "delayed_sip"] = "iex"
    poll_seconds: int = Field(default=300, ge=60)
    bootstrap_demo: bool = True
    api_token: SecretStr = SecretStr("")
