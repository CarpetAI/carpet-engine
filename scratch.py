import requests
import json
import os
import logging
from datetime import datetime
from google.cloud import storage
from google.oauth2 import service_account
from google.cloud import firestore
from app.services.firestore_service import get_session_ids
from app.services.analysis_service import generate_activity_events
from app.services.firebase_service import get_fb_session_events

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)

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

def analyze_last_50_sessions(project_id: str = "f91c1c07-2a54-4756-8b2f-9b4fff44da39"):
    """
    Pull the last 50 sessions and run analysis on them using process_session_replay.
    
    Args:
        project_id: The project ID to fetch sessions for
        
    Returns:
        Dictionary with analysis results
    """
    print(f"Starting analysis of last 50 sessions for project: {project_id}")
    
    try:
        # Get the last 50 sessions from Firestore
        sessions = get_session_ids(project_id)
        
        if not sessions:
            print("No sessions found for this project")
            return {"status": "no_sessions", "message": "No sessions found"}
        
        # Limit to last 50 sessions
        sessions = sessions[:50]
        print(f"Found {len(sessions)} sessions to analyze")
        
        analysis_results = {
            "project_id": project_id,
            "total_sessions": len(sessions),
            "successful_analyses": 0,
            "failed_analyses": 0,
            "session_results": [],
            "summary": {
                "total_events": 0,
                "total_actions": 0,
                "total_chunks": 0,
                "stored_chunks": 0
            }
        }
        
        for i, session in enumerate(sessions, 1):
            session_id = session.get("sessionId")
            print(f"\n[{i}/{len(sessions)}] Analyzing session: {session_id}")
            
            try:
                # Fetch events for this session
                events = fetch_events_from_api(session_id)
                
                if not events:
                    print(f"No events found for session {session_id}")
                    analysis_results["failed_analyses"] += 1
                    analysis_results["session_results"].append({
                        "session_id": session_id,
                        "status": "no_events",
                        "message": "No events found"
                    })
                    continue
                
                print(f"Found {len(events)} events for session {session_id}")
                
                # Run analysis using process_session_replay
                result = process_session_replay(session_id, events)
                print("HUBBAADDAA")
                
                # Update summary statistics
                if result.get("status") == "success":
                    analysis_results["successful_analyses"] += 1
                    analysis_results["summary"]["total_events"] += result.get("total_events", 0)
                    analysis_results["summary"]["total_actions"] += result.get("total_actions", 0)
                    analysis_results["summary"]["total_chunks"] += result.get("total_chunks", 0)
                    analysis_results["summary"]["stored_chunks"] += result.get("stored_chunks", 0)
                    
                    print(f"✓ Analysis successful: {result.get('total_actions')} actions, {result.get('total_chunks')} chunks, {result.get('stored_chunks')} stored")
                else:
                    analysis_results["failed_analyses"] += 1
                    print(f"✗ Analysis failed: {result.get('message', 'Unknown error')}")
                
                analysis_results["session_results"].append(result)
                
            except Exception as e:
                print(f"Error analyzing session {session_id}: {e}")
                analysis_results["failed_analyses"] += 1
                analysis_results["session_results"].append({
                    "session_id": session_id,
                    "status": "error",
                    "message": str(e)
                })
        
        # Print final summary
        print(f"\n{'='*50}")
        print(f"ANALYSIS COMPLETE")
        print(f"{'='*50}")
        print(f"Project ID: {project_id}")
        print(f"Total sessions processed: {analysis_results['total_sessions']}")
        print(f"Successful analyses: {analysis_results['successful_analyses']}")
        print(f"Failed analyses: {analysis_results['failed_analyses']}")
        print(f"Total events processed: {analysis_results['summary']['total_events']}")
        print(f"Total actions extracted: {analysis_results['summary']['total_actions']}")
        print(f"Total chunks created: {analysis_results['summary']['total_chunks']}")
        print(f"Total chunks stored in Pinecone: {analysis_results['summary']['stored_chunks']}")
        print(f"{'='*50}")
        
        return analysis_results
        
    except Exception as e:
        print(f"Error in analyze_last_50_sessions: {e}")
        return {"status": "error", "message": str(e)}
    
