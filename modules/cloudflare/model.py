from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ImagesDirectUploadIn(BaseModel):
    """
    Request a one-time direct-upload URL for Cloudflare Images.
    Rules:
      - If `require_signed_urls` is True, DO NOT send `custom_id` (Cloudflare limitation).
    """

    require_signed_urls: bool = False
    expiry: datetime | None = Field(
        default=None, description="Optional ISO8601 expiry for the upload URL."
    )
    custom_id: str | None = Field(
        default=None,
        description="Only for PUBLIC images. Forbidden when require_signed_urls=True.",
    )
    metadata: dict[str, str] | None = Field(
        default=None, description="Optional string metadata to store with the image."
    )


class ImagesDirectUploadOut(BaseModel):
    id: str = Field(
        description="Image ID (Cloudflare-generated unless custom_id used for public images)."
    )
    upload_url: str = Field(
        alias="uploadURL",
        description="One-time URL to which the client uploads the file.",
    )


class ImageDetails(BaseModel):
    """
    Normalized image metadata we return to callers.
    `status` is derived from Cloudflare's `draft` field:
      - 'ready'  => draft is absent/false
      - 'draft'  => draft is true (upload not completed yet)
    """

    id: str
    filename: str | None = None
    status: Literal["ready", "draft"] = "ready"
    require_signed_urls: bool = False
    variants: list[str] = Field(
        default_factory=list, description="Full variant URLs returned by Cloudflare."
    )
    delivered_urls: dict[str, str] = Field(
        default_factory=dict,
        description="Convenience map variant_name -> imagedelivery.net/{hash}/{id}/{variant}",
    )


class StreamDirectUploadIn(BaseModel):
    """
    Create a Direct Creator Upload for Cloudflare Stream.
    Use `kind="basic"` for small files, `kind="tus"` for resumable uploads on the client.
    """

    kind: Literal["basic", "tus"] = "basic"
    # Access model
    require_signed_urls: bool = True
    # Optional controls
    allowed_origins: list[str] | None = None
    creator: str | None = Field(
        default=None, description="Your internal creator/user id."
    )
    meta: dict[str, str] | None = None
    expiry: datetime | None = None
    # Soft hints for client UX (not sent to Cloudflare)
    max_duration_seconds: int = 3600


class StreamDirectUploadOut(BaseModel):
    uid: str
    upload_url: str = Field(
        alias="uploadURL",
        description="URL the client uploads to (works for basic and tus).",
    )
    is_tus: bool = False


class StreamTokenIn(BaseModel):
    video_uid: str
    ttl_seconds: int = 3600
    viewer_id: str | None = Field(
        default=None, description="Employee/slack id for your own analytics."
    )


class StreamTokenOut(BaseModel):
    token: str
    iframe_url: str


class PlayerEventIn(BaseModel):
    """
    Events forwarded from your viewer page (Slack, LumApps, Web).
    """

    video_uid: str
    event: Literal["loadstart", "play", "pause", "timeupdate", "ended", "error"]
    position_sec: float = 0.0
    duration_sec: float | None = None
    viewer_id: str | None = None
    context: Literal["slack", "lumapps", "web"] = "web"
    message_ts: str | None = None  # Slack message ts (if applicable)
    channel: str | None = None  # Slack channel id/name (if applicable)
    user_agent: str | None = None


class PlayerStatsOut(BaseModel):
    video_uid: str
    unique_viewers: int
    avg_watch_pct: float
    completions: int
