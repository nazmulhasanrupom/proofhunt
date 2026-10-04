"""Layer A: code checks (free, exact). Layer B: LLM extraction. Quote verification."""
import re

import tldextract

from ..services import llm
from .fingerprints import detect_tech, tech_in_text
from .verify import person_in_text, quote_in_text

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
OBFUSCATED_RE = re.compile(r"([a-zA-Z0-9._%+\-]+)\s*[\[\(]\s*at\s*[\]\)]\s*([a-zA-Z0-9\-\.]+?)\s*[\[\(]\s*dot\s*[\]\)]\s*([a-zA-Z]{2,})", re.I)
PHONE_RE = re.compile(r"\+\d[\d\s().\-]{8,16}\d")
UK_POSTCODE = re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b")
US_STATE_ZIP = re.compile(r",\s*([A-Z]{2})\s+\d{5}(?:-\d{4})?\b")
CA_PROVINCE = re.compile(r",\s*(AB|BC|MB|NB|NL|NS|ON|PE|QC|SK)\s+[A-Z]\d[A-Z]\s*\d[A-Z]\d\b")
AU_STATE = re.compile(r",?\s*(NSW|VIC|QLD|WA|SA|TAS|ACT|NT)\s+\d{4}\b")
COUNTRY_NAMES = {
    "united states": "United States", "usa": "United States", "u.s.a": "United States",
    "united kingdom": "United Kingdom", "england": "United Kingdom", "scotland": "United Kingdom", "wales": "United Kingdom",
    "canada": "Canada", "australia": "Australia",
}
TLD_COUNTRY = {"co.uk": "United Kingdom", "uk": "United Kingdom", "com.au": "Australia", "au": "Australia", "ca": "Canada"}
PHONE_COUNTRY = {"+44": "United Kingdom", "+61": "Australia"}
CITY_TZ_US = {"CA": "America/Los_Angeles", "WA": "America/Los_Angeles", "OR": "America/Los_Angeles", "NV": "America/Los_Angeles",
              "AZ": "America/Phoenix", "CO": "America/Denver", "UT": "America/Denver", "NM": "America/Denver",
              "TX": "America/Chicago", "IL": "America/Chicago", "MN": "America/Chicago", "MO": "America/Chicago"}


def find_emails(text: str, domain: str) -> list[str]:
    found = set(m.lower() for m in EMAIL_RE.findall(text))
    for u, d, tld in OBFUSCATED_RE.findall(text):
        found.add(f"{u}@{d}.{tld}".lower())
    # the company's own address. The same brand on another ending counts too (hallam.agency / hallam.co.uk),
    # a picture name like logo@2x.png or a gmail address does not
    own = tldextract.extract(domain).domain
    return sorted(e for e in found if tldextract.extract(e.split("@")[1]).domain == own)


def find_country(text: str, domain: str) -> tuple[str | None, str | None]:
    """Returns (country, us_state). Order: address text, phone code, domain ending."""
    state = None
    m = US_STATE_ZIP.search(text)
    if m:
        state = m.group(1)
        return "United States", state
    if CA_PROVINCE.search(text):
        return "Canada", None
    if AU_STATE.search(text):
        return "Australia", None
    if UK_POSTCODE.search(text):
        return "United Kingdom", None
    low = text.lower()
    for k, v in COUNTRY_NAMES.items():
        if re.search(rf"(?<![a-z]){re.escape(k)}(?![a-z])", low):
            return v, None
    for p in PHONE_RE.findall(text):
        p = re.sub(r"[\s().\-]", "", p)
        for code, c in PHONE_COUNTRY.items():
            if p.startswith(code):
                return c, None
    suffix = tldextract.extract(domain).suffix
    return TLD_COUNTRY.get(suffix), None


LINK_RE = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")


def clean_line(line: str) -> str:
    line = LINK_RE.sub(r"\1", line)
    line = re.sub(r"[*_`#>|\\]", " ", line)
    return re.sub(r"\s+", " ", line).strip(" -\u2022\u25cf")


