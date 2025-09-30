# app/config/settings.py
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # general
    FRONTEND_BASE_URL: str = "https://clapp.test.env"
    LOGGING_LEVEL: str = "INFO"

    # redis
    SENTINEL_HOST: str | None = None
    SENTINEL_PORT: int = 8000
    SENTINEL_USER: str | None = None
    SENTINEL_PASSWORD: str | None = None
    REDIS_USER: str | None = None
    REDIS_PASSWORD: str | None = None
    CA_CERT_B64: str | None = None
    CLIENT_CERT_B64: str | None = None
    CLIENT_KEY_B64: str | None = None

    # mongo
    MONGO_USER_RW: str | None = None
    MONGO_PASS: str | None = None
    MONGO_HOSTS: str | None = None

    # jira
    JIRA_BASE_URL: str = ""
    JIRA_USER: str = ""
    JIRA_USER_PASSWORD: str = ""

    # google
    GOOGLE_DRIVE_FOLDER_ID: str | None = None
    GOOGLE_CREDENTIALS_JSON: str = ""
    SCOPES: list = ["https://www.googleapis.com/auth/drive"]
    _KM_GROUP: str = "km@exness.com"

    # sentry
    SENTRY_DSN: str | None = None

    # Okta - UAT (Corporate)
    OKTA_CLIENT_ID: str | None = None
    OKTA_CLIENT_SECRET: str | None = None
    OKTA_DOMAIN: str | None = None

    # Okta - DEV (Your personal account)
    OKTA_CLIENT_ID_DEV: str | None = None
    OKTA_CLIENT_SECRET_DEV: str | None = None
    OKTA_DOMAIN_DEV: str | None = None

    # Session Management
    SESSION_SECRET_KEY: str = "a-simple-but-long-secret-for-dev-only"

    # HiBob
    HR_MEDIUM_API_KEY: str | None = None

    # Cloudflare (Images + Stream)
    CF_ACCOUNT_ID: str | None = None  # required
    CF_API_TOKEN: str | None = None  # token with Images & Stream perms

    # Images delivery
    CF_IMAGES_ACCOUNT_HASH: str | None = None  # for imagedelivery.net URLs
    CF_IMAGES_DEFAULT_VARIANT: str = "public"  # your public variant name

    # Stream playback + embeds
    CF_STREAM_CUSTOMER_CODE: str | None = (
        None  # used in customer-<code>.cloudflarestream.com
    )
    CF_STREAM_REQUIRE_SIGNED: bool = True  # default: private playback

    # Stream signed playback (RS256, local signing)
    CF_STREAM_SIGNING_KEY_ID: str | None = None  # 'kid' from /stream/keys
    CF_STREAM_PRIVATE_KEY_PEM_B64: str | None = (
        None  # base64-encoded PEM (store in secrets)
    )


settings = Settings()  # singleton
