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
