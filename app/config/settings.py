import os
from typing import Optional
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    bucket_name: str = "session-replays"
    service_account_key_path: str = os.getenv("SERVICE_ACCOUNT_KEY_PATH", "app/config/serviceAccountKey.json")
    api_title: str = "Session Events API"
    api_description: str = "API for retrieving session events from Google Cloud Storage"
    api_version: str = "1.0.0"
    host: str = "0.0.0.0"
    port: int = int(os.getenv("PORT", 8000))
    debug: bool = False
    
    # External API keys
    pinecone_api_key: Optional[str] = os.getenv("PINECONE_API_KEY")
    openai_api_key: Optional[str] = os.getenv("OPENAI_API_KEY")
    
    class Config:
        env_file = ".env"
        case_sensitive = False

settings = Settings() 