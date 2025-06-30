from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Dict, Any
import logging
from app.services.firestore_service import save_user

APPLOGGER = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["users"])

class ClerkWebhookEvent(BaseModel):
    data: dict
    object: str
    type: str

@router.post("/clerk-webhook/users")
async def clerk_webhook(request: Request):
    try:
        body = await request.json()
        event = ClerkWebhookEvent(**body)
        APPLOGGER.info(f"Received Clerk webhook event type: {event.type}")

        if event.type == "user.created":
            user_data = event.data
            user_id = user_data.get("id")

            primary_email_id = user_data.get("primary_email_address_id")
            email_addresses = user_data.get("email_addresses", [])
            
            primary_email = None
            for email in email_addresses:
                if email.get("id") == primary_email_id:
                    primary_email = email.get("email_address")
                    break

            user_info = {
                "id": user_id,
                "email": primary_email,
                "firstName": user_data.get("first_name"),
                "lastName": user_data.get("last_name"),
                "createdAt": user_data.get("created_at"),
                "projects": []
            }

            success = save_user(user_info)
            if success:
                return JSONResponse(content={"success": True, "message": "User saved successfully"})
            else:
                raise HTTPException(status_code=500, detail="Failed to save user")

        return JSONResponse(content={"success": True, "message": "Webhook processed"})

    except Exception as e:
        APPLOGGER.error(f"Error processing Clerk webhook: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to process webhook") 