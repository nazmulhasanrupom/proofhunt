from pydantic import BaseModel, Field


class CompanyFilters(BaseModel):
    anyCountry: bool = False          # true: every country is allowed and searches have no country in them. `countries` is then ignored
    countries: list[str] = ["United States", "United Kingdom", "Canada", "Australia"]
    employeeRanges: list[list[int]] = [[1, 10], [11, 50]]
    allowUnknownSize: bool = True
    webKeywords: list[str] = ["seo agency", "content marketing", "link building", "digital marketing agency", "white label seo"]
    minKeywordHits: int = 1
    excludeDomains: list[str] = []
    cooldownDays: int = 180


class PersonFilters(BaseModel):
    titlePriority: list[str] = ["founder", "co-founder", "ceo", "coo", "head of operations"]
    excludeTitle: list[str] = ["intern", "assistant", "junior", "coordinator"]
    seniority: list[str] = ["owner", "c_suite"]
    excludeSeniority: list[str] = ["intern", "entry"]
    matchMode: str = "title_or_seniority"


class QualifyFilters(BaseModel):
    minFitScore: int = 70
    maybeFrom: int = 50
    demoFrom: int = 85


class EmailFilters(BaseModel):
    allowGeneric: bool = True
    allowNoPerson: bool = True   # no named person on the site: email the generic address instead of dropping the company
    requireMx: bool = True


class CampaignFilters(BaseModel):
    leadsWanted: int = Field(100, ge=1)
    maxCompaniesToScan: int = Field(500, ge=1)
    maxCreditsPerRun: int = Field(2500, ge=1)       # hard cap for the whole run: the run pauses
    maxCreditsPerStage: int = Field(500, ge=1)      # each stage gets its own fresh limit. At the limit the run moves on
    maxLlmCallsPerStage: int = Field(300, ge=1)
    maxPerCompany: int = 1
    company: CompanyFilters = CompanyFilters()
    person: PersonFilters = PersonFilters()
    qualify: QualifyFilters = QualifyFilters()
    email: EmailFilters = EmailFilters()
