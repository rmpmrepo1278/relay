import os
import httpx
import argparse

PAPERLESS_URL = os.environ.get("PAPERLESS_URL", "http://127.0.0.1:8000")
PAPERLESS_TOKEN = os.environ.get("PAPERLESS_API_TOKEN")

def query_paperless(query):
    if not PAPERLESS_TOKEN:
        return "Error: PAPERLESS_API_TOKEN not set."
    headers = {"Authorization": f"Token {PAPERLESS_TOKEN}"}
    try:
        search_url = f"{PAPERLESS_URL}/api/documents/?query={query}&limit=5"
        resp = httpx.get(search_url, headers=headers, timeout=10.0)
        resp.raise_for_status()
        docs = resp.json().get("results", [])
        if not docs:
            return "No matching documents found in Paperless."
        out = [f"Found {len(docs)} documents:"]
        for doc in docs[:5]:
            title = doc.get("title", "Untitled")
            doc_id = doc.get("id", "?")
            out.append(f"  {title} (ID: {doc_id})")
        return "\n".join(out)
    except Exception as e:
        return f"Error: {e}"

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", required=True)
    args = parser.parse_args()
    print(query_paperless(args.query))
