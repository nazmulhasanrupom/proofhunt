"""Batches of 5 that finish before the next search, the 2-month cache, and the CSV download."""
import asyncio
import csv
import io
from datetime import datetime, timedelta, timezone

from app.pipeline import extract, orchestrator
from app.routers import export
from app.services import cache, scraper


# ---------- batches ----------
def test_a_batch_is_five_and_goes_all_the_way_to_the_emails(monkeypatch):
    """Search -> 5 companies -> every stage incl. report and emails -> only then the next 5, and only then the next search."""
    calls: list[str] = []
    found = {"n": 0}
    pending: list[str] = []                         # companies found, in the order they were found

    async def fake_discovery(run_id, campaign, cap, should_stop, round_cap):
        calls.append("search")
        for _ in range(7):                          # one search finds 7: more than one batch
            found["n"] += 1
            pending.append(f"c{found['n']}")

    def stage(name):
        async def fn():
            calls.append(name)
        return fn

    batches = []

    def work(run_id, camp, stop, ids, when=None):
        batches.append(list(ids))
        return {n: stage(n) for n in ("audit", "extract", "contacts", "judge")}

    async def one_stage(run_id, name, fn):
        await fn()
        return True
    monkeypatch.setattr(orchestrator.discovery, "run", fake_discovery)
    monkeypatch.setattr(orchestrator, "_count", lambda run_id, *st: 0 if st else found["n"])
    monkeypatch.setattr(orchestrator, "_next_batch", lambda run_id, seen: [c for c in pending if c not in seen][:orchestrator.BATCH])
    monkeypatch.setattr(orchestrator, "_stage", one_stage)
    monkeypatch.setattr(orchestrator, "_work_stages", work)
    monkeypatch.setattr(orchestrator, "_lead_stages", lambda run_id, camp, stop, ids: {n: stage(n) for n in ("assets", "sequences")})
    monkeypatch.setattr(orchestrator, "_save_counters", lambda run_id: {"found": found["n"], "qualified": 0})
    monkeypatch.setattr(orchestrator, "log_event", lambda *a, **k: None)
    monkeypatch.setattr(orchestrator, "_set", lambda *a, **k: None)

    camp = {"filters": {"leadsWanted": 100, "maxCompaniesToScan": 14}}
    asyncio.run(orchestrator._hunt("r1", camp, lambda: False))
    assert orchestrator.BATCH == 5
    assert batches[:2] == [["c1", "c2", "c3", "c4", "c5"], ["c6", "c7"]]       # first 5, then the next ones
    searches = [i for i, c in enumerate(calls) if c == "search"]
    assert len(searches) >= 2
    before_second = calls[:searches[1]]
    assert before_second.count("judge") == 2 and before_second.count("sequences") >= 2   # both batches reached the emails first
    one = calls[searches[0] + 1:]
    assert one[:6] == ["audit", "extract", "contacts", "judge", "assets", "sequences"]  # one batch: all stages in order


# ---------- cache ----------
class Tbl:
    """A tiny table: select / eq / gte / lt / upsert / delete, in memory."""
    def __init__(self, rows): self.rows, self.f, self.op, self.payload = rows, [], "select", None
    def select(self, *_): self.op = "select"; return self
    def eq(self, c, v): self.f.append(lambda r: r.get(c) == v); return self
    def gte(self, c, v): self.f.append(lambda r: r.get(c) >= v); return self
    def lt(self, c, v): self.f.append(lambda r: r.get(c) < v); return self
    def limit(self, *_): return self
    def upsert(self, row, on_conflict=None):
        self.op, self.payload, self.key = "upsert", row, on_conflict.split(","); return self
    def delete(self): self.op = "delete"; return self
    def execute(self):
        hit = [r for r in self.rows if all(f(r) for f in self.f)]
        if self.op == "upsert":
            for r in self.rows:
                if all(r.get(k) == self.payload.get(k) for k in self.key):
                    r.update(self.payload); break
            else:
                self.rows.append(dict(self.payload))
        elif self.op == "delete":
            for r in hit:
                self.rows.remove(r)
        return type("R", (), {"data": hit})()


class Db:
    def __init__(self, **t): self.t = t
    def table(self, n): return Tbl(self.t[n])


def ago(days): return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
GOOD = "word " * 40


def test_cache_is_two_months():
    assert cache.CACHE_DAYS == 60


