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
        # Skip blank rows and date-header rows (blue divider rows)
        bid_date_raw = row[0]
        project_name = row[3]  # Column D

        if not project_name or str(project_name).strip() == "":
            continue
        if not bid_date_raw:
            continue

        # Parse bid date
        try:
            if isinstance(bid_date_raw, datetime):
                bid_date = bid_date_raw
            else:
                bid_date = datetime.strptime(str(bid_date_raw).strip(), "%m/%d/%Y")
        except Exception:
            continue  # skip rows where col A isn't a real date (e.g. the blue header rows)

        # Skip bids that are already past — only keep future/today bids
        if bid_date.date() < today.date():
            continue

        # Keywords from column E
        keywords_raw = row[4] or ""
        keywords = [k.strip() for k in str(keywords_raw).replace("\n", ",").split(",") if k.strip()]

        bids.append({
            "job_name": str(project_name).strip(),
            "bid_date": bid_date.strftime("%m/%d/%Y"),
            "keywords": keywords,
            "team": str(row[7] or "").strip(),  # Column H
        })

    print(f"Loaded {len(bids)} active bids from registry")
    for b in bids:
        print(f"  - {b['job_name']} (due {b['bid_date']}) | keywords: {', '.join(b['keywords'][:3])}...")
    return bids

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
