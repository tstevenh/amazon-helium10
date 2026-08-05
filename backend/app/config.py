from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database
    database_url: str

    # JWT
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 480

    # Fernet encryption (for Amazon tokens at rest)
    fernet_key: str = ""

    # Amazon Advertising API
    amazon_client_id: str = ""
    amazon_client_secret: str = ""
    amazon_redirect_uri: str = "http://localhost:8000/accounts/oauth/callback"
    amazon_api_base_url: str = "https://advertising-api.amazon.com"
    # When true, skip real Amazon API calls and return mock profile data.
    # Set AMAZON_MOCK_MODE=false when real credentials are available.
    amazon_mock_mode: bool = False
    amazon_full_sync_max_pages: int = 0  # 0 = unlimited; set >0 for emergency page cap

    # Performance sync: how many days of history to pull on first sync.
    # Subsequent syncs (already-synced profiles) use a 3-day rolling window.
    # Amazon Ads Reporting API typically supports up to 2 years (730 days).
    amazon_perf_lookback_days: int = 90   # Max lookback; Amazon keeps ~90-95 days. Max 31 days per API request (chunked automatically)

    # Frontend URL — used to redirect the browser after OAuth callback completes.
    # In Docker: http://localhost:3000 (user-facing port)
    # Change to your public domain in production.
    frontend_url: str = "http://localhost:3000"

    # Runtime
    env: str = "dev"


settings = Settings()


def validate_real_mode_config() -> list[str]:
    """
    Returns a list of environment variable names that are required in real
    mode but not set.

    Does not raise — callers decide what to do with missing vars.

    Required in real mode:
      AMAZON_CLIENT_ID      — LWA app client ID from Amazon Developer Console
      AMAZON_CLIENT_SECRET  — LWA app client secret
      AMAZON_REDIRECT_URI   — must exactly match the URI registered in your LWA app
      AMAZON_API_BASE_URL   — Amazon Ads API base (https://advertising-api.amazon.com)
      FERNET_KEY            — symmetric key for encrypting stored tokens at rest
    """
    if settings.amazon_mock_mode:
        return []

    required: dict[str, str] = {
        "AMAZON_CLIENT_ID":     settings.amazon_client_id,
        "AMAZON_CLIENT_SECRET": settings.amazon_client_secret,
        "AMAZON_REDIRECT_URI":  settings.amazon_redirect_uri,
        "AMAZON_API_BASE_URL":  settings.amazon_api_base_url,
        "FERNET_KEY":           settings.fernet_key,
    }
    return [name for name, value in required.items() if not value]
