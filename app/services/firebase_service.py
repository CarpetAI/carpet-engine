import os
from typing import List, Dict, Any
import json
import logging
from google.cloud import storage
from google.oauth2 import service_account
from app.config.settings import settings

APPLOGGER = logging.getLogger(__name__)

def get_storage_client():
    creds = service_account.Credentials.from_service_account_file(
        settings.service_account_key_path
    )
    return storage.Client(credentials=creds, project=creds.project_id)

def get_bucket(bucket_name):
    client = get_storage_client()
    return client.bucket(bucket_name)

def get_fb_session_events(session_id: str) -> List[Dict[str, Any]]:
    if not session_id or not isinstance(session_id, str):
        APPLOGGER.error(f"Invalid session_id: {session_id}")
        return []
    try:
        bucket_name = settings.bucket_name
        bucket = get_bucket(bucket_name)
        blob = bucket.blob(f"sessions/{session_id}.json")
        if not blob.exists():
            APPLOGGER.info(f"Session {session_id} not found in storage")
            return []
        data = json.loads(blob.download_as_text())
        events = data.get("events", [])
        if not events:
            APPLOGGER.info(f"No events found for session {session_id}")
        APPLOGGER.info(f"Retrieved {len(events)} events for session {session_id}")
        return events
    except Exception as e:
        APPLOGGER.error(f"Error retrieving events for session {session_id}: {e}")
        return [] 