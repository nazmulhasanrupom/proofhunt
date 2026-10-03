import json
import random
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from app.pipeline.contacts import has_word, match_email, pick_person, seniority
from app.pipeline.discovery import clean_domains, main_domain
from app.pipeline.extract import code_checks, find_country, find_emails, verify_items
from app.pipeline.filters import apply_filters
from app.pipeline.judge import enforce_rules
from app.pipeline.sequences import OPTOUT, check_email
from app.pipeline.audit import pick_pages
from app.pipeline.verify import quote_in_text
from app.schemas import CampaignFilters
from app.sending import scheduler as sch
from app.sending import tracker as trk

PF = CampaignFilters().person.model_dump()
FIX = Path(__file__).parent / "fixtures"


def test_domain_and_blocklist():
    assert main_domain("https://blog.agency.co.uk/x") == "agency.co.uk"
    out = clean_domains([{"url": "https://clutch.co/a"}, {"url": "https://www.foo.com/"}, {"url": "https://foo.com/b"}], {"bar.com"})
    assert [o["domain"] for o in out] == ["foo.com"]


def test_title_words():
    assert not has_word("Project Coordinator", "coo")
    assert has_word("COO", "coo")
    for t in ("Co-Founder", "cofounder", "Co Founder"):
        assert has_word(t, "co-founder")


def test_seniority_and_pick():
    assert seniority("Vice President of Sales") == "head"
    assert seniority("Junior Designer") == "entry"
    assert seniority("Managing Director") == "owner"
    people = [{"name": "A B", "title": "Project Coordinator"}, {"name": "C D", "title": "COO"},
              {"name": "E F", "title": "Founder"}, {"name": "G H", "title": "Intern Founder"}]
    assert pick_person(people, PF)["name"] == "E F"
    assert pick_person([{"name": "A", "title": "Designer"}], PF) is None


def test_email_match():
    emails = [{"email": "info@x.com", "url": "u"}, {"email": "jane.doe@x.com", "url": "u2"}, {"email": "support@x.com", "url": "u"}]
    assert match_email("Jane Doe", emails, True)["kind"] == "personal"
    assert match_email("Bob Roe", emails, True)["email"] == "info@x.com"
    assert match_email("Bob Roe", [{"email": "support@x.com", "url": "u"}], True) is None
    assert match_email("Bob Roe", emails, False) is None


def test_verify():
    page = "We are **a small** agency.\n\nOur founder, Jane   Doe."
    assert quote_in_text("a small agency", page)
    assert not quote_in_text("a huge agency", page)
    ok, bad = verify_items([{"quote": "Jane Doe", "url": "u"}, {"quote": "nope", "url": "u"}], [{"url": "u", "markdown": page}])
    assert len(ok) == 1 and len(bad) == 1


def test_extract_basics():
    assert find_emails("write jane [at] x [dot] com or bob@gmail.com or hi@x.com", "x.com") == ["hi@x.com", "jane@x.com"]
    assert find_country("Office, Austin, TX 78701", "x.com") == ("United States", "TX")
    assert find_country("London EC1A 1BB", "x.com")[0] == "United Kingdom"
    pages = [{"url": "https://x.com", "kind": "home", "markdown": "[Monthly Report](https://x.com/r)\n\nWe build monthly report decks for our clients every week. Email hi@x.com", "raw_html": "<script src=wp-content>"},
             {"url": "https://x.com/careers", "kind": "careers", "markdown": "We are hiring a Content Writer to join our team today\nApply now", "raw_html": None}]
    sigs = [{"id": "1", "detector_type": "phrase", "config": {"phrases": ["monthly report"]}},
            {"id": "2", "detector_type": "tech_absent", "config": {"tech": ["dashthis"]}},
            {"id": "3", "detector_type": "hiring_role", "config": {"roles": ["content writer"]}}]
    r = code_checks("x.com", pages, sigs, ["decks"])
    assert len(r["evidence"]) == 3 and r["keyword_hits"] == ["decks"] and r["tech"].get("wordpress")


def test_filters():
    f = CampaignFilters().model_dump()
    base = {"country": "Canada", "size_estimate": 5, "keyword_hits": ["a"]}
    assert apply_filters(base, f) is None
    assert apply_filters({**base, "country": "France"}, f)
    assert apply_filters({**base, "size_estimate": 200}, f)
    assert apply_filters({**base, "keyword_hits": []}, f)


def test_judge_rules():
    o = enforce_rules({"fit_score": 90, "offer_row_id": "r1", "evidence_ids": ["zzz"]}, {"a"}, {"r1"})
    assert o["fit_score"] == 40 and o["evidence_ids"] == []


def test_email_checks():
    good = {"step": 0, "subject": "monthly reports", "body": "Hi Jane, Acme does X.\n" + OPTOUT, "evidence_ids": ["a"]}
    assert check_email(good, "Acme", {"a"}) == []
    bad = {"step": 1, "subject": "Re", "body": "synergy {name} http://a.com http://b.com " + "w " * 90, "evidence_ids": ["q"]}
    assert len(check_email(bad, "Acme", {"a"})) >= 5