def sentence_around(text: str, needle: str, min_words: int = 6, maxlen: int = 300) -> str | None:
    """First real sentence (not a menu link) that holds `needle`. None if there is none."""
    n = needle.lower()
    for line in text.splitlines():
        cl = clean_line(line)
        if n in cl.lower() and len(cl.split()) >= min_words:
            return cl[:maxlen]
    return None


def code_checks(domain: str, pages: list[dict], signals: list[dict], keywords: list[str]) -> dict:
    """pages: [{url, kind, markdown, raw_html}]. signals: signal rows (with detector_type, config)."""
    all_md = "\n".join(p["markdown"] or "" for p in pages)
    home = next((p for p in pages if p["kind"] == "home"), pages[0] if pages else None)
    raw = (home or {}).get("raw_html") or ""
    emails = []
    for p in pages:
        for e in find_emails((p["markdown"] or "") + "\n" + (raw if p is home else ""), domain):
            if not any(x["email"] == e for x in emails):
                emails.append({"email": e, "url": p["url"]})
    country, state = find_country(all_md, domain)
    low = all_md.lower()
    keyword_hits = [k for k in keywords if k.lower() in low]
    careers = [p for p in pages if p["kind"] == "careers"]
    year = re.findall(r"(?:©|&copy;|copyright)\s*(?:\d{4}\s*[-–]\s*)?(20\d{2})", all_md + raw, re.I)

    evidence = []
    for s in signals:
        t, cfg = s["detector_type"], s.get("config") or {}
        if t == "phrase":
            for ph in cfg.get("phrases", []):
                hit = next(((p, q) for p in pages if (q := sentence_around(p["markdown"] or "", ph))), None)
                if hit:
                    evidence.append({"signal_id": s["id"], "kind": "manual_process", "quote": hit[1], "url": hit[0]["url"]})
                    break
        elif t == "tech_absent":
            hay = all_md + raw
            if not any(tech_in_text(x, hay) for x in cfg.get("tech", [])) and home:
                evidence.append({"signal_id": s["id"], "kind": "tech",
                                 "quote": f"No sign of {', '.join(cfg.get('tech', []))} on the site",
                                 "url": home["url"], "code": True})
        elif t == "tech_present":
            hay = all_md + raw
            hit = next((x for x in cfg.get("tech", []) if tech_in_text(x, hay)), None)
            if hit and home:
                evidence.append({"signal_id": s["id"], "kind": "tech",
                                 "quote": f"Site uses {hit}", "url": home["url"], "code": True})
        elif t == "hiring_role" and careers:
            for role in cfg.get("roles", []):
                hit = next(((p, q) for p in careers if (q := sentence_around(p["markdown"] or "", role, 4))), None)
                if hit:
                    evidence.append({"signal_id": s["id"], "kind": "hiring", "quote": hit[1], "url": hit[0]["url"]})
                    break
    return {
        "emails": emails, "country": country, "us_state": state, "tech": detect_tech(raw),
        "keyword_hits": keyword_hits, "has_careers": bool(careers),
        "copyright_year": int(year[-1]) if year else None, "evidence": evidence,
    }


TEAM_LINE = re.compile(r"founder|owner|\bceo\b|\bcoo\b|\bcmo\b|managing director|director|head of|president|principal|partner|"
                       r"our team|meet the|meet our|leadership|employees|team members|staff|people", re.I)
KIND_WEIGHT = {"about": 3.0, "home": 2.0, "contact": 1.5, "careers": 1.5, "services": 1.0}
IMAGE_ONLY = re.compile(r"^\s*(!\[[^\]]*\]\([^)]*\)\s*)+$")


def compact(md: str) -> str:
    """Drop whole noise lines only (blank, image-only, repeated menu lines). Kept lines stay word for word,
    so a quote the model copies from here is still found in the saved page."""
    seen, out = set(), []
    for line in (md or "").splitlines():
        s = line.strip()
        if not s or IMAGE_ONLY.match(s):
            continue
        if len(s) < 120:
            if s in seen:
                continue
            seen.add(s)
        out.append(line.rstrip())
    return "\n".join(out)


