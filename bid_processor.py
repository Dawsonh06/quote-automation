import os
import json
from datetime import datetime
from dotenv import load_dotenv
import base64

from utils.graph_auth import get_access_token
from utils.email_ops import get_unprocessed_emails, get_attachments, get_email_raw, mark_as_read, send_notification_email
from utils.sharepoint import get_site_id, get_drive_id, upload_file, read_json_file, write_json_file, append_to_log, ensure_folder_exists, prune_old_log_entries
from bid_registry import load_active_bids, find_bid_folder, ensure_bid_folders_exist
from bid_archiver import archive_expired_bids
from classifier import classify_email
from matcher import process_all_attachments, match_email_body
from file_namer import generate_filename
from vendor_database import upsert_vendor

load_dotenv()

MAILBOX = os.getenv("BIDS_MAILBOX")
SP_SITE = os.getenv("SHAREPOINT_SITE")
BIDS_BASE = os.getenv("SHAREPOINT_BIDS_BASE")
ITB_BASE = os.getenv("SHAREPOINT_ITB_BASE")
REVIEW_FOLDER = os.getenv("REVIEW_FOLDER")
REGISTRY_PATH = os.getenv("BID_REGISTRY_PATH")
WATCH_FOLDER = os.getenv("WATCH_FOLDER")
BIDS_PAST_PATH = os.getenv("SHAREPOINT_BIDS_PAST")

PROCESSED_IDS_PATH = "AI Shadow - Bids/processed_email_ids.json"
LOG_PATH = "AI Shadow - Bids/processing_log.xlsx"

def _clean_matched_bid(matched_bid):
    """Strip any trailing '| Keywords: ...' the model accidentally included."""
    if not matched_bid:
        return None
    return matched_bid.split("|")[0].strip() or None


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

    print("\nEnsuring bid folders exist...")
    ensure_bid_folders_exist(token, drive_id, BIDS_BASE, active_bids, BIDS_PAST_PATH)

    print("\nChecking for expired bids to archive...")
    archive_expired_bids(token, drive_id, BIDS_BASE, BIDS_PAST_PATH)
    print()

    print("Pruning processing log entries older than 30 days...")
    pruned = prune_old_log_entries(token, drive_id, LOG_PATH, days=30)
    print(f"  Removed {pruned} old log entries\n" if pruned else "  No old entries to remove\n")

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

            log_row = [subject, sender, classification, "", "", "", "", "", "", "", ""]

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
                    # No PDF — analyse the email body text directly
                    print(f"  No PDF attachments — analysing email body...")
                    body_result = match_email_body(subject, sender, body, active_bids)
                    confidence  = body_result.get("confidence", "low")
                    matched_bid = _clean_matched_bid(body_result.get("matched_bid"))
                    vendor      = body_result.get("vendor", "Unknown Vendor")
                    scope       = body_result.get("scope", "Unknown Scope")
                    price       = body_result.get("total_price")

                    safe_subject = "".join(c for c in subject if c.isalnum() or c in " -_()").strip()[:80]
                    filename     = generate_filename(None, vendor, price, f"{safe_subject}.txt")

                    print(f"  Match: matched_bid={matched_bid!r}  confidence={confidence}")
                    if confidence in ("high", "medium") and matched_bid:
                        folder_path = find_bid_folder(token, drive_id, BIDS_BASE, matched_bid)
                        if not folder_path:
                            print(f"  WARNING: No folder found for '{matched_bid}', sending to review")
                            folder_path = REVIEW_FOLDER
                    else:
                        folder_path = REVIEW_FOLDER

                    txt_content = f"Subject: {subject}\nFrom: {sender}\n\n{body}"
                    upload_file(token, drive_id, folder_path, filename, txt_content.encode("utf-8"))
                    print(f"  Body-only quote: {filename} -> {folder_path}  [{confidence}]")

                    log_row = [subject, sender, classification, matched_bid or "",
                               confidence, vendor, scope, str(price or ""), filename, folder_path, ""]
                    try:
                        append_to_log(token, drive_id, LOG_PATH, log_row)
                    except Exception as log_err:
                        print(f"  WARNING: Could not write to log (file may be open): {log_err}")
                else:
                    results = process_all_attachments(attachments, active_bids)

                    for result in results:
                        original_name = result["original_filename"]
                        is_quote      = result.get("is_quote", True)
                        confidence    = result.get("confidence", "low")
                        matched_bid   = _clean_matched_bid(result.get("matched_bid"))
                        vendor        = result.get("vendor", "Unknown Vendor")
                        scope         = result.get("scope") or result.get("category_long", "Unknown Scope")
                        price         = result.get("total_price")

                        print(f"    Match: matched_bid={matched_bid!r}  confidence={confidence}")
                        if not is_quote:
                            # Supporting document — file alongside quote but don't rename
                            if confidence in ("high", "medium") and matched_bid:
                                folder_path = find_bid_folder(token, drive_id, BIDS_BASE, matched_bid)
                                if not folder_path:
                                    folder_path = REVIEW_FOLDER
                            else:
                                folder_path = REVIEW_FOLDER
                            filename = f"SUPPORT - {vendor} - {original_name}"
                            print(f"    Supporting doc: {filename} -> {folder_path}")
                        else:
                            # It's a quote — rename and route
                            filename = generate_filename(
                                result.get("category_short"),
                                vendor,
                                price,
                                original_name
                            )
                            if confidence in ("high", "medium") and matched_bid:
                                folder_path = find_bid_folder(token, drive_id, BIDS_BASE, matched_bid)
                                if not folder_path:
                                    print(f"    WARNING: No folder found for '{matched_bid}', sending to review")
                                    folder_path = REVIEW_FOLDER
                            else:
                                folder_path = REVIEW_FOLDER
                            print(f"    Quote: {filename} -> {folder_path}  [{confidence}]")

                        att = next((a for a in attachments if a["name"] == original_name), None)
                        if not att:
                            print(f"    WARNING: Could not find attachment bytes for '{original_name}' — skipping upload and log")
                            continue

                        file_bytes = base64.b64decode(att["content_bytes"])
                        upload_file(token, drive_id, folder_path, filename, file_bytes)

                        if is_quote:
                            # File to 1010-BIDS BY TRADE as well
                            category_short = result.get("category_short")
                            if category_short and category_short != "Unknown":
                                trade_folder = f"1010-BIDS BY TRADE/{category_short}"
                                try:
                                    ensure_folder_exists(token, drive_id, trade_folder)
                                    upload_file(token, drive_id, trade_folder, filename, file_bytes)
                                    print(f"    Also filed to trade folder: {trade_folder}")
                                except Exception as e:
                                    print(f"    WARNING: Could not file to trade folder: {e}")

                            # Update vendor database
                            try:
                                upsert_vendor(token, drive_id, {
                                    "company": result.get("vendor"),
                                    "email": sender,
                                    "phone": result.get("phone"),
                                    "location": result.get("location"),
                                    "category_short": category_short,
                                    "bid_name": matched_bid or "",
                                    "quote_date": datetime.today().strftime("%m/%d/%Y")
                                })
                            except Exception as e:
                                print(f"    WARNING: Could not update vendor database: {e}")

                        log_row = [subject, sender, classification, matched_bid or "",
                                   confidence, vendor, scope, str(price or ""),
                                   filename, folder_path, ""]
                        try:
                            append_to_log(token, drive_id, LOG_PATH, log_row)
                        except Exception as log_err:
                            print(f"    WARNING: Could not write to log (file may be open): {log_err}")

            else:
                log_row[9] = "Skipped - not a quote or ITB"
                log_row[10] = ""
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
