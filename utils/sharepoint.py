import requests
import json
import os

GRAPH_BASE = "https://graph.microsoft.com/v1.0"

def get_site_id(token, sharepoint_site):
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{GRAPH_BASE}/sites/{sharepoint_site}"
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.json()["id"]

def get_drive_id(token, site_id):
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{GRAPH_BASE}/sites/{site_id}/drives"
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    drives = response.json().get("value", [])
    for drive in drives:
        if drive.get("name") == "Documents":
            return drive["id"]
    return drives[0]["id"]

def upload_file(token, drive_id, folder_path, filename, file_bytes):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/octet-stream"}
    path = f"{folder_path}/{filename}".replace("//", "/")
    url = f"{GRAPH_BASE}/drives/{drive_id}/root:/{path}:/content"
    response = requests.put(url, headers=headers, data=file_bytes)
    response.raise_for_status()
    return response.json().get("webUrl")

def read_json_file(token, drive_id, file_path):
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{GRAPH_BASE}/drives/{drive_id}/root:/{file_path}:/content"
    response = requests.get(url, headers=headers)
    if response.status_code == 404:
        return {}
    response.raise_for_status()
    return response.json()

def write_json_file(token, drive_id, file_path, data):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    url = f"{GRAPH_BASE}/drives/{drive_id}/root:/{file_path}:/content"
    response = requests.put(url, headers=headers, data=json.dumps(data, indent=2))
    response.raise_for_status()

def append_to_log(token, drive_id, log_path, row_data):
    import openpyxl
    import io
    from datetime import datetime

    headers_auth = {"Authorization": f"Bearer {token}"}
    url = f"{GRAPH_BASE}/drives/{drive_id}/root:/{log_path}:/content"
    response = requests.get(url, headers=headers_auth)

    if response.status_code == 404:
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Processing Log"
        ws.append(["Timestamp", "Subject", "Sender", "Classification",
                   "Matched Bid", "Confidence", "Vendor", "Scope",
                   "Price", "Filename", "Filed To", "Notes"])
    else:
        wb = openpyxl.load_workbook(io.BytesIO(response.content))
        ws = wb.active

    ws.append([datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")] + row_data)

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)

    requests.put(url, headers={**headers_auth, "Content-Type": "application/octet-stream"},
                 data=buffer.read()).raise_for_status()
