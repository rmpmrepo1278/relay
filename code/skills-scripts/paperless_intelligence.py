import os
import httpx
import json

# Configuration
PAPERLESS_URL = os.environ.get("PAPERLESS_URL", "http://192.168.29.10:8000")
PAPERLESS_TOKEN = os.environ.get("PAPERLESS_API_TOKEN")
LOCAL_LLM_URL = "http://localhost:8081/v1/chat/completions"

def query_paperless(query: str) -> str:
    """
    Searches Paperless documents and uses local LLM to answer questions about them.
    Keeps all document analysis 100% private and local.
    """
    if not PAPERLESS_TOKEN:
        return "Error: PAPERLESS_API_TOKEN not set in environment."

    headers = {"Authorization": f"Token {PAPERLESS_TOKEN}"}
    
    # 1. Search Paperless for relevant documents
    try:
        search_url = f"{PAPERLESS_URL}/api/documents/?query={query}"
        resp = httpx.get(search_url, headers=headers, timeout=10.0)
        resp.raise_for_status()
        docs = resp.json().get("results", [])
        
        if not docs:
            return "No matching documents found in Paperless."
            
        # 2. Extract content from the top 3 documents
        context = ""
        for doc in docs[:3]:
            context += f"--- Document: {doc['title']} ---\n{doc['content']}\n\n"
            
        # 3. Use Local LLM to analyze the context
        prompt = f"""
        You are a private intelligence assistant. Analyze the following document excerpts to answer the user's question.
        User Question: "{query}"
        
        Context:
        {context[:15000]}  # Cap context
        
        Answer based ONLY on the provided context. If the answer is not in the context, say so.
        """
        
        llm_resp = httpx.post(
            LOCAL_LLM_URL,
            json={
                "model": "local",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1
            },
            timeout=60.0
        )
        
        if llm_resp.status_code == 200:
            return llm_resp.json()["choices"][0]["message"]["content"]
        else:
            return f"Local LLM Error: {llm_resp.status_code}"
            
    except Exception as e:
        return f"Error in Paperless Intelligence: {str(e)}"
