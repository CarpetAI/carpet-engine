import logging
from typing import Dict, Any, List

APPLOGGER = logging.getLogger(__name__)


def clean_consecutive_input_events(parsed_events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not parsed_events:
        return []
    
    cleaned_events = []
    i = 0
    
    while i < len(parsed_events):
        current_event = parsed_events[i]
        
        if current_event.get("element_type") != "input":
            cleaned_events.append(current_event)
            i += 1
            continue
        
        input_sequence_end = i
        while (input_sequence_end < len(parsed_events) and 
               parsed_events[input_sequence_end].get("element_type") == "input"):
            input_sequence_end += 1
        
        if input_sequence_end > i:
            last_input_event = parsed_events[input_sequence_end - 1]
            cleaned_events.append(last_input_event)
        
        i = input_sequence_end
    
    return cleaned_events


def clean_consecutive_scroll_events(parsed_events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not parsed_events:
        return []
    
    cleaned_events = []
    i = 0
    
    while i < len(parsed_events):
        current_event = parsed_events[i]
        
        if current_event.get("element_type") != "scroll":
            cleaned_events.append(current_event)
            i += 1
            continue
        
        scroll_sequence_end = i
        while (scroll_sequence_end < len(parsed_events) and 
               parsed_events[scroll_sequence_end].get("element_type") == "scroll"):
            scroll_sequence_end += 1
        
        if scroll_sequence_end > i:
            last_scroll_event = parsed_events[scroll_sequence_end - 1]
            cleaned_events.append(last_scroll_event)
        
        i = scroll_sequence_end
    
    return cleaned_events


def clean_events(parsed_events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    try:
        cleaned_events = clean_consecutive_input_events(parsed_events)
        cleaned_events = clean_consecutive_scroll_events(cleaned_events)
        return cleaned_events
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Error cleaning events: {e}")
        return parsed_events