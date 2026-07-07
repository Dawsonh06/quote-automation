import requests
import openpyxl
import io
from datetime import datetime

GRAPH_BASE = "https://graph.microsoft.com/v1.0"

# Generic civil-engineering/construction vocabulary that recurs across unrelated
# projects (e.g. "Fryingpan Creek Bridge" and "Heron Street Bridge Grid Deck
# Replace" share "bridge", "grid", "deck" without being the same job at all).
# These are stripped before comparing job names so matches are driven by the
# words that actually distinguish one project from another.
GENERIC_JOB_WORDS = {
    "bridge", "bridges", "street", "avenue", "boulevard", "highway", "road", "roads",
    "grid", "deck", "decks", "replace", "replacement", "rehab", "rehabilitation",
    "rehabilitate", "improvement", "improvements", "upgrade", "upgrades", "retrofit",
    "project", "phase", "construction", "reservoir", "reservoirs", "station", "stations",
    "creek", "park", "campus", "building", "buildings", "facility", "facilities",
    "system", "systems", "water", "sewer", "storm", "stormwater", "wastewater",
    "pump", "pumping", "seismic", "box", "girder", "culvert", "culverts",
    "over", "north", "south", "east", "west",
}


def _distinguishing_words(name):
    """Significant words in a job name, excluding generic construction vocabulary."""
    return [w for w in name.lower().split() if len(w) > 3 and w not in GENERIC_JOB_WORDS]

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

def _transfer_past_folder_contents(token, drive_id, bids_past_path, job_name, new_folder_id):
    """Move files from a matching past-bids folder into a newly created current folder."""
    headers = {"Authorization": f"Bearer {token}"}

    resp = requests.get(
        f"{GRAPH_BASE}/drives/{drive_id}/root:/{bids_past_path}:/children",
        headers=headers,
    )
    if resp.status_code != 200:
        return

    past_folder = None
    for item in resp.json().get("value", []):
        if item.get("folder") is None:
            continue
        # Folder names are "M.D.YY Job Name" — strip the date prefix and require an exact match on the job name.
        parts = item["name"].split(" ", 1)
        if len(parts) == 2 and parts[1].lower() == job_name.lower():
            past_folder = item
            break

    if not past_folder:
        return

    items_resp = requests.get(
        f"{GRAPH_BASE}/drives/{drive_id}/items/{past_folder['id']}/children",
        headers=headers,
    )
    if items_resp.status_code != 200:
        return

    items = items_resp.json().get("value", [])
    if not items:
        return

    print(f"  Found matching past folder '{past_folder['name']}' — transferring contents to new folder")

    patch_headers = {**headers, "Content-Type": "application/json"}
    moved = 0
    for item in items:
        move_resp = requests.patch(
            f"{GRAPH_BASE}/drives/{drive_id}/items/{item['id']}",
            headers=patch_headers,
            json={"parentReference": {"id": new_folder_id}},
        )
        if move_resp.status_code in (200, 201):
            moved += 1
            print(f"    Transferred: {item['name']}")
        else:
            print(f"    WARNING: Could not transfer '{item['name']}': {move_resp.status_code}")

    print(f"  Transferred {moved} item(s) from '{past_folder['name']}'")


def ensure_bid_folders_exist(token, drive_id, bids_current_path, active_bids, bids_past_path=None):
    """
    For each active bid, checks if a matching folder exists in 1000-BIDS-CURRENT.
    If not, creates one using the format: M.D.YY Job Name
    """
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # Get existing folders — store full items so we have IDs for the transfer step
    url = f"{GRAPH_BASE}/drives/{drive_id}/root:/{bids_current_path}:/children"
    response = requests.get(url, headers={"Authorization": f"Bearer {token}"})
    response.raise_for_status()
    existing_items = {i["name"].lower(): i for i in response.json().get("value", []) if i.get("folder")}

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

        # Find a matching existing folder and capture its item (for the ID).
        # Use AND (not OR) for the date-prefix check: two bids can share the same
        # date, so the prefix alone isn't enough to confirm it's *this* job's folder.
        date_prefix_lower = date_prefix.lower()
        # Fall back to the unfiltered word list on the rare job name that is
        # entirely generic vocabulary, so it can still be matched/created once
        # instead of spawning a new folder on every run.
        job_words = _distinguishing_words(job_name) or [w for w in job_name.lower().split() if len(w) > 3]
        matched_item = None
        if job_words:
            for existing_name, existing_item in existing_items.items():
                if ((existing_name.startswith(date_prefix_lower + " ") and
                     sum(1 for w in job_words if w in existing_name) >= min(2, len(job_words))) or
                        sum(1 for w in job_words if w in existing_name) >= max(3, len(job_words))):
                    matched_item = existing_item
                    break

        if matched_item:
            print(f"  Folder exists: {matched_item['name']}")
            if bids_past_path:
                _transfer_past_folder_contents(token, drive_id, bids_past_path, job_name, matched_item["id"])
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
                if bids_past_path:
                    _transfer_past_folder_contents(token, drive_id, bids_past_path, job_name, resp.json()["id"])
            else:
                print(f"  ERROR creating {folder_name}: {resp.status_code} {resp.text}")


def _best_matching_folder(token, drive_id, base_path, words, required):
    """Returns the child folder under base_path with the highest distinguishing-word
    overlap (at least `required`), or None if nothing clears the bar."""
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{GRAPH_BASE}/drives/{drive_id}/root:/{base_path}:/children"
    response = requests.get(url, headers=headers)
    if response.status_code == 404:
        return None
    response.raise_for_status()

    best_folder = None
    best_score = 0
    for folder in response.json().get("value", []):
        if folder.get("folder") is None:
            continue
        folder_name = folder["name"].lower()
        score = sum(1 for w in words if w in folder_name)
        if score >= required and score > best_score:
            best_score = score
            best_folder = folder

    return best_folder


def find_bid_folder(token, drive_id, bids_base, project_name, bids_past_path=None):
    """
    Searches 1000-BIDS-CURRENT for a folder whose name contains the project name.
    Falls back to bids_past_path (e.g. a quote arriving after the bid's folder was
    already archived) if given and nothing matches in bids_base.
    Returns the folder path if found, None if not.
    """
    words = _distinguishing_words(project_name) or [w for w in project_name.lower().split() if len(w) > 3]
    if not words:
        return None

    required = min(2, len(words))

    best_folder = _best_matching_folder(token, drive_id, bids_base, words, required)
    if best_folder:
        return f"{bids_base}/{best_folder['name']}"

    if bids_past_path:
        best_folder = _best_matching_folder(token, drive_id, bids_past_path, words, required)
        if best_folder:
            return f"{bids_past_path}/{best_folder['name']}"

    return None
