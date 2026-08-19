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

    # Retry policy for paginated Amazon list fetches. A single dropped
    # connection part-way through ~230 sequential page requests used to
    # discard the entire fetch (observed 2026-08-04: ~215k keywords lost).
    amazon_fetch_max_retries: int = 4
    amazon_fetch_backoff_sec: float = 2.0

    # Amazon report generation is queued on their side and highly variable —
    # measured 23 min and 40 min for the identical 2-day report on the same
    # day (2026-08-04). The old hardcoded 180-poll (~40 min) ceiling meant
    # ad-group and keyword reports were abandoned every single time.
    amazon_report_poll_max_attempts: int = 1440   # 1440 x 10s = 4 hours
    amazon_report_poll_interval_sec: int = 10

    # Background worker (Celery + Redis)
    redis_url: str = "redis://redis:6379/0"
    # Periodic full sync interval. 0 disables the schedule entirely.
    sync_schedule_hours: int = 6
    # How often enabled rules are evaluated. Spec workflow 4 is a daily
    # job. 0 disables it — rules can still be run by hand.
    rule_schedule_hours: int = 24

    # ── Amazon WRITE access ────────────────────────────────────────────────
    # Master kill-switch for every mutating Amazon Ads call. Defaults to False
    # so no environment can change a live ad account by accident — including a
    # fresh clone, a test run, or a misconfigured deploy. Turn on ONLY when the
    # team has explicitly authorised writes, and turn it back off afterwards.
    amazon_write_enabled: bool = False

    # Failure alerting. POSTs JSON to this URL (Slack/Discord/n8n webhook).
    # Empty disables delivery — send_alert() logs at ERROR and returns False.
    # A missing alert channel must never crash the scheduler, but it must
    # also never look like success.
    alert_webhook_url: str = ""
    # An account with no successful sync in this many hours is "stale".
    # A sync that silently never runs is as damaging as one that errors.
    sync_stale_after_hours: int = 24
    health_check_interval_minutes: int = 30
    # A job left at queued/running for longer than this is orphaned: the
    # worker died without reaching mark_failed. Must stay above Celery's hard
    # task_time_limit (6h5m) so a slow-but-alive sync is never reaped.
    #
    # This matters more than it looks. has_active() counts queued|running and
    # the router refuses a new sync while one is active, so an orphan does not
    # merely spin the UI — it blocks every future sync for that account until
    # someone edits the table by hand. A host reboot mid-sync did exactly that.
    sync_orphan_after_hours: int = 7
    # Suppress an identical notification repeated inside this window.
    #
    # Health checks run every 30 minutes and re-report conditions that persist,
    # so one stale account produced 47 identical rows in 24 hours. Delivered to
    # a real channel that is 47 messages for one problem — the team mutes it,
    # and the app is back to failing silently, which is the exact thing the
    # alerting was built to prevent. 6 hours still reminds; it does not spam.
    notification_dedupe_minutes: int = 360
    # Dayparting reconciles state rather than firing on edges, so this is the
    # error bound: a missed run means campaigns sit in the wrong state for at
    # most this long. Windows are whole hours, so 60 is the natural default.
    dayparting_interval_minutes: int = 60
    # Ceiling on bid writes per schedule per run.
    #
    # Amazon has no hourly bid multiplier, so a bid window has to be written
    # per keyword. This account has 222,384 targets; one campaign with 5,000
    # keywords means 5,000 writes when a window opens and 5,000 more when it
    # closes, twice a day, against a rate-limited API. The cap bounds that.
    #
    # Whatever the cap drops is LOGGED and recorded on the run, never silently
    # skipped — a truncated reconcile that looked complete would be worse than
    # a slow one. Reconciliation means the remainder is picked up next hour.
    dayparting_max_bid_writes_per_run: int = 500
    # Daily digest cadence. 0 disables it. Not a cron expression on purpose —
    # Beat here uses plain intervals, and a fake cron would imply a wall-clock
    # guarantee this scheduler does not offer.
    digest_interval_hours: int = 24

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
