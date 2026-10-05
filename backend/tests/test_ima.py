"""IMA profiles: the agency brief is checked against its text, the brand searches, the pages to read, the inboxes. No live calls."""
from app.pipeline import audit, contacts, ima_brief
from app.pipeline.discovery import IMA_TEMPLATES, build_queries
from app.schemas import CampaignFilters

BRIEF = """Fylint is a creator agency. Sender: Nazmul Hasan. Website: https://fylint.com. Brand pays only when a deal closes.
Niches: AI tools, SaaS.
Creator: Sam Codes https://youtube.com/@samcodes. Niche AI tools. Average 45K views per video. Audience: United States, India.
Past sponsors: Notion. Open to deals now.
Creator: Lena Builds https://youtube.com/@lenabuilds. Niche SaaS."""


def ai(**kw):
    return {"agency": {"name": "Fylint", "sender_name": "Nazmul Hasan", "website": "https://fylint.com", "commission_model": "brand pays when a deal closes"},
            "niches": ["AI tools", "SaaS"], "roster": [], **kw}


def test_numbers_and_names_must_be_in_the_brief():
    out = ima_brief.normalize(ai(roster=[
        {"name": "Sam Codes", "channel_url": "https://youtube.com/@samcodes", "niche": "AI tools", "avg_views": "45K", "subscribers": "300K",
         "audience_countries": ["United States", "Narnia"], "past_sponsors": ["Notion", "Acme"], "open_to_deals": True},
    ]), BRIEF)
    c = out["roster"][0]
    assert c["avg_views"] == "45K"                        # written in the brief: kept
    assert c["subscribers"] == ""                         # not in the brief: dropped, never invented
    assert c["audience_countries"] == ["United States"]   # a country the brief does not name is dropped
    assert c["past_sponsors"] == ["Notion"]
    assert c["open_to_deals"] is True


def test_a_number_must_match_whole():
    assert ima_brief.numbers_in_text("45K", ima_brief._squash("avg 45K views"))
    assert not ima_brief.numbers_in_text("5K", ima_brief._squash("avg 45K views"))      # "5K" is not inside "45K"
    assert not ima_brief.numbers_in_text("10K", ima_brief._squash("avg 110K views"))
    assert ima_brief.numbers_in_text("120,000", ima_brief._squash("about 120000 views"))
    assert ima_brief.numbers_in_text("a lot", "")                                         # no number: nothing to check


def test_channel_link_and_website_must_be_in_the_brief():
    out = ima_brief.normalize(ai(roster=[{"name": "Sam", "channel_url": "https://youtube.com/@fake"}]), BRIEF)
    assert out["roster"][0]["channel_url"] == ""
    bad = ai()
    bad["agency"]["website"] = "https://other.com"
    assert ima_brief.normalize(bad, BRIEF)["agency"]["website"] == ""


def test_parsed_keeps_the_cv_keys():
    out = ima_brief.normalize(ai(roster=[{"name": "Sam Codes", "niche": "AI tools", "avg_views": "45K"}, {"name": "", "channel_url": ""}]), BRIEF)
    assert out["kind"] == "ima" and len(out["roster"]) == 1            # a block with no name and no link is dropped
    assert out["name"] == "Nazmul Hasan"                                 # the sender, like the name of a CV
    assert out["skills"] == ["AI tools", "SaaS"] and out["tools"] == []
    assert out["proof_points"] == ["Sam Codes, AI tools, 45K average views"]
    assert "Fylint" in out["headline"]


def test_no_niche_list_uses_the_roster_niches():
    out = ima_brief.normalize(ai(niches=[], roster=[{"name": "Sam", "niche": "AI tools"}]), BRIEF)
    assert out["niches"] == ["AI tools"]


# ---- brand searches ----

def filters(**kw):
    f = CampaignFilters().model_dump()
    f["company"].update(webKeywords=["ai writing tool", "note taking app"], **kw)
    return f


def test_brand_queries_are_creator_spend_searches():
    qs = build_queries(filters(), [], "ima")
    assert qs[0] == '"ai writing tool" "creator program"'
    assert '"note taking app" careers "creator partnerships"' in qs
    assert len(qs) == 2 * len(IMA_TEMPLATES) and len(set(qs)) == len(qs)
    assert not any("agency" in q for q in qs)                          # a brand search never looks for agencies
    assert qs[1] == '"note taking app" "creator program"'               # template by template: a small run covers every keyword


