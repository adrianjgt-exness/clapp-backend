from pydantic import BaseModel, Field


class TokenExchangeRequest(BaseModel):
    """
    Request body for swapping an authorization code for tokens during sign-in.
    Used after the identity provider redirects back to CLApp.
    """

    code: str = Field(
        ...,
        description="One-time authorization code received from the identity provider.",
        examples=["0.AAA..."],
    )
    stage: str = Field(
        ..., description="Deployment stage this login belongs to.", examples=["dev"]
    )
    redirect_uri: str = Field(
        ...,
        description="Exact redirect URI registered with the identity provider.",
        examples=["https://clapp.test.env/auth/callback"],
    )
    code_verifier: str = Field(
        ...,
        description="PKCE code verifier paired with the original challenge.",
        examples=["lKpK9..."],
    )
    nonce: str = Field(
        ...,
        description="Nonce used to prevent replay attacks.",
        examples=["2c8f1a4e-9c9c-4e2a-8d6e-2c1d3d3c7f2a"],
    )
