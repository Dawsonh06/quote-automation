import anthropic
import base64
import os
from dotenv import load_dotenv

load_dotenv()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

def classify_email(subject, sender, body, attachments):
    """
    Returns one of: "quote", "itb", "other"
    Uses Haiku for speed and cost efficiency.
    """
    attachment_names = ", ".join([a["name"] for a in attachments]) if attachments else "none"

    prompt = f"""You are helping a construction company sort incoming bid-related emails.

Email details:
- Subject: {subject}
- From: {sender}
- Attachments: {attachment_names}
- Body preview: {body[:1000]}

Classify this email into exactly one of these categories:

"quote" - A subcontractor or supplier is submitting a price/bid for work on a specific project.
  Signs: attachment with pricing, mentions of unit prices or lump sums, scope of work described,
  phrases like "please find our quote", "we are pleased to offer", "our bid for"

"itb" - An invitation to bid. Someone is asking MJ Hughes to submit a price.
  Signs: from an owner/GC/agency, mentions bid due date, plan set attached,
  phrases like "invitation to bid", "request for proposal", "please submit your bid by"

"other" - Everything else. Addendum notices, questions, confirmations, newsletters,
  out of office replies, "are you bidding this?", plan room notifications without a bid request.

Respond with JSON only, no other text:
{{"classification": "quote" or "itb" or "other", "reasoning": "one sentence explanation"}}"""

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}]
    )

    import json
    text = response.content[0].text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    return json.loads(text)
