from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response, status

from .model import (
    ImageDetails,
    ImagesDirectUploadIn,
    ImagesDirectUploadOut,
    PlayerEventIn,
    StreamDirectUploadIn,
    StreamDirectUploadOut,
    StreamTokenIn,
    StreamTokenOut,
)
from .service import cloudflare_service
from config import logger, settings
from dependencies import require_admin, require_redis_session

router = APIRouter(prefix="/cloudflare", tags=["Cloudflare"])

# ======================
# Images
# ======================


@router.post(
    "/images/direct-upload",
    response_model=ImagesDirectUploadOut,
    summary="Get an upload link for a picture",
    description=(
        "Use this when you want to upload an image **directly from your device to Cloudflare** (the file does not pass through our servers).\n\n"
        "**How it works**\n"
        "1) Call this endpoint to get a one-time **uploadURL** and an **id**.\n"
        "2) Send the actual file to **uploadURL** using a standard form upload (`file` field).\n"
        "3) Store the returned **id** in your record—we use it to show the image later.\n\n"
        "**Notes**\n"
        "• If `require_signed_urls` is `true`, Cloudflare will generate a private image; do **not** set `custom_id` in that case.\n"
        "• You can safely ignore the *Creator* column in Cloudflare for direct uploads; we keep attribution in our own system.\n\n"
        "**Example request body**\n"
        "```json\n"
        '{ "require_signed_urls": false }\n'
        "```\n"
        "**Example response**\n"
        "```json\n"
        '{ "id": "<image_id>", "uploadURL": "https://upload.imagedelivery.net/..." }\n'
        "```"
    ),
)
async def create_images_direct_upload(
    body: ImagesDirectUploadIn,
    session=Depends(require_redis_session),
):
    return await cloudflare_service.images_create_direct_upload(body)


@router.get(
    "/images/{image_id}",
    response_model=ImageDetails,
    summary="Get picture details and ready-to-use links",
    description=(
        "Returns the status and delivery links for a previously uploaded image.\n\n"
        "**What you get**\n"
        "• `status` — `ready` when the upload finished, `draft` while Cloudflare is still processing.\n"
        "• `delivered_urls` — copy-pasteable links to show the image (by variant).\n\n"
        "**Example**\n"
        "```json\n"
        "{\n"
        '  "id": "<image_id>",\n'
        '  "status": "ready",\n'
        '  "delivered_urls": {\n'
        '    "public": "https://imagedelivery.net/<hash>/<image_id>/public"\n'
        "  }\n"
        "}\n"
        "```"
    ),
)
async def get_image_meta(
    image_id: str,
    session=Depends(require_redis_session),
):
    return await cloudflare_service.images_get_meta(image_id)


@router.delete(
    "/images/{image_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a picture (admins only)",
    description=(
        "Permanently removes an image from Cloudflare.\n\n"
        "**Who can use this**: Admins only."
    ),
)
async def delete_image(
    image_id: str,
    _admin=Depends(require_admin),  # deletion restricted to admins
):
    await cloudflare_service.images_delete(image_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/images/webhook",
    summary="(System) Cloudflare Images webhook",
    description=(
        "Receives status notifications from Cloudflare when image uploads finish or fail. "
        "No action required by end-users. Used by the system for monitoring."
    ),
)
async def images_webhook(request: Request):
    payload = await request.json()
    logger.info(f"CF Images webhook payload: {payload}")
    # TODO: add signature/secret validation if you enable it
    return {"ok": True}


# ======================
# Stream (video)
# ======================


@router.post(
    "/stream/direct-upload",
    response_model=StreamDirectUploadOut,
    summary="Get an upload link for a video",
    description=(
        "Use this to upload a video **directly from your device to Cloudflare Stream**.\n\n"
        "**How it works**\n"
        "1) Call this endpoint with `kind`:\n"
        "   • `basic` — small files; single POST upload.\n"
        "   • `tus` — large files; resumable upload using a TUS client.\n"
        "2) You receive a **uid** (video id) and an **uploadURL**.\n"
        "3) Send the file to **uploadURL** (your app/FE handles the actual upload).\n\n"
        "**Access control**\n"
        "If `require_signed_urls` is true, the video will require a short-lived playback token (we issue this with `/stream/token`).\n\n"
        "**Example request body**\n"
        "```json\n"
        '{ "kind": "basic", "require_signed_urls": true, "creator": "<your_user_id>" }\n'
        "```\n"
        "**Example response**\n"
        "```json\n"
        '{ "uid": "<video_uid>", "uploadURL": "https://upload.videodelivery.net/...", "is_tus": false }\n'
        "```"
    ),
)
async def create_stream_direct_upload(
    body: StreamDirectUploadIn,
    session=Depends(require_redis_session),
):
    return await cloudflare_service.stream_direct_upload(body)


