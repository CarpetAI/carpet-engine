import logging
from typing import Any, Dict, List
from pydantic import BaseModel

from app.services.firestore_service import save_action_events, save_action_id_batch
from app.services.intelligence_service import generate_event_log_from_events

APPLOGGER = logging.getLogger(__name__)


class ActionObject(BaseModel):
    action: str
    element_type: str
    metadata: Dict[str, Any]
    id: str


def build_node_map(node, node_map=None):
    if node_map is None:
        node_map = {}

    if "id" in node:
        node_map[node["id"]] = node

    if "childNodes" in node:
        for child in node["childNodes"]:
            build_node_map(child, node_map)

    return node_map


def extract_text_content(node: Dict[str, Any]) -> str:
    text_parts = []

    if "textContent" in node and node["textContent"]:
        text_parts.append(node["textContent"].strip())

    if "childNodes" in node:
        for child in node["childNodes"]:
            child_text = extract_text_content(child)
            if child_text:
                text_parts.append(child_text)

    full_text = " ".join(text_parts)
    cleaned_text = " ".join(full_text.split())

    return cleaned_text


def extract_attributes(node: Dict[str, Any]) -> Dict[str, str]:
    attributes = node.get("attributes", {})

    semantic_attrs = {}
    semantic_keys = ["id", "placeholder", "title", "alt", "aria-label", "href"]

    for key, value in attributes.items():
        if key in semantic_keys and value:
            semantic_attrs[key] = value

    text_content = extract_text_content(node)
    if text_content:
        semantic_attrs["text"] = text_content

    return semantic_attrs


def detect_action(event: Dict[str, Any]) -> str:
    data = event.get("data")
    if data.get("source") == 2 and data.get("type") == 2:  # Click event
        return "clicked"
    elif data.get("source") == 5:  # Input event
        return "input"
    elif data.get("source") == 3:  # Scroll event
        return "scrolled"
    return ""


def get_scroll_direction(
    current_x: int, current_y: int, last_x: int, last_y: int
) -> str:
    x_change = current_x - last_x
    y_change = current_y - last_y

    if abs(x_change) > abs(y_change):
        if x_change > 0:
            return "right"
        elif x_change < 0:
            return "left"
        else:
            return ""
    else:
        if y_change > 0:
            return "down"
        elif y_change < 0:
            return "up"
        else:
            return ""


def should_skip_click(node: Dict[str, Any], attributes: Dict[str, str]) -> bool:
    if not node:
        return True

    tag_name = node.get("tagName", "").lower()
    generic_tags = [
        "div",
        "span",
        "section",
        "article",
        "main",
        "aside",
        "header",
        "footer",
    ]

    if tag_name in generic_tags:
        has_text = "text" in attributes and attributes["text"]
        has_meaningful_attrs = any(
            key in attributes
            for key in ["id", "placeholder", "title", "alt", "aria-label", "href"]
        )

        return not (has_text or has_meaningful_attrs)

    return False


def clean_text(text: str) -> str:
    """Clean text to create a valid action ID by removing special characters and emojis"""
    import re

    # Remove emojis and special characters, keep only alphanumeric and spaces
    cleaned = re.sub(r"[^\w\s]", "", text)
    # Trim whitespace, replace spaces with underscores and convert to lowercase
    return cleaned.strip().replace(" ", "_").lower()


def clean_url(url: str) -> str:
    """Extract domain and first endpoint from URL"""
    from urllib.parse import urlparse

    try:
        parsed = urlparse(url)
        domain = parsed.netloc
        path = parsed.path.strip("/")

        if not domain:
            return "unknown"

        if not path:
            return domain

        first_endpoint = path.split("/")[0]
        return f"{domain}/{first_endpoint}"

    except Exception:
        return "unknown"


def generate_action_string(action_object: ActionObject) -> str:
    action = action_object.action
    element = action_object.element_type
    id = action_object.id

    if action == "input":
        input_value = action_object.metadata.get("input_value", "")
        return f"User input '{input_value}' on {element} with id {id}"
    elif action == "scrolled":
        scroll_direction = action_object.metadata.get("scroll_direction", "unknown")
        return f"User scrolled {scroll_direction}"
    elif action == "clicked":
        text = action_object.metadata.get("text", "")
        if text:
            return f"User clicked on {element} with text '{text}' and id {id}"
        else:
            return f"User clicked on {element} with id {id}"


