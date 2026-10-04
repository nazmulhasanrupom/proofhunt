def size_bucket(n: int | None) -> str:
    if not n:
        return "unknown"
    if n <= 10:
        return "1 - 10"
    if n <= 50:
        return "11 - 50"
    return "51+"


def apply_filters(company: dict, f: dict) -> str | None:
    """Return a reason string if the company must be dropped, else None."""
    c = f["company"]
    country = company.get("country")
    if country and c["countries"] and country not in c["countries"]:
        return f"country {country} not wanted"
    size = company.get("size_estimate")
    if size:
        if not any(lo <= size <= hi for lo, hi in c["employeeRanges"]):
            ranges = ", ".join(f"{lo}-{hi}" for lo, hi in c["employeeRanges"])
            return f"size {size} is outside the allowed ranges ({ranges})"
    elif not c["allowUnknownSize"]:
        return "size unknown (this campaign does not allow unknown size)"
    hits = len(company.get("keyword_hits") or [])
    if hits < c["minKeywordHits"]:
        return f"keyword hits {hits} < {c['minKeywordHits']}"
    return None
