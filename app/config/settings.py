from typing import Optional
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    bucket_name: str = "session-replays"
    service_account_key_path: str = "app/config/serviceAccountKey.json"
    api_title: str = "Session Events API"
    api_description: str = "API for retrieving session events from Google Cloud Storage"
    api_version: str = "1.0.0"
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False
    class Config:
        env_file = ".env"
        case_sensitive = False
settings = Settings() 