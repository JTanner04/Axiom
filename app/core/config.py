from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AXIOM_", env_file=".env", extra="ignore")
    database_path: str = "data/axiom.db"
    trading_mode: Literal["paper"] = "paper"
