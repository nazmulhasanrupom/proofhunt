"""Pause and cancel: a stopped run cannot spend, cannot start again, and the buttons say what really happened."""
import pytest
from fastapi import HTTPException

from app.pipeline import orchestrator
from app.routers import runs
from app.services import usage


class Q:
    """A table that remembers its filters. `table` rows are what the run looks like in the database."""
    def __init__(self, db, name): self.db, self.name, self.upd, self.filters, self.one = db, name, None, [], False
    def select(self, *_): return self
    def single(self): self.one = True; return self
    def eq(self, *a): self.filters.append(("eq",) + a); return self
    def in_(self, col, vals): self.filters.append(("in", col, vals)); return self
    def update(self, row): self.upd = row; return self
    def execute(self):
        class R: pass
        r = R()
        rows = self.db.rows.get(self.name, [])
        ok = lambda row: all((f[2] == row.get(f[1])) if f[0] == "eq" else (row.get(f[1]) in f[2]) for f in self.filters if f[1] in row)
        hit = [x for x in rows if ok(x)]
        if self.upd is not None:
            for x in hit:
                x.update(self.upd)
        r.data = hit if self.upd is not None or self.filters else rows
        if self.one:
            r.data = hit[0]
        return r


class Db:
    def __init__(self, **rows): self.rows = rows
    def table(self, name): return Q(self, name)


def run_row(status): return {"id": "r1", "status": status, "stage": "audit", "counters": {}, "campaign_id": "c1", "credits_used": 0, "started_at": None}


@pytest.mark.parametrize("status", ["paused", "cancelled"])
def test_stopped_run_cannot_spend(monkeypatch, status):
    monkeypatch.setattr(usage, "get_db", lambda: Db(runs=[run_row(status)], campaigns=[{"id": "c1", "filters": {}}]))
    monkeypatch.setattr(usage.settings, "dev_firecrawl_credit_limit", None)
    monkeypatch.setattr(usage.settings, "dev_llm_call_limit", None)
    with pytest.raises(usage.RunStopped):
        usage.check_credit_budget(1, "r1")               # before a Firecrawl call
    with pytest.raises(usage.RunStopped):
        usage.check_llm_budget("r1")                     # before an AI call
    with pytest.raises(usage.RunStopped):
        usage.check_run_active("r1")                     # after a 429 wait
    assert issubclass(usage.RunStopped, usage.BudgetExceeded) and not issubclass(usage.RunStopped, usage.StageLimitReached)
    usage.check_run_active(None)                         # no run (a manual action): never blocked


def test_running_run_can_spend(monkeypatch):
    monkeypatch.setattr(usage, "get_db", lambda: Db(runs=[run_row("running")], campaigns=[{"id": "c1", "filters": {}}]))
    monkeypatch.setattr(usage.settings, "dev_firecrawl_credit_limit", None)
    monkeypatch.setattr(usage.settings, "dev_llm_call_limit", None)
    usage.check_credit_budget(1, "r1")
    usage.check_llm_budget("r1")


@pytest.mark.parametrize("status,starts", [("queued", True), ("running", True), ("paused", False), ("cancelled", False), ("done", False), ("failed", False)])
def test_only_a_queued_run_starts(monkeypatch, status, starts):
    db = Db(runs=[run_row(status)])
    monkeypatch.setattr(orchestrator, "get_db", lambda: db)
    assert orchestrator._claim(db.rows["runs"][0]) is starts
    assert db.rows["runs"][0]["status"] == ("running" if starts else status)   # a paused run is not turned back to running


def test_end_state_does_not_overwrite_your_pause(monkeypatch):
    db = Db(runs=[run_row("paused")])
    monkeypatch.setattr(orchestrator, "get_db", lambda: db)
    assert orchestrator._finish("r1", status="done") is False and db.rows["runs"][0]["status"] == "paused"
    db.rows["runs"][0]["status"] = "running"
    assert orchestrator._finish("r1", status="done") is True and db.rows["runs"][0]["status"] == "done"


@pytest.mark.parametrize("call,status,expect", [
    (runs.pause, "running", "paused"), (runs.pause, "queued", "paused"), (runs.pause, "paused", "paused"),
    (runs.cancel, "running", "cancelled"), (runs.cancel, "paused", "cancelled"), (runs.cancel, "cancelled", "cancelled"),
])
def test_pause_and_cancel_work(monkeypatch, call, status, expect):
    db = Db(runs=[run_row(status)], events=[])
    monkeypatch.setattr(runs, "get_db", lambda: db)
    monkeypatch.setattr(runs, "log_event", lambda *a, **k: None)
    assert call("r1") == {"ok": True, "status": expect} and db.rows["runs"][0]["status"] == expect


@pytest.mark.parametrize("call,status", [(runs.pause, "done"), (runs.pause, "failed"), (runs.pause, "cancelled"), (runs.cancel, "done"), (runs.cancel, "failed")])
def test_pause_and_cancel_say_when_they_did_nothing(monkeypatch, call, status):
    db = Db(runs=[run_row(status)])
    monkeypatch.setattr(runs, "get_db", lambda: db)
    with pytest.raises(HTTPException) as e:
        call("r1")
    assert e.value.status_code == 409 and status in e.value.detail and db.rows["runs"][0]["status"] == status
    db.rows["runs"] = []
    with pytest.raises(HTTPException) as e:
        call("r1")
    assert e.value.status_code == 404


def test_discovery_stops_between_searches(monkeypatch):
    """A paused run must not start the next search."""
    import asyncio
    from app.pipeline import discovery
    from app.schemas import CampaignFilters
    searches = []

    async def fake_search(q, limit, run_id=None):
        searches.append(q)
        return {"results": [], "credits": 2}

    class D:
        def table(self, name):
            class T:
                def __getattr__(s, _): return lambda *a, **k: s
                def execute(s): return type("R", (), {"data": [], "count": 0})()
            return T()

    async def no_llm(*a, **k): return {"queries": []}
    monkeypatch.setattr(discovery, "get_db", lambda: D())
    monkeypatch.setattr(discovery, "load_map", lambda pid: [])
    monkeypatch.setattr(discovery.firecrawl, "search", fake_search)
    monkeypatch.setattr(discovery.llm, "complete_json", no_llm)
    f = CampaignFilters().model_dump()
    f["company"]["webKeywords"] = ["a", "b", "c"]
    camp = {"filters": f, "profile_id": "p"}
    stop_after = {"n": 2}

    def should_stop():
        stop_after["n"] -= 1
        return stop_after["n"] < 0
    asyncio.run(discovery.run("r1", camp, 500, should_stop))
    assert len(searches) == 2 and len(searches) < len(discovery.build_queries(f, []))   # it stopped, and did not finish the list


def test_judge_stops_when_the_leads_wanted_exist(monkeypatch):
    """The rest of the batch stays 'contacted': no AI call goes to a company you do not need."""
    import asyncio
    from app.pipeline import judge
    judged = []

    async def fake_judge(c, camp, run_id):
        judged.append(c["id"])
        return "qualified"
    monkeypatch.setattr(judge, "judge_company", fake_judge)
    monkeypatch.setattr(judge, "scope_todo", lambda run_id, statuses, ids=None: [{"id": i, "domain": f"{i}.com"} for i in "abcd"])
    monkeypatch.setattr(judge, "log_event", lambda *a, **k: None)
    monkeypatch.setattr(judge, "get_db", lambda: None)
    asyncio.run(judge.run("r1", {}, lambda: False, None, lambda: len(judged) >= 2))
    assert judged == ["a", "b"]
