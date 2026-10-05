"""Any country, and the AI recommended fill: what the code does with the AI answer. No live calls."""
import asyncio

from app.pipeline import campaign_fill as cf
from app.pipeline.discovery import build_queries
from app.pipeline.filters import apply_filters
from app.pipeline.judge import lead_timezone
from app.schemas import CampaignFilters

DEFAULT = CampaignFilters().model_dump()


def merged(out, left=None, current=None):
    return cf.merge(current or DEFAULT, out, left)


# ---- any country ----

def test_any_country_filter():
    f = CampaignFilters().model_dump()
    co = {"country": "India", "size_estimate": 5, "keyword_hits": ["seo"]}
    assert apply_filters(co, f) == "country India not wanted"
    f["company"]["anyCountry"] = True
    assert apply_filters(co, f) is None                    # no country is refused
    f["company"]["anyCountry"] = False
    f["company"]["countries"] = []
    assert apply_filters(co, f) is None                    # an empty list never meant "none allowed"


def test_any_country_queries():
    f = CampaignFilters().model_dump()
    f["company"]["webKeywords"] = ["seo"]
    assert build_queries(f, []) == [f'"seo" agency {c}' for c in f["company"]["countries"]]   # as before
    f["company"]["anyCountry"] = True
    assert build_queries(f, []) == ['"seo" agency']        # no trailing space, no country
    f["company"]["anyCountry"], f["company"]["countries"] = False, []
    assert build_queries(f, []) == ['"seo" agency']        # empty list: still searches


def test_more_time_zones():
    assert lead_timezone("India", None) == "Asia/Kolkata"
    assert lead_timezone("United States", None) == "America/New_York"
    assert lead_timezone("Narnia", None) is None            # unknown: the sender uses its default


# ---- the AI answer is cleaned ----

def test_keywords_are_cleaned():
    out = {"company": {"webKeywords": ['  "SEO Agency" ', "seo agency", "Link Building", "", "x" * 90] + [f"k{i}" for i in range(20)]}}
    kws = merged(out)[0]["company"]["webKeywords"]
    assert kws[:2] == ["seo agency", "link building"]       # lowercase, no quotes, no repeats
    assert len(kws) == 12 and len(kws[2]) == 60             # at most 12, each at most 60 characters


def test_countries_use_full_names():
    out = {"company": {"countries": ["USA", "uk", "new zealand", "Germany", "AU", "usa"]}}
    assert merged(out)[0]["company"]["countries"] == ["United States", "United Kingdom", "New Zealand", "Germany", "Australia"]
    f, _ = merged({"company": {"anyCountry": True, "countries": []}})
    assert f["company"]["anyCountry"] is True and f["company"]["countries"] == DEFAULT["company"]["countries"]   # kept for when you switch it off


def test_ranges_and_hits():
    out = {"company": {"employeeRanges": [[1, 10], [11, 50], [50, 10], ["a", 3], [5], [0, 4], [1.0, 10.0]],
                       "webKeywords": ["a", "b"], "minKeywordHits": 4}}
    c = merged(out)[0]["company"]
    assert c["employeeRanges"] == [[1, 10], [11, 50]]       # bad pairs dropped, no repeats
    assert c["minKeywordHits"] == 2                         # cannot ask for more hits than there are keywords


def test_what_the_ai_leaves_out_stays():
    cur = CampaignFilters().model_dump()
    cur["company"]["excludeDomains"] = ["mine.com"]
    cur["person"]["titlePriority"] = ["owner"]
    f, _ = merged({"company": {"excludeDomains": ["Other.com", "MINE.com"]}}, current=cur)
    assert f["company"]["excludeDomains"] == ["mine.com", "other.com"]   # yours are never dropped
    assert f["person"]["titlePriority"] == ["owner"]
    f, _ = merged({}, current=cur)                                       # an empty answer changes no targeting field
    assert f["company"] == {**cur["company"], "minKeywordHits": 1} and f["person"] == cur["person"] and f["qualify"] == cur["qualify"]


def test_person_values_are_limited_to_known_ones():
    out = {"person": {"seniority": ["Owner", "ninja", "c_suite"], "excludeSeniority": ["entry", "king"], "titlePriority": ["Founder", "FOUNDER", "Head of SEO"]}}
    p = merged(out)[0]["person"]
    assert p["seniority"] == ["owner", "c_suite"] and p["excludeSeniority"] == ["entry"] and p["titlePriority"] == ["founder", "head of seo"]


