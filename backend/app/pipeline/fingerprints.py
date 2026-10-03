"""Tech fingerprints: name -> substrings searched in homepage rawHtml (lowercase)."""
FINGERPRINTS: dict[str, list[str]] = {
    # CRM / marketing
    "hubspot": ["js.hs-scripts.com", "hs-analytics", "hubspot.com"],
    "pipedrive": ["pipedrive"],
    "activecampaign": ["activecampaign"],
    "mailchimp": ["mailchimp", "chimpstatic"],
    "klaviyo": ["klaviyo"],
    # booking
    "calendly": ["calendly.com"],
    "acuityscheduling": ["acuityscheduling"],
    "hubspot meetings": ["meetings.hubspot.com"],
    "tidycal": ["tidycal"],
    "savvycal": ["savvycal"],
    # chat
    "intercom": ["intercom"],
    "crisp": ["crisp.chat"],
    "tawk": ["tawk.to"],
    "drift": ["js.driftt.com", "drift.com"],
    "livechat": ["livechatinc"],
    "tidio": ["tidio"],
    # forms
    "typeform": ["typeform"],
    "jotform": ["jotform"],
    "gravityforms": ["gravityforms", "gform_"],
    "wpforms": ["wpforms"],
    "hubspot forms": ["forms.hsforms"],
    # platform
    "wordpress": ["wp-content"],
    "webflow": ["webflow"],
    "wix": ["wixstatic", "wix.com"],
    "squarespace": ["squarespace"],
    "framer": ["framer.com", "framerusercontent"],
    # reporting tools
    "agencyanalytics": ["agencyanalytics"],
    "dashthis": ["dashthis"],
    "whatagraph": ["whatagraph"],
    "swydo": ["swydo"],
    "looker studio": ["lookerstudio.google.com", "datastudio.google.com"],
    # analytics
    "gtag": ["gtag("],
    "googletagmanager": ["googletagmanager"],
    "hotjar": ["hotjar"],
}


def detect_tech(raw_html: str) -> dict[str, bool]:
    h = (raw_html or "").lower()
    return {name: any(s in h for s in subs) for name, subs in FINGERPRINTS.items() if any(s in h for s in subs)}


def tech_in_text(name: str, haystack: str) -> bool:
    """A tech name from a signal config: use fingerprints if known, else plain substring."""
    import re
    n = name.lower().strip()
    h = haystack.lower()
    subs = FINGERPRINTS.get(n, [])
    whole = re.search(rf"(?<![a-z0-9]){re.escape(n)}(?![a-z0-9])", h) is not None  # "make" must not match "makeup"
    return whole or any(s in h for s in subs)
