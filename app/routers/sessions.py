from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from typing import List, Dict, Any, Optional
import json
import logging
from datetime import datetime, timedelta
from app.services.firebase_service import get_fb_session_events, get_bucket
from app.services.firestore_service import (
    get_session_ids,
    get_user_projects,
    create_project,
    get_project,
    save_session_metadata,
    get_project_by_api_key,
    get_firestore_client,
    get_action_events_from_action_id,
    get_random_session_ids_with_events,
    save_project_insights,
    get_latest_insights,
)
from app.services.analysis_service import generate_activity_events
from app.services.intelligence_service import generate_project_insights
import time

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
            APPLOGGER.error(
                f"Invalid API key: {api_key} for session id {data.get('sessionId')}"
            )
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
                if session_duration > timedelta(minutes=60):
                    APPLOGGER.info(
                        f"Session {session_id} exceeds 30 minutes. Refusing to save."
                    )
                    return JSONResponse(
                        content={
                            "status": "too_long",
                            "message": "Session exceeds 30 minutes",
                        }
                    )

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
        if new_events:
            generate_activity_events(new_events, session_id, project_id)
        success = save_session_metadata(session_id, gcs_url, project_id)

        if success:
            return JSONResponse(content={"status": "success", "file": gcs_url})
        else:
            raise HTTPException(
                status_code=500, detail="Failed to save session metadata"
            )

    except Exception as e:
        APPLOGGER.error(f"Error saving session replay data: {str(e)}")
        raise HTTPException(
            status_code=500, detail="Failed to save session replay data"
        )


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
        return JSONResponse(
            content={
                "success": True,
                "message": "Project created successfully",
                "project": project_data,
            }
        )
    except Exception as e:
        APPLOGGER.error(f"Error creating project: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to create project")


