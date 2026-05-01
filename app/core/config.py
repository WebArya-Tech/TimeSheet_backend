import os
from typing import Any, Dict, Optional

from pydantic import PostgresDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "Time Sheet Management System"
    API_V1_STR: str = "/api/v1"
    
    SECRET_KEY: str = "super-secret-key-change-this-in-production"
    # 60 minutes * 24 hours * 8 days = 8 days
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 8

    DATABASE_URL: str = "mongodb://localhost:27017"
    SERVER_PORT: int = 9079
    
    FIRST_SUPERUSER: str = "superadmin@example.com"
    FIRST_SUPERUSER_PASSWORD: str = "superadminpassword"

    model_config = SettingsConfigDict(case_sensitive=True, env_file=".env", env_file_encoding='utf-8')


settings = Settings()
