import os
import logging
from typing import List, Dict, Any, Optional
from pinecone import Pinecone
from openai import OpenAI

APPLOGGER = logging.getLogger(__name__)

def get_relevant_chunks_for_rag(query: str, session_id: Optional[str] = None, top_k: int = 5) -> List[Dict[str, Any]]:
    try:
        api_key = os.getenv("PINECONE_API_KEY")
        if not api_key:
            APPLOGGER.error("PINECONE_API_KEY not found in environment variables")
            return []
        
        pc = Pinecone(api_key=api_key)
        index = pc.Index("session-replays")
        
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        query_response = client.embeddings.create(
            model="text-embedding-3-small",
            input=[query],
            encoding_format="float"
        )
        query_embedding = query_response.data[0].embedding
        
        filter_string = None
        if session_id:
            filter_string = f'session_id = "{session_id}"'
        
        search_response = index.query(
            vector=query_embedding,
            top_k=top_k,
            filter=filter_string,
            include_metadata=True
        )
        
        relevant_chunks = []
        for match in search_response.matches:
            chunk_info = {
                "session_id": match.metadata.get("session_id"),
                "chunk_index": match.metadata.get("chunk_index"),
                "relevance_score": match.score,
                "text": match.metadata.get("text", "")
            }
            relevant_chunks.append(chunk_info)
        
        APPLOGGER.info(f"Retrieved {len(relevant_chunks)} relevant chunks for RAG query: '{query[:50]}...'")
        return relevant_chunks
        
    except Exception as e:
        APPLOGGER.error(f"Error retrieving chunks for RAG: {e}")
        return [] 