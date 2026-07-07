import anthropic
import base64
import json
import os
import re
from dotenv import load_dotenv

load_dotenv()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

def load_categories():
    import json, os
    path = os.path.join(os.path.dirname(__file__), "config", "vendor_categories.json")
    with open(path) as f:
        return json.load(f)


def match_and_extract(attachment, active_bids):
    """
    Takes a single PDF attachment and the active bid list.
    Returns match result with bid, confidence, vendor, category, price.
    """
    bid_summary = "\n".join([
        f"- Job name: \"{b['job_name']}\" | Match keywords: {', '.join(b['keywords'])}"
        for b in active_bids
    ])

    pdf_data = attachment["content_bytes"]

    categories = load_categories()
    category_list = "\n".join([f"- {c['long']} → use code: {c['short']}" for c in categories])

    prompt = f"""You are helping a construction company process incoming subcontractor quotes.

Active bids MJ Hughes is currently pursuing:
{bid_summary}

Analyze the attached PDF and return a JSON object with these fields:

- matched_bid: The exact job name string (only the part in quotes) from the list above that this quote is for, or null if you can't determine it
- confidence: "high" (document references this project by name, owner, project/contract number, or 2+ matching keywords),
              "medium" (some overlap with a bid's name/keywords/location/scope, but not a clean match),
              "low" (nothing in the document points to any active bid)
- vendor: Company name submitting the quote
- category_long: The full category name from this list that best describes what this vendor is quoting
- category_short: The corresponding short code for that category
- Both must come from this exact list — do not invent new categories:
{category_list}
- total_price: Total dollar amount as a number if there is one clear lump sum total, null if there are only unit prices, multiple alternates, or the total is unclear
- phone: Vendor phone number if visible on the document, null if not found
- location: Vendor city and state if visible on the document (e.g. "Portland, OR"), null if not found
- reasoning: One sentence explaining your match decision
- is_quote: true if this PDF contains pricing/scope of work, false if it is a supporting document (insurance cert, spec sheet, reference letter, etc.)

Rules:
- Construction quotes typically list the project name near the top of the document in formats like:
  "Project: ________", "Re: ________", "Job: ________", "Project Name: ________",
  "Attention: ________", or in a header/title block at the top of the page.
  Always check these fields first before looking elsewhere in the document.
- After finding the project name in the document, compare it against the active bid list
  using both the project name AND the keywords. A match on either is sufficient.
- Bid registry job names are often shortened, reordered, or phrased differently than the
  vendor's own document title (extra words like "Project", a project/bid number, a city name,
  or an owner's name added or dropped do NOT prevent a match). Match on the core distinguishing
  words and place names, not on exact phrasing. Do not require an exact or near-exact string match.
- Default to "high" confidence whenever the document's project name shares 2 or more significant
  words with an active bid's job name (or one of its keywords), even if extra words, a project
  number, or different word order are present. Example: a document titled "Westbrook Reservoirs
  Improvements Project #23873" IS a high-confidence match against an active bid named "Westbrook
  Reservoirs Improvements" or "Nob Hill Water — Westbrook Reservoirs" — the shared "Westbrook
  Reservoirs" is enough; the project number is not a mismatch.
- Use "medium" for weaker signals: matching location/owner/scope but no shared project-name words,
  or a single shared keyword.
- Only use "low" when you truly cannot connect the document to any bid on the list at all.
- When in doubt between two confidence levels, or between guessing a bid and returning null,
  prefer the higher confidence / the guess — a human reviews every "quote" either way, and a
  wrong guess is far cheaper than an obvious match getting dropped into the unmatched pile.
- If total_price is ambiguous, return null - do not guess.
- If no active bids match, return matched_bid as null and confidence as "low".
- Supporting documents (insurance certs, W9s, spec sheets) should have is_quote set to false.

Respond with JSON only, no other text."""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=500,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": pdf_data
                    }
                },
                {
                    "type": "text",
                    "text": prompt
                }
            ]
        }]
    )

    text = response.content[0].text.strip()
    # Strip markdown code fences if the model wrapped the JSON
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    return json.loads(text)


def match_email_body(subject, sender, body, active_bids):
    """Match a body-only quote email (no PDF attachment) to an active bid.

    Uses the email subject, sender, and body text instead of a PDF document.
    Returns the same structure as match_and_extract.
    """
    bid_summary = "\n".join([
        f"- Job name: \"{b['job_name']}\" | Match keywords: {', '.join(b['keywords'])}"
        for b in active_bids
    ])

    prompt = f"""You are helping a construction company process incoming subcontractor quotes.

Active bids MJ Hughes is currently pursuing:
{bid_summary}

Analyze this email and return a JSON object with these fields:

- matched_bid: The exact job name string (only the part in quotes) from the list above that this quote is for, or null if you can't determine it
- confidence: "high" (email references this project by name, owner, project/contract number, or 2+ matching keywords),
              "medium" (some overlap with a bid's name/keywords/location/scope, but not a clean match),
              "low" (nothing in the email points to any active bid)
- vendor: Company name submitting the quote
- scope: 3-6 word description of what they are quoting (e.g. "Concrete pumping services")
- total_price: Total dollar amount as a number if there is one clear lump sum, null otherwise
- reasoning: One sentence explaining your match decision
- is_quote: true if this email contains pricing or scope of work, false otherwise

Email details:
Subject: {subject}
From: {sender}
Body:
{body[:3000]}

Rules:
- Bid registry job names are often shortened, reordered, or phrased differently than how the
  sender refers to the project (extra words, a bid number, a city name, or an owner's name added
  or dropped do NOT prevent a match). Match on the core distinguishing words and place names, not
  on exact phrasing. Do not require an exact or near-exact string match.
- Default to "high" confidence whenever the email's subject or body shares 2 or more significant
  words with an active bid's job name (or one of its keywords), even with extra words or different
  word order present.
- Use "medium" for weaker signals: matching location/owner/scope but no shared project-name words,
  or a single shared keyword.
- Only use "low" when you truly cannot connect the email to any bid on the list at all.
- When in doubt between two confidence levels, or between guessing a bid and returning null,
  prefer the higher confidence / the guess — a human reviews every "quote" either way, and a
  wrong guess is far cheaper than an obvious match getting dropped into the unmatched pile.
- If no active bids match, return matched_bid as null and confidence as "low"

Respond with JSON only, no other text."""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}]
    )

    text = response.content[0].text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    return json.loads(text)


def process_all_attachments(attachments, active_bids):
    """
    Processes every PDF attachment in an email individually.
    Returns a list of results, one per attachment.
    """
    results = []

    for attachment in attachments:
        print(f"    Analyzing attachment: {attachment['name']}")
        try:
            result = match_and_extract(attachment, active_bids)
            result["original_filename"] = attachment["name"]
            results.append(result)
        except Exception as e:
            print(f"    ERROR on {attachment['name']}: {e}")
            results.append({
                "original_filename": attachment["name"],
                "matched_bid": None,
                "confidence": "low",
                "vendor": "Unknown",
                "category_long": "Unknown",
                "category_short": "Unknown",
                "total_price": None,
                "is_quote": True,
                "reasoning": f"Processing error: {str(e)}"
            })

    return results
