import requests
import openpyxl
import io
from datetime import datetime

GRAPH_BASE = "https://graph.microsoft.com/v1.0"

def load_active_bids(token, drive_id, registry_path):
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{GRAPH_BASE}/drives/{drive_id}/root:/{registry_path}:/content"
    response = requests.get(url, headers=headers)
    response.raise_for_status()

    wb = openpyxl.load_workbook(io.BytesIO(response.content), data_only=True)
    ws = wb["BIDDING NOW"] if "BIDDING NOW" in wb.sheetnames else wb.active

    bids = []
    today = datetime.today()

    for row in ws.iter_rows(min_row=2, values_only=True):
        bid_date_raw = row[0]   # Column A
        keywords_raw = row[7]   # Column H (hidden)
        project_name = row[9]   # Column J

        if not project_name or str(project_name).strip() == "":
            continue
        if not bid_date_raw:
            continue

        try:
            if isinstance(bid_date_raw, datetime):
                bid_date = bid_date_raw
            else:
                bid_date = datetime.strptime(str(bid_date_raw).strip(), "%m/%d/%Y")
        except Exception:
            continue

        if bid_date.date() < today.date():
            continue

        keywords = [k.strip() for k in str(keywords_raw or "").replace("\n", ",").split(",") if k.strip()]

        bids.append({
            "job_name": str(project_name).strip(),
            "bid_date": bid_date.strftime("%m/%d/%Y"),
            "keywords": keywords,
        })

    print(f"Loaded {len(bids)} active bids from registry")
    for b in bids:
        print(f"  - {b['job_name']} (due {b['bid_date']}) | keywords: {', '.join(b['keywords'][:3])}...")
    return bids

def ensure_bid_folders_exist(token, drive_id, bids_current_path, active_bids):
    """
    For each active bid, checks if a matching folder exists in 1000-BIDS-CURRENT.
    If not, creates one using the format: M.D.YY Job Name
    """
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # Get existing folders
    url = f"{GRAPH_BASE}/drives/{drive_id}/root:/{bids_current_path}:/children"
    response = requests.get(url, headers={"Authorization": f"Bearer {token}"})
    response.raise_for_status()
    existing = [i["name"].lower() for i in response.json().get("value", []) if i.get("folder")]

    for bid in active_bids:
        job_name = bid["job_name"]
        bid_date = bid["bid_date"]  # format: MM/DD/YYYY from registry loader

        # Format date as M.D.YY
        try:
            dt = datetime.strptime(bid_date, "%m/%d/%Y")
            date_prefix = f"{dt.month}.{dt.day}.{str(dt.year)[2:]}"
        except Exception:
            print(f"  Could not parse date for {job_name}, skipping folder creation")
            continue

        folder_name = f"{date_prefix} {job_name}"

        # Check if a folder already exists that contains the job name
        date_prefix_lower = date_prefix.lower()
        job_words = [w for w in job_name.lower().split() if len(w) > 4]
        already_exists = any(
            existing_name.startswith(date_prefix_lower) or
            sum(1 for w in job_words if w in existing_name) >= 3
            for existing_name in existing
        )

        if already_exists:
            print(f"  Folder exists: {folder_name}")
        else:
            print(f"  Creating folder: {folder_name}")
            create_url = f"{GRAPH_BASE}/drives/{drive_id}/root:/{bids_current_path}:/children"
            resp = requests.post(
                create_url,
                headers=headers,
                json={"name": folder_name, "folder": {}, "@microsoft.graph.conflictBehavior": "rename"}
            )
            if resp.status_code in (200, 201):
                print(f"  Created: {folder_name}")
            else:
                print(f"  ERROR creating {folder_name}: {resp.status_code} {resp.text}")


def find_bid_folder(token, drive_id, bids_base, project_name):
    """
    Searches 1000-BIDS-CURRENT for a folder whose name contains the project name.
    Returns the folder path if found, None if not.
    """
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{GRAPH_BASE}/drives/{drive_id}/root:/{bids_base}:/children"
    response = requests.get(url, headers=headers)
    response.raise_for_status()

    folders = response.json().get("value", [])
    project_lower = project_name.lower()

    for folder in folders:
        if folder.get("folder") is None:
            continue
        folder_name = folder["name"].lower()
        # Check if folder name contains key words from project name
        # Match if 3+ consecutive words from project name appear in folder name
        words = [w for w in project_lower.split() if len(w) > 3]
        matches = sum(1 for w in words if w in folder_name)
        if matches >= 2:
            return f"{bids_base}/{folder['name']}"

    return None
