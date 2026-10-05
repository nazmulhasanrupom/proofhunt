"""Phase 9 checks: budget stops, config, login guard, stats helpers. No live calls."""
import pytest

from app import main
from app.config import Settings
from app.routers import stats
from app.services import usage


class FakeTable:
    def __init__(self, row): self.row = row
    def select(self, *_): return self
    def eq(self, *_): return self
    def single(self): return self
    def execute(self):
        class R: pass
        r = R(); r.data = self.row
        return r


class FakeDb:
    def __init__(self, tables): self.tables = tables
    def table(self, name): return FakeTable(self.tables[name])


def test_empty_dev_limits_mean_no_limit(monkeypatch):
    monkeypatch.setenv("DEV_FIRECRAWL_CREDIT_LIMIT", "")
    monkeypatch.setenv("DEV_LLM_CALL_LIMIT", " ")
    s = Settings(_env_file=None)
    assert s.dev_firecrawl_credit_limit is None and s.dev_llm_call_limit is None


def test_credit_budget_stops(monkeypatch):
    monkeypatch.setattr(usage.settings, "dev_firecrawl_credit_limit", 150)
    monkeypatch.setattr(usage, "total_usage", lambda: {"credits": 148, "calls": 0})
    monkeypatch.setattr(usage, "get_db", lambda: FakeDb({"runs": {"credits_used": 0, "campaign_id": "c"}, "campaigns": {"filters": {}}}))
    usage.check_credit_budget(2)                      # exactly at the limit: allowed
    with pytest.raises(usage.BudgetExceeded):
        usage.check_credit_budget(3)                  # over: stop
    monkeypatch.setattr(usage.settings, "dev_firecrawl_credit_limit", None)
    usage.check_credit_budget(10_000)                 # limit cleared: no stop


def test_per_run_credit_cap(monkeypatch):
    monkeypatch.setattr(usage.settings, "dev_firecrawl_credit_limit", None)
    monkeypatch.setattr(usage, "get_db", lambda: FakeDb({"runs": {"credits_used": 38, "campaign_id": "c"},
                                                          "campaigns": {"filters": {"maxCreditsPerRun": 40}}}))
    usage.check_credit_budget(2, "r")
    with pytest.raises(usage.BudgetExceeded):
        usage.check_credit_budget(3, "r")


def test_llm_budget_stops(monkeypatch):
    monkeypatch.setattr(usage.settings, "dev_llm_call_limit", 100)
    monkeypatch.setattr(usage, "total_usage", lambda: {"credits": 0, "calls": 99})
    usage.check_llm_budget()
    monkeypatch.setattr(usage, "total_usage", lambda: {"credits": 0, "calls": 100})
    with pytest.raises(usage.BudgetExceeded):
        usage.check_llm_budget()


def test_password_check(monkeypatch):
    monkeypatch.setattr(main.settings, "access_password", "s3cret")
    assert main.password_ok("Bearer s3cret")
    assert main.password_ok("bearer s3cret")
    assert not main.password_ok("Bearer wrong")
    assert not main.password_ok("s3cret")             # needs the Bearer word
    assert not main.password_ok("")


def test_stats_helpers():
    assert stats._band(85) == "80+" and stats._band(70) == "70-79" and stats._band(10) == "under 60" and stats._band(None) == "under 60"
    rows = stats._rates({"a": [4, 1], "b": [2, 2], "c": [0, 0]})
    assert [r["key"] for r in rows] == ["b", "a", "c"]   # best rate first
    assert rows[0]["rate"] == 1.0 and rows[2]["rate"] == 0   # no division by zero


def test_secret_key_errors(monkeypatch):
    from cryptography.fernet import Fernet
    from app.services import gmail
    monkeypatch.setattr(gmail.settings, "app_secret_key", "not-a-key")
    with pytest.raises(gmail.GmailError):
        gmail.encrypt("x")
    good, other = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    monkeypatch.setattr(gmail.settings, "app_secret_key", good)
    saved = gmail.encrypt("refresh-token")
    assert gmail.decrypt(saved) == "refresh-token"
    monkeypatch.setattr(gmail.settings, "app_secret_key", other)   # key changed
    with pytest.raises(gmail.GmailAuthError):
        gmail.decrypt(saved)


