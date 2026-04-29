import re

def generate_filename(scope, vendor, total_price, original_name):
    """
    Generates a clean filename like:
    Concrete Pumping - Ralphs Concrete - $48500.pdf
    Rebar Supply - Harris Rebar - NoPrice.pdf
    """
    def clean(text):
        text = str(text or "Unknown").strip()
        # Remove characters not safe for filenames
        text = re.sub(r'[<>:"/\\|?*]', '', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text[:50]  # cap length

    scope_clean = clean(scope) if scope else "Unknown Scope"
    vendor_clean = clean(vendor) if vendor else "Unknown Vendor"

    if total_price and str(total_price).replace('.', '').isdigit():
        price_str = f"${int(float(total_price)):,}"
    else:
        price_str = "NoPrice"

    return f"{scope_clean} - {vendor_clean} - {price_str}.pdf"
