import os
import json
from datetime import datetime
from dotenv import load_dotenv
import base64

from utils.graph_auth import get_access_token
from utils.email_ops import get_unprocessed_emails, get_attachments, get_email_raw, mark_as_read, send_notification_email
from utils.sharepoint import get_site_id, get_drive_id, upload_file, read_json_file, write_json_file, append_to_log
from bid_registry import load_active_bids, find_bid_folder
from classifier import classify_email
from matcher import process_all_attachments
from file_namer import generate_filename

load_dotenv()

MAILBOX = os.getenv("BIDS_MAILBOX")
SP_SITE = os.getenv("SHAREPOINT_SITE")
BIDS_BASE = os.getenv("SHAREPOINT_BIDS_BASE")
ITB_BASE = os.getenv("SHAREPOINT_ITB_BASE")
REVIEW_FOLDER = os.getenv("REVIEW_FOLDER")
REGISTRY_PATH = os.getenv("BID_REGISTRY_PATH")
WATCH_FOLDER = os.getenv("WATCH_FOLDER")

PROCESSED_IDS_PATH = "AI Shadow - Bids/processed_email_ids.json"
LOG_PATH = "AI Shadow - Bids/processing_log.xlsx"

def main():
    print(f"\n{'='*50}")
    print(f"Bids Processor starting — {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*50}\n")

    token = get_access_token()
    site_id = get_site_id(token, SP_SITE)
    drive_id = get_drive_id(token, site_id)

    # Load already-processed email IDs
    processed_ids = read_json_file(token, drive_id, PROCESSED_IDS_PATH)
    print(f"Already processed: {len(processed_ids)} emails\n")

    # Load active bids from registry
    active_bids = load_active_bids(token, drive_id, REGISTRY_PATH)
    if not active_bids:
        print("No active bids found in registry. Exiting.")
        return

    # Get unprocessed emails
    emails = get_unprocessed_emails(token, MAILBOX, processed_ids, folder_name=WATCH_FOLDER)
    print(f"New emails to process: {len(emails)}\n")

    errors = []

    for email in emails:
        email_id = email["id"]
        subject = email.get("subject", "(no subject)")
        sender = email.get("from", {}).get("emailAddress", {}).get("address", "unknown")
        body = email.get("body", {}).get("content", "")

        print(f"Processing: {subject} | From: {sender}")

        try:
            attachments = get_attachments(token, MAILBOX, email_id)

            # Stage 1: Classify
            classification_result = classify_email(subject, sender, body, attachments)
            classification = classification_result["classification"]
            print(f"  Classification: {classification} — {classification_result['reasoning']}")

            log_row = [subject, sender, classification, "", "", "", "", "", "", ""]

            if classification == "itb":
                all_attachments = get_attachments(token, MAILBOX, email_id, pdf_only=False)
                safe_subject = "".join(c for c in subject if c.isalnum() or c in " -_()").strip()[:80]
                eml_filename = f"{safe_subject}.eml"
                eml_bytes = get_email_raw(token, MAILBOX, email_id)
                upload_file(token, drive_id, ITB_BASE, eml_filename, eml_bytes)
                print(f"  Filed ITB email: {eml_filename} -> {ITB_BASE}")
                if not all_attachments:
                    log_row[9] = ITB_BASE
                else:
                    for att in all_attachments:
                        file_bytes = base64.b64decode(att["content_bytes"])
                        upload_file(token, drive_id, ITB_BASE, att["name"], file_bytes)
                        print(f"  Filed ITB attachment: {att['name']} -> {ITB_BASE}")
                    log_row[9] = ITB_BASE

            elif classification == "quote":
                if not attachments:
                    upload_file(token, drive_id, REVIEW_FOLDER,
                               f"NO_ATTACHMENT_{email_id[:8]}.txt",
                               f"Email with no attachment:\nSubject: {subject}\nFrom: {sender}".encode())
                    log_row[9] = "No PDF attachments"
                    print(f"  No attachments, noted in review folder")
                else:
                    from matcher import process_all_attachments
                    results = process_all_attachments(attachments, active_bids)

                    for result in results:
                        original_name = result["original_filename"]
                        is_quote = result.get("is_quote", True)
                        confidence = result.get("confidence", "low")
                        matched_bid = result.get("matched_bid")
                        vendor = result.get("vendor", "Unknown Vendor")
                        scope = result.get("scope", "Unknown Scope")
                        price = result.get("total_price")

                        if not is_quote:
                            # Supporting document — file alongside quote but don't rename
                            if confidence == "high" and matched_bid:
                                folder_path = find_bid_folder(token, drive_id, BIDS_BASE, matched_bid)
                                if not folder_path:
                                    folder_path = REVIEW_FOLDER
                            else:
                                folder_path = REVIEW_FOLDER
                            filename = f"SUPPORT - {vendor} - {original_name}"
                            print(f"    Supporting doc: {filename} -> {folder_path}")
                        else:
                            # It's a quote — rename and match
                            filename = generate_filename(scope, vendor, price, original_name)
                            if confidence == "high" and matched_bid:
                                folder_path = find_bid_folder(token, drive_id, BIDS_BASE, matched_bid)
                                if not folder_path:
                                    print(f"    WARNING: No folder found for '{matched_bid}', sending to review")
                                    folder_path = REVIEW_FOLDER
                            else:
                                folder_path = REVIEW_FOLDER
                            print(f"    Quote: {filename} -> {folder_path}")

                        # Find the attachment bytes
                        att = next((a for a in attachments if a["name"] == original_name), None)
                        if att:
                            file_bytes = base64.b64decode(att["content_bytes"])
                            upload_file(token, drive_id, folder_path, filename, file_bytes)

                        log_row = [subject, sender, classification, matched_bid or "",
                                   confidence, vendor, scope, str(price or ""),
                                   filename, folder_path]
                        try:
                            append_to_log(token, drive_id, LOG_PATH, log_row)
                        except Exception as log_err:
                            print(f"    WARNING: Could not write to log (file may be open): {log_err}")

            else:
                log_row[9] = "Skipped - not a quote or ITB"
                print(f"  Skipped (classified as other)")

            mark_as_read(token, MAILBOX, email_id)

            processed_ids[email_id] = {
                "processed_at": datetime.utcnow().isoformat(),
                "subject": subject,
                "classification": classification
            }

            if classification != "quote":
                try:
                    append_to_log(token, drive_id, LOG_PATH, log_row)
                except Exception as log_err:
                    print(f"  WARNING: Could not write to log (file may be open): {log_err}")

        except Exception as e:
            print(f"  ERROR: {e}")
            errors.append(f"Subject: {subject}\nFrom: {sender}\nError: {e}")
            processed_ids[email_id] = {
                "processed_at": datetime.utcnow().isoformat(),
                "subject": subject,
                "classification": "error",
                "error": str(e)
            }

    write_json_file(token, drive_id, PROCESSED_IDS_PATH, processed_ids)
    print(f"\nDone. Processed {len(emails)} emails.")

    if errors:
        error_body = f"The bids processor encountered {len(errors)} error(s) on {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}:\n\n"
        error_body += "\n\n---\n\n".join(errors)
        send_notification_email(token, MAILBOX, f"Bids Processor Error ({len(errors)} failed)", error_body)
        print(f"Error notification sent for {len(errors)} failed email(s).")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"FATAL ERROR: {e}")
        try:
            token = get_access_token()
            send_notification_email(
                token, MAILBOX,
                "Bids Processor - Fatal Error",
                f"The bids processor crashed at {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}:\n\n{e}"
            )
        except Exception:
            pass
        raise