def _stage_db(used: dict, filters: dict):
    return FakeDb({"runs": {"stage": "audit", "campaign_id": "c", "counters": {"stage_usage": {"audit": used}}},
                   "campaigns": {"filters": filters}})


def test_stage_limit_moves_on_not_pauses(monkeypatch):
    monkeypatch.setattr(usage.settings, "dev_firecrawl_credit_limit", None)
    monkeypatch.setattr(usage, "get_db", lambda: _stage_db({"credits": 98}, {"maxCreditsPerStage": 100}))
    usage.check_credit_budget(2, "r")                       # exactly at the stage limit: allowed
    with pytest.raises(usage.StageLimitReached) as e:
        usage.check_credit_budget(3, "r")
    assert isinstance(e.value, usage.BudgetExceeded)          # old code that re-raises BudgetExceeded still works
    assert e.value.stage == "audit" and e.value.limit == 100


def test_stage_llm_limit_and_fresh_stage(monkeypatch):
    monkeypatch.setattr(usage.settings, "dev_llm_call_limit", None)
    monkeypatch.setattr(usage, "get_db", lambda: _stage_db({"llm_calls": 5}, {"maxLlmCallsPerStage": 5}))
    with pytest.raises(usage.StageLimitReached):
        usage.check_llm_budget("r")
    # another stage has used nothing, so it has its own full limit
    db = FakeDb({"runs": {"stage": "judge", "campaign_id": "c", "counters": {"stage_usage": {"audit": {"llm_calls": 5}}}},
                 "campaigns": {"filters": {"maxLlmCallsPerStage": 5}}})
    monkeypatch.setattr(usage, "get_db", lambda: db)
    usage.check_llm_budget("r")


def test_old_campaign_gets_default_stage_limits():
    from app.schemas import CampaignFilters
    old = {"leadsWanted": 10, "maxCompaniesToScan": 3, "maxCreditsPerRun": 40}   # saved before the new fields existed
    f = CampaignFilters.model_validate(old)
    assert f.maxCreditsPerStage == 500 and f.maxLlmCallsPerStage == 300


def test_rewrite_keeps_optout_and_signature():
    from app.pipeline import rewrite
    from app.pipeline.sequences import OPTOUT
    body = f"Hi Sam, Acme writes city pages by hand.\n\nWant the report?\n\n{OPTOUT}\n\nJane Doe\n1 Main St"
    core, tail = rewrite.split_body(body)
    assert core.endswith("Want the report?") and tail.startswith(OPTOUT) and tail.endswith("1 Main St")
    new = rewrite.join_body("New text about Acme.", tail)
    assert new.endswith(tail) and "New text about Acme." in new
    assert rewrite.warnings_for(0, "city pages", new, "Acme", []) == []
    assert any("company name" in w for w in rewrite.warnings_for(0, "city pages", new.replace("Acme", "they"), "Acme", []))
    assert rewrite.join_body("x", "").endswith(OPTOUT)       # opt-out line was removed by hand: it comes back


def test_firecrawl_backoff_and_pacing(monkeypatch):
    import asyncio, time
    from app.services import firecrawl as fc
    assert fc.backoff_seconds(0, None) == 5 and fc.backoff_seconds(1, None) == 10 and fc.backoff_seconds(2, None) == 20
    assert fc.backoff_seconds(0, 30) == 30                  # Firecrawl's own hint wins when longer
    assert fc.backoff_seconds(9, None) == 90                # never more than 90 s

    monkeypatch.setattr(fc.settings, "firecrawl_min_interval", 0.1)
    monkeypatch.setattr(fc, "_interval", 0.0)
    monkeypatch.setattr(fc, "_next_at", 0.0)

    async def three():
        t = time.monotonic()
        await asyncio.gather(fc._pace(), fc._pace(), fc._pace())
        return time.monotonic() - t
    assert asyncio.run(three()) >= 0.19                     # three callers leave 0.1 s apart, not at once

    fc._slow_down(0)                                        # a 429: the gap grows
    assert fc._interval > 0.1
    before = fc._interval
    fc._speed_up()
    assert 0.1 <= fc._interval < before                     # and shrinks again after a success


# ---- Crawl4AI reader, text for the AI, contacts, filters ----

def _crawl_item(**kw):
    base = {"success": True, "status_code": 200, "redirected_status_code": 200, "html": "<html>x</html>",
            "links": {"internal": [{"href": "https://a.com/about"}, {"href": "https://a.com/x["}, {"href": "https://a.com/y#top"}]},
            "markdown": {"raw_markdown": "raw " * 60, "fit_markdown": "fit " * 60}}
    return {**base, **kw}


