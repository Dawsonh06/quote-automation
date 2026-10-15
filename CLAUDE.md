# Bids Email Processor (MJ Hughes Construction)

Automatically files subcontractor/supplier quotes and invitations to bid (ITBs) that arrive in the bids mailbox. Runs in Azure every 5 minutes. Owner: Dawson (dawson.h@mjhughes.com).

## What it does

`bid_processor.py` is the entry point. Each run:

1. Gets a Microsoft Graph token (`utils/graph_auth.py`, app-only client credentials).
2. Loads processed email IDs and the active bid registry from SharePoint (`bid_registry.py`).
3. Creates missing bid folders and archives expired ones (`bid_archiver.py`; folder names start with a `M.D.YY` date).
4. Prunes processing-log rows older than 30 days.
5. Fetches unread emails from the `WATCH_FOLDER` mail folder in `BIDS_MAILBOX` (`utils/email_ops.py`).
6. For each email:
   - `classifier.py` (Claude) classifies it as `quote`, `itb`, or `other`.
   - **itb**: the `.eml` and all attachments go to `SHAREPOINT_ITB_BASE`.
   - **quote**: `matcher.py` (Claude) reads the PDFs, or the body if there's no PDF, and extracts the matched bid, confidence, vendor, scope, price, phone, and location. High/medium confidence files go to that bid's folder. Everything else goes to `REVIEW_FOLDER`. Quotes are renamed by `file_namer.py` (`SCOPE - Vendor - $Price.pdf`), copied to `1010-BIDS BY TRADE/<category>`, and recorded in the subcontractor database (`vendor_database.py`).
   - **other**: skipped.
   - The email is marked read, logged to `AI Shadow - Bids/processing_log.xlsx`, and its ID is saved to `AI Shadow - Bids/processed_email_ids.json`.
7. On any error, emails a notification from the bids mailbox.

Config: `config/vendor_categories.json` (trade categories) and `config/scope_categories.json`.

One-off/maintenance scripts (not part of the scheduled run): `create_bid_pipeline_list.py`, `create_trade_folders.py`, `debug_folder.py`, `debug_processed.py`, `remove_from_processed.py`.

## Settings and secrets

- All config comes from environment variables: `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_CLIENT_SECRET`, `ANTHROPIC_API_KEY`, `BIDS_MAILBOX`, `SHAREPOINT_SITE`, `SHAREPOINT_BIDS_BASE`, `SHAREPOINT_BIDS_PAST`, `SHAREPOINT_ITB_BASE`, `REVIEW_FOLDER`, `BID_REGISTRY_PATH`, `WATCH_FOLDER`.
- Locally they come from `.env`, which is never committed. In production they're set on the Azure Container Apps job, not baked into the image (`.dockerignore` excludes `.env`). A new variable must be added to the job too, or production gets `None`.
- Never hardcode secrets, and never commit or print `.env`. **This GitHub repo is public.**
- `SHADOW_MODE` is set on the Azure job but the code doesn't currently read it. It does nothing.

## Running and deploying

- **Running locally hits production.** It reads the real mailbox, marks emails read, and writes to real SharePoint folders and logs. Don't run `bid_processor.py` locally without checking with Dawson first.
- There are no automated tests. Check changes by reading the code carefully, and watch the next run's output after deploying.
- **Deploy:** `deploy.bat`. It builds the image in Azure Container Registry `mjhughestickets` (`bids-processor:latest`) and starts the job `mjhughes-bids-job` in resource group `ticket-processor-rg`. It requires `az login` plus AcrPush/Contributor access. Deploy builds from the local folder, so `git pull` and commit first.
- View job runs/logs in the Azure Portal under the Container Apps job → Execution history.

## Working rules

- Multiple people edit this repo. Always `git pull` before making changes, and commit + push when done.
- Keep changes small and focused. Write commit messages that describe the behavior change.
- Graph drive paths must go through `_encode_drive_path` in `utils/sharepoint.py` (filenames can contain `#`, `%`, `?`).
- Graph list calls must follow `@odata.nextLink` pagination; don't assume one page.
- Bid matching in `bid_registry.py` deliberately ignores generic construction words (`GENERIC_JOB_WORDS`). Be careful loosening it, because false matches file quotes into the wrong bid.
