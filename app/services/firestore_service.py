import logging
import uuid
import secrets
import time
from typing import Optional, Dict, Any
from google.cloud import firestore
from google.oauth2 import service_account
from app.config.settings import settings

APPLOGGER = logging.getLogger(__name__)

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
            "timestamp": int(time.time())
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
        
        db.collection('users').document(user_id).set(user_info)
        
        APPLOGGER.info(f"Saved user {user_id} to Firestore")
        return True
        
    except Exception as e:
        APPLOGGER.error(f"Error saving user: {e}")
        return False

def get_project(project_id: str):
    try:
        db = get_firestore_client()
        
        project_doc = db.collection('projects').document(project_id).get()
        if not project_doc.exists:
            APPLOGGER.warning(f"Project {project_id} not found")
            return None
        
        project_data = project_doc.to_dict()
        
        return {
            "id": project_id,
            "name": project_data.get("name"),
            "createdAt": project_data.get("createdAt"),
            "createdBy": project_data.get("createdBy"),
            "publicApiKey": project_data.get("publicApiKey")
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
            "publicApiKey": public_api_key
        }
        
        db.collection('projects').document(project_id).set(project_data)
    
        user_ref = db.collection('users').document(user_id)
        user_doc = user_ref.get()
        
        if user_doc.exists:
            user_data = user_doc.to_dict()
            projects = user_data.get('projects', [])
            projects.append(project_id)
            user_ref.update({'projects': projects})
        else:
            user_ref.set({'projects': [project_id]})
        
        APPLOGGER.info(f"Created project {project_id} for user {user_id}")
        
        return {
            "id": project_id,
            "name": name,
            "publicApiKey": public_api_key
        }
        
    except Exception as e:
        APPLOGGER.error(f"Error creating project: {e}")
        raise e

def get_user_projects(user_id: str):
    try:
        db = get_firestore_client()
        
        user_doc = db.collection('users').document(user_id).get()
        if not user_doc.exists:
            APPLOGGER.warning(f"User {user_id} not found")
            return []
        
        user_data = user_doc.to_dict()
        project_ids = user_data.get('projects', [])
        
        if not project_ids:
            APPLOGGER.info(f"No projects found for user {user_id}")
            return []
        
        projects = []
        for project_id in project_ids:
            project_doc = db.collection('projects').document(project_id).get()
            if project_doc.exists:
                project_data = project_doc.to_dict()
                projects.append({
                    "id": project_id,
                    "name": project_data.get("name"),
                    "createdAt": project_data.get("createdAt") #seconds since epoch
                })
        
        APPLOGGER.info(f"Retrieved {len(projects)} projects for user {user_id}")
        return projects
        
    except Exception as e:
        APPLOGGER.error(f"Error retrieving projects for user {user_id}: {e}")
        return []

def get_session_ids(project_id: str):
    """Fetch session IDs from Firestore session_replays collection"""
    try:
        db = get_firestore_client()
        
        query = db.collection('session_replays').where('projectId', '==', project_id).order_by('timestamp', direction=firestore.Query.DESCENDING)
        
        snapshot = query.get()
        
        sessions = []
        for doc in snapshot:
            data = doc.to_dict()
            sessions.append({
                "sessionId": data.get("sessionId"),
                "timestamp": data.get("timestamp"),
                "url": data.get("url"),
                "gcs_path": data.get("gcs_path"),
            })
        
        APPLOGGER.info(f"Retrieved {len(sessions)} sessions from Firestore for project_id: {project_id}")
        return sessions
        
    except Exception as e:
        APPLOGGER.error(f"Error retrieving sessions from Firestore: {e}")
        return [] 

def get_project_by_api_key(api_key: str):
    try:
        db = get_firestore_client()
        project_doc = db.collection('projects').where('publicApiKey', '==', api_key).get()
        if not project_doc:
            APPLOGGER.warning(f"API key {api_key} not found")
            return None
        return project_doc[0].to_dict()
    except Exception as e:
        APPLOGGER.error(f"Error retrieving project by API key {api_key}: {e}")
        return None