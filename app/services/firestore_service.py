import logging
import uuid
import secrets
import time
import json
from typing import Optional, Dict, Any, List
from google.cloud import firestore
from google.oauth2 import service_account
from app.config.settings import settings

APPLOGGER = logging.getLogger(__name__)


def estimate_tokens(text: str) -> int:
    """Estimate token count for text (rough approximation: 1 token ≈ 4 characters)"""
    return len(text) // 4


def get_firestore_client():
    creds = service_account.Credentials.from_service_account_file(
        settings.service_account_key_path
    )
    return firestore.Client(credentials=creds, project=creds.project_id)


def save_session_metadata(session_id: str, gcs_path: str, project_id: str):
    try:
        db = get_firestore_client()

        session_data = {
            "sessionId": session_id,
            "gcs_path": gcs_path,
            "projectId": project_id,
            "timestamp": int(time.time()),
        }

        db.collection("session_replays").document(session_id).set(session_data)

        APPLOGGER.info(f"Saved session metadata for {session_id}")
        return True

    except Exception as e:
        APPLOGGER.error(f"Error saving session metadata: {e}")
        return False


def save_user(user_info: Dict[str, Any]):
    try:
        db = get_firestore_client()

        user_id = user_info.get("id")
        if not user_id:
            APPLOGGER.error("User ID is required")
            return False

        db.collection("users").document(user_id).set(user_info)

        APPLOGGER.info(f"Saved user {user_id} to Firestore")
        return True

    except Exception as e:
        APPLOGGER.error(f"Error saving user: {e}")
        return False


def get_project(project_id: str):
    try:
        db = get_firestore_client()

        project_doc = db.collection("projects").document(project_id).get()
        if not project_doc.exists:
            APPLOGGER.warning(f"Project {project_id} not found")
            return None

        project_data = project_doc.to_dict()

        return {
            "id": project_id,
            "name": project_data.get("name"),
            "createdAt": project_data.get("createdAt"),
            "createdBy": project_data.get("createdBy"),
            "publicApiKey": project_data.get("publicApiKey"),
        }

    except Exception as e:
        APPLOGGER.error(f"Error retrieving project {project_id}: {e}")
        return None


def create_project(name: str, user_id: str):
    try:
        db = get_firestore_client()

        project_id = str(uuid.uuid4())
        public_api_key = f"pk_{secrets.token_urlsafe(32)}"

        project_data = {
            "id": project_id,
            "name": name,
            "createdAt": int(time.time()),
            "createdBy": user_id,
            "publicApiKey": public_api_key,
        }

        db.collection("projects").document(project_id).set(project_data)

        user_ref = db.collection("users").document(user_id)
        user_doc = user_ref.get()

        if user_doc.exists:
            user_data = user_doc.to_dict()
            projects = user_data.get("projects", [])
            projects.append(project_id)
            user_ref.update({"projects": projects})
        else:
            user_ref.set({"projects": [project_id]})

        APPLOGGER.info(f"Created project {project_id} for user {user_id}")

        return {"id": project_id, "name": name, "publicApiKey": public_api_key}

    except Exception as e:
        APPLOGGER.error(f"Error creating project: {e}")
        raise e


def get_user_projects(user_id: str):
    try:
        db = get_firestore_client()

        user_doc = db.collection("users").document(user_id).get()
        if not user_doc.exists:
            APPLOGGER.warning(f"User {user_id} not found")
            return []

        user_data = user_doc.to_dict()
        project_ids = user_data.get("projects", [])

        if not project_ids:
            APPLOGGER.info(f"No projects found for user {user_id}")
            return []

        projects = []
        for project_id in project_ids:
            project_doc = db.collection("projects").document(project_id).get()
            if project_doc.exists:
                project_data = project_doc.to_dict()
                projects.append(
                    {
                        "id": project_id,
                        "name": project_data.get("name"),
                        "createdAt": project_data.get(
                            "createdAt"
                        ),  # seconds since epoch
                    }
                )

        APPLOGGER.info(f"Retrieved {len(projects)} projects for user {user_id}")
        return projects

    except Exception as e:
        APPLOGGER.error(f"Error retrieving projects for user {user_id}: {e}")
        return []


def get_session_ids(project_id: str):
    """Fetch session IDs from Firestore session_replays collection"""
    try:
        db = get_firestore_client()

        query = (
            db.collection("session_replays")
            .where("projectId", "==", project_id)
            .order_by("timestamp", direction=firestore.Query.DESCENDING)
        )

        snapshot = query.get()

        sessions = []
        for doc in snapshot:
            data = doc.to_dict()
            sessions.append(
                {
                    "sessionId": data.get("sessionId"),
                    "timestamp": data.get("timestamp"),
                    "url": data.get("url"),
                    "gcs_path": data.get("gcs_path"),
                }
            )

        APPLOGGER.info(
            f"Retrieved {len(sessions)} sessions from Firestore for project_id: {project_id}"
        )
        return sessions

    except Exception as e:
        APPLOGGER.error(f"Error retrieving sessions from Firestore: {e}")
        return []


def get_project_by_api_key(api_key: str):
    try:
        db = get_firestore_client()
        project_doc = (
            db.collection("projects").where("publicApiKey", "==", api_key).get()
        )
        if not project_doc:
            APPLOGGER.warning(f"API key {api_key} not found")
            return None
        return project_doc[0].to_dict()
    except Exception as e:
        APPLOGGER.error(f"Error retrieving project by API key {api_key}: {e}")
        return None


