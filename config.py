from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/exchange_db"
    secret_key: str = "dev-secret-key-change-in-production"
    access_token_expire_hours: int = 8

    evolution_api_url: str = "http://localhost:8080"
    evolution_api_key: str = ""
    evolution_instance: str = "default"

    tron_mnemonic: str = ""
    trongrid_api_key: str = ""

    base_url: str = "http://localhost:8000"

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
