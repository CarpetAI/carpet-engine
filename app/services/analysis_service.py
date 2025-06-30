import os
import logging
from typing import Any, Dict, List, Optional
from pydantic import BaseModel
from openai import OpenAI
from pinecone.grpc import PineconeGRPC as Pinecone
from pinecone import ServerlessSpec

from app.services.firebase_service import get_bucket

APPLOGGER = logging.getLogger(__name__)


class ActionLog(BaseModel):
    """Represents a user action extracted from session replay events."""
    timestamp: int
    action: str
    elements_on_screen: List[str] = []


def generate_action_logs(events: List[Dict[str, Any]]) -> List[ActionLog]:
    """
    Convert rrweb events into a filtered, ordered list of ActionLog objects.
    
    Extracts meaningful user interactions:
    - CLICK: on buttons/links or elements with role="button"/type="submit"
    - INPUT: when user finishes typing in form fields
    - SCROLL: at 25%, 50%, 75%, and 100% of document height
    - PAGE_LOAD: when pages load or navigation occurs
    
    Args:
        events: List of rrweb event dictionaries with keys: "type", "timestamp", "data"
        
    Returns:
        List of ActionLog objects representing user actions
    """
    if not events:
        return []

    APPLOGGER.info(f"Processing {len(events)} events in generate_action_logs")
    
    # Count event types for debugging
    event_type_counts = {}
    for ev in events:
        ev_type = ev.get('type')
        event_type_counts[ev_type] = event_type_counts.get(ev_type, 0) + 1
    APPLOGGER.info(f"Event type distribution: {event_type_counts}")
    
    node_map: Dict[int, Dict[str, Any]] = {}
    actions: List[ActionLog] = []
    first_ts: int | None = None
    current_url: str = ""

    def build(node: Dict[str, Any]):
        """Build node map from DOM tree."""
        node_map[node["id"]] = node
        for child in node.get("childNodes") or []:
            build(child)

    def format_time(ms: int) -> str:
        """Convert milliseconds to 'min s' format."""
        if ms < 60000:
            return f"{ms // 1000}s"
        else:
            minutes = ms // 60000
            seconds = (ms % 60000) // 1000
            return f"{minutes}m {seconds}s"

    def get_element_text(nid: int) -> str:
        """Get the text content of an element, including its children."""
        n = node_map.get(nid, {})
        if not n:
            return ""
        
        text = (n.get("textContent") or "").strip()
        if text:
            return text
        
        child_texts = []
        for child in n.get("childNodes") or []:
            child_text = get_element_text(child.get("id"))
            if child_text:
                child_texts.append(child_text)
        
        return " ".join(child_texts).strip()

    def get_button_text(nid: int) -> str:
        """Get meaningful text for a button element."""
        n = node_map.get(nid, {})
        if not n:
            return "unknown"
        
        attrs = n.get("attributes") or {}
        tag = n.get("tagName", "").lower()
        
        # Handle images
        if tag == "img":
            alt_text = attrs.get("alt", "")
            if alt_text:
                return alt_text
            
            src = attrs.get("src", "")
            if src:
                filename = src.split("/")[-1].split(".")[0]
                return f"image: {filename}"
        
        # Check attributes in order of preference
        for attr_name in ["aria-label", "title", "placeholder"]:
            attr_value = attrs.get(attr_name)
            if attr_value:
                if attr_name == "placeholder":
                    return f"placeholder: {attr_value}"
                return attr_value
        
        # Get text content
        text = get_element_text(nid)
        if text and text.strip():
            return text.strip()
        
        # Try child nodes
        child_texts = []
        for child in n.get("childNodes") or []:
            child_node = node_map.get(child.get("id"), {})
            if child_node:
                child_text = child_node.get("textContent", "").strip()
                if child_text:
                    child_texts.append(child_text)
                else:
                    grandchild_texts = []
                    for grandchild in child_node.get("childNodes") or []:
                        grandchild_text = get_element_text(grandchild.get("id"))
                        if grandchild_text:
                            grandchild_texts.append(grandchild_text)
                    if grandchild_texts:
                        child_texts.append(" ".join(grandchild_texts))
        
        if child_texts:
            return " ".join(child_texts).strip()
        
        # Check value attribute
        value = attrs.get("value")
        if value:
            return value
        
        # Check parent for navigation context
        parent = n.get("parentId")
        if parent:
            parent_node = node_map.get(parent, {})
            if parent_node:
                parent_tag = parent_node.get("tagName", "").lower()
                parent_attrs = parent_node.get("attributes") or {}
                
                if parent_tag == "a":
                    href = parent_attrs.get("href", "")
                    if href and href.startswith("http"):
                        parent_text = get_element_text(parent)
                        if parent_text:
                            return parent_text
                
                parent_text = get_element_text(parent)
                if parent_text and len(parent_text) < 100:
                    return parent_text
        
        # Check data attributes
        for attr_name, attr_value in attrs.items():
            if attr_name in ["data-text", "data-label", "data-title"] and attr_value:
                return attr_value
        
        # Fallback
        if tag == "button":
            return "button"
        elif tag == "a":
            href = attrs.get("href", "")
            if href:
                if href.startswith("http") and not href.startswith("/"):
                    return f"Element 'link' with text '{text}' (external)"
                else:
                    return f"Element 'link' with text '{text}'"
            else:
                return f"Element 'link' with text '{text}'"
        else:
            return tag

    def get_input_label(nid: int) -> str:
        """Get meaningful label for an input element."""
        if nid == -1 or nid not in node_map:
            return "unknown"
        n = node_map.get(nid, {})
        attrs = n.get("attributes") or {}
        
        # Check attributes in order of preference
        for attr_name in ["aria-label", "name", "id"]:
            attr_value = attrs.get(attr_name)
            if attr_value:
                return attr_value
        
        input_type = attrs.get("type")
        if input_type:
            return f"{input_type} input"
        
        placeholder = attrs.get("placeholder")
        if placeholder and len(placeholder) < 30:
            return placeholder
        
        # Check data attributes
        for key, value in attrs.items():
            if key.startswith("data-") and value and len(value) < 30:
                return value
        
        # Look for label elements
        parent = n.get("parentId")
        if parent:
            parent_node = node_map.get(parent, {})
            if parent_node:
                for child in parent_node.get("childNodes", []):
                    if child.get("tagName", "").lower() == "label":
                        label_text = get_element_text(child.get("id"))
                        if label_text and len(label_text) < 50:
                            return label_text
        
        return "input field"

    def is_clickable(nid: int) -> bool:
        """Check if an element is clickable."""
        n = node_map.get(nid, {})
        tag = (n.get("tagName") or "").lower()
        if tag in {"button", "a"}:
            return True
        attrs = n.get("attributes") or {}
        return attrs.get("role") == "button" or attrs.get("type") == "submit"

    def get_element_description(nid: int) -> Optional[str]:
        """Get natural language description of an element for LLM consumption."""
        n = node_map.get(nid, {})
        if not n:
            return None
        
        tag = n.get("tagName", "").lower()
        attrs = n.get("attributes") or {}
        
        if tag in ["button", "a"]:
            text = get_button_text(nid)
        elif tag in ["input", "textarea", "select"]:
            text = get_input_label(nid)
        else:
            text = get_element_text(nid)
            if not text or len(text) > 100:
                text = tag
        
        if not text or text == "unknown":
            return None
        
        if tag == "button":
            return f"Element 'button' with text '{text}'"
        elif tag == "a":
            href = attrs.get("href", "")
            if href:
                if href.startswith("http") and not href.startswith("/"):
                    return f"Element 'link' with text '{text}' (external)"
                else:
                    return f"Element 'link' with text '{text}'"
            else:
                return f"Element 'link' with text '{text}'"
        elif tag == "input":
            input_type = attrs.get("type", "text")
            placeholder = attrs.get("placeholder", "")
            if placeholder:
                return f"Element 'input' with text '{text}' and placeholder '{placeholder}'"
            else:
                return f"Element 'input' with text '{text}'"
        elif tag == "textarea":
            placeholder = attrs.get("placeholder", "")
            if placeholder:
                return f"Element 'textarea' with text '{text}' and placeholder '{placeholder}'"
            else:
                return f"Element 'textarea' with text '{text}'"
        elif tag == "select":
            return f"Element 'select' with text '{text}'"
        else:
            return f"Element '{tag}' with text '{text}'"

    def get_elements_on_screen() -> List[str]:
        """Get all interactive elements currently visible on screen."""
        elements = []
        
        for node_id, node in node_map.items():
            tag_name = node.get("tagName", "").lower()
            
            if is_clickable(node_id) or tag_name in ["input", "textarea", "select"]:
                description = get_element_description(node_id)
                if description and description not in elements:
                    elements.append(description)
        
        return elements

    def has_significant_difference(current_elements: List[str], previous_elements: List[str], current_url: str, previous_url: str) -> bool:
        """Determine if there's a significant difference that warrants showing elements_on_screen."""
        if current_url != previous_url:
            return True
        
        if previous_elements:
            count_diff = abs(len(current_elements) - len(previous_elements))
            if count_diff > len(previous_elements) * 0.2:
                return True
        
        if not previous_elements:
            return True
        
        current_set = set(current_elements)
        previous_set = set(previous_elements)
        new_elements = current_set - previous_set
        
        significant_new = [elem for elem in new_elements if any(keyword in elem.lower() for keyword in ['button', 'link', 'input'])]
        if len(significant_new) > 0:
            return True
        
        return False

    def create_pending_page_load_action():
        """Create and return a pending page load action if one exists."""
        nonlocal pending_page_load, pending_page_load_timestamp, previous_elements, previous_url
        if pending_page_load and pending_page_load_timestamp is not None:
            current_elements = get_elements_on_screen()
            should_show_elements = has_significant_difference(current_elements, previous_elements, pending_page_load, previous_url)
            
            action = ActionLog(
                timestamp=pending_page_load_timestamp, 
                action=f"Page loaded: {pending_page_load}", 
                elements_on_screen=current_elements if should_show_elements else ["No significant change from previous state"]
            )
            
            previous_elements = current_elements
            previous_url = pending_page_load
            pending_page_load = None
            pending_page_load_timestamp = None
            
            return action
        return None

    # Build DOM from first snapshot
    snapshot_count = 0
    pending_page_load = None
    pending_page_load_timestamp = None
    current_url = ""
    
    # Find first Meta event for URL
    for ev in events:
        if ev.get("type") == 4:
            url = ev.get("data", {}).get("href", "")
            if url:
                pending_page_load = url
                pending_page_load_timestamp = ev.get("timestamp", 0)
                current_url = url
                break
    
    # Build DOM from first snapshot
    for ev in events:
        if ev.get("type") == 2:  # Full snapshot
            snapshot_count += 1
            snapshot_node = ev.get("data", {}).get("node", {})
            build(snapshot_node)
            break
    
    APPLOGGER.info(f"Found {snapshot_count} snapshot events, node_map size: {len(node_map)}")

    first_ts = min(ev.get("timestamp", 0) for ev in events) if events else 0

    actions: List[ActionLog] = []
    previous_elements = []
    previous_url = ""
    
    # Log initial page load
    if pending_page_load and snapshot_count > 0:
        current_elements = get_elements_on_screen()
        actions.append(ActionLog(
            timestamp=pending_page_load_timestamp - first_ts,
            action=f"Page loaded: {pending_page_load}",
            elements_on_screen=current_elements
        ))
        previous_elements = current_elements
        previous_url = pending_page_load
        pending_page_load = None
        pending_page_load_timestamp = None

    # Process all events in chronological order
    last_scroll_y = 0
    last_scroll_bucket = -1
    incremental_count = 0
    click_count = 0
    input_count = 0
    scroll_count = 0
    page_change_count = 0
    
    # Track input field values
    input_field_values = {}
    input_field_first_seen = {}
    input_field_last_change = {}
    input_field_initial_values = {}
    
    sorted_events = sorted(events, key=lambda x: x.get("timestamp", 0))
    
    for ev in sorted_events:
        ev_type = ev.get("type")
        t = ev.get("timestamp") - first_ts
        
        # Handle Meta events (page loads and navigation)
        if ev_type == 4:
            doc_height = ev.get("data", {}).get("height", 0)
            url = ev.get("data", {}).get("href", "")
            if url and url != current_url:
                node_map.clear()
                current_url = url
                pending_page_load = url
                pending_page_load_timestamp = t
        
        # Handle incremental events
        elif ev_type == 3:
            incremental_count += 1
            d = ev.get("data", {})
            src = d.get("source")
            if src is None:
                continue

            # Rebuild node map on DOM mutations
            if src == 0:  # DOM mutation
                adds = d.get("adds", [])
                for add in adds:
                    node = add.get("node", {})
                    parent_id = add.get("parentId")
                    if node:
                        build(node)
                        
                        if parent_id is not None and parent_id in node_map:
                            parent_node = node_map[parent_id]
                            if "childNodes" not in parent_node:
                                parent_node["childNodes"] = []
                            parent_node["childNodes"].append({"id": node.get("id")})
                
                removes = d.get("removes", [])
                for remove in removes:
                    nid = remove.get("id")
                    if nid is not None and nid in node_map:
                        del node_map[nid]

            # Handle clicks
            elif src == 2:  # MouseInteraction events
                interaction_type = d.get("type")
                nid = d.get("id")
                
                if nid is not None and is_clickable(nid):
                    if interaction_type == 2:  # Click
                        click_count += 1
                        n = node_map.get(nid, {})
                        tag = n.get("tagName", "").lower()
                        attrs = n.get("attributes", {})
                        button_text = get_button_text(nid)
                        
                        if button_text and button_text != "unknown":
                            pending_action = create_pending_page_load_action()
                            if pending_action:
                                actions.append(pending_action)
                            
                            current_elements = get_elements_on_screen()
                            should_show_elements = has_significant_difference(current_elements, previous_elements, current_url, previous_url)
                            
                            if tag == "a":
                                href = attrs.get("href", "")
                                if href and href.startswith("http"):
                                    if button_text.startswith("placeholder: "):
                                        actions.append(ActionLog(timestamp=t, action=f"User clicked {tag} with {button_text}", elements_on_screen=current_elements if should_show_elements else ["No significant change from previous state"]))
                                    else:
                                        actions.append(ActionLog(timestamp=t, action=f"User clicked {tag} with text \"{button_text}\"", elements_on_screen=current_elements if should_show_elements else ["No significant change from previous state"]))
                                else:
                                    if button_text.startswith("placeholder: "):
                                        actions.append(ActionLog(timestamp=t, action=f"User clicked {tag} with {button_text}", elements_on_screen=current_elements if should_show_elements else ["No significant change from previous state"]))
                                    else:
                                        actions.append(ActionLog(timestamp=t, action=f"User clicked {tag} with text \"{button_text}\"", elements_on_screen=current_elements if should_show_elements else ["No significant change from previous state"]))
                            else:
                                if button_text.startswith("placeholder: "):
                                    actions.append(ActionLog(timestamp=t, action=f"User clicked {tag} with {button_text}", elements_on_screen=current_elements if should_show_elements else ["No significant change from previous state"]))
                                else:
                                    actions.append(ActionLog(timestamp=t, action=f"User clicked {tag} with text \"{button_text}\"", elements_on_screen=current_elements if should_show_elements else ["No significant change from previous state"]))
                            
                            if should_show_elements:
                                previous_elements = current_elements

            # Handle input events
            elif src == 5:  # Input event
                input_count += 1
                nid = d.get("id")
                if nid is not None and "text" in d:
                    current_value = d.get("text", "")
                    
                    if nid not in input_field_first_seen:
                        input_field_first_seen[nid] = t
                        input_field_values[nid] = current_value
                        input_field_initial_values[nid] = current_value
                        input_field_last_change[nid] = t
                    else:
                        previous_value = input_field_values.get(nid, "")
                        last_change_time = input_field_last_change.get(nid, 0)
                        initial_value = input_field_initial_values.get(nid, "")
                        
                        if current_value != previous_value:
                            # Filter out programmatic changes
                            if (current_value == initial_value and t - last_change_time < 1000 or
                                t - last_change_time < 50 or
                                current_value == "" and previous_value == initial_value or
                                abs(len(current_value) - len(previous_value)) == 1 and t - last_change_time < 200):
                                pass
                            else:
                                input_label = get_input_label(nid)
                                display_value = current_value
                                
                                if current_value:
                                    pending_action = create_pending_page_load_action()
                                    if pending_action:
                                        actions.append(pending_action)
                                    
                                    current_elements = get_elements_on_screen()
                                    should_show_elements = has_significant_difference(current_elements, previous_elements, current_url, previous_url)
                                    actions.append(ActionLog(timestamp=t, action=f"User typed \"{display_value}\" in the {input_label} field", elements_on_screen=current_elements if should_show_elements else ["No significant change from previous state"]))
                                    if should_show_elements:
                                        previous_elements = current_elements
                                elif previous_value:
                                    pending_action = create_pending_page_load_action()
                                    if pending_action:
                                        actions.append(pending_action)
                                    
                                    current_elements = get_elements_on_screen()
                                    should_show_elements = has_significant_difference(current_elements, previous_elements, current_url, previous_url)
                                    actions.append(ActionLog(timestamp=t, action=f"User cleared the {input_label} field", elements_on_screen=current_elements if should_show_elements else ["No significant change from previous state"]))
                                    if should_show_elements:
                                        previous_elements = current_elements
                        
                        input_field_values[nid] = current_value
                        input_field_last_change[nid] = t

            # Handle scroll events
            elif src == 3 and doc_height:
                scroll_count += 1
                y = d.get("y", 0)
                pct = min(max(y / doc_height, 0.0), 1.0)
                bucket = int(pct * 4)
                if bucket != last_scroll_bucket:
                    last_scroll_bucket = bucket
                    
                    scroll_descriptions = {
                        0: "top of the page (0%)",
                        1: "quarter way down the page (25%)",
                        2: "halfway down the page (50%)",
                        3: "three-quarters down the page (75%)",
                        4: "bottom of the page (100%)"
                    }
                    scroll_desc = scroll_descriptions.get(bucket, f"{bucket*25}% of the page")
                    
                    current_elements = get_elements_on_screen()
                    should_show_elements = has_significant_difference(current_elements, previous_elements, current_url, previous_url)
                    
                    pending_action = create_pending_page_load_action()
                    if pending_action:
                        actions.append(pending_action)
                        current_elements = get_elements_on_screen()
                        should_show_elements = has_significant_difference(current_elements, previous_elements, current_url, previous_url)
                    
                    actions.append(ActionLog(timestamp=t, action=f"User scrolled to {scroll_desc}", elements_on_screen=current_elements if should_show_elements else ["No significant change from previous state"]))
                    if should_show_elements:
                        previous_elements = current_elements
                last_scroll_y = y

    APPLOGGER.info(f"Processed {incremental_count} incremental events: {click_count} clicks, {input_count} inputs, {scroll_count} scrolls, {page_change_count} page changes")
    APPLOGGER.info(f"Generated {len(actions)} action logs")

    # Add final pending page load action
    pending_action = create_pending_page_load_action()
    if pending_action:
        actions.append(pending_action)
        APPLOGGER.info(f"Added final page load action, total actions: {len(actions)}")

    return actions


