import os, json, requests
from utils.graph_auth import get_access_token
from utils.sharepoint import get_site_id, get_drive_id
from dotenv import load_dotenv

load_dotenv()

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
SP_SITE = os.getenv("SHAREPOINT_SITE")
BIDS_BY_TRADE = "1010-BIDS BY TRADE"

with open("config/vendor_categories.json") as f:
    categories = json.load(f)

token = get_access_token()
site_id = get_site_id(token, SP_SITE)
drive_id = get_drive_id(token, site_id)

headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

# Get existing folders
url = f"{GRAPH_BASE}/drives/{drive_id}/root:/{BIDS_BY_TRADE}:/children"
existing = [i["name"] for i in requests.get(url, headers=headers).json().get("value", [])]
print(f"Existing folders: {len(existing)}")

created = 0
skipped = 0
for cat in categories:
    folder_name = cat["short"]
    if folder_name in existing:
        skipped += 1
        continue
    resp = requests.post(url, headers=headers,
        json={"name": folder_name, "folder": {}, "@microsoft.graph.conflictBehavior": "rename"})
    if resp.status_code in (200, 201):
        print(f"  Created: {folder_name}")
        created += 1
    else:
        print(f"  ERROR: {folder_name} — {resp.status_code} {resp.text}")

print(f"\nDone. Created {created}, skipped {skipped} already existing.")
