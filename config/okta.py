from authlib.integrations.starlette_client import OAuth

from .logger import logger
from .settings import settings

# Create a single OAuth registry that will hold multiple client configurations
oauth = OAuth()

# --- Register the UAT client (Corporate Okta) ---
if all([settings.OKTA_CLIENT_ID, settings.OKTA_CLIENT_SECRET, settings.OKTA_DOMAIN]):
    oauth.register(
        name="okta_uat",
        client_id=settings.OKTA_CLIENT_ID,
        client_secret=settings.OKTA_CLIENT_SECRET,
        server_metadata_url=f"{settings.OKTA_DOMAIN}/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )
    logger.info("Registered 'okta_uat' client.")

# --- Register the DEV client (Your personal Okta) ---
if all(
    [
        settings.OKTA_CLIENT_ID_DEV,
        settings.OKTA_CLIENT_SECRET_DEV,
        settings.OKTA_DOMAIN_DEV,
    ]
):
    oauth.register(
        name="okta_dev",
        client_id=settings.OKTA_CLIENT_ID_DEV,
        client_secret=settings.OKTA_CLIENT_SECRET_DEV,
        server_metadata_url=f"{settings.OKTA_DOMAIN_DEV}/oauth2/default/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )
    logger.info("Registered 'okta_dev' client.")