def test_generate_activity_event():
    events = get_fb_session_events("34b49186-2097-4b71-9f67-ab28b5850d65")
    generate_activity_events(events, "34b49186-2097-4b71-9f67-ab28b5850d65", "f91c1c07-2a54-4756-8b2f-9b4fff44da39")
    
def process_existing_replays(project_id: str):
    """
    Process all existing replays for a given project ID.
    
    Args:
        project_id: The project ID to process sessions for
        
    Returns:
        Dictionary with processing results and statistics
    """
    print(f"Starting to process existing replays for project: {project_id}")
    
    try:
        # Get all sessions for this project from Firestore
        sessions = get_session_ids(project_id)[:10]
        if not sessions:
            print("No sessions found for this project")
            return {"status": "no_sessions", "message": "No sessions found"}
        
        print(f"Found {len(sessions)} sessions to process")
        
        processing_results = {
            "project_id": project_id,
            "total_sessions": len(sessions),
            "successful_analyses": 0,
            "failed_analyses": 0,
            "session_results": [],
            "summary": {
                "total_events_processed": 0,
                "total_actions_generated": 0
            }
        }
        
        for i, session in enumerate(sessions, 1):
            session_id = session.get("sessionId")
            print(f"\n[{i}/{len(sessions)}] Processing session: {session_id}")
            
            try:
                # Get events for this session from the database
                events = get_fb_session_events(session_id)
                
                if not events:
                    print(f"No events found for session {session_id}")
                    processing_results["failed_analyses"] += 1
                    processing_results["session_results"].append({
                        "session_id": session_id,
                        "status": "no_events",
                        "message": "No events found"
                    })
                    continue
                
                print(f"Found {len(events)} events for session {session_id}")
                
                # Run analysis using generate_activity_event
                generate_activity_events(events, session_id, project_id)
                
                # Update summary statistics
                processing_results["successful_analyses"] += 1
                processing_results["summary"]["total_events_processed"] += len(events)
                
                print(f"✓ Analysis successful: {len(events)} events processed")
                
                processing_results["session_results"].append({
                    "session_id": session_id,
                    "status": "success",
                    "events_processed": len(events)
                })
                
            except Exception as e:
                print(f"Error processing session {session_id}: {e}")
                processing_results["failed_analyses"] += 1
                processing_results["session_results"].append({
                    "session_id": session_id,
                    "status": "error",
                    "message": str(e)
                })
        
        # Print final summary
        print(f"\n{'='*50}")
        print(f"PROCESSING COMPLETE")
        print(f"{'='*50}")
        print(f"Project ID: {project_id}")
        print(f"Total sessions processed: {processing_results['total_sessions']}")
        print(f"Successful analyses: {processing_results['successful_analyses']}")
        print(f"Failed analyses: {processing_results['failed_analyses']}")
        print(f"Total events processed: {processing_results['summary']['total_events_processed']}")
        print(f"{'='*50}")
        
        return processing_results
        
    except Exception as e:
        print(f"Error in process_existing_replays: {e}")
        return {"status": "error", "message": str(e)}
    

def main():
    # Update all session replays with project ID
    # project_id = "5694ea67-5b4a-4ac8-a5bd-3268e3a7bb88"
    # print(f"Updating all session replays with project ID: {project_id}")
    # updated_count = update_session_replays_with_project_id(project_id)
    # # print(f"Updated {updated_count} session replays")
    
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
        
    #     save_session_metadata(session_id, gcs_path, "f91c1c07-2a54-4756-8b2f-9b4fff44da39")
        
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

    # Run analysis on last 50 sessions
    # analyze_last_50_sessions()

    # test_generate_activity_event()
    process_existing_replays("f91c1c07-2a54-4756-8b2f-9b4fff44da39")

if __name__ == "__main__":
    main()