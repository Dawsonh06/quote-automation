import anthropic
import base64
import json
import os
import re
from dotenv import load_dotenv

load_dotenv()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

def match_and_extract(attachment, active_bids):
    """
    Takes a single PDF attachment and the active bid list.
    Returns match result with bid, confidence, vendor, scope, price.
    """
    bid_summary = "\n".join([
        f"- Job name: \"{b['job_name']}\" | Match keywords: {', '.join(b['keywords'])}"
        for b in active_bids
    ])

    pdf_data = attachment["content_bytes"]

    prompt = f"""You are helping a construction company process incoming subcontractor quotes.

Active bids MJ Hughes is currently pursuing:
{bid_summary}

Analyze the attached PDF and return a JSON object with these fields:

- matched_bid: The exact job name string (only the part in quotes) from the list above that this quote is for, or null if you can't determine it
- confidence: "high" (document clearly references this project by name, owner, or unique identifier),
              "medium" (likely match based on location/scope but not explicitly named),
              "low" (can't confidently match to any active bid)
- vendor: Company name submitting the quote
- scope: 3-6 word description of what they are quoting (e.g. "Concrete pumping services", "Rebar supply and installation")
- total_price: Total dollar amount as a number if there is one clear lump sum total, null if there are only unit prices, multiple alternates, or the total is unclear
- reasoning: One sentence explaining your match decision
- is_quote: true if this PDF contains pricing/scope of work, false if it is a supporting document (insurance cert, spec sheet, reference letter, etc.)

Rules:
- Only return "high" confidence if the document contains the project name, owner name, contract number, or a keyword that uniquely identifies one of the active bids
- If total_price is ambiguous, return null - do not guess
- If no active bids match, return matched_bid as null and confidence as "low"
- Supporting documents (insurance certs, W9s, spec sheets) should have is_quote set to false

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
- confidence: "high" (email clearly references this project by name, owner, or unique identifier),
              "medium" (likely match based on location/scope but not explicitly named),
              "low" (can't confidently match to any active bid)
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
- Only return "high" confidence if the email contains the project name, owner name, or a keyword that uniquely identifies one of the active bids
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
                "scope": "Unknown",
                "total_price": None,
                "is_quote": True,
                "reasoning": f"Processing error: {str(e)}"
            })

    return results