def test_page_cache_serves_fresh_ignores_old_and_purge_deletes(monkeypatch):
    db = Db(page_cache=[{"url": "https://a.com", "kind": "home", "markdown": GOOD, "raw_html": "<p>", "cached_at": ago(10)},
                        {"url": "https://old.com", "kind": "home", "markdown": GOOD, "raw_html": None, "cached_at": ago(61)}],
            extract_cache=[{"domain": "old.com", "sig": "s", "payload": {}, "cached_at": ago(70)},
                           {"domain": "a.com", "sig": "s", "payload": {"x": 1}, "cached_at": ago(1)}])
    monkeypatch.setattr(cache, "get_db", lambda: db)
    assert cache.page_get("https://a.com")["markdown"] == GOOD
    assert cache.page_get("https://old.com") is None            # too old: read again
    assert cache.extract_get("a.com", "s") == {"x": 1} and cache.extract_get("old.com", "s") is None
    assert cache.purge() == {"page_cache": 1, "extract_cache": 1}
    assert [r["url"] for r in db.t["page_cache"]] == ["https://a.com"]


def test_errors_and_empty_pages_are_not_cached(monkeypatch):
    db = Db(page_cache=[])
    monkeypatch.setattr(cache, "get_db", lambda: db)
    cache.page_put("https://x.com", "home", "", None)                                    # could not read
    cache.page_put("https://x.com", "home", "tiny", None)                                # empty page
    cache.page_put("https://x.com", "home", GOOD + " This domain is for sale", None)     # parked
    assert db.t["page_cache"] == []
    cache.page_put("https://x.com", "home", GOOD, "<html>")
    assert len(db.t["page_cache"]) == 1


def test_no_cache_tables_means_no_cache_not_a_crash(monkeypatch):
    class Broken:
        def table(self, n): raise RuntimeError("relation does not exist")
    monkeypatch.setattr(cache, "get_db", lambda: Broken())
    assert cache.page_get("u") is None and cache.extract_get("d", "s") is None
    cache.page_put("u", "home", GOOD, None)
    cache.extract_put("d", "s", {})


def test_another_profile_reuses_the_page_and_pays_no_credit(monkeypatch):
    pages = []
    db = Db(pages=pages, page_cache=[{"url": "https://a.com", "kind": "home", "markdown": GOOD, "raw_html": "<p>", "cached_at": ago(5)}])
    monkeypatch.setattr(scraper, "get_db", lambda: db)
    monkeypatch.setattr(cache, "get_db", lambda: db)

    async def boom(*a, **k): raise AssertionError("must not be read again")
    monkeypatch.setattr(scraper.firecrawl, "fetch", boom)
    monkeypatch.setattr(scraper.crawl4ai, "enabled", lambda: False)
    out = asyncio.run(scraper.scrape("https://a.com", ["markdown"], False, "company-of-profile-2", "home"))
    assert out["cached"] and out["markdown"] == GOOD
    assert pages[0]["company_id"] == "company-of-profile-2"


def test_a_page_older_than_two_months_is_read_again(monkeypatch):
    pages = [{"company_id": "c", "url": "https://a.com", "kind": "home", "markdown": GOOD, "raw_html": None, "fetched_at": ago(90)}]
    db = Db(pages=pages, page_cache=[])
    monkeypatch.setattr(scraper, "get_db", lambda: db)
    monkeypatch.setattr(cache, "get_db", lambda: db)
    monkeypatch.setattr(scraper.crawl4ai, "enabled", lambda: False)
    fetched = []

    async def fetch(url, formats, main, run_id):
        fetched.append(url)
        return {"markdown": "fresh " * 40, "links": [], "raw_html": "<p>", "status": 200}
    monkeypatch.setattr(scraper.firecrawl, "fetch", fetch)
    out = asyncio.run(scraper.scrape("https://a.com", ["markdown"], False, "c", "home"))
    assert fetched == ["https://a.com"] and out["markdown"].startswith("fresh")
    assert pages[0]["markdown"].startswith("fresh") and len(db.t["page_cache"]) == 1


def test_a_failed_read_is_not_cached(monkeypatch):
    db = Db(pages=[], page_cache=[])
    monkeypatch.setattr(scraper, "get_db", lambda: db)
    monkeypatch.setattr(cache, "get_db", lambda: db)
    monkeypatch.setattr(scraper.crawl4ai, "enabled", lambda: False)

    async def fetch(*a, **k): raise scraper.firecrawl.ScrapeError("404")
    monkeypatch.setattr(scraper.firecrawl, "fetch", fetch)
    try:
        asyncio.run(scraper.scrape("https://bad.com", ["markdown"], False, "c", "home"))
    except scraper.firecrawl.ScrapeError:
        pass
    assert db.t["page_cache"] == [] and db.t["pages"] == []