def test_brand_queries_have_no_country():
    assert build_queries(filters(anyCountry=False), [], "ima") == build_queries(filters(anyCountry=True), [], "ima")


def test_freelancer_queries_do_not_change():
    f = filters(anyCountry=True)
    assert build_queries(f, []) == build_queries(f, [], "freelancer") == ['"ai writing tool" agency', '"note taking app" agency']


# ---- pages to read ----

LINKS = ["/about", "/contact", "/careers", "/creators", "/blog", "/pricing"]


def test_brands_read_the_creator_page_first():
    kinds = [k for k, _ in audit.pick_pages("https://brand.com", LINKS, audit.PRIORITY_IMA)]
    assert kinds == ["creators", "about", "careers"]
    old = [k for k, _ in audit.pick_pages("https://brand.com", LINKS)]
    assert old == ["about", "contact", "careers"]                       # a freelancer profile reads what it read before


def test_affiliate_and_ambassador_pages_count_as_creator_pages():
    for path in ("/affiliates", "/ambassador-program", "/influencers", "/partner-program"):
        assert audit.pick_pages("https://b.com", [path], audit.PRIORITY_IMA)[0][0] == "creators"


# ---- inboxes ----

def test_creator_inboxes_only_for_ima():
    emails = [{"email": "creators@brand.com", "url": "https://brand.com/creators"}]
    assert contacts.match_email("", emails, True) is None
    m = contacts.match_email("", emails, True, contacts.GENERIC_IMA)
    assert m and m["kind"] == "generic"
    assert contacts.match_email("", emails, False, contacts.GENERIC_IMA) is None   # still needs allowGeneric


# ---- the lead sheet: no judge, no emails, one row per brand ----

from app.pipeline import brand_leads as bl, orchestrator
from app.routers import brand_leads as bl_router

COMPANY = {"id": "c1", "domain": "notion.so", "name": "Notion", "country": "United States", "size_estimate": 600, "source_url": "https://notion.so/creators",
           "keyword_hits": ["note taking app"], "facts": {"sells": "Notion is a connected workspace", "emails": [
               {"email": "partnerships@notion.so", "url": "https://notion.so/contact"}, {"email": "privacy@notion.so", "url": "https://notion.so/privacy"}]}}
EV = [{"signal_id": "s1", "kind": "manual_process", "quote": "Join the Notion creator program", "url": "https://notion.so/creators", "verified": True},
      {"signal_id": "s2", "kind": "manual_process", "quote": "Become an affiliate", "url": "https://notion.so/affiliates", "verified": True},
      {"signal_id": "s1", "kind": "tech", "quote": "hubspot", "url": "https://notion.so", "verified": True}]
NAMES = {"s1": "Creator program page", "s2": "Affiliate program"}


def test_email_found_is_good_to_go():
    person = {"name": "Ann Lee", "title": "Head of Partnerships", "email": "ann@notion.so", "email_source": "https://notion.so/team"}
    r = bl.build_row(COMPANY, person, EV, NAMES)
    assert r["type"] == "good to go"
    assert r["brand"] == "Notion" and r["brand_url"] == "https://notion.so" and r["website_url"] == "https://notion.so/creators"
    assert r["emails"] == "ann@notion.so; partnerships@notion.so"        # the contact first, then the rest. privacy@ is left out
    assert r["employees"] == "600" and r["category"] == "Notion is a connected workspace"
    assert r["creators"] == "Creator program page; Affiliate program"
    assert r["sponsorships"] == "“Join the Notion creator program” (https://notion.so/creators) | “Become an affiliate” (https://notion.so/affiliates)"
    assert r["proof_count"] == 2                                          # the tech fingerprint is not proof
    assert (r["contact_name"], r["contact_title"], r["email_source"]) == ("Ann Lee", "Head of Partnerships", "https://notion.so/team")


def test_no_email_is_kept_as_do_manually():
    c = {**COMPANY, "facts": {"sells": "", "emails": [{"email": "jobs@notion.so", "url": "x"}]}, "size_estimate": None, "source_url": None}
    r = bl.build_row(c, None, [], {})
    assert r["type"] == "do manually" and r["emails"] == ""                # jobs@ is not a contact
    assert r["employees"] == "" and r["category"] == "note taking app"     # no size on the site: empty. no 'sells': the keyword
    assert r["website_url"] == "https://notion.so" and r["proof_count"] == 0 and r["contact_name"] is None


