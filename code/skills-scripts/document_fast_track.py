import os
import glob
import logging

# Target Folders from Homelab Map
VAULT_PATHS = {
    'personal': '/mnt/usb/files/paperless-consume/personal/',
    'career': '/mnt/usb/files/paperless-consume/ebooks/career/',
    'buddhism': '/mnt/usb/files/paperless-consume/ebooks/buddhism/',
    'ids': '/mnt/usb/files/paperless-consume/ids/'
}

def search_documents(query: str) -> list:
    """
    Fast, targeted search across homelab document folders.
    Returns a list of matching file paths.
    """
    query_lower = query.lower()
    matches = []
    
    # 1. Check if the query matches a specific vault category
    search_dirs = list(VAULT_PATHS.values())
    for category, path in VAULT_PATHS.items():
        if category in query_lower:
            search_dirs = [path]
            break
            
    # 2. Perform search (case-insensitive)
    for directory in search_dirs:
        if not os.path.exists(directory):
            continue
        
        # We'll walk the directory for case-insensitive matching
        for root, dirs, files in os.walk(directory):
            for file in files:
                if query_lower in file.lower():
                    matches.append(os.path.join(root, file))
        
    # 3. Dedup and limit
    unique_matches = list(set(matches))
    return sorted(unique_matches, key=lambda x: os.path.getmtime(x), reverse=True)[:10]