def test_signature_depends_on_ai_signals_only():
    a = [{"name": "Slow reports", "config": {"question": "q"}}]
    assert cache.signal_sig(a) == cache.signal_sig([{"name": " slow reports ", "config": {"question": "q"}}])
    assert cache.signal_sig(a) != cache.signal_sig([]) != cache.signal_sig([{"name": "Other", "config": {}}])


def test_cached_extract_is_checked_and_filled(monkeypatch):
    monkeypatch.setattr(extract.cache, "extract_get", lambda d, s: {"company_name": "Acme", "people": [{"name": "A", "title": "CEO"}]})
    ex = extract.cached_extract("acme.com", "s")
    assert ex["company_name"] == "Acme" and ex["hiring_roles"] == [] and ex["people"][0]["quote"] == ""
    monkeypatch.setattr(extract.cache, "extract_get", lambda d, s: {"people": "garbage"})
    assert extract.cached_extract("acme.com", "s") is None
    monkeypatch.setattr(extract.cache, "extract_get", lambda d, s: None)
    assert extract.cached_extract("acme.com", "s") is None


# ---------- csv ----------
def test_csv_cells_cannot_run_as_formulas():
    assert export.safe("=1+1") == "'=1+1" and export.safe("@x") == "'@x" and export.safe("-5 off") == "'-5 off"
    assert export.safe(None) == "" and export.safe(["a", "b"]) == "a; b" and export.safe("one\ntwo") == "one two"


def test_csv_has_every_company_and_its_contact_and_judgment(monkeypatch):
    db = Db(
        companies=[{"id": "1", "profile_id": "p", "domain": "a.com", "name": "A, Inc", "status": "qualified", "fail_reason": None,
                    "country": "UK", "size_estimate": 5, "size_bucket": "1 - 10", "tech": {"wordpress": True}, "keyword_hits": ["seo"],
                    "facts": {"sells": "SEO", "emails": [{"email": "hi@a.com"}]}, "first_seen": "t", "last_audited_at": None},
                   {"id": "2", "profile_id": "p", "domain": "b.com", "name": "=EVIL()", "status": "failed", "fail_reason": "parked",
                    "country": None, "size_estimate": None, "size_bucket": None, "tech": {}, "keyword_hits": [], "facts": {},
                    "first_seen": "t", "last_audited_at": None},
                   {"id": "3", "profile_id": "other", "domain": "c.com", "name": "C", "status": "new", "fail_reason": None, "country": None,
                    "size_estimate": None, "size_bucket": None, "tech": {}, "keyword_hits": [], "facts": {}, "first_seen": "t", "last_audited_at": None}],
        people=[{"company_id": "1", "selected": True, "name": "Ann", "title": "CEO", "email": "ann@a.com", "email_kind": "personal", "email_source": "https://a.com/c"}],
        judgments=[{"company_id": "1", "created_at": "1", "fit_score": 10, "problem": "old"}, {"company_id": "1", "created_at": "2", "fit_score": 88, "problem": "slow", "fix": "f", "value_estimate": "v", "confidence": "high"}],
        evidence=[{"company_id": "1", "quote": "we do it by hand", "verified": True}, {"company_id": "1", "quote": "nope", "verified": False}],
        leads=[{"company_id": "1", "stage": "ready"}])

    class Q(Tbl):
        def in_(self, c, vals): self.f.append(lambda r: r.get(c) in vals); return self
        def order(self, *a, **k): return self
    class D(Db):
        def table(self, n): return Q(self.t[n])
    monkeypatch.setattr(export, "get_db", lambda: D(**db.t))
    rows = export.rows_for("p", ["2", "1", "3"])          # "3" is another profile's company: never in the file
    out = list(csv.DictReader(io.StringIO(export.make_csv(rows))))
    assert [r["domain"] for r in out] == ["b.com", "a.com"]  # your order
    a = out[1]
    assert a["name"] == "A, Inc" and a["contact_email"] == "ann@a.com" and a["score"] == "88" and a["problem"] == "slow"
    assert a["evidence"] == "“we do it by hand”" and a["lead_stage"] == "ready" and a["all_emails_on_site"] == "hi@a.com"
    assert out[0]["name"] == "'=EVIL()" and out[0]["fail_reason"] == "parked"
