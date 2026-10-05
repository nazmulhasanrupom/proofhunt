"""Profiles: which profile a call is for, names, log lines, sender name, saved pages. No live calls."""
import asyncio

import pytest
from fastapi import HTTPException

from app import deps
from app.routers import profiles
from app.sending import scheduler as sch
from app.services import cache, scraper, usage

A, B = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"


class Query:
    """Remembers the table and the filters. `rows` maps a table name to its rows, or to a function of the filters."""
    def __init__(self, db, table): self.db, self.name, self.filters, self.row = db, table, [], None
    def select(self, *_, **__): return self
    def eq(self, col, val): self.filters.append((col, val)); return self
    def gte(self, *_): return self             # age is checked in the cache tests
    def limit(self, *_): return self
    def order(self, *_, **__): return self
    def insert(self, row): self.row = row; return self
    def upsert(self, row, **_): self.row = row; return self
    def execute(self):
        class R: pass
        r = R()
        if self.row is not None:
            self.db.inserted.append((self.name, self.row))
            r.data = [self.row]
        else:
            self.db.queries.append((self.name, self.filters))
            rows = self.db.rows.get(self.name, [])
            r.data = rows(self.filters) if callable(rows) else [x for x in rows if all(x.get(c) == v for c, v in self.filters)]
        return r


class Db:
    def __init__(self, **rows): self.rows, self.inserted, self.queries = rows, [], []
    def table(self, name): return Query(self, name)


# ---- which profile a call is for ----

def test_profile_header_must_be_a_uuid():
    assert deps.profile_id(A.upper()) == A                      # same id, one spelling
    for bad in ("", "nope", "123", "'; drop table profiles;--"):
        with pytest.raises(HTTPException) as e:
            deps.profile_id(bad)
        assert e.value.status_code == 400
    assert deps.as_uuid(None) is None


def test_names():
    assert profiles.clean_name("  SEO   specialist ") == "SEO specialist"
    for bad in ("", "   ", "x" * 61):
        with pytest.raises(HTTPException) as e:
            profiles.clean_name(bad)
        assert e.value.status_code == 422
    assert profiles.clean_name("x" * 60)                        # the limit itself is fine


def test_name_taken_ignores_case_and_self(monkeypatch):
    monkeypatch.setattr(profiles, "get_db", lambda: Db(profiles=[{"id": A, "name": "SEO Lead"}]))
    assert profiles._name_taken("seo lead")
    assert not profiles._name_taken("seo lead", except_id=A)    # renaming a profile to its own name (new case) is fine
    assert not profiles._name_taken("Web dev")
    with pytest.raises(HTTPException) as e:
        profiles._check_name_free("SEO LEAD")
    assert e.value.status_code == 409


# ---- log lines know their profile ----

def test_log_event_finds_the_profile(monkeypatch):
    db = Db(runs=[{"id": "r1", "profile_id": A}], leads=[{"id": "l1", "profile_id": B}], events=[])
    monkeypatch.setattr(usage, "get_db", lambda: db)
    usage._profile_of.clear()
    usage.log_event("r1", "info", "run", "x")
    usage.log_event(None, "info", "email", "x", lead_id="l1")
    usage.log_event(None, "info", "app", "x")                                   # no run, no lead: for the whole app
    usage.log_event("r1", "info", "run", "x", profile_id=B)                     # given: wins
    got = [row["profile_id"] for name, row in db.inserted if name == "events"]
    assert got == [A, B, None, B]
    usage.log_event("r1", "info", "run", "again")
    assert sum(1 for name, _ in db.queries if name == "runs") == 1               # the run was looked up once, then remembered


# ---- the name on the email ----

def test_sender_name(monkeypatch):
    db = Db(profiles=[{"id": A, "parsed": {"name": ""}}, {"id": B, "parsed": {"name": "Sam Lee"}}])
    monkeypatch.setattr(sch, "get_db", lambda: db)
    assert sch.sender_name({"sender_name": "From Settings"}, B) == "From Settings"
    assert sch.sender_name({}, B) == "Sam Lee"                                   # the CV of that profile
    assert sch.sender_name({}, A) == ""
    assert sch.sender_name({}) == "Sam Lee"                                      # no profile asked: the first CV with a name


# ---- a page saved for one profile is not read again for another ----

def test_saved_page_is_copied_to_the_other_profile(monkeypatch):
    saved_elsewhere = {"url": "https://a.com", "kind": "home", "markdown": "saved text " * 20, "raw_html": "<h>"}
    # nothing for this company, but the same url is in the cache (another profile read it)
    db = Db(pages=[], page_cache=[saved_elsewhere])
    monkeypatch.setattr(scraper, "get_db", lambda: db)
    monkeypatch.setattr(cache, "get_db", lambda: db)
    monkeypatch.setattr(scraper.crawl4ai, "enabled", lambda: (_ for _ in ()).throw(AssertionError("must not read the site again")))
    out = asyncio.run(scraper.scrape("https://a.com", [], False, B, "home"))
    assert out["cached"] and out["raw_html"] == "<h>"
    copied = [row for name, row in db.inserted if name == "pages"]
    assert copied and copied[0]["company_id"] == B and copied[0]["markdown"].startswith("saved text")


# ---- a database that was not updated ----

def test_missing_migration_gets_a_plain_message(monkeypatch):
    from postgrest.exceptions import APIError

    class Failing(Query):
        def execute(self):
            raise APIError({"message": "column profiles.name does not exist", "code": "42703", "hint": None, "details": None})

    class OldDb(Db):
        def table(self, name): return Failing(self, name)

    monkeypatch.setattr(profiles, "get_db", lambda: OldDb())
    with pytest.raises(HTTPException) as e:
        profiles.list_profiles()
    assert e.value.status_code == 503 and "003_profiles.sql" in e.value.detail