def test_best_site_email_when_nobody_matched():
    facts = {"emails": [{"email": "hello@b.com", "url": "1"}, {"email": "creators@b.com", "url": "2"}, {"email": "x@b.com", "url": "3"}]}
    assert bl.first_site_email(facts)["email"] == "creators@b.com"          # an inbox made for creators first
    assert bl.first_site_email({"emails": [{"email": "x@b.com", "url": "3"}, {"email": "hello@b.com", "url": "1"}]})["email"] == "hello@b.com"
    assert bl.first_site_email({"emails": [{"email": "x@b.com", "url": "3"}]})["email"] == "x@b.com"
    assert bl.first_site_email({"emails": [{"email": "privacy@b.com", "url": "3"}]}) is None
    assert bl.first_site_email({}) is None


def test_csv_has_your_columns_in_order():
    rows = [{**bl.build_row(COMPANY, {"email": "ann@notion.so", "name": "Ann"}, EV, NAMES), "emails": "=bad@x.com"}]
    text = bl_router.make_csv(rows)
    header = text.splitlines()[0].split(",")
    assert header[:9] == ["website_url", "Brand", "brand_url", "category", "sponsorships", "creators", "Emails", "Employees", "type"]
    assert "'=bad@x.com" in text                                            # a cell that starts with = never runs as a formula


def test_ima_stops_after_the_brand_stage(monkeypatch):
    camp = {"profile_id": "p", "filters": {}}
    monkeypatch.setattr(orchestrator, "kind_of", lambda pid: "ima")
    assert list(orchestrator._work_stages("r", camp, lambda: False, None)) == ["audit", "extract", "contacts", "brand_leads"]
    assert orchestrator._lead_stages("r", camp, lambda: False, None) == {}   # no report, no demo, no emails
    monkeypatch.setattr(orchestrator, "kind_of", lambda pid: "freelancer")
    assert list(orchestrator._work_stages("r", camp, lambda: False, None)) == ["audit", "extract", "contacts", "judge"]
    assert list(orchestrator._lead_stages("r", camp, lambda: False, None)) == ["assets", "sequences"]


class _Rec:
    """A database that records updates and inserts. `people` is what the people table holds."""
    def __init__(self, people): self.people, self.log = people, []
    def table(self, name):
        rec = self
        class T:
            def __init__(s): s.op = None
            def select(s, *_): return s
            def eq(s, *_): return s
            def order(s, *_, **__): return s
            def update(s, row): s.op = ("update", name, row); return s
            def insert(s, row): s.op = ("insert", name, row); return s
            def execute(s):
                if s.op:
                    rec.log.append(s.op)
                return type("R", (), {"data": rec.people if name == "people" and not s.op else []})()
        return T()


def _contacts(monkeypatch, kind, facts, people, mx=True):
    import asyncio
    db = _Rec(people)
    monkeypatch.setattr(contacts, "get_db", lambda: db)
    monkeypatch.setattr(contacts, "kind_of", lambda pid: kind)
    monkeypatch.setattr(contacts, "scope_todo", lambda run_id, st, ids: [{"id": "c1", "domain": "brand.com", "name": "Brand", "facts": facts}])

    async def fake_mx(d): return mx
    monkeypatch.setattr(contacts, "mx_ok", fake_mx)
    f = CampaignFilters().model_dump()
    asyncio.run(contacts.run("r", {"filters": f, "profile_id": "p"}, lambda: False))
    return [op for op in db.log if op[1] == "companies"]


def test_ima_brand_with_no_email_is_kept(monkeypatch):
    ops = _contacts(monkeypatch, "ima", {"emails": []}, [])
    assert ops == [("update", "companies", {"status": "contacted", "fail_reason": None})]   # not no_contact: the sheet says "do manually"


def test_freelancer_with_no_email_is_still_dropped(monkeypatch):
    ops = _contacts(monkeypatch, "freelancer", {"emails": []}, [])
    assert ops[0][2]["status"] == "no_contact"


def test_ima_brand_uses_any_site_email(monkeypatch):
    db_ops = _contacts(monkeypatch, "ima", {"emails": [{"email": "x@brand.com", "url": "https://brand.com/contact"}]}, [])
    assert db_ops == [("update", "companies", {"status": "contacted"})]


def test_ima_email_that_cannot_receive_mail_is_do_manually(monkeypatch):
    ops = _contacts(monkeypatch, "ima", {"emails": [{"email": "x@brand.com", "url": "u"}]}, [], mx=False)
    assert ops == [("update", "companies", {"status": "contacted", "fail_reason": None})]
