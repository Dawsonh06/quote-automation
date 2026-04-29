import os
import requests
from dotenv import load_dotenv
from utils.graph_auth import get_access_token
from utils.sharepoint import get_site_id, get_drive_id, read_json_file, write_json_file

load_dotenv()

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
MAILBOX = os.getenv("BIDS_MAILBOX")
WATCH_FOLDER = os.getenv("WATCH_FOLDER")
SP_SITE = os.getenv("SHAREPOINT_SITE")
PROCESSED_IDS_PATH = "AI Shadow - Bids/processed_email_ids.json"

token = get_access_token()
headers = {"Authorization": f"Bearer {token}"}

site_id = get_site_id(token, SP_SITE)
drive_id = get_drive_id(token, site_id)
processed_ids = read_json_file(token, drive_id, PROCESSED_IDS_PATH)

# Find the unread email in BIDS @ MJH
folder_url = f"{GRAPH_BASE}/users/{MAILBOX}/mailFolders?$top=100"
r = requests.get(folder_url, headers=headers)
folders = r.json().get("value", [])
folder_id = next(f["id"] for f in folders if f["displayName"] == WATCH_FOLDER)

msg_url = f"{GRAPH_BASE}/users/{MAILBOX}/mailFolders/{folder_id}/messages?$top=10&$filter=isRead eq false"
r = requests.get(msg_url, headers=headers)
msgs = r.json().get("value", [])

removed = 0
for m in msgs:
    email_id = m["id"]
    subject = m.get("subject", "(no subject)")
    if email_id in processed_ids:
        print(f"Removing from processed_ids: {subject}")
        del processed_ids[email_id]
        removed += 1

if removed:
    write_json_file(token, drive_id, PROCESSED_IDS_PATH, processed_ids)
    print(f"Removed {removed} email(s) from processed_ids.")
else:
    print("No unread emails found in processed_ids.")
