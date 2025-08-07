import os
import logging
from typing import Dict, Any, List
from openai import OpenAI
from app.services.firestore_service import get_existing_action_ids, estimate_tokens
from app.utils import clean_events
import json

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
            - PREFER EXISTING ACTION IDs when they match the user's intent
            - Only create new action IDs when there's no suitable existing match
            - Use semantic, logical descriptions instead of technical details
            - Focus on what the user is trying to accomplish
            - Be specific but concise. Use the attributes for context.
            - Use lowercase with underscores for action_id
            - NEVER use generic element types like "button", "span", "div", "h1", "h2", etc. in action IDs
            - Instead, describe what the element does or contains (e.g., "clicked_submit_button", "clicked_nav_link", "clicked_product_title")
            - Look at text content, aria-labels, titles, and other attributes to understand purpose
            - Examples: "clicked_view_photos", "clicked_submit_form", "clicked_navigation_menu", "clicked_add_to_cart", "clicked_user_profile"
            - For page load, try to determine the page type by the url or title. Please be specific on what type of page loaded.
            - Only include the URL in the action_id if the page type is completely unclear or unknown
            - Examples: "page_loaded_home", "page_loaded_product_details", "page_loaded_checkout", "page_loaded_user_profile"
            - Only use "page_loaded_[url]" when you cannot determine what type of page it is
            
            Return a JSON array of action_id strings only, in the same order as the events.
            """

            system_message = {
                "role": "system",
                "content": "You are an expert at analyzing user interactions and generating meaningful action descriptions. You prioritize reusing existing action IDs when they match the user's intent.",
            }
            
            response_format_config = {
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
            }

            response = client.chat.completions.create(
                model="gpt-4.1",
                messages=[system_message, {"role": "user", "content": prompt}],
                response_format=response_format_config,
                temperature=0.3,
                max_tokens=1000,
            )

            result = response.choices[0].message.content

            max_retries = 3
            retry_count = 0
            batch_action_ids = None

            while retry_count < max_retries:
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
                        break
                    else:
                        APPLOGGER.error(
                            f"Invalid response format for batch {batch_start}-{batch_end}: expected {len(batch_events)} action IDs, got {len(batch_action_ids) if isinstance(batch_action_ids, list) else 'non-list'}"
                        )
                        retry_count += 1
                        if retry_count < max_retries:
                            response = client.chat.completions.create(
                                model="gpt-4.1",
                                messages=[system_message, {"role": "user", "content": prompt}],
                                response_format=response_format_config,
                                temperature=0.3,
                                max_tokens=1000,
                            )
                            result = response.choices[0].message.content

                except json.JSONDecodeError as e:
                    APPLOGGER.error(
                        f"Failed to parse LLM response as JSON for batch {batch_start}-{batch_end}: {e}"
                    )
                    retry_count += 1
                    if retry_count < max_retries:
                        response = client.chat.completions.create(
                            model="gpt-4.1",
                            messages=[system_message, {"role": "user", "content": prompt}],
                            response_format=response_format_config,
                            temperature=0.3,
                            max_tokens=1000,
                        )
                        result = response.choices[0].message.content

            if retry_count >= max_retries or not batch_action_ids:
                fallback_ids = [
                    f"clicked_unknown" for j in range(len(batch_events))
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
    cleaned_events: List[Dict[str, Any]],
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
    if not cleaned_events:
        return []
    
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


def generate_project_insights(sessions_data: Dict[str, List[Dict]], project_id: str, max_tokens: int = 8000) -> List[Dict[str, Any]]:
    try:
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        
        sessions_to_include = {}
        current_tokens = 0
        
        for session_id, events in sessions_data.items():
            session_json = json.dumps(events)
            session_tokens = estimate_tokens(session_json)
            
            if max_tokens is not None and current_tokens + session_tokens > max_tokens:
                APPLOGGER.info(f"Token limit reached ({current_tokens}/{max_tokens}). Stopping at {len(sessions_to_include)} sessions.")
                break
            
            sessions_to_include[session_id] = events
            current_tokens += session_tokens
        
        if not sessions_to_include:
            APPLOGGER.warning("No sessions could be included within token limit")
            return []
        
        sessions_json = json.dumps(sessions_to_include, indent=2)
        
        prompt = f"""
        Analyze this user session data and generate actionable insights that would help the product team know what to build next.
        
        Examples of insights:
        - User behavior patterns that suggest feature opportunities
        - Pain points or friction in the user journey
        - Underutilized features that could be improved
        - User needs that aren't being met
        - Opportunities for new features or improvements
        - Any other insights that would help the product team know what to build next
        
        
        Session Data: {sessions_json}
        
        Make insights actionable and specific to help guide product development decisions.
        """
    
        response = client.chat.completions.create(
            model="o3-mini",
            reasoning_effort="medium",
            messages=[
                {
                    "role": "system",
                    "content": "You are an expert product analyst who helps teams understand user behavior and identify opportunities for product improvements. You provide actionable insights based on user session data.",
                },
                {"role": "user", "content": prompt},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "insights_array",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "insights": {
                                "type": "array",
                                "description": "List of insight objects.",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "title": {"type": "string", "minLength": 1},
                                        "description": {"type": "string", "minLength": 1},
                                    },
                                    "required": ["title", "description"],
                                    "additionalProperties": False,
                                },
                                "maxItems": 3
                            }
                        },
                        "required": ["insights"],
                        "additionalProperties": False,
                    },
                },
            },
            max_completion_tokens=1500,
        )
        
        result = response.choices[0].message.content
        
        try:
            insights_data = json.loads(result)
            insights = insights_data.get("insights", [])
            
            APPLOGGER.info(f"Generated {len(insights)} insights for project {project_id} using {len(sessions_to_include)} sessions ({current_tokens} tokens)")
            return insights
            
        except json.JSONDecodeError as e:
            APPLOGGER.error(f"Failed to parse LLM response as JSON: {e}")
            return []
            
    except Exception as e:
        APPLOGGER.error(f"Error generating project insights: {e}")
        return []