def generate_activity_events(
    events: List[Dict[str, Any]], session_id: str, project_id: str, batch_size: int = 10
):
    """
    Generate activity logs from rrweb events.

    Args:
        events: List of rrweb event dictionaries with keys: "type", "timestamp", "data"
        session_id: The session ID to include in event logs
        project_id: The project ID to get existing action IDs for reuse
        batch_size: Maximum number of events to process in a single LLM request (default: 10)
    """
    node_map = {}
    parsed_events = []
    last_scroll_y = 0
    last_scroll_x = 0
    for event in events:
        if event.get("type") == 2:
            node_map = build_node_map(event["data"]["node"])

        elif event.get("type") == 3:
            data = event.get("data")
            id = data.get("id")

            action = detect_action(event)
            if action == "clicked":
                node = node_map.get(id)
                if node:
                    attributes = extract_attributes(node)
                    parsed_events.append(
                        {
                            "id": id,
                            "action": action,
                            "element_type": node.get("tagName", "") if node else "",
                            "attributes": attributes,
                            "timestamp": event.get("timestamp"),
                        }
                    )
            elif action == "input":
                node = node_map.get(id)
                if node:
                    attributes = extract_attributes(node)
                    input_value = data.get('text', '')
                    attributes["input_value"] = input_value
                    parsed_events.append(
                        {
                            "id": id,
                            "action": action,
                            "element_type": node.get("tagName", "") if node else "",
                            "attributes": attributes,
                            "timestamp": event.get("timestamp"),
                        }
                    )
            elif action == "scrolled":
                x = data.get('x', 0)
                y = data.get('y', 0)
                scroll_direction = get_scroll_direction(x, y, last_scroll_x, last_scroll_y)
                last_scroll_x = x
                last_scroll_y = y
                if scroll_direction:
                    parsed_events.append(
                        {
                            "id": id,
                            "action": action,
                            "element_type": "scroll",
                            "attributes": {"scroll_direction": scroll_direction},
                            "timestamp": event.get("timestamp"),
                        }
                    )
        elif event.get("type") == 4:
            data = event.get("data", {})
            page_url = data.get("href", "Unknown")
            title = data.get("title", "Unknown")
            action_string = f"Page loaded: {page_url}"
            parsed_events.append(
                {
                    "id": "page_load",
                    "action": "page_loaded",
                    "element_type": "page",
                    "attributes": {"url": page_url, "title": title},
                    "timestamp": event.get("timestamp"),
                    "action_string": action_string,
                }
            )

    event_logs = generate_event_log_from_events(parsed_events, session_id, project_id, batch_size)

    if event_logs:
        action_id_counter = {}
        action_logs = []

        for event_log in event_logs:
            action_id = event_log.get("action_id")
            if action_id:
                action_id_counter[action_id] = action_id_counter.get(action_id, 0) + 1

                action_string = event_log.get("action_string")
                if not action_string:
                    action_string = generate_action_string(
                        ActionObject(
                            action=event_log.get("action"),
                            element_type=event_log.get("element_type"),
                            id=str(event_log.get("id")),
                            metadata=event_log.get("attributes"),
                        )
                    )
                action_logs.append(
                    {
                        "action_id": action_id,
                        "action_string": action_string,
                        "session_id": session_id,
                        "element_type": event_log.get("element_type"),
                        "attributes": event_log.get("attributes"),
                        "timestamp": event_log.get("timestamp"),
                    }
                )

        if action_id_counter:
            save_action_id_batch(action_id_counter, project_id)
           
        save_action_events(action_logs, project_id)

    return event_logs


# def process_session_replay(session_id: str, events: List[Dict[str, Any]]) -> Dict[str, Any]:
#     """
#     Process session replay events through the full pipeline.

#     Args:
#         session_id: The session ID to process
#         events: List of rrweb events

#     Returns:
#         Dictionary with processing results and statistics
#     """
#     try:
#         APPLOGGER.info(f"Processing session replay {session_id} with {len(events)} events")
#         action_logs = generate_action_logs(events)
#         if not action_logs:
#             return {
#                 "session_id": session_id,
#                 "status": "no_actions",
#                 "message": "No actions extracted from events",
#                 "chunks": []
#             }

#         chunks = chunk_session_actions(action_logs, session_id)
#         embedded_chunks = embed_chunks(chunks)
#         stored_count = store_chunks_in_pinecone(embedded_chunks)