def pick_text(text: str, budget: int) -> str:
    """Keep the start of the page, then the parts around names and job titles, until the budget is used."""
    if len(text) <= budget:
        return text
    lines = text.splitlines()
    head, used = [], 0
    for ln in lines:
        if used + len(ln) + 1 > budget * 0.4:
            break
        head.append(ln)
        used += len(ln) + 1
    keep = set(range(len(head)))
    for i, ln in enumerate(lines[len(head):], start=len(head)):
        if TEAM_LINE.search(ln):
            keep.update(range(max(len(head), i - 4), min(len(lines), i + 5)))
    out, size, last = [], 0, -2
    for i in sorted(keep):
        ln = lines[i]
        if size + len(ln) + 1 > budget:
            break
        if i != last + 1 and out:
            out.append("...")
        out.append(ln)
        size += len(ln) + 1
        last = i
    return "\n".join(out)


def build_llm_input(pages: list[dict], max_chars: int = 48000) -> str:
    """Give each page a share of the budget (the About page the biggest). A long page is cut to its start
    plus the parts about people, so the team section is not lost."""
    texts = [(p, compact(p["markdown"] or "")) for p in pages]
    todo = {i: KIND_WEIGHT.get(p.get("kind") or "", 1.0) for i, (p, _) in enumerate(texts)}
    share: dict[int, int] = {}
    remaining = max_chars
    for i in sorted(todo, key=lambda k: len(texts[k][1])):   # short pages first, they give back what they do not need
        w = todo[i] / sum(todo[j] for j in todo if j not in share)
        give = min(len(texts[i][1]), int(remaining * w))
        share[i] = give
        remaining -= give
    return "\n\n".join(f"### PAGE: {p['url']}\n{pick_text(t, share[i])}" for i, (p, t) in enumerate(texts))


from pydantic import BaseModel  # noqa: E402


class _Person(BaseModel):
    name: str = ""
    title: str = ""
    quote: str = ""
    url: str = ""


class _Role(BaseModel):
    role: str = ""
    quote: str = ""
    url: str = ""


class _Sig(BaseModel):
    signal_name: str = ""
    quote: str = ""
    url: str = ""


class ExtractOut(BaseModel):
    company_name: str = ""
    sells: str = ""
    serves: str = ""
    employee_estimate: int | None = None
    size_quote: str = ""
    people: list[_Person] = []
    hiring_roles: list[_Role] = []
    llm_signals: list[_Sig] = []
    country_guess: str = ""


async def llm_extract(pages: list[dict], llm_signals: list[dict], run_id: str | None) -> dict:
    task = ""
    if llm_signals:
        task = "LLM signals to look for (use exact names):\n" + "\n".join(
            f"- {s['name']}: {(s.get('config') or {}).get('question') or s.get('description') or ''}" for s in llm_signals) + "\n\n"
    return await llm.complete_json("extract", "fast", llm.load_prompt("extract"),
                                   task + build_llm_input(pages), ExtractOut, run_id)


