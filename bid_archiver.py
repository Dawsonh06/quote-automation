import requests
from datetime import datetime

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


def parse_folder_date(folder_name):
    try:
        parts = folder_name.strip().split(" ")
        date_part = parts[0]
        segments = date_part.split(".")
        if len(segments) != 3:
            return None
        month, day, year = int(segments[0]), int(segments[1]), int(segments[2])
        if year < 100:
            year += 2000
        return datetime(year, month, day)
    except Exception:
        return None


def get_folder_id(token, drive_id, folder_path):
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{GRAPH_BASE}/drives/{drive_id}/root:/{folder_path}"
    response = requests.get(url, headers=headers)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json()["id"]


def get_child_folders(token, drive_id, folder_path):
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{GRAPH_BASE}/drives/{drive_id}/root:/{folder_path}:/children"
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    items = response.json().get("value", [])
    return [i for i in items if i.get("folder") is not None]


def move_folder(token, drive_id, item_id, destination_folder_path):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    dest_id = get_folder_id(token, drive_id, destination_folder_path)
    if not dest_id:
        parent_path = "/".join(destination_folder_path.split("/")[:-1])
        folder_name = destination_folder_path.split("/")[-1]
        create_url = f"{GRAPH_BASE}/drives/{drive_id}/root:/{parent_path}:/children"
        resp = requests.post(create_url, headers=headers,
                             json={"name": folder_name, "folder": {}})
        resp.raise_for_status()
        dest_id = resp.json()["id"]
    url = f"{GRAPH_BASE}/drives/{drive_id}/items/{item_id}"
    response = requests.patch(url, headers=headers, json={
        "parentReference": {"id": dest_id}
    })
    response.raise_for_status()


def archive_expired_bids(token, drive_id, bids_current_path, bids_past_path):
    today = datetime.today()
    folders = get_child_folders(token, drive_id, bids_current_path)
    print(f"  Found {len(folders)} folders in {bids_current_path}")

    archived = []
    skipped = []

    for folder in folders:
        name = folder["name"]
        item_id = folder["id"]

        if "99999" in name or "unable" in name.lower():
            print(f"  Skipping review folder: {name}")
            continue

        bid_date = parse_folder_date(name)

        if bid_date is None:
            print(f"  No date prefix found, skipping: {name}")
            skipped.append(name)
            continue

        if bid_date.date() < today.date():
            print(f"  Archiving expired bid: {name} (due {bid_date.strftime('%m/%d/%Y')})")
            try:
                move_folder(token, drive_id, item_id, bids_past_path)
                archived.append(name)
                print(f"  Moved to: {bids_past_path}")
            except Exception as e:
                import traceback
                print(f"  ERROR archiving {name}: {e}")
                traceback.print_exc()
        else:
            print(f"  Active bid: {name} (due {bid_date.strftime('%m/%d/%Y')})")

    print(f"\nArchive summary: {len(archived)} archived, {len(skipped)} skipped")
    return archived
