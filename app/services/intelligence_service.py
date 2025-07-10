import os
import logging
from typing import Dict, Any, List
from openai import OpenAI
from app.services.firestore_service import get_existing_action_ids

APPLOGGER = logging.getLogger(__name__)


def clean_consecutive_input_events(parsed_events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Remove consecutive input events, keeping only the last one in each sequence.
    
    Args:
        parsed_events: List of parsed events
        
    Returns:
        List of events with consecutive input events cleaned up
    """
    if not parsed_events:
        return []
    
    cleaned_events = []
    i = 0
    
    while i < len(parsed_events):
        current_event = parsed_events[i]
        
        if current_event.get("action") != "input":
            cleaned_events.append(current_event)
            i += 1
            continue
        
        input_sequence_end = i
        while (input_sequence_end < len(parsed_events) and 
               parsed_events[input_sequence_end].get("action") == "input"):
            input_sequence_end += 1
        
        if input_sequence_end > i:
            last_input_event = parsed_events[input_sequence_end - 1]
            cleaned_events.append(last_input_event)
            APPLOGGER.info(f"Cleaned up {input_sequence_end - i} consecutive input events, keeping last one")
        
        i = input_sequence_end
    
    APPLOGGER.info(f"Cleaned events: {len(parsed_events)} -> {len(cleaned_events)}")
    return cleaned_events


def clean_consecutive_scroll_events(parsed_events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Remove consecutive scroll events, keeping only the last one in each sequence.
    
    Args:
        parsed_events: List of parsed events
        
    Returns:
        List of events with consecutive scroll events cleaned up
    """
    if not parsed_events:
        return []
    
    cleaned_events = []
    i = 0
    
    while i < len(parsed_events):
        current_event = parsed_events[i]
        
        if current_event.get("action") != "scrolled":
            cleaned_events.append(current_event)
            i += 1
            continue
        
        scroll_sequence_end = i
        while (scroll_sequence_end < len(parsed_events) and 
               parsed_events[scroll_sequence_end].get("action") == "scrolled"):
            scroll_sequence_end += 1
        
        if scroll_sequence_end > i:
            last_scroll_event = parsed_events[scroll_sequence_end - 1]
            cleaned_events.append(last_scroll_event)
            APPLOGGER.info(f"Cleaned up {scroll_sequence_end - i} consecutive scroll events, keeping last one")
        
        i = scroll_sequence_end
    
    APPLOGGER.info(f"Cleaned scroll events: {len(parsed_events)} -> {len(cleaned_events)}")
    return cleaned_events


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
            - For page load, try to determine the page type by the url or title
            - For input events, use the attributes to determine the input type
            
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

    cleaned_events = clean_consecutive_input_events(parsed_events)
    cleaned_events = clean_consecutive_scroll_events(cleaned_events)
    
    action_ids = generate_action_id_with_llm(cleaned_events, project_id, batch_size)
    APPLOGGER.info(
        f"Returned {len(action_ids)} action IDs and cleaned events length is {len(cleaned_events)}"
    )

    if action_ids and len(action_ids) == len(cleaned_events):
        for i, event in enumerate(cleaned_events):
            action_id = action_ids[i]
            cleaned_events[i]["action_id"] = action_id

        return cleaned_events

    return []