def verify_items(items: list[dict], pages: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split items into (verified, dropped). Each item has quote + url."""
    by_url = {p["url"]: p["markdown"] or "" for p in pages}
    ok, bad = [], []
    for it in items:
        text = by_url.get(it.get("url"))
        texts = list(by_url.values()) if text is None else [text]   # url not exact: try all pages
        hit = any(quote_in_text(it.get("quote", ""), t) for t in texts)
        if not hit and it.get("name") and it.get("title"):
            hit = any(person_in_text(it["name"], it["title"], t) for t in texts)
        (ok if hit else bad).append(it)
    return ok, bad


# ---------- stage runner (touches the database) ----------
from ..db import get_db  # noqa: E402
from ..services.usage import BudgetExceeded, log_event  # noqa: E402
from .scope import todo as scope_todo  # noqa: E402
from .filters import apply_filters, size_bucket  # noqa: E402
from .offer_map import load_map  # noqa: E402


async def run(run_id: str, campaign: dict, should_stop, ids: list[str] | None = None):
    db = get_db()
    f = campaign["filters"]
    rows = [r for r in load_map(campaign["profile_id"]) if r["active"]]
    signals = [{**s, "offer_row_id": r["id"]} for r in rows for s in r["signals"] if s["active"]]
    code_signals = [s for s in signals if s["detector_type"] != "llm"]
    llm_signals = [s for s in signals if s["detector_type"] == "llm"]
    todo = scope_todo(run_id, ["audited"], ids)
    for c in todo:
        if should_stop():
            return
        pages = db.table("pages").select("url,kind,markdown,raw_html").eq("company_id", c["id"]).execute().data
        try:
            a = code_checks(c["domain"], pages, code_signals, f["company"]["webKeywords"])
            ex = await llm_extract(pages, llm_signals, run_id)
        except BudgetExceeded:
            raise  # a limit is not the company's fault: it stays 'audited' and is picked up next time
        except Exception as e:
            db.table("companies").update({"status": "failed", "fail_reason": f"extract error: {str(e)[:200]}"}).eq("id", c["id"]).execute()
            log_event(run_id, "error", "extract", f"{c['domain']}: {e}")
            continue

        # verify LLM quotes
        people, p_bad = verify_items(ex["people"], pages)
        roles, r_bad = verify_items(ex["hiring_roles"][:3], pages)  # cap: a careers page can list 20 roles
        lsigs, s_bad = verify_items(ex["llm_signals"], pages)
        for b in p_bad + r_bad + s_bad:
            log_event(run_id, "warn", "verify", f"{c['domain']}: quote not found, dropped", b)

        db.table("evidence").delete().eq("company_id", c["id"]).execute()
        db.table("people").delete().eq("company_id", c["id"]).execute()
        ev = [{**e, "company_id": c["id"], "verified": True} for e in a["evidence"]]
        for e in ev:
            e.pop("code", None)
        by_name = {s["name"].lower(): s["id"] for s in llm_signals}
        for r in roles:
            ev.append({"company_id": c["id"], "kind": "hiring", "quote": r["quote"], "url": r["url"], "verified": True})
        for s in lsigs:
            ev.append({"company_id": c["id"], "signal_id": by_name.get(s["signal_name"].lower()),
                       "kind": "other", "quote": s["quote"], "url": s["url"], "verified": True})
        if ev:
            db.table("evidence").insert(ev).execute()
        if people:
            db.table("people").insert([{"company_id": c["id"], "name": p["name"], "title": p["title"],
                                        "source": "website", "source_url": p["url"]} for p in people]).execute()

        size = ex["employee_estimate"]
        if size is not None and ex["size_quote"] and not verify_items([{"quote": ex["size_quote"], "url": ""}], pages)[0]:
            size = None  # size claim has no real quote
        if size is None and len(people) >= 3:  # one or two names do not tell the company size
            size = len(people)
        country = a["country"] or (ex["country_guess"] or None)
        upd = {
            "name": ex["company_name"] or c["name"], "country": country, "size_estimate": size,
            "size_bucket": size_bucket(size), "tech": a["tech"], "keyword_hits": a["keyword_hits"],
            "facts": {"sells": ex["sells"], "serves": ex["serves"], "emails": a["emails"],
                      "us_state": a["us_state"], "has_careers": a["has_careers"],
                      "copyright_year": a["copyright_year"],
                      "employee_estimate": ex["employee_estimate"], "size_quote": ex["size_quote"]},
            "status": "extracted",
        }
        reason = apply_filters({**c, **upd}, f)
        if reason:
            upd.update({"status": "filtered_out", "fail_reason": reason})
        db.table("companies").update(upd).eq("id", c["id"]).execute()
        why = f" ({reason}; campaign '{campaign.get('name')}')" if reason else ""
        log_event(run_id, "info", "extract", f"{c['domain']}: {upd['status']}{why}",
                  {"evidence": len(ev), "people": len(people), "country": country, "size": size})
