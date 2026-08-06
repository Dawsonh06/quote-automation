import requests

GRAPH_BASE = "https://graph.microsoft.com/v1.0"

def get_unprocessed_emails(token, mailbox, processed_ids, folder_name=None):
    headers = {"Authorization": f"Bearer {token}"}

    if folder_name:
        # Find the folder ID first
        folder_id = get_or_create_folder(token, mailbox, folder_name)
        url = f"{GRAPH_BASE}/users/{mailbox}/mailFolders/{folder_id}/messages?$top=50&$filter=isRead eq false&$orderby=receivedDateTime desc"
    else:
        url = f"{GRAPH_BASE}/users/{mailbox}/messages?$top=50&$filter=isRead eq false&$orderby=receivedDateTime desc"

    # Page through the full result set. Emails that get manually moved into the
    # folder keep their original receivedDateTime, so with $orderby=receivedDateTime
    # desc an old manually-moved email can be older than the 50 newest unread items
    # and would otherwise never appear if we stopped at the first page.
    messages = []
    while url:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        payload = response.json()
        messages.extend(payload.get("value", []))
        url = payload.get("@odata.nextLink")

    return [m for m in messages if m["id"] not in processed_ids]

def get_email_raw(token, mailbox, message_id):
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{GRAPH_BASE}/users/{mailbox}/messages/{message_id}/$value"
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.content

def mark_as_read(token, mailbox, message_id):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    url = f"{GRAPH_BASE}/users/{mailbox}/messages/{message_id}"
    requests.patch(url, headers=headers, json={"isRead": True}).raise_for_status()

def get_attachments(token, mailbox, message_id, pdf_only=True):
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{GRAPH_BASE}/users/{mailbox}/messages/{message_id}/attachments"
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    attachments = response.json().get("value", [])
    return [
        {
            "name": a["name"],
            "content_type": a.get("contentType", ""),
            "content_bytes": a.get("contentBytes", "")
        }
        for a in attachments
        if a.get("contentBytes") and (not pdf_only or a.get("name", "").lower().endswith(".pdf"))
    ]

def send_notification_email(token, mailbox, subject, body):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    url = f"{GRAPH_BASE}/users/{mailbox}/sendMail"
    payload = {
        "message": {
            "subject": subject,
            "body": {"contentType": "Text", "content": body},
            "toRecipients": [{"emailAddress": {"address": "dawson.h@mjhughes.com"}}]
        }
    }
    requests.post(url, headers=headers, json=payload).raise_for_status()

def move_email(token, mailbox, message_id, folder_name):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    # Get or create folder
    folder_id = get_or_create_folder(token, mailbox, folder_name)
    url = f"{GRAPH_BASE}/users/{mailbox}/messages/{message_id}/move"
    response = requests.post(url, headers=headers, json={"destinationId": folder_id})
    response.raise_for_status()

def get_or_create_folder(token, mailbox, folder_name):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # Check top-level folders first
    url = f"{GRAPH_BASE}/users/{mailbox}/mailFolders"
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    for folder in response.json().get("value", []):
        if folder["displayName"] == folder_name:
            return folder["id"]

    # Check child folders of Inbox (most custom sort folders live here)
    inbox_children_url = f"{GRAPH_BASE}/users/{mailbox}/mailFolders/inbox/childFolders"
    response = requests.get(inbox_children_url, headers=headers)
    response.raise_for_status()
    for folder in response.json().get("value", []):
        if folder["displayName"] == folder_name:
            return folder["id"]

    # Not found anywhere — create as a top-level folder
    response = requests.post(url, headers=headers, json={"displayName": folder_name})
    response.raise_for_status()
    return response.json()["id"]
