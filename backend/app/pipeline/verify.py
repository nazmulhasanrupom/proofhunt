import re


def normalize(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"[*_`#>\[\]()|~\\]", " ", s)
    s = s.replace("’", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", s).strip()


def quote_in_text(quote: str, page_text: str) -> bool:
    q = normalize(quote)
    return bool(q) and q in normalize(page_text)