#         return {
#             "session_id": session_id,
#             "status": "success",
#             "total_events": len(events),
#             "total_actions": len(action_logs),
#             "total_chunks": len(chunks),
#             "stored_chunks": stored_count,
#             "chunks": embedded_chunks
#         }

#     except Exception as e:
#         APPLOGGER.error(f"Error processing session replay {session_id}: {e}")
#         return {
#             "session_id": session_id,
#             "status": "error",
#             "message": str(e),
#             "chunks": []
#         }


# def store_chunks_in_pinecone(chunks: List[Dict[str, Any]], index_name: str = "session-replays") -> int:
#     """
#     Store embedded chunks in Pinecone vector database.

#     Args:
#         chunks: List of embedded chunk dictionaries
#         index_name: Name of the Pinecone index to use

#     Returns:
#         Number of chunks successfully stored
#     """
#     if not chunks:
#         return 0

#     try:
#         api_key = os.getenv("PINECONE_API_KEY")
#         if not api_key:
#             APPLOGGER.error("PINECONE_API_KEY not found in environment variables")
#             return 0

#         pc = Pinecone(api_key=api_key)

#         # Create index if it doesn't exist
#         if not pc.has_index(index_name):
#             APPLOGGER.info(f"Creating Pinecone index: {index_name}")
#             pc.create_index(
#                 name=index_name,
#                 vector_type="dense",
#                 dimension=1536,
#                 metric="cosine",
#                 spec=ServerlessSpec(
#                     cloud="aws",
#                     region="us-east-1"
#                 ),
#                 deletion_protection="disabled",
#                 tags={"environment": "development"}
#             )

#         index = pc.Index(index_name)

#         # Prepare vectors for upsert
#         vectors = []
#         for chunk in chunks:
#             if "embedding" not in chunk:
#                 APPLOGGER.warning(f"Chunk {chunk.get('chunk_index', 'unknown')} has no embedding, skipping")
#                 continue

#             vector_id = f"{chunk['session_id']}_{chunk['chunk_index']}"

#             metadata = {
#                 "session_id": chunk["session_id"],
#                 "chunk_index": chunk["chunk_index"],
#                 "action_count": chunk["action_count"],
#                 "start_time": chunk["start_time"],
#                 "end_time": chunk["end_time"],
#                 "duration_ms": chunk["duration_ms"],
#                 "total_chunks": chunk["total_chunks"],
#                 "chunk_type": chunk["chunk_type"],
#                 "text": chunk["text"]
#             }

#             vectors.append({
#                 "id": vector_id,
#                 "values": chunk["embedding"],
#                 "metadata": metadata
#             })

#         if not vectors:
#             APPLOGGER.warning("No valid vectors to store")
#             return 0

#         # Upsert vectors in batches
#         batch_size = 100
#         stored_count = 0

#         for i in range(0, len(vectors), batch_size):
#             batch = vectors[i:i + batch_size]
#             try:
#                 index.upsert(vectors=batch)
#                 stored_count += len(batch)
#                 APPLOGGER.info(f"Stored batch {i//batch_size + 1}: {len(batch)} vectors")
#             except Exception as e:
#                 APPLOGGER.error(f"Error storing batch {i//batch_size + 1}: {e}")

#         APPLOGGER.info(f"Successfully stored {stored_count} chunks in Pinecone")
#         return stored_count

#     except Exception as e:
#         APPLOGGER.error(f"Error storing chunks in Pinecone: {e}")
#         return 0


# def embed_chunks(chunks: List[Dict[str, Any]], model: str = "text-embedding-3-small") -> List[Dict[str, Any]]:
#     """
#     Embed session replay chunks using OpenAI's embedding model.

#     Args:
#         chunks: List of chunk dictionaries with text content
#         model: OpenAI embedding model to use

#     Returns:
#         List of chunks with embeddings added
#     """
#     if not chunks:
#         return []

#     try:
#         client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
#         texts = [chunk["text"] for chunk in chunks]

#         APPLOGGER.info(f"Embedding {len(texts)} chunks using {model}")

#         response = client.embeddings.create(
#             model=model,
#             input=texts,
#             encoding_format="float"
#         )