def test_crawl4ai_parse():
    from app.services import crawl4ai as c4
    out = c4.parse_crawl(_crawl_item(), main_only=True)
    assert out["markdown"].startswith("fit") and out["links"] == ["https://a.com/about"] and out["raw_html"]
    assert c4.parse_crawl(_crawl_item(), main_only=False)["markdown"].startswith("raw")
    with pytest.raises(c4.PageGone):                       # the site says 404: do not pay another reader for the same answer
        c4.parse_crawl(_crawl_item(redirected_status_code=404, status_code=301), True)
    with pytest.raises(c4.Crawl4aiError) as e:             # 403 / empty page: Firecrawl may do better
        c4.parse_crawl(_crawl_item(status_code=403, redirected_status_code=403), True)
    assert not isinstance(e.value, c4.PageGone)
    with pytest.raises(c4.Crawl4aiError):
        c4.parse_crawl(_crawl_item(markdown={"raw_markdown": "tiny", "fit_markdown": ""}), False)
    md_only = _crawl_item(links={}, markdown={"raw_markdown": "see [about](https://a.com/about) and [home](/) " + "x" * 120, "fit_markdown": ""})
    assert c4.parse_crawl(md_only, False)["links"] == ["https://a.com/about", "/"]


def test_scraper_falls_back_to_firecrawl(monkeypatch):
    import asyncio
    from app.services import scraper, crawl4ai as c4, firecrawl as fc

    class Saved:
        def __init__(self): self.rows = []
        def table(self, _): return self
        def select(self, *_): return self
        def eq(self, *_): return self
        def gte(self, *_): return self
        def limit(self, *_): return self
        def upsert(self, row, **_): self.rows.append(row); return self
        def execute(self):
            class R: data = []
            return R()
    db = Saved()
    monkeypatch.setattr(scraper, "get_db", lambda: db)
    monkeypatch.setattr(scraper, "log_event", lambda *a, **k: None)
    monkeypatch.setattr(c4, "enabled", lambda: True)
    calls = []

    async def fc_fetch(url, formats, main, run_id=None):
        calls.append("firecrawl")
        return {"markdown": "from firecrawl " * 20, "links": [], "raw_html": None, "status": 200, "cached": False}
    monkeypatch.setattr(fc, "fetch", fc_fetch)

    async def c4_ok(url, main):
        calls.append("crawl4ai")
        return {"markdown": "from crawl4ai " * 20, "links": [], "raw_html": "<h>", "status": 200, "cached": False}
    monkeypatch.setattr(c4, "fetch", c4_ok)
    r = asyncio.run(scraper.scrape("https://a.com", [], False, "cid", "home"))
    assert calls == ["crawl4ai"] and r["source"] == "crawl4ai" and db.rows[-1]["raw_html"] == "<h>"

    async def c4_fail(url, main):
        raise c4.Crawl4aiError("timeout")
    monkeypatch.setattr(c4, "fetch", c4_fail)
    calls.clear()
    r = asyncio.run(scraper.scrape("https://a.com", [], False, "cid", "about"))
    assert calls == ["firecrawl"] and r["source"] == "firecrawl"

    async def c4_gone(url, main):
        raise c4.PageGone("page returned HTTP 404")
    monkeypatch.setattr(c4, "fetch", c4_gone)
    calls.clear()
    with pytest.raises(fc.ScrapeError):
        asyncio.run(scraper.scrape("https://a.com/nope", [], False, "cid", "about"))
    assert calls == []                                      # no credit spent on a real 404


def test_team_section_is_not_cut_off():
    from app.pipeline.extract import build_llm_input
    filler = "\n".join(f"Service line number {i} about our work and pricing" for i in range(3000))   # a very long page
    about = filler + "\n\n## Our team\n\nJane Doe\n\nFounder & CEO\n"
    out = build_llm_input([{"url": "https://a.com", "kind": "home", "markdown": filler},
                           {"url": "https://a.com/about", "kind": "about", "markdown": about}])
    assert "Jane Doe" in out and "Founder & CEO" in out     # old code kept only the first 12000 characters of each page
    assert len(out) < 50000