@router.post(
    "/stream/token",
    response_model=StreamTokenOut,
    summary="Create a short-lived video access token",
    description=(
        "Generates a **temporary playback token** for private videos. "
        "Use this when the video requires signed access.\n\n"
        "**What you get**\n"
        "• `token` — the signed token.\n"
        "• `iframe_url` — a ready-to-use link that you can embed (e.g., in Slack, LumApps, or a web page).\n\n"
        "**Example request body**\n"
        "```json\n"
        '{ "video_uid": "<video_uid>", "ttl_seconds": 3600 }\n'
        "```\n"
        "**Example response**\n"
        "```json\n"
        '{ "token": "<jwt>", "iframe_url": "https://customer-<code>.cloudflarestream.com/<jwt>/iframe" }\n'
        "```"
    ),
)
async def create_stream_token(
    body: StreamTokenIn,
    session=Depends(require_redis_session),
):
    viewer_id = body.viewer_id or session.get("user", {}).get("id")
    if settings.CF_STREAM_REQUIRE_SIGNED and not viewer_id:
        # Not strictly required, but strongly recommended for attribution
        logger.warning("Signed playback without viewer_id; proceeding.")
    return cloudflare_service.stream_generate_token(
        StreamTokenIn(
            video_uid=body.video_uid, ttl_seconds=body.ttl_seconds, viewer_id=viewer_id
        )
    )


@router.get(
    "/stream/{video_uid}/embed",
    summary="Get an embeddable video link (iframe)",
    description=(
        "Returns a **copy-pasteable iframe URL** for the video. "
        "If the video is private, the link is signed automatically.\n\n"
        "**Example response**\n"
        "```json\n"
        '{ "iframe_url": "https://customer-<code>.cloudflarestream.com/<uid_or_token>/iframe", "signed": true }\n'
        "```"
    ),
)
async def get_stream_iframe(
    video_uid: str,
    session=Depends(require_redis_session),
):
    if settings.CF_STREAM_REQUIRE_SIGNED:
        out = cloudflare_service.stream_generate_token(
            StreamTokenIn(video_uid=video_uid)
        )
        return {"iframe_url": out.iframe_url, "signed": True}
    return {
        "iframe_url": cloudflare_service.stream_make_iframe_url(video_uid),
        "signed": False,
    }


# Optional webhook (processing/ready events)
@router.post(
    "/stream/webhook",
    summary="(System) Cloudflare Stream webhook",
    description=(
        "Receives processing/ready notifications from Cloudflare Stream (e.g., when a video is ready to play). "
        "No action required by end-users. Used by the system for monitoring."
    ),
)
async def stream_webhook(request: Request):
    sig = request.headers.get("Webhook-Signature")
    body = await request.body()
    logger.info(f"CF Stream webhook sig={sig} body={body[:512]!r}")
    # TODO: verify signature against your webhook secret when configured
    return {"ok": True}


# ======================
# Player event tracking (first-party analytics)
# ======================


@router.post(
    "/stream/events",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Record a player event (play, pause, progress)",
    description=(
        "Used by our viewer pages to send simple playback events to the backend. "
        "This powers basic engagement metrics when Cloudflare Analytics are not enabled.\n\n"
        "**Typical events**: `play`, `pause`, `timeupdate`, `ended`.\n"
        "**Who uses this**: our web pages and embeds (e.g., Slack, LumApps). End-users do not call this directly."
    ),
)
async def track_event(
    body: PlayerEventIn,
    request: Request,
    session=Depends(require_redis_session),
):
    ua = request.headers.get("user-agent")

    # robust viewer id from session
    sess_user = session.get("user", {}) or {}
    viewer_id = (
        body.viewer_id
        or sess_user.get("id")  # some modules use 'id'
        or sess_user.get("_id")  # your sessions use '_id'  <-- key difference
        or sess_user.get("email")  # last-resort stable identifier
    )

    # make sure the event we store carries viewer_id
    body.viewer_id = viewer_id

    # also pass the same id as user_id for convenience
    await cloudflare_service.track_player_event(body, user_id=viewer_id, ua=ua)
    return {"queued": True}


@router.get(
    "/stream/stats/video/{video_uid}",
    summary="See simple viewing stats for a video",
    description=(
        "Returns an at-a-glance summary of viewer engagement **from our own event logs** "
        "(unique viewers, average watch %, and number of completions). "
        "This is separate from Cloudflare Analytics and works even if Cloudflare Analytics are disabled.\n\n"
        "**Example response**\n"
        "```json\n"
        '{ "unique_viewers": 12, "avg_watch_pct": 0.72, "completions": 5 }\n'
        "```"
    ),
)
async def video_stats(
    video_uid: str,
    session=Depends(require_redis_session),
):
    return await cloudflare_service.compute_video_stats(video_uid)