#         embedded_chunks = []
#         for i, chunk in enumerate(chunks):
#             embedded_chunk = chunk.copy()
#             embedded_chunk["embedding"] = response.data[i].embedding
#             embedded_chunk["embedding_model"] = model
#             embedded_chunk["embedding_dimensions"] = len(response.data[i].embedding)
#             embedded_chunks.append(embedded_chunk)

#         APPLOGGER.info(f"Successfully embedded {len(embedded_chunks)} chunks")
#         return embedded_chunks

#     except Exception as e:
#         APPLOGGER.error(f"Error embedding chunks: {e}")
#         return chunks


# def chunk_session_actions(action_logs: List[ActionLog], session_id: str, max_chunk_size: int = 500, max_actions_per_chunk: int = 10) -> List[Dict[str, Any]]:
#     """
#     Chunk session action logs into semantic units for processing.

#     Args:
#         action_logs: List of action log objects to chunk
#         session_id: The session ID for metadata
#         max_chunk_size: Maximum tokens per chunk (approximate)
#         max_actions_per_chunk: Maximum actions per chunk

#     Returns:
#         List of chunk dictionaries with metadata ready for embedding
#     """
#     if not action_logs:
#         return []

#     chunks = []
#     current_chunk_actions = []
#     current_chunk_size = 0

#     for action in action_logs:
#         action_text = f"{action.action}"
#         if action.elements_on_screen:
#             action_text += f" Elements: {', '.join(action.elements_on_screen)}"

#         action_tokens = len(action_text) // 4

#         would_exceed_size = current_chunk_size + action_tokens > max_chunk_size
#         would_exceed_actions = len(current_chunk_actions) >= max_actions_per_chunk

#         if (would_exceed_size or would_exceed_actions) and current_chunk_actions:
#             chunk = create_chunk_from_actions(current_chunk_actions, session_id, len(chunks))
#             chunks.append(chunk)

#             current_chunk_actions = []
#             current_chunk_size = 0

#         current_chunk_actions.append(action)
#         current_chunk_size += action_tokens

#     if current_chunk_actions:
#         chunk = create_chunk_from_actions(current_chunk_actions, session_id, len(chunks))
#         chunks.append(chunk)

#     for chunk in chunks:
#         chunk["total_chunks"] = len(chunks)
#         chunk["chunk_type"] = "session_replay"

#     APPLOGGER.info(f"Created {len(chunks)} chunks for session {session_id}")
#     return chunks


# def create_chunk_from_actions(actions: List[ActionLog], session_id: str, chunk_index: int) -> Dict[str, Any]:
#     """
#     Create a chunk dictionary from a list of actions.

#     Args:
#         actions: List of actions to include in this chunk
#         session_id: The session ID for metadata
#         chunk_index: The index of this chunk

#     Returns:
#         Chunk dictionary with text and metadata
#     """
#     lines = []
#     for i, action in enumerate(actions, 1):
#         timestamp_str = format_timestamp(action.timestamp)
#         action_line = f"{i}. [{timestamp_str}] {action.action}"
#         lines.append(action_line)

#         if action.elements_on_screen and action.elements_on_screen != ["No significant change from previous state"]:
#             elements_text = "; ".join(action.elements_on_screen)
#             lines.append(f"   Elements on screen: {elements_text}")

#     chunk_text = "\n".join(lines)

#     start_time = actions[0].timestamp if actions else 0
#     end_time = actions[-1].timestamp if actions else 0
#     duration = end_time - start_time

#     return {
#         "session_id": session_id,
#         "chunk_index": chunk_index,
#         "text": chunk_text,
#         "action_count": len(actions),
#         "start_time": start_time,
#         "end_time": end_time,
#         "duration_ms": duration,
#         "estimated_tokens": len(chunk_text) // 4,
#         "actions": [
#             {
#                 "timestamp": action.timestamp,
#                 "action": action.action,
#                 "elements_on_screen": action.elements_on_screen
#             }
#             for action in actions
#         ]
#     }


# def format_timestamp(ms: int) -> str:
#     """Convert milliseconds to human-readable timestamp."""
#     if ms < 60000:
#         return f"{ms // 1000}s"
#     elif ms < 3600000:
#         minutes = ms // 60000
#         seconds = (ms % 60000) // 1000
#         return f"{minutes}m {seconds}s"
#     else:
#         hours = ms // 3600000
#         minutes = (ms % 3600000) // 60000
#         return f"{hours}h {minutes}m"