def test_pick_pages():
    links = ["/about-us", "https://x.com/contact", "https://other.com/careers", "/careers", "/services/seo", "/team"]
    kinds = [k for k, _ in pick_pages("https://x.com", links)]
    assert kinds == ["about", "contact", "careers"]


def utc(*a):
    return datetime(*a, tzinfo=timezone.utc)


def test_scheduler_rules():
    # warm-up: 10 before any real send, +5 per full week, never above the cap
    now = utc(2026, 10, 5, 12)
    assert sch.warmup_cap(20, True, None, now) == 10
    assert sch.warmup_cap(20, True, now - timedelta(days=15), now) == 20
    assert sch.warmup_cap(40, True, now - timedelta(days=15), now) == 20
    assert sch.warmup_cap(40, False, None, now) == 40 and sch.warmup_cap(99, False, None, now) == 50
    # gap: stable for one last-send time, always inside [min, max]
    last = utc(2026, 10, 5, 12)
    g = sch.gap_seconds(last, 180, 540)
    assert g == sch.gap_seconds(last, 180, 540) and 180 <= g <= 540
    # business days skip the weekend: Fri + 3 = Wed, Thu + 4 = Wed
    assert sch.add_business_days(date(2026, 10, 2), 3) == date(2026, 10, 7)
    assert sch.add_business_days(date(2026, 10, 1), 4) == date(2026, 10, 7)
    # window in the lead's zone (New York is UTC-4 in October): 9:00-16:30 local
    s, e = time(9), time(16, 30)
    assert sch.in_window(utc(2026, 10, 5, 14), "America/New_York", s, e)       # Mon 10:00 local
    assert not sch.in_window(utc(2026, 10, 5, 12), "America/New_York", s, e)   # Mon 08:00 local
    assert not sch.in_window(utc(2026, 10, 5, 21), "America/New_York", s, e)   # Mon 17:00 local
    assert not sch.in_window(utc(2026, 10, 3, 15), "America/New_York", s, e)   # Saturday
    rng = random.Random(1)
    for at in (utc(2026, 10, 5, 21), utc(2026, 10, 3, 15), utc(2026, 10, 5, 12)):  # after, weekend, before
        nxt = sch.next_slot(at, "America/New_York", s, e, rng)
        assert nxt > at and sch.in_window(nxt, "America/New_York", s, e)
        assert nxt - at < timedelta(days=3, hours=3)
    # follow-up: Fri 10:00 local + 3 business days = Wed 10:00 local, already in the window
    fri = utc(2026, 10, 2, 14)
    assert sch.followup_time(fri, 3, "America/New_York", s, e, rng) == utc(2026, 10, 7, 14)
    # bounce pause: 4 bounces in 24 h pause until the 4th newest is 24 h old
    bs = [utc(2026, 10, 5, h) for h in (8, 9, 10, 11)]
    assert sch.bounce_pause_until(bs[:3], utc(2026, 10, 5, 12)) is None
    assert sch.bounce_pause_until(bs, utc(2026, 10, 5, 12)) == utc(2026, 10, 6, 8)
    # blocked: exact email or whole domain
    assert sch.is_blocked("A@x.com", {"a@x.com"}) and sch.is_blocked("b@x.com", {"x.com"})
    assert not sch.is_blocked("b@y.com", {"x.com"})


def test_reply_detection():
    fx = json.loads((FIX / "gmail_thread.json").read_text())
    new = trk.find_new_replies(fx["thread"], "ME@gmail.com", set())
    assert [m["id"] for m in new] == ["m2", "m4"]            # not my own mail, not the bounce daemon
    assert [m["id"] for m in trk.find_new_replies(fx["thread"], "me@gmail.com", {"m2"})] == ["m4"]
    text = trk.extract_text(fx["reply_full"])
    assert text.startswith("No thanks") and "wrote:" in text
    assert trk.clean_reply(text) == "No thanks"               # the quoted history is gone
    assert trk.extract_text({"payload": {"mimeType": "text/html", "body": {"data": fx["reply_full"]["payload"]["parts"][1]["body"]["data"]}}}) == "No thanks"


def test_optout_and_bounce():
    for t in ("No", "no thanks", "Please stop", "Remove me from your list", "unsubscribe", "Stop emailing me"):
        assert trk.looks_like_optout(t), t
    for t in ("No problem, send the report", "Sounds good, let's talk Tuesday", "Not now, maybe next quarter",
              "Thanks for reaching out. We have no budget at the moment but I will keep you in mind."):
        assert not trk.looks_like_optout(t), t
    fx = json.loads((FIX / "gmail_thread.json").read_text())
    assert trk.parse_bounce("Delivery Status Notification (Failure)", fx["bounce_text"], {"jane@acme.com"}) == ("jane@acme.com", True)
    assert trk.parse_bounce("Delivery Status Notification (Failure)", fx["bounce_text"], {"other@x.com"})[0] is None
    assert trk.parse_bounce("Delivery Status Notification (Delay)", fx["bounce_text"], {"jane@acme.com"})[0] is None
    assert trk.parse_bounce("Undelivered", "mailbox full\nStatus: 4.2.2 jane@acme.com", {"jane@acme.com"}) == ("jane@acme.com", False)
