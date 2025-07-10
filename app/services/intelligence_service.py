import os
import logging
from typing import Dict, Any, List
from openai import OpenAI
from app.services.firestore_service import get_existing_action_ids

APPLOGGER = logging.getLogger(__name__)


def generate_action_id_with_llm(
    parsed_events: List[Dict[str, Any]], project_id: str = None, batch_size: int = 10
) -> List[str]:
    """
    Use LLM to generate intelligent action IDs from parsed events.

    Args:
        parsed_events: List of events with action, element_type, and attributes
        project_id: Optional project ID to get existing action IDs for reuse
        batch_size: Maximum number of events to process in a single LLM request

    Returns:
        List of action_id strings in the same order as the input events
    """
    if not parsed_events:
        return []

    try:
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

        existing_action_ids = set()
        if project_id:
            existing_action_ids = set(get_existing_action_ids(project_id))

        all_action_ids = existing_action_ids.copy()
        all_action_ids_list = []

        for i in range(0, len(parsed_events), batch_size):
            batch_events = parsed_events[i : i + batch_size]
            batch_start = i + 1
            batch_end = min(i + batch_size, len(parsed_events))

            APPLOGGER.info(
                f"Processing batch {batch_start}-{batch_end} of {len(parsed_events)} events"
            )

            existing_ids_text = ""
            if all_action_ids:
                existing_ids_text = f"""
                
                EXISTING ACTION IDs (PREFER THESE WHEN THEY MATCH THE INTENT):
                {', '.join(sorted(all_action_ids))}
                
                IMPORTANT: If any of the existing action IDs above match the user's intent for an event, use that existing ID instead of creating a new one. Only create new action IDs when there's no suitable existing match.
                """

            events_json = str(batch_events)

            prompt = f"""
            Analyze these user interaction events and generate intelligent, semantic action IDs.
            
            Events: {events_json}{existing_ids_text}
            
            For each event, generate an action_id: A short, descriptive identifier that captures the user's intent.
            
            Rules:
            - Use semantic, logical descriptions instead of technical details
            - Focus on what the user is trying to accomplish
            - Be specific but concise
            - Use lowercase with underscores for action_id
            - Examples: "clicked_view_photos", "clicked_submit_form", "clicked_navigation_menu"
            - PREFER EXISTING ACTION IDs when they match the user's intent
            - Only create new action IDs when there's no suitable existing match
            - For page load, try to specify the page by the url or title
            
            Return a JSON array of action_id strings only, in the same order as the events.
            """

            response = client.chat.completions.create(
                model="gpt-4.1",
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert at analyzing user interactions and generating meaningful action descriptions. You prioritize reusing existing action IDs when they match the user's intent.",
                    },
                    {"role": "user", "content": prompt},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "action_id_array",
                        "strict": True,
                        "schema": {
                            "type": "object",
                            "properties": {
                                "action_ids": {
                                    "type": "array",
                                    "description": "List of action_id strings.",
                                    "items": {"type": "string", "minLength": 1},
                                }
                            },
                            "required": ["action_ids"],
                            "additionalProperties": False,
                        },
                    },
                },
                temperature=0.3,
                max_tokens=1000,
            )

            result = response.choices[0].message.content

            try:
                import json

                batch_action_ids = json.loads(result).get("action_ids", [])
                print("batch_action_ids", batch_action_ids)

                if isinstance(batch_action_ids, list) and len(batch_action_ids) == len(
                    batch_events
                ):
                    for action_id in batch_action_ids:
                        all_action_ids.add(action_id)

                    all_action_ids_list.extend(batch_action_ids)
                    APPLOGGER.info(
                        f"Successfully generated {len(batch_action_ids)} action IDs for batch {batch_start}-{batch_end}"
                    )
                else:
                    APPLOGGER.error(
                        f"Invalid response format for batch {batch_start}-{batch_end}: expected {len(batch_events)} action IDs, got {len(batch_action_ids) if isinstance(batch_action_ids, list) else 'non-list'}"
                    )
                    fallback_ids = [
                        f"clicked_element_{j}" for j in range(len(batch_events))
                    ]
                    all_action_ids_list.extend(fallback_ids)

            except json.JSONDecodeError as e:
                APPLOGGER.error(
                    f"Failed to parse LLM response as JSON for batch {batch_start}-{batch_end}: {e}"
                )
                fallback_ids = [
                    f"clicked_element_{j}" for j in range(len(batch_events))
                ]
                all_action_ids_list.extend(fallback_ids)

        APPLOGGER.info(
            f"Generated {len(all_action_ids_list)} total action IDs for {len(parsed_events)} events"
        )
        return all_action_ids_list

    except Exception as e:
        APPLOGGER.error(f"Error generating action IDs with LLM: {e}")
        return []


def generate_event_log_from_events(
    parsed_events: List[Dict[str, Any]],
    session_id: str,
    project_id: str = None,
    batch_size: int = 10,
) -> List[Dict[str, Any]]:
    """
    Generate intelligent event logs from parsed events using LLM.

    Args:
        parsed_events: List of parsed events with action, element_type, and attributes
        session_id: The session ID to include in event logs
        project_id: Optional project ID to get existing action IDs for reuse
        batch_size: Maximum number of events to process in a single LLM request

    Returns:
        List of event logs with intelligent action_id and session_id
    """
    if not parsed_events:
        return []

    action_ids = generate_action_id_with_llm(parsed_events, project_id, batch_size)
    APPLOGGER.info(
        f"Returned {len(action_ids)} action IDs and parsed events length is {len(parsed_events)}"
    )

    if action_ids and len(action_ids) == len(parsed_events):
        for i, event in enumerate(parsed_events):
            action_id = action_ids[i]
            parsed_events[i]["action_id"] = action_id

        return parsed_events

    return []