def process_session_replay(session_id: str, events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Process session replay events through the full pipeline.
    
    Args:
        session_id: The session ID to process
        events: List of rrweb events
        
    Returns:
        Dictionary with processing results and statistics
    """
    try:
        APPLOGGER.info(f"Processing session replay {session_id} with {len(events)} events")
        action_logs = generate_action_logs(events)
        if not action_logs:
            return {
                "session_id": session_id,
                "status": "no_actions",
                "message": "No actions extracted from events",
                "chunks": []
            }
        
        chunks = chunk_session_actions(action_logs, session_id)
        embedded_chunks = embed_chunks(chunks)
        stored_count = store_chunks_in_pinecone(embedded_chunks)
        
        return {
            "session_id": session_id,
            "status": "success",
            "total_events": len(events),
            "total_actions": len(action_logs),
            "total_chunks": len(chunks),
            "stored_chunks": stored_count,
            "chunks": embedded_chunks
        }
        
    except Exception as e:
        APPLOGGER.error(f"Error processing session replay {session_id}: {e}")
        return {
            "session_id": session_id,
            "status": "error",
            "message": str(e),
            "chunks": []
        }


def store_chunks_in_pinecone(chunks: List[Dict[str, Any]], index_name: str = "session-replays") -> int:
    """
    Store embedded chunks in Pinecone vector database.
    
    Args:
        chunks: List of embedded chunk dictionaries
        index_name: Name of the Pinecone index to use
        
    Returns:
        Number of chunks successfully stored
    """
    if not chunks:
        return 0
    
    try:
        api_key = os.getenv("PINECONE_API_KEY")
        if not api_key:
            APPLOGGER.error("PINECONE_API_KEY not found in environment variables")
            return 0
        
        pc = Pinecone(api_key=api_key)
        
        # Create index if it doesn't exist
        if not pc.has_index(index_name):
            APPLOGGER.info(f"Creating Pinecone index: {index_name}")
            pc.create_index(
                name=index_name,
                vector_type="dense",
                dimension=1536, 
                metric="cosine",
                spec=ServerlessSpec(
                    cloud="aws",
                    region="us-east-1"
                ),
                deletion_protection="disabled",
                tags={"environment": "development"}
            )
        
        index = pc.Index(index_name)
        
        # Prepare vectors for upsert
        vectors = []
        for chunk in chunks:
            if "embedding" not in chunk:
                APPLOGGER.warning(f"Chunk {chunk.get('chunk_index', 'unknown')} has no embedding, skipping")
                continue
            
            vector_id = f"{chunk['session_id']}_{chunk['chunk_index']}"
            
            metadata = {
                "session_id": chunk["session_id"],
                "chunk_index": chunk["chunk_index"],
                "action_count": chunk["action_count"],
                "start_time": chunk["start_time"],
                "end_time": chunk["end_time"],
                "duration_ms": chunk["duration_ms"],
                "total_chunks": chunk["total_chunks"],
                "chunk_type": chunk["chunk_type"],
                "text": chunk["text"]
            }
            
            vectors.append({
                "id": vector_id,
                "values": chunk["embedding"],
                "metadata": metadata
            })
        
        if not vectors:
            APPLOGGER.warning("No valid vectors to store")
            return 0
        
        # Upsert vectors in batches
        batch_size = 100
        stored_count = 0
        
        for i in range(0, len(vectors), batch_size):
            batch = vectors[i:i + batch_size]
            try:
                index.upsert(vectors=batch)
                stored_count += len(batch)
                APPLOGGER.info(f"Stored batch {i//batch_size + 1}: {len(batch)} vectors")
            except Exception as e:
                APPLOGGER.error(f"Error storing batch {i//batch_size + 1}: {e}")
        
        APPLOGGER.info(f"Successfully stored {stored_count} chunks in Pinecone")
        return stored_count
        
    except Exception as e:
        APPLOGGER.error(f"Error storing chunks in Pinecone: {e}")
        return 0


def embed_chunks(chunks: List[Dict[str, Any]], model: str = "text-embedding-3-small") -> List[Dict[str, Any]]:
    """
    Embed session replay chunks using OpenAI's embedding model.
    
    Args:
        chunks: List of chunk dictionaries with text content
        model: OpenAI embedding model to use
        
    Returns:
        List of chunks with embeddings added
    """
    if not chunks:
        return []
    
    try:
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        texts = [chunk["text"] for chunk in chunks]
        
        APPLOGGER.info(f"Embedding {len(texts)} chunks using {model}")
        
        response = client.embeddings.create(
            model=model,
            input=texts,
            encoding_format="float"
        )
        
        embedded_chunks = []
        for i, chunk in enumerate(chunks):
            embedded_chunk = chunk.copy()
            embedded_chunk["embedding"] = response.data[i].embedding
            embedded_chunk["embedding_model"] = model
            embedded_chunk["embedding_dimensions"] = len(response.data[i].embedding)
            embedded_chunks.append(embedded_chunk)
        
        APPLOGGER.info(f"Successfully embedded {len(embedded_chunks)} chunks")
        return embedded_chunks
        
    except Exception as e:
        APPLOGGER.error(f"Error embedding chunks: {e}")
        return chunks


def chunk_session_actions(action_logs: List[ActionLog], session_id: str, max_chunk_size: int = 500, max_actions_per_chunk: int = 10) -> List[Dict[str, Any]]:
    """
    Chunk session action logs into semantic units for processing.
    
    Args:
        action_logs: List of action log objects to chunk
        session_id: The session ID for metadata
        max_chunk_size: Maximum tokens per chunk (approximate)
        max_actions_per_chunk: Maximum actions per chunk
        
    Returns:
        List of chunk dictionaries with metadata ready for embedding
    """
    if not action_logs:
        return []
    
    chunks = []
    current_chunk_actions = []
    current_chunk_size = 0
    
    for action in action_logs:
        action_text = f"{action.action}"
        if action.elements_on_screen:
            action_text += f" Elements: {', '.join(action.elements_on_screen)}"
        
        action_tokens = len(action_text) // 4
        
        would_exceed_size = current_chunk_size + action_tokens > max_chunk_size
        would_exceed_actions = len(current_chunk_actions) >= max_actions_per_chunk
        
        if (would_exceed_size or would_exceed_actions) and current_chunk_actions:
            chunk = create_chunk_from_actions(current_chunk_actions, session_id, len(chunks))
            chunks.append(chunk)
            
            current_chunk_actions = []
            current_chunk_size = 0
        
        current_chunk_actions.append(action)
        current_chunk_size += action_tokens
    
    if current_chunk_actions:
        chunk = create_chunk_from_actions(current_chunk_actions, session_id, len(chunks))
        chunks.append(chunk)
    
    for chunk in chunks:
        chunk["total_chunks"] = len(chunks)
        chunk["chunk_type"] = "session_replay"
    
    APPLOGGER.info(f"Created {len(chunks)} chunks for session {session_id}")
    return chunks


def create_chunk_from_actions(actions: List[ActionLog], session_id: str, chunk_index: int) -> Dict[str, Any]:
    """
    Create a chunk dictionary from a list of actions.
    
    Args:
        actions: List of actions to include in this chunk
        session_id: The session ID for metadata
        chunk_index: The index of this chunk
        
    Returns:
        Chunk dictionary with text and metadata
    """
    lines = []
    for i, action in enumerate(actions, 1):
        timestamp_str = format_timestamp(action.timestamp)
        action_line = f"{i}. [{timestamp_str}] {action.action}"
        lines.append(action_line)
        
        if action.elements_on_screen and action.elements_on_screen != ["No significant change from previous state"]:
            elements_text = "; ".join(action.elements_on_screen)
            lines.append(f"   Elements on screen: {elements_text}")
    
    chunk_text = "\n".join(lines)
    
    start_time = actions[0].timestamp if actions else 0
    end_time = actions[-1].timestamp if actions else 0
    duration = end_time - start_time
    
    return {
        "session_id": session_id,
        "chunk_index": chunk_index,
        "text": chunk_text,
        "action_count": len(actions),
        "start_time": start_time,
        "end_time": end_time,
        "duration_ms": duration,
        "estimated_tokens": len(chunk_text) // 4,
        "actions": [
            {
                "timestamp": action.timestamp,
                "action": action.action,
                "elements_on_screen": action.elements_on_screen
            }
            for action in actions
        ]
    }


def format_timestamp(ms: int) -> str:
    """Convert milliseconds to human-readable timestamp."""
    if ms < 60000:
        return f"{ms // 1000}s"
    elif ms < 3600000:
        minutes = ms // 60000
        seconds = (ms % 60000) // 1000
        return f"{minutes}m {seconds}s"
    else:
        hours = ms // 3600000
        minutes = (ms % 3600000) // 60000
        return f"{hours}h {minutes}m"


