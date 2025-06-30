from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from typing import List, Dict, Any, Optional
import json
import logging
from datetime import datetime, timedelta
from app.services.firebase_service import get_fb_session_events, get_bucket
from app.services.firestore_service import get_session_ids, get_user_projects, create_project, get_project, save_session_metadata, get_project_by_api_key
from app.services.analysis_service import process_session_replay
from app.services.rag_service import get_relevant_chunks_for_rag

APPLOGGER = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["sessions"])

@router.post("/session-events")
async def save_session_replay_data(request: Request):
    try:
        APPLOGGER.info("Saving session replay data")
        data = await request.json()
        api_key = data.get("apiKey")
        
        project = get_project_by_api_key(api_key)
        if not project:
            APPLOGGER.error(f"Invalid API key: {api_key} for session id {data.get('sessionId')}")
            raise HTTPException(status_code=401, detail="Invalid API key")
        
        project_id = project.get("id")
        session_id = data.get("sessionId")
        new_events = data.get("events", [])
        
        if not session_id:
            raise HTTPException(status_code=400, detail="Missing sessionId")
        
        bucket_name = "session-replays"
        bucket = get_bucket(bucket_name)
        blob = bucket.blob(f"sessions/{session_id}.json")
        
        if blob.exists():
            existing_data = json.loads(blob.download_as_text())
            existing_events = existing_data.get("events", [])
        else:
            existing_events = []
        
        all_events = existing_events + new_events

        if all_events:
            first_ts = all_events[0].get("timestamp")
            last_ts = all_events[-1].get("timestamp")
            if first_ts and last_ts:
                first_dt = datetime.fromtimestamp(first_ts / 1000)
                last_dt = datetime.fromtimestamp(last_ts / 1000)
                session_duration = last_dt - first_dt
                if session_duration > timedelta(minutes=30):
                    return JSONResponse(content={
                        "status": "too_long",
                        "message": "Session exceeds 30 minutes",
                    })

        session_json = {
            "sessionId": session_id,
            "events": all_events,
            "timestamp": data.get("timestamp"),
        }
        
        blob.upload_from_string(
            json.dumps(session_json, ensure_ascii=False, indent=2),
            content_type="application/json",
        )
        
        gcs_url = f"gs://{bucket_name}/sessions/{session_id}.json"
        events = session_json.get("events", [])
        success = save_session_metadata(session_id, gcs_url, project_id)
        process_session_replay(session_id, events)
        
        if success:
            return JSONResponse(content={"status": "success", "file": gcs_url})
        else:
            raise HTTPException(status_code=500, detail="Failed to save session metadata")
            
    except Exception as e:
        APPLOGGER.error(f"Error saving session replay data: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to save session replay data")

@router.post("/projects")
async def create_project_endpoint(request: Dict[str, Any]):
    try:
        name = request.get("name")
        user_id = request.get("user_id")
        
        if not name:
            raise HTTPException(status_code=400, detail="Project name is required")
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID is required")
        
        project_data = create_project(name, user_id)
        return JSONResponse(content={
            "success": True,
            "message": "Project created successfully",
            "project": project_data
        })
    except Exception as e:
        APPLOGGER.error(f"Error creating project: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to create project")

@router.get("/projects/{project_id}")
async def get_project_endpoint(project_id: str):
    try:
        project = get_project(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        return JSONResponse(content={
            "success": True,
            "message": "Project retrieved successfully",
            "project": project
        })
    except HTTPException:
        raise
    except Exception as e:
        APPLOGGER.error(f"Error getting project {project_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get project")

@router.get("/projects")
async def get_projects_endpoint(user_id: str = Query(..., description="User ID to fetch projects for")):
    try:
        projects = get_user_projects(user_id)
        return JSONResponse(content={
            "success": True,
            "message": "User projects retrieved successfully",
            "projects": projects
        })
    except Exception as e:
        APPLOGGER.error(f"Error getting projects for user {user_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get user projects")

@router.get("/session-ids")
async def get_session_ids_endpoint(project_id: str = Query(..., description="Filter sessions by project ID")):
    try:
        sessions = get_session_ids(project_id)
        return JSONResponse(content={
            "success": True,
            "message": "Session replay IDs retrieved successfully",
            "sessions": sessions
        })
    except Exception as e:
        APPLOGGER.error(f"Error getting session IDs: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get session IDs")

@router.get("/sessions/{session_id}/events")
async def get_session_events(session_id: str):
    APPLOGGER.info(f"Getting session events for {session_id}")
    try:
        events = get_fb_session_events(session_id)
        return JSONResponse(content={"events": events})
    except Exception as e:
        APPLOGGER.error(f"Error getting session events for {session_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get session events")

@router.post("/rag/query")
async def rag_query_endpoint(request: Dict[str, Any]):
    try:
        question = request.get("question")
        session_id = request.get("session_id")
        top_k = request.get("top_k", 10)
        
        APPLOGGER.info(f"RAG query endpoint called with question: {question}, session_id: {session_id}, top_k: {top_k}")
        
        if not question:
            raise HTTPException(status_code=400, detail="Question is required")
        
        relevant_chunks = get_relevant_chunks_for_rag(question, session_id, top_k)
        
        if not relevant_chunks:
            return JSONResponse(content={
                "context": "No relevant chunks found",
                "relevant_chunks": [],
                "success": True
            })
        
        context_parts = []
        for i, chunk in enumerate(relevant_chunks, 1):
            session_id = chunk.get('session_id', 'unknown')
            relevance = chunk['relevance_score']
            data = chunk['text']
            context_parts.append(f"Chunk {i}: {{session_id: {session_id}, relevance: {relevance:.3f}, data: {data}}}")
        
        context = "\n\n".join(context_parts)
        
        return JSONResponse(content={
            "context": context,
            "relevant_chunks": relevant_chunks,
            "success": True
        })
        
    except Exception as e:
        APPLOGGER.error(f"Error in RAG query: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to process RAG query") 