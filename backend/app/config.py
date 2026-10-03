from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    deepseek_api_key: str = ""
    deepseek_model_fast: str = "deepseek-flash"
    deepseek_model_smart: str = "deepseek-v4-pro"

    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/auth/google/callback"

    supabase_url: str = ""
    supabase_key: str = ""

    firecrawl_api_key: str = ""
    # Be gentle with Firecrawl. Free plans allow few requests per minute and few at once.
    firecrawl_min_interval: float = 2.0   # seconds to wait between two requests (any task)
    firecrawl_concurrency: int = 2        # requests in flight at the same time
    firecrawl_max_retries: int = 6        # after a 429 "too many requests": wait, then try again this many times

    app_secret_key: str = ""
    redis_url: str = "redis://redis:6379/0"
    frontend_url: str = "http://localhost:5173"
    public_base_url: str = ""
    dry_run: bool = True
    dev_firecrawl_credit_limit: int | None = 150
    dev_llm_call_limit: int | None = 100

    companies_house_api_key: str = ""

    # Hosting: when set, every API call needs this password (except /health, /r/{token}, the Google callback).
    access_password: str = ""

    @field_validator("dev_firecrawl_credit_limit", "dev_llm_call_limit", mode="before")
    @classmethod
    def _empty_is_none(cls, v):
        # "Clear the dev limits" in .env means an empty value. That must not crash the app.
        return None if isinstance(v, str) and not v.strip() else v


settings = Settings()
