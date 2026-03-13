from pydantic_settings import BaseSettings
from functools import lru_cache
import os


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///./vibenetbackup.db"
    SECRET_KEY: str = "change-me"
    BACKUP_DIR: str = "./backups"
    SSH_KEY_DIR: str = "./ssh_keys"
    OXIDIZED_URL: str = "http://localhost:8888"
    LOG_LEVEL: str = "INFO"
    HOST: str = "0.0.0.0"
    PORT: int = 5005
    
    # Security settings
    AUTH_USERNAME: str = "admin"
    AUTH_PASSWORD: str = "admin"  # CHANGE THIS IN PRODUCTION!
    CORS_ORIGINS: str = "http://localhost:5005,http://127.0.0.1:5005,http://0.0.0.0:5005"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
