import requests
import json
import os
from datetime import datetime
from google.cloud import storage
from google.oauth2 import service_account
from google.cloud import firestore

def get_storage_client():
    creds = service_account.Credentials.from_service_account_file(
        "app/config/serviceAccountKey.json"
    )
    return storage.Client(credentials=creds, project=creds.project_id)

def get_firestore_client():
    creds = service_account.Credentials.from_service_account_file(
        "app/config/serviceAccountKey.json"
    )
    return firestore.Client(credentials=creds, project=creds.project_id)

def get_bucket(bucket_name):
    client = get_storage_client()
    return client.bucket(bucket_name)

def update_session_replays_with_project_id(project_id: str):
    """Update all session replays to have the specified project ID"""
    try:
        db = get_firestore_client()
        
        # Get all session replays
        snapshot = db.collection('session_replays').get()
        
        updated_count = 0
        for doc in snapshot:
            doc_ref = doc.reference
            doc_ref.update({'projectId': project_id})
            updated_count += 1
            print(f"Updated session replay: {doc.id}")
        
        print(f"Successfully updated {updated_count} session replays with project ID: {project_id}")
        return updated_count
        
    except Exception as e:
        print(f"Error updating session replays: {e}")
        return 0

def fetch_session_ids():
    """Fetch all session IDs from the API"""
    url = "http://localhost:8002/api/session-ids"
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.json().get("sessions", [])
    except requests.exceptions.RequestException as e:
        print(f"Error fetching session IDs: {e}")
        return []

def fetch_events_from_api(session_id):
    """Fetch events from the API endpoint"""
    url = f"http://localhost:8002/api/sessions/{session_id}/events"
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.json().get("events", [])
    except requests.exceptions.RequestException as e:
        print(f"Error fetching events for session {session_id}: {e}")
        return []

def save_session_to_bucket(session_id, events, timestamp=None):
    """Save session data to Google Cloud Storage bucket"""
    try:
        bucket_name = "session-replays"
        bucket = get_bucket(bucket_name)
        
        session_json = {
            "sessionId": session_id,
            "events": events,
            "timestamp": timestamp or datetime.now().isoformat(),
        }
        
        blob = bucket.blob(f"sessions/{session_id}.json")
        blob.upload_from_string(
            json.dumps(session_json, indent=2),
            content_type="application/json"
        )
        
        print(f"Successfully saved session {session_id} to bucket")
        return True
        
    except Exception as e:
        print(f"Error saving session {session_id} to bucket: {e}")
        return False

def main():
    # Update all session replays with project ID
    project_id = "5694ea67-5b4a-4ac8-a5bd-3268e3a7bb88"
    print(f"Updating all session replays with project ID: {project_id}")
    updated_count = update_session_replays_with_project_id(project_id)
    # print(f"Updated {updated_count} session replays")
    
    # print("\nFetching session IDs...")
    # sessions = fetch_session_ids()
    
    # if not sessions:
    #     print("No sessions found")
    #     return
    
    # print(f"Found {len(sessions)} sessions")
    
    # for session in sessions:
    #     session_id = session.get("sessionId")
    #     timestamp = session.get("timestamp")
    #     url = session.get("url")
    #     gcs_path = session.get("gcs_path")
        
    #     print(f"\nProcessing session: {session_id}")
    #     print(f"URL: {url}")
    #     print(f"GCS Path: {gcs_path}")
        
    #     events = fetch_events_from_api(session_id)
        
    #     if events:
    #         print(f"Found {len(events)} events")
    #         success = save_session_to_bucket(session_id, events, timestamp)
    #         if success:
    #             print("Session saved successfully!")
    #         else:
    #             print("Failed to save session")
    #     else:
    #         print("No events found for this session")

if __name__ == "__main__":
    main() 