def test_scores_stay_in_order():
    q = merged({"qualify": {"minFitScore": 99, "maybeFrom": 90, "demoFrom": 10}})[0]["qualify"]
    assert (q["maybeFrom"], q["minFitScore"], q["demoFrom"]) == (90, 95, 95)
    q = merged({"qualify": {"minFitScore": 10, "maybeFrom": 5, "demoFrom": 200}})[0]["qualify"]
    assert (q["maybeFrom"], q["minFitScore"], q["demoFrom"]) == (20, 40, 100)
    q = merged({"qualify": {"minFitScore": "abc", "maybeFrom": float("nan"), "demoFrom": float("inf")}})[0]["qualify"]
    assert q == {"minFitScore": 70, "maybeFrom": 50, "demoFrom": 85}    # junk (text, NaN, Infinity) keeps the current value


# ---- the budget cannot be passed ----

def test_budget_follows_the_credits_left():
    out = {"maxCompaniesToScan": 500, "leadsWanted": 50, "maxCreditsPerRun": 9000, "maxCreditsPerStage": 10, "maxLlmCallsPerStage": 1}
    f, notes = merged(out, left=150)
    assert cf.run_cost(f["maxCompaniesToScan"]) <= 150 and f["maxCompaniesToScan"] >= 28   # as many as the credits allow
    assert f["maxCreditsPerRun"] <= 150 and f["maxCreditsPerRun"] >= cf.run_cost(f["maxCompaniesToScan"])
    assert f["maxCreditsPerStage"] >= f["maxCompaniesToScan"] * 4      # the audit stage can read every company
    assert f["maxLlmCallsPerStage"] >= f["maxCompaniesToScan"]
    assert f["leadsWanted"] <= f["maxCompaniesToScan"]
    assert notes and "150" in notes[0]
    f, notes = merged({"maxCompaniesToScan": 30}, left=150)
    assert f["maxCompaniesToScan"] == 30 and not [n for n in notes if "limited" in n]   # fits: no note
    f, _ = merged({"maxCompaniesToScan": 400}, left=None)
    assert f["maxCompaniesToScan"] == 400                              # unknown balance: no cap
    f, _ = merged({"maxCompaniesToScan": 400}, left=0)
    assert f["maxCompaniesToScan"] == 1                                # nothing left: the smallest run


def test_empty_answer_changes_nothing_but_warns():
    f, notes = cf.merge({**DEFAULT, "company": {**DEFAULT["company"], "webKeywords": []}}, {}, None)
    assert f["company"]["webKeywords"] == [] and f["company"]["minKeywordHits"] == 0
    assert any("keywords" in n for n in notes)


# ---- the whole call, with the AI answer faked ----

def test_suggest_sends_the_profile_and_returns_a_full_form(monkeypatch):
    class Q:
        def __init__(self, rows): self.rows = rows
        def select(self, *_): return self
        def eq(self, *_): return self
        def order(self, *_, **__): return self
        def limit(self, *_): return self
        def execute(self): return type("R", (), {"data": self.rows})()

    class Db:
        def table(self, name):
            return Q({"profiles": [{"name": "SEO", "parsed": {"name": "Sam", "headline": "SEO pro", "skills": ["seo"], "proof_points": ["+300% traffic"]}}],
                      "campaigns": [{"name": "Old", "filters": {"company": {"webKeywords": ["ppc"]}}}]}.get(name, []))

    seen = {}

    async def fake_llm(task, model, system, user, schema, run_id=None, temperature=0.1):
        import json
        seen.update(task=task, user=json.loads(user))
        return schema.model_validate({"name": "UK SEO agencies", "why": "because", "maxCompaniesToScan": 20,
                                      "company": {"webKeywords": ["seo agency"], "countries": ["uk"]}}).model_dump()

    monkeypatch.setattr(cf, "get_db", lambda: Db())
    monkeypatch.setattr(cf, "load_map", lambda pid: [{"active": True, "service": "SEO audits", "problems": ["p"], "ideal_customer": {"industry": "agencies"},
                                                      "signals": [{"active": True, "name": "s", "detector_type": "phrase", "config": {"phrases": ["x"]}}]}])
    monkeypatch.setattr(cf.llm, "complete_json", fake_llm)
    monkeypatch.setattr(cf, "kind_of", lambda pid: "freelancer")
    out = asyncio.run(cf.suggest("pid", "My campaign", "only the UK", DEFAULT, 1000))
    assert seen["task"] == "campaign_fill"
    u = seen["user"]
    assert u["cv"]["headline"] == "SEO pro" and u["offer_map"][0]["service"] == "SEO audits" and u["offer_map"][0]["signals"][0]["name"] == "s"
    assert u["campaign_name"] == "My campaign" and u["note_from_freelancer"] == "only the UK" and u["credits_left"] == 1000
    assert u["other_campaigns"] == [{"name": "Old", "web_keywords": ["ppc"]}]
    assert out["name"] == "UK SEO agencies" and out["used_offer_map"] is True
    assert out["filters"]["company"]["countries"] == ["United Kingdom"] and out["filters"]["maxCompaniesToScan"] == 20
    CampaignFilters.model_validate(out["filters"])                   # a form the rest of the app accepts


