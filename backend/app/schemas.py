from pydantic import BaseModel, Field


class CompanyFilters(BaseModel):
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
    requireMx: bool = True


class CampaignFilters(BaseModel):
    leadsWanted: int = Field(100, ge=1)
    maxCompaniesToScan: int = Field(500, ge=1)
    maxCreditsPerRun: int = Field(2500, ge=1)
    maxPerCompany: int = 1
    company: CompanyFilters = CompanyFilters()
    person: PersonFilters = PersonFilters()
    qualify: QualifyFilters = QualifyFilters()
    email: EmailFilters = EmailFilters()
