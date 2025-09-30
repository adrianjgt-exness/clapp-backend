from fastapi import APIRouter, Header, Query, Request

from .model import TokenExchangeRequest
from .service import auth_service
from config import redis_client

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.get(
    "/config",
    summary="Get sign-in configuration (Okta)",
    description=(
        "**What this does:** Returns the settings the app uses to start sign-in with Okta.\n\n"
        "**You provide:** The deployment stage (`dev` or `uat`).\n"
        "**You get:** A small JSON object the frontend uses to launch the login flow."
    ),
    responses={
        200: {
            "description": "Okta configuration for the selected stage.",
            "content": {
                "application/json": {
                    "example": {
                        "issuer": "https://okta.example.com/oauth2/default",
                        "client_id": "your-client-id",
                        "redirect_uri": "https://clapp.test.env/auth/callback",
                        "scopes": ["openid", "profile", "email"],
                        "audience": "api://default",
                    }
                }
            },
        },
        400: {"description": "Stage was missing or invalid."},
        500: {"description": "Could not load configuration."},
    },
)
async def get_okta_config(
    stage: str = Query(
        ...,
        description="The deployment stage",
        enum=["dev", "uat"],
        examples={"dev": {"value": "dev"}, "uat": {"value": "uat"}},
    ),
):
    """
    Provides the necessary, non-secret Okta configuration to the frontend
    by calling the authentication service.
    """
    return auth_service.get_okta_config(stage)


@router.post("/token/exchange")
async def exchange_token(request: Request, payload: TokenExchangeRequest):
    """
    Receives an authorization code from the frontend, creates a session
    in Redis, and returns a session token.
    """
    session_data = await auth_service.exchange_code_for_token_and_session(
        request,
        payload.code,
        payload.stage,
        payload.redirect_uri,
        payload.code_verifier,
        payload.nonce,
    )
    return session_data


@router.post(
    "/logout",
    summary="Sign out and clear your session",
    description=(
        "**What this does:** Logs you out by removing your session from the server.\n\n"
        "**You provide:** `Authorization: Bearer <access-token>` header.\n"
        "**You get:** A simple confirmation. Safe to call even if you’re already logged out."
    ),
    responses={
        200: {
            "description": "Signed out (idempotent).",
            "content": {
                "application/json": {
                    "example": {
                        "status": "success",
                        "message": "Logged out successfully.",
                    }
                }
            },
        },
        500: {"description": "Could not complete logout."},
    },
)
async def logout(
    authorization: str | None = Header(
        None,
        description="Bearer token of the current session, e.g., `Bearer eyJ...`",
        examples={"bearer": {"summary": "Example", "value": "Bearer eyJhbGciOi..."}},
    ),
):
    """
    Logs the user out by deleting their session from Redis.
    """
    if not authorization or not authorization.startswith("Bearer "):
        return {"status": "success"}

    token = authorization.split(" ")[1]
    session_key = f"session:{token}"

    await redis_client.delete(session_key)

    return {"status": "success", "message": "Logged out successfully."}