def test_prompt_example_matches_the_schema():
    """The JSON shape in the prompt is what the AI copies. If it drifts from the schema, answers start failing."""
    import json
    from app.services.llm import load_prompt
    text = load_prompt("campaign_fill")
    shape = json.loads(text[text.index('{"name"'):])
    assert cf.FillOut.model_validate(shape)
    top = set(shape) - {"name", "why"}
    assert top == set(cf.FillOut.model_fields) - {"name", "why"}      # the prompt names every field the code reads
    for part, model in (("company", cf._Company), ("person", cf._Person), ("qualify", cf._Qualify), ("email", cf._Email)):
        assert set(shape[part]) == set(model.model_fields), part


def test_ima_suggest_sends_the_brief_and_uses_the_ima_prompt(monkeypatch):
    """An IMA profile gets the brand-hunting prompt, and the AI reads the agency brief, not a CV."""
    class Q:
        def __init__(self, rows): self.rows = rows
        def select(self, *_): return self
        def eq(self, *_): return self
        def order(self, *_, **__): return self
        def limit(self, *_): return self
        def execute(self): return type("R", (), {"data": self.rows})()

    parsed = {"name": "Nazmul", "kind": "ima", "agency": {"name": "Fylint"}, "niches": ["AI tools"],
              "roster": [{"name": "Sam", "channel_url": "https://youtube.com/@sam", "niche": "AI tools", "avg_views": "45K", "audience_countries": ["India"],
                          "content_style": "demos", "past_sponsors": [], "open_to_deals": True}]}

    class Db:
        def table(self, name):
            return Q({"profiles": [{"name": "Fylint", "parsed": parsed}], "campaigns": []}.get(name, []))

    seen = {}

    async def fake_llm(task, model, system, user, schema, run_id=None, temperature=0.1):
        import json
        seen.update(task=task, system=system, user=json.loads(user))
        return schema.model_validate({"company": {"webKeywords": ["ai writing tool"], "anyCountry": True, "employeeRanges": [[1, 100000]]},
                                      "person": {"titlePriority": ["influencer marketing manager"]}}).model_dump()

    monkeypatch.setattr(cf, "get_db", lambda: Db())
    monkeypatch.setattr(cf, "load_map", lambda pid: [{"active": True, "service": "AI writing tools", "problems": ["reach"], "ideal_customer": {"industry": "SaaS"},
                                                      "signals": [{"active": True, "name": "Creator program", "detector_type": "phrase", "config": {"phrases": ["creator program"]}}]}])
    monkeypatch.setattr(cf.llm, "complete_json", fake_llm)
    monkeypatch.setattr(cf, "kind_of", lambda pid: "ima")
    out = asyncio.run(cf.suggest("pid", "", "only AI brands", DEFAULT, None))
    u = seen["user"]
    assert "BRANDS that already pay creators" in seen["system"]
    assert u["brief"]["niches"] == ["AI tools"] and u["brief"]["roster"][0]["avg_views"] == "45K"
    assert "channel_url" not in u["brief"]["roster"][0] and "cv" not in u      # no links or CV fields go to the AI
    assert u["brand_map"][0]["niche"] == "AI writing tools" and u["note_from_agency"] == "only AI brands"
    assert out["used_offer_map"] is True
    f = out["filters"]["company"]
    assert f["webKeywords"] == ["ai writing tool"] and f["anyCountry"] is True and f["employeeRanges"] == [[1, 100000]]
    assert out["filters"]["person"]["titlePriority"] == ["influencer marketing manager"]


def test_ima_prompt_example_matches_the_schema():
    import json
    from app.services.llm import load_prompt
    text = load_prompt("campaign_fill_ima")
    shape = json.loads(text[text.index('{"name"'):])
    assert cf.FillOut.model_validate(shape)
    assert set(shape) - {"name", "why"} == set(cf.FillOut.model_fields) - {"name", "why"}
    for part, model in (("company", cf._Company), ("person", cf._Person), ("qualify", cf._Qualify), ("email", cf._Email)):
        assert set(shape[part]) == set(model.model_fields), part


def test_other_ima_prompts_show_valid_json_shapes():
    """The prompts the AI copies a shape from must match what the code reads."""
    import json
    from app.pipeline.discovery import PrescreenOut, QueriesOut
    from app.pipeline.offer_map import OfferMapOut
    from app.pipeline.ima_brief import ParsedBrief
    from app.services.llm import load_prompt
    for name, model in (("ima_parse", ParsedBrief), ("brand_map", OfferMapOut), ("queries_ima", QueriesOut), ("prescreen_ima", PrescreenOut)):
        text = load_prompt(name)
        start = text.index("JSON shape:") + len("JSON shape:")
        shape = json.loads(text[start:text.index("\n\n", start) if "\n\n" in text[start:] else len(text)].split("\nReturn one item")[0].strip().replace('"yes|no|unsure"', '"yes"'))
        assert model.model_validate(shape), name
