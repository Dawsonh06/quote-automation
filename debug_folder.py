import os
import requests
from dotenv import load_dotenv
from utils.graph_auth import get_access_token

load_dotenv()

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
MAILBOX = os.getenv("BIDS_MAILBOX")
WATCH_FOLDER = os.getenv("WATCH_FOLDER")

token = get_access_token()
headers = {"Authorization": f"Bearer {token}"}

print(f"Looking for folder: '{WATCH_FOLDER}'\n")

# Fetch all top-level folders with pagination
url = f"{GRAPH_BASE}/users/{MAILBOX}/mailFolders?$top=100"
all_folders = []
while url:
    r = requests.get(url, headers=headers)
    r.raise_for_status()
    data = r.json()
    all_folders.extend(data.get("value", []))
    url = data.get("@odata.nextLink")

print(f"Total top-level folders found: {len(all_folders)}")
matches = [f for f in all_folders if f["displayName"] == WATCH_FOLDER]
print(f"Folders named '{WATCH_FOLDER}': {len(matches)}\n")

for f in all_folders:
    marker = " <-- MATCH" if f["displayName"] == WATCH_FOLDER else ""
    print(f"  [{f['id'][:12]}...] {f['displayName']} (unread: {f.get('unreadItemCount', '?')}){marker}")

if matches:
    folder_id = matches[0]["id"]
    print(f"\nFetching unread emails from first match (id: {folder_id[:12]}...)...")
    url = f"{GRAPH_BASE}/users/{MAILBOX}/mailFolders/{folder_id}/messages?$top=10&$filter=isRead eq false&$orderby=receivedDateTime desc"
    r = requests.get(url, headers=headers)
    r.raise_for_status()
    msgs = r.json().get("value", [])
    print(f"Unread emails in folder: {len(msgs)}")
    for m in msgs:
        print(f"  - {m.get('subject', '(no subject)')} | {m.get('receivedDateTime', '')}")