def save_action_id_batch(action_ids: Dict[str, int], project_id: str):
    try:
        db = get_firestore_client()
        batch = db.batch()
        
        for action_id, count in action_ids.items():
            doc_ref = db.collection("projects").document(project_id).collection(
                "action_ids"
            ).document(action_id)
            
            doc = doc_ref.get()
            if doc.exists:
                current_count = doc.to_dict().get('count', 0)
                batch.update(doc_ref, {'count': current_count + count})
            else:
                batch.set(doc_ref, {'count': count})
        
        batch.commit()
        return True
            
    except Exception as e:
        APPLOGGER.error(f"Error saving action IDs in batch: {e}")
        return False


def save_action_events(events: Dict[str, Any], project_id: str):
    try:
        db = get_firestore_client()
        total_events = len(events)
        events_list = list(events) if isinstance(events, dict) else events
        
        # Process in batches of 500 (Firestore limit)
        batch_size = 500
        total_saved = 0
        
        for i in range(0, len(events_list), batch_size):
            batch = db.batch()
            batch_events = events_list[i:i + batch_size]
            
            for event in batch_events:
                doc_ref = db.collection("projects").document(project_id).collection(
                    "action_events"
                ).document()
                batch.set(doc_ref, event)
            
            batch.commit()
            total_saved += len(batch_events)
        
        return True
    except Exception as e:
        APPLOGGER.error(f"Error saving action events in batch: {e}")
        return False

def get_action_events_from_action_id(project_id: str, action_id: str, max_tokens: int = 8000):
    """
    Get all events with the specified action_id and surrounding context events.
    
    Args:
        project_id: The project ID
        action_id: The specific action ID to find
        max_tokens: Maximum tokens to return (default: 4000 tokens)
        
    Returns:
        Dictionary with all events having the action_id and surrounding context events
    """
    try:
        db = get_firestore_client()
        
        action_events_ref = db.collection("projects").document(project_id).collection(
            "action_events"
        ).where('action_id', '==', action_id)
        
        action_events_docs = action_events_ref.stream()
        target_events = []
        
        for doc in action_events_docs:
            event_data = doc.to_dict()
            target_events.append(event_data)
        
        if not target_events:
            APPLOGGER.warning(f"No events found with action_id {action_id} for project {project_id}")
            return None
        
        session_ids = list(set([event.get('session_id') for event in target_events if event.get('session_id')]))
        
        session_metadata = {}
        for session_id in session_ids:
            session_doc = db.collection("session_replays").document(session_id).get()
            if session_doc.exists:
                session_data = session_doc.to_dict()
                session_metadata[session_id] = session_data.get('timestamp', 0)
            else:
                session_metadata[session_id] = 0
        
        session_ids.sort(key=lambda session_id: session_metadata.get(session_id, 0), reverse=True)
        
        context_events_by_session = {}
        seen_document_ids = set()
        current_tokens = 0
        sessions_included = 0
        
        for session_id in session_ids:
            session_events_ref = db.collection("projects").document(project_id).collection(
                "action_events"
            ).where('session_id', '==', session_id)
            
            session_docs = session_events_ref.stream()
            session_events = []
            
            for doc in session_docs:
                event_data = doc.to_dict()
                
                if doc.id not in seen_document_ids:
                    event_data.pop('session_id', None)
                    event_data.pop('local_id', None)
                    
                    session_events.append(event_data)
                    seen_document_ids.add(doc.id)
            
            session_events.sort(key=lambda x: x.get('timestamp', 0))
            
            # Estimate tokens for this session
            session_json = json.dumps(session_events)
            session_tokens = estimate_tokens(session_json)
            
            if max_tokens is not None and current_tokens + session_tokens > max_tokens:
                APPLOGGER.info(f"Token limit reached ({current_tokens}/{max_tokens}). Stopping at {sessions_included} sessions.")
                break
            
            context_events_by_session[session_id] = session_events
            current_tokens += session_tokens
            sessions_included += 1
        
        total_context_events = sum(len(events) for events in context_events_by_session.values())
        token_info = f" ({current_tokens} tokens)" if max_tokens is not None else ""
        APPLOGGER.info(f"Retrieved {len(target_events)} events with action_id {action_id} and {total_context_events} context events across {len(context_events_by_session)} sessions{token_info}")
        
        return {
            "target_events": target_events,
            "context_events_by_session": context_events_by_session,
            "session_ids": session_ids,
            "action_id": action_id
        }
        
    except Exception as e:
        APPLOGGER.error(f"Error getting action events for {action_id}: {e}")
        return None


def get_existing_action_ids(project_id: str) -> List[str]:
    """
    Get all existing action IDs for a project from Firestore.
    
    Args:
        project_id: The project ID to get action IDs for
        
    Returns:
        List of existing action ID strings
    """
    try:
        db = get_firestore_client()
        
        action_ids_ref = db.collection("projects").document(project_id).collection("action_ids")
        docs = action_ids_ref.stream()
        
        existing_action_ids = []
        for doc in docs:
            existing_action_ids.append(doc.id)
        
        APPLOGGER.info(f"Retrieved {len(existing_action_ids)} existing action IDs for project {project_id}")
        return existing_action_ids
        
    except Exception as e:
        APPLOGGER.error(f"Error getting existing action IDs for project {project_id}: {e}")
        return []
    