import re

def generate_filename(category_short, vendor, total_price, original_name):
    def clean(text):
        text = str(text or "Unknown").strip()
        import re
        text = re.sub(r'[<>:"/\\|?*]', '', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text[:50]

    scope_clean = clean(category_short) if category_short else "UNKNOWN"
    vendor_clean = clean(vendor) if vendor else "Unknown Vendor"

    if total_price and str(total_price).replace('.','').isdigit():
        price_str = f"${int(float(total_price)):,}"
    else:
        price_str = "NoPrice"

    return f"{scope_clean} - {vendor_clean} - {price_str}.pdf"