@router.get("/projects/{project_id}")
async def get_project_endpoint(project_id: str):
    try:
        project = get_project(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        return JSONResponse(
            content={
                "success": True,
                "message": "Project retrieved successfully",
                "project": project,
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        APPLOGGER.error(f"Error getting project {project_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get project")


@router.get("/projects")
async def get_projects_endpoint(
    user_id: str = Query(..., description="User ID to fetch projects for")
):
    try:
        projects = get_user_projects(user_id)
        return JSONResponse(
            content={
                "success": True,
                "message": "User projects retrieved successfully",
                "projects": projects,
            }
        )
    except Exception as e:
        APPLOGGER.error(f"Error getting projects for user {user_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get user projects")


@router.get("/session-ids")
async def get_session_ids_endpoint(
    project_id: str = Query(..., description="Filter sessions by project ID")
):
    try:
        sessions = get_session_ids(project_id)
        return JSONResponse(
            content={
                "success": True,
                "message": "Session replay IDs retrieved successfully",
                "sessions": sessions,
            }
        )
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


@router.get("/projects/{project_id}/action-ids")
async def get_project_action_ids(
    project_id: str,
    start: Optional[int] = Query(None, description="Start time in seconds since epoch"),
    end: Optional[int] = Query(None, description="End time in seconds since epoch"),
):
    try:
        db = get_firestore_client()

        if start is not None or end is not None:
            start_ms = int(start) * 1000 if start is not None else None
            end_ms = int(end) * 1000 if end is not None else None
            APPLOGGER.info(
                f"Getting action IDs for project {project_id} start: {start_ms}, end: {end_ms}"
            )

            action_ids_ref = (
                db.collection("projects").document(project_id).collection("action_ids")
            )
            action_ids_docs = action_ids_ref.stream()

            action_ids = []
            for doc in action_ids_docs:
                action_id = doc.id

                action_events_ref = (
                    db.collection("projects")
                    .document(project_id)
                    .collection("action_events")
                )
                query = action_events_ref.where("action_id", "==", action_id)

                if start_ms is not None:
                    query = query.where("timestamp", ">=", start_ms)

                if end_ms is not None:
                    query = query.where("timestamp", "<=", end_ms)

                events_docs = query.stream()
                count = sum(1 for _ in events_docs)

                action_ids.append({"id": action_id, "count": count})

        else:
            action_ids_ref = (
                db.collection("projects").document(project_id).collection("action_ids")
            )
            docs = action_ids_ref.stream()

            action_ids = []
            for doc in docs:
                doc_data = doc.to_dict()
                action_ids.append({"id": doc.id, "count": doc_data.get("count", 0)})

        APPLOGGER.info(
            f"Retrieved {len(action_ids)} action IDs for project {project_id}"
        )

        return JSONResponse(
            content={
                "success": True,
                "message": f"Retrieved {len(action_ids)} action IDs",
                "project_id": project_id,
                "action_ids": action_ids,
            }
        )

    except Exception as e:
        APPLOGGER.error(f"Error getting action IDs for project {project_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get action IDs")


@router.post("/rag/query")
async def rag_query_endpoint(request: Dict[str, Any]):
    try:
        action_id = request.get("action_id")
        project_id = request.get("project_id")

        APPLOGGER.info(
            f"RAG query endpoint called with action_id: {action_id}, project_id: {project_id}"
        )

        if not action_id:
            raise HTTPException(status_code=400, detail="Action ID is required")
        if not project_id:
            raise HTTPException(status_code=400, detail="Project ID is required")

        result = get_action_events_from_action_id(project_id, action_id)

        if not result:
            return JSONResponse(
                content={
                    "success": False,
                    "message": f"No events found with action_id {action_id}",
                    "target_events": [],
                    "context_events": [],
                }
            )

        target_events = result["target_events"]
        context_events_by_session = result["context_events_by_session"]
        session_ids = result["session_ids"]

        total_context_events = sum(
            len(events) for events in context_events_by_session.values()
        )

        response_data = {
            "success": True,
            "message": f"Retrieved {len(target_events)} events with action_id {action_id} and {total_context_events} context events across {len(context_events_by_session)} sessions",
            "target_events": target_events,
            "context_events_by_session": context_events_by_session,
            "session_ids": session_ids,
            "action_id": action_id,
            "summary": {
                "total_target_events": len(target_events),
                "total_context_events": total_context_events,
                "sessions_involved": len(session_ids),
                "sessions_with_context": len(context_events_by_session),
                "action_id": action_id,
            },
        }

        return JSONResponse(content=response_data)

    except Exception as e:
        APPLOGGER.error(f"Error in RAG query: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to process RAG query")


@router.post("/projects/insights")
async def generate_all_projects_insights_endpoint(request: Dict[str, Any] = None):
    try:
        APPLOGGER.info("Generating insights for all projects")

        db = get_firestore_client()
        projects_ref = db.collection("projects")
        projects_docs = projects_ref.stream()
        
        all_results = []
        session_count = 5
        if request and "session_count" in request:
            session_count = min(max(request["session_count"], 1), 10)

        for project_doc in projects_docs:
            project_id = project_doc.id
            project_data = project_doc.to_dict()
            
            try:
                session_ids, sessions_data = get_random_session_ids_with_events(
                    project_id, session_count
                )
                
                if session_ids:
                    insights = generate_project_insights(sessions_data, project_id)
                    if insights:
                        save_project_insights(project_id, insights, session_ids)
                        total_events = sum(len(events) for events in sessions_data.values())
                        
                        project_result = {
                            "project_id": project_id,
                            "project_name": project_data.get("name", "Unknown"),
                            "insights": insights,
                            "sessions_analyzed": session_ids,
                            "summary": {
                                "sessions_analyzed": len(session_ids),
                                "total_events": total_events,
                                "insights_generated": len(insights),
                            },
                        }
                        all_results.append(project_result)
                        
                        APPLOGGER.info(
                            f"Generated {len(insights)} insights for project {project_id}"
                        )
                    else:
                        APPLOGGER.warning(f"Failed to generate insights for project {project_id}")
                else:
                    APPLOGGER.info(f"No sessions found for project {project_id}")
                    
            except Exception as e:
                APPLOGGER.error(f"Error processing project {project_id}: {str(e)}")
                continue

        response_data = {
            "success": True,
            "projects_processed": len(all_results),
            "results": all_results,
            "created_at": int(time.time()),
        }

        APPLOGGER.info(f"Successfully processed {len(all_results)} projects")
        return JSONResponse(content=response_data)

    except Exception as e:
        APPLOGGER.error(f"Error generating insights for all projects: {str(e)}")
        raise HTTPException(
            status_code=500, detail="Failed to generate project insights"
        )


@router.get("/projects/{project_id}/insights")
async def get_project_insights_endpoint(
    project_id: str, limit: int = Query(3, ge=1, le=10)
):
    try:
        APPLOGGER.info(f"Getting latest insights for project {project_id}")

        project = get_project(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        insights = get_latest_insights(project_id, limit)

        response_data = {
            "success": True,
            "insights": insights,
            "project_id": project_id,
            "summary": {"total_insights": len(insights), "limit": limit},
        }

        APPLOGGER.info(
            f"Successfully retrieved {len(insights)} insights for project {project_id}"
        )
        return JSONResponse(content=response_data)

    except HTTPException:
        raise
    except Exception as e:
        APPLOGGER.error(f"Error getting insights for project {project_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get project insights")
