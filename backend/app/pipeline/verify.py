import re


def normalize(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"[*_`#>\[\]()|~\\]", " ", s)
    s = s.replace("’", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", s).strip()


def person_in_text(name: str, title: str, page_text: str) -> bool:
    """A team page often puts an image or a link between the name and the title, so the model's quote is not
    one clean line. The person still counts when the name is on the page and the title words stand close by."""
    n, txt = normalize(name), normalize(page_text)
    words = {w for w in re.findall(r"[a-z]+", normalize(title)) if len(w) >= 3}
    if not n or not words:
        return False
    i = txt.find(n)
    while i != -1:
        near = set(re.findall(r"[a-z]+", txt[max(0, i - 300): i + len(n) + 300]))
        if words <= near:
            return True
        i = txt.find(n, i + 1)
    return False


def quote_in_text(quote: str, page_text: str) -> bool:
    q = normalize(quote)
    return bool(q) and q in normalize(page_text)