def test_compaction_keeps_lines_word_for_word():
    from app.pipeline.extract import compact
    md = "Menu\n\n![logo](x.png)\n\nMenu\n[Jane Doe](/jane) CEO\n\n\nMenu"
    assert compact(md) == "Menu\n[Jane Doe](/jane) CEO"


def test_person_with_image_between_name_and_title():
    from app.pipeline.extract import verify_items
    page = "Ronak Meghani\n\n![photo](https://x/r.jpg)\n\nCEO & Co-Founder\n\nMitul Patel\n\nDirector"
    pages = [{"url": "https://a.com/about", "markdown": page}]
    ok, bad = verify_items([{"url": "https://a.com/about", "name": "Ronak Meghani", "title": "CEO & Co-Founder",
                             "quote": "Ronak Meghani\n\nCEO & Co-Founder"}], pages)
    assert len(ok) == 1 and not bad
    ok, bad = verify_items([{"url": "https://a.com/about", "name": "Ronak Meghani", "title": "Chief Wizard",
                             "quote": "Ronak Meghani Chief Wizard"}], pages)
    assert not ok and len(bad) == 1                         # a made-up title still fails


def test_contact_fallback_to_generic_address():
    from app.pipeline.contacts import pick_contact
    from app.schemas import CampaignFilters
    f = CampaignFilters().model_dump()
    emails = [{"email": "admin@acme.com", "url": "https://acme.com/contact"}]
    person, match, why = pick_contact([], emails, f)             # nobody named on the site
    assert why is None and person["name"] == "" and match["kind"] == "generic" and person["id"] is None
    f["email"]["allowNoPerson"] = False
    assert pick_contact([], emails, f) == (None, None, "no person")
    f["email"]["allowNoPerson"] = True
    boss = [{"id": "1", "name": "Sam Lee", "title": "Founder"}]
    person, match, why = pick_contact(boss, emails, f)
    assert person["name"] == "Sam Lee" and match["email"] == "admin@acme.com"
    assert pick_contact(boss, [], f) == (None, None, "no usable email")


def test_filter_reason_names_the_ranges():
    from app.pipeline.filters import apply_filters
    from app.schemas import CampaignFilters
    f = CampaignFilters().model_dump()
    why = apply_filters({"country": "United States", "size_estimate": 250, "keyword_hits": ["seo agency"]}, f)
    assert "250" in why and "1-10, 11-50" in why


def test_resume_point_reuses_saved_work():
    from app.routers.companies import resume_point
    from app.schemas import CampaignFilters
    f = CampaignFilters().model_dump()
    facts = {"sells": "seo"}
    big = {"status": "filtered_out", "facts": facts, "country": "United States", "size_estimate": 250, "keyword_hits": ["x"], "fail_reason": "old"}
    assert resume_point(big, True, False, f)[0] == "filtered_out"          # still too big for this campaign: no AI call
    f["company"]["employeeRanges"] = [[1, 1000]]
    assert resume_point(big, True, False, f) == ("extracted", None)         # widened the range: goes on, free
    assert resume_point({"status": "no_contact", "facts": facts}, True, False, f)[0] == "audited"
    assert resume_point({"status": "no_contact", "facts": facts}, False, False, f)[0] == "new"
    assert resume_point({"status": "rejected", "facts": facts}, True, True, f)[0] == "contacted"
    assert resume_point({"status": "qualified"}, True, True, f)[0] == "qualified"


def test_client_in_a_testimonial_is_not_a_contact():
    from app.pipeline.contacts import pick_contact
    from app.schemas import CampaignFilters
    f = CampaignFilters().model_dump()
    emails = [{"email": "info@hallam.agency", "url": "https://hallam.agency/contact"}]
    people = [{"id": "1", "name": "Dan Roche", "title": "CMO at Workbooks"},
              {"id": "2", "name": "Jules Strong", "title": "VP Marketing EMEA at Lattice"}]
    person, match, why = pick_contact(people, emails, f, {"hallam"})
    assert person["name"] == "" and match["kind"] == "generic"          # no staff named: the generic address, not a client
    staff = [{"id": "3", "name": "Sam Hall", "title": "Founder at Hallam"}] + people
    assert pick_contact(staff, emails, f, {"hallam"})[0]["name"] == "Sam Hall"
    assert pick_contact([{"id": "4", "name": "Ann", "title": "CEO"}], emails, f, {"hallam"})[0]["name"] == "Ann"
