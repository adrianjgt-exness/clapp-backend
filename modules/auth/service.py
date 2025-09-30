import secrets

from fastapi import HTTPException, Request

from config import logger, oauth, settings
from modules.hibob.service import HibobService
from modules.user_sessions.model import SessionData
from modules.user_sessions.service import session_service
from modules.users.service import UserService


class AuthService:
    @staticmethod
    def get_okta_config(stage: str):
        """
        Returns the appropriate, non-secret Okta configuration for the given stage.
        """
        logger.info(f"Fetching Okta configuration for stage: '{stage}'")
        if stage == "dev":
            return {
                "clientId": settings.OKTA_CLIENT_ID_DEV,
                "oktaDomain": settings.OKTA_DOMAIN_DEV,
                "redirectUri": "http://localhost:3000/oauth-success",
                "authorizationServerPath": "/oauth2/default/v1/authorize",
            }
        elif stage == "uat":
            return {
                "clientId": settings.OKTA_CLIENT_ID,
                "oktaDomain": settings.OKTA_DOMAIN,
                "redirectUri": "https://clapp.test.env/oauth-success",
                "authorizationServerPath": "/oauth2/v1/authorize",
            }
        raise HTTPException(status_code=400, detail=f"Invalid stage provided: {stage}")

    @staticmethod
    async def exchange_code_for_token_and_session(
        request: Request,
        code: str,
        stage: str,
        redirect_uri: str,
        code_verifier: str,
        nonce: str,
    ):
        """
        Exchanges an authorization code for Okta tokens, then creates a custom
        session in Redis and returns a secure session token.
        """
        provider = "okta_dev" if stage == "dev" else "okta_uat"
        client = getattr(oauth, provider, None)
        if not client:
            raise HTTPException(
                status_code=500, detail=f"OAuth client '{provider}' not configured."
            )

        try:
            logger.info(
                f"Attempting token exchange for provider '{provider}' with redirect_uri: '{redirect_uri}'"
            )
            token_data = await client.fetch_access_token(
                code=code,
                redirect_uri=redirect_uri,
                code_verifier=code_verifier,
            )
            okta_user_info = await client.parse_id_token(token_data, nonce=nonce)
            user_email = okta_user_info.get("email")
            logger.info(f"Successfully parsed ID token. User email: {user_email}")

            if not user_email:
                raise HTTPException(
                    status_code=450, detail="Could not retrieve user info from Okta."
                )

            hibob_employee = None
            try:
                logger.info(
                    f"Making service call to fetch HiBob data for: {user_email}"
                )
                hibob_employees = await HibobService.find_employee_by_email(user_email)
                if hibob_employees:
                    # Safely get the first employee object from the list
                    hibob_employee = hibob_employees[0]
                else:
                    logger.warning(f"No data found in HiBob for {user_email}")
            except Exception as hibob_error:
                logger.error(
                    f"Failed during HibobService call. Error: {hibob_error}",
                    exc_info=True,
                )

            app_user = await UserService.update_or_create_user(
                user_email=user_email,
                hibob_employee=hibob_employee,
            )

            session_token = secrets.token_urlsafe(32)
            session_object = SessionData(user=app_user, cache={})

            success = await session_service.create_session(
                session_object, session_token
            )
            if not success:
                raise HTTPException(
                    status_code=500, detail="Failed to create user session."
                )

            # Return the token and the full session object to the frontend
            return {
                "session_token": session_token,
                "user": session_object.model_dump(by_alias=True),
            }

        except Exception as e:
            logger.error(
                f"Error during token exchange for provider '{provider}'. Error: {e}",
                exc_info=True,
            )
            raise (
                e
                if isinstance(e, HTTPException)
                else HTTPException(
                    status_code=400,
                    detail="Invalid authorization code or token exchange failed.",
                )
            )


auth_service = AuthService()
