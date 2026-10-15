import os
import sys
import requests
from datetime import date
from dotenv import load_dotenv
from utils.graph_auth import get_access_token

load_dotenv()

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
SP_SITE_HOST = os.getenv("SHAREPOINT_SITE")  # e.g. vancouvermjhughes.sharepoint.com
LIST_NAME = "Active Bid Pipeline"

BIDS = [
    {"Project Name": "Orchard Diversion",        "Bid Date": "2026-05-28", "Bid Time": "1:00 PM",  "Owner Agency": "Spencer", "Status": "Ready for Review"},
    {"Project Name": "N of Martin Way PCCP",      "Bid Date": "2026-06-03", "Bid Time": "2:00 PM",  "Owner Agency": "TBD",     "Status": "Considering"},
    {"Project Name": "I-84 Rieth (ODOT)",         "Bid Date": "2026-06-04", "Bid Time": "9:00 AM",  "Owner Agency": "Spencer", "Status": "Loaded"},
    {"Project Name": "Shilo Levee",               "Bid Date": "2026-06-04", "Bid Time": "2:00 PM",  "Owner Agency": "TBD",     "Status": "Considering"},
    {"Project Name": "Frying Pan",                "Bid Date": "2026-06-10", "Bid Time": "11:00 AM", "Owner Agency": "Mike",    "Status": "Loaded"},
    {"Project Name": "Heron Street",              "Bid Date": "2026-06-11", "Bid Time": "10:00 AM", "Owner Agency": "Mike",    "Status": "Considering"},
    {"Project Name": "I-84 Spruce Street",        "Bid Date": "2026-06-16", "Bid Time": "9:00 AM",  "Owner Agency": "Spencer", "Status": "Considering"},
    {"Project Name": "Westbrook Reservoir Repairs","Bid Date": "2026-06-17", "Bid Time": "2:00 PM",  "Owner Agency": "Dawson",  "Status": "Considering"},
]


def get_site_id(token):
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{GRAPH_BASE}/sites/{SP_SITE_HOST}:/sites/root"
    # Try root site first
    r = requests.get(f"{GRAPH_BASE}/sites/{SP_SITE_HOST}", headers=headers)
    if r.status_code == 200:
        return r.json()["id"]
    raise Exception(f"Could not find site {SP_SITE_HOST}: {r.status_code} {r.text}")


def check_permissions(token):
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.get(f"{GRAPH_BASE}/sites", headers=headers)
    if r.status_code == 403:
        print("\nERROR: Missing Sites.ReadWrite.All permission.")
        print("To fix, go to Azure Portal:")
        print("  1. Azure Active Directory → App registrations → email-to-excel-automation")
        print("  2. API permissions → Add a permission → Microsoft Graph → Application permissions")
        print("  3. Add: Sites.ReadWrite.All")
        print("  4. Click 'Grant admin consent'")
        sys.exit(1)


def delete_existing_list(token, site_id):
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.get(f"{GRAPH_BASE}/sites/{site_id}/lists", headers=headers)
    r.raise_for_status()
    for lst in r.json().get("value", []):
        if lst["displayName"] == LIST_NAME:
            list_id = lst["id"]
            print(f"  Found existing list '{LIST_NAME}', deleting...")
            requests.delete(f"{GRAPH_BASE}/sites/{site_id}/lists/{list_id}", headers=headers).raise_for_status()
            print(f"  Deleted.")
            return


def create_list(token, site_id):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {
        "displayName": LIST_NAME,
        "columns": [
            {
                "name": "ProjectName",
                "displayName": "Project Name",
                "text": {"allowMultipleLines": False},
                "required": True,
            },
            {
                "name": "BidDate",
                "displayName": "Bid Date",
                "dateTime": {"displayAs": "default", "format": "dateOnly"},
            },
            {
                "name": "BidTime",
                "displayName": "Bid Time",
                "text": {"allowMultipleLines": False},
            },
            {
                "name": "OwnerAgency",
                "displayName": "Owner Agency",
                "text": {"allowMultipleLines": False},
            },
            {
                "name": "LeadEstimator",
                "displayName": "Lead Estimator",
                "personOrGroup": {"allowMultipleSelection": False, "chooseFromType": "peopleOnly"},
            },
            {
                "name": "Status",
                "displayName": "Status",
                "choice": {
                    "allowTextEntry": False,
                    "choices": ["Considering", "Loaded", "Ready for Review", "Reviewed"],
                    "displayAs": "dropDownMenu",
                },
            },
            {
                "name": "DaysUntilBid",
                "displayName": "Days Until Bid",
                "calculated": {
                    "formula": '=INT([Bid Date]-TODAY())',
                    "outputType": "number",
                },
            },
            {
                "name": "Blockers",
                "displayName": "Blockers",
                "text": {"allowMultipleLines": True, "linesForEditing": 3},
            },
            {
                "name": "ProjectFolderLink",
                "displayName": "Project Folder Link",
                "hyperlinkOrPicture": {"isPicture": False},
            },
        ],
        "list": {"template": "genericList"},
    }
    r = requests.post(f"{GRAPH_BASE}/sites/{site_id}/lists", headers=headers, json=payload)
    if r.status_code not in (200, 201):
        raise Exception(f"Failed to create list: {r.status_code} {r.text}")
    data = r.json()
    print(f"  Created list: {data['displayName']} (id: {data['id']})")
    return data["id"]


def seed_items(token, site_id, list_id):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    for bid in BIDS:
        payload = {
            "fields": {
                "ProjectName": bid["Project Name"],
                "BidDate":     bid["Bid Date"],
                "BidTime":     bid["Bid Time"],
                "OwnerAgency": bid["Owner Agency"],
                "Status":      bid["Status"],
            }
        }
        r = requests.post(
            f"{GRAPH_BASE}/sites/{site_id}/lists/{list_id}/items",
            headers=headers,
            json=payload,
        )
        if r.status_code in (200, 201):
            print(f"  Added: {bid['Project Name']}")
        else:
            print(f"  ERROR adding {bid['Project Name']}: {r.status_code} {r.text}")


def get_list_url(token, site_id, list_id):
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.get(f"{GRAPH_BASE}/sites/{site_id}", headers=headers)
    r.raise_for_status()
    web_url = r.json()["webUrl"]
    r2 = requests.get(f"{GRAPH_BASE}/sites/{site_id}/lists/{list_id}", headers=headers)
    r2.raise_for_status()
    list_web_url = r2.json().get("webUrl", f"{web_url}/Lists/{LIST_NAME.replace(' ', '%20')}")
    return list_web_url


def main():
    print("Authenticating...")
    token = get_access_token()

    print("Checking permissions...")
    check_permissions(token)

    print(f"Finding SharePoint site: {SP_SITE_HOST}")
    site_id = get_site_id(token)
    print(f"  Site ID: {site_id}")

    print(f"\nChecking for existing '{LIST_NAME}' list...")
    delete_existing_list(token, site_id)

    print(f"\nCreating list '{LIST_NAME}'...")
    list_id = create_list(token, site_id)

    print(f"\nSeeding {len(BIDS)} bids...")
    seed_items(token, site_id, list_id)

    print(f"\nFetching list URL...")
    url = get_list_url(token, site_id, list_id)

    print(f"\n{'='*60}")
    print(f"Done! Active Bid Pipeline list created.")
    print(f"URL: {url}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
