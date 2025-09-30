import base64
import json
import time
from typing import Any

from fastapi import HTTPException
import httpx
from jose import jwt

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
from config import db, logger, settings

CF_API = "https://api.cloudflare.com/client/v4"


class CloudflareService:
    # ------------------------------
    # internal helpers
    # ------------------------------
    @staticmethod
    def _auth_headers() -> dict[str, str]:
        if not settings.CF_API_TOKEN:
            raise RuntimeError("CF_API_TOKEN is not configured")
        return {"Authorization": f"Bearer {settings.CF_API_TOKEN}"}

    @staticmethod
    def _images_delivery_url(image_id: str, variant: str | None = None) -> str:
        acct = settings.CF_IMAGES_ACCOUNT_HASH
        v = variant or settings.CF_IMAGES_DEFAULT_VARIANT
        return f"https://imagedelivery.net/{acct}/{image_id}/{v}"

    @staticmethod
    def _load_stream_private_key() -> str:
        if not settings.CF_STREAM_PRIVATE_KEY_PEM_B64:
            raise RuntimeError("CF_STREAM_PRIVATE_KEY_PEM_B64 not configured")
        return base64.b64decode(settings.CF_STREAM_PRIVATE_KEY_PEM_B64).decode()

    # ------------------------------
    # Images
    # ------------------------------
    @staticmethod
    async def images_create_direct_upload(
        payload: ImagesDirectUploadIn,
    ) -> ImagesDirectUploadOut:
        """
        Create a one-time direct-upload URL for Cloudflare Images (v2).
        - If require_signed_urls=True, DO NOT allow custom_id (Cloudflare cannot make custom-ID images private).
        - Accepts optional expiry and metadata (string map).
        """
        if payload.require_signed_urls and payload.custom_id:
            # Service layer raises HTTPException to match your style in other modules
            raise HTTPException(
                status_code=400,
                detail="Custom ID paths cannot be used with signed URLs; omit `custom_id` for private images.",
            )

        url = f"{CF_API}/accounts/{settings.CF_ACCOUNT_ID}/images/v2/direct_upload"

        # Force multipart/form-data even without a file: httpx uses (None, value) tuples.
        files: dict[str, tuple[str | None, str]] = {}

        if payload.require_signed_urls:
            files["requireSignedURLs"] = (None, "true")
        if payload.expiry:
            files["expiry"] = (None, payload.expiry.isoformat())
        if payload.custom_id:
            files["id"] = (None, payload.custom_id)
        if payload.metadata:
            files["metadata"] = (None, json.dumps(payload.metadata))

        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(
                url, headers=CloudflareService._auth_headers(), files=files
            )
            r.raise_for_status()
            data = r.json()["result"]
            return ImagesDirectUploadOut(
                id=data.get("id", ""), uploadURL=data["uploadURL"]
            )

    @staticmethod
    async def images_get_meta(image_id: str) -> ImageDetails:
        """
        Fetch image details and normalize.
        - Readiness is derived from `draft` (no 'uploaded' boolean).
        - Return both full variant URLs from CF and canonical imagedelivery.net URLs.
        """
        url = f"{CF_API}/accounts/{settings.CF_ACCOUNT_ID}/images/v1/{image_id}"
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url, headers=CloudflareService._auth_headers())
            r.raise_for_status()
            img = r.json()["result"]

        status = "draft" if img.get("draft") else "ready"
        variants: list[str] = img.get("variants", []) or []

        delivered_urls: dict[str, str] = {}
        if variants:
            for vurl in variants:
                variant_name = vurl.rstrip("/").split("/")[-1]
                delivered_urls[variant_name] = CloudflareService._images_delivery_url(
                    image_id, variant_name
                )
        else:
            delivered_urls[settings.CF_IMAGES_DEFAULT_VARIANT] = (
                CloudflareService._images_delivery_url(image_id)
            )

        return ImageDetails(
            id=img["id"],
            filename=img.get("filename"),
            status=status,
            require_signed_urls=img.get("requireSignedURLs", False),
            variants=variants,
            delivered_urls=delivered_urls,
        )

    @staticmethod
    async def images_delete(image_id: str) -> None:
        url = f"{CF_API}/accounts/{settings.CF_ACCOUNT_ID}/images/v1/{image_id}"
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.delete(url, headers=CloudflareService._auth_headers())
            r.raise_for_status()

    # ------------------------------
    # Stream (Direct Creator Uploads)
    # ------------------------------
    @staticmethod
    async def stream_direct_upload(
        payload: StreamDirectUploadIn,
    ) -> StreamDirectUploadOut:
        """
        Create a Direct Creator Upload for Cloudflare Stream.
        - Returns { uid, uploadURL } used by client for both simple and TUS uploads.
        - is_tus flag is a hint for the FE which client to use.
        """
        url = f"{CF_API}/accounts/{settings.CF_ACCOUNT_ID}/stream/direct_upload"

        body: dict[str, Any] = {
            "requireSignedURLs": bool(payload.require_signed_urls),
            "maxDurationSeconds": int(payload.max_duration_seconds),
        }
        if payload.allowed_origins:
            body["allowedOrigins"] = payload.allowed_origins
        if payload.creator:
            body["creator"] = payload.creator
        if payload.meta:
            body["meta"] = payload.meta
        if payload.expiry:
            body["expiry"] = payload.expiry.isoformat()

        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(
                url, headers=CloudflareService._auth_headers(), json=body
            )
            r.raise_for_status()
            data = r.json()["result"]
            return StreamDirectUploadOut(
                uid=data["uid"],
                uploadURL=data["uploadURL"],
                is_tus=(payload.kind == "tus"),
            )

    # ------------------------------
    # Stream playback token (RS256) — header-only `kid`
    # ------------------------------
    @staticmethod
    def stream_make_iframe_url(video_uid: str, signed_token: str | None = None) -> str:
        code = settings.CF_STREAM_CUSTOMER_CODE
        token_or_uid = signed_token or video_uid
        return f"https://customer-{code}.cloudflarestream.com/{token_or_uid}/iframe"

    @staticmethod
    def stream_generate_token(inp: StreamTokenIn) -> StreamTokenOut:
        """
        Mint a short-lived playback token locally (RS256).
        - Put kid in the JWT header (standard); payload includes sub/exp/nbf/iat.
        - sub must be the video UID.
        """
        key_pem = CloudflareService._load_stream_private_key()
        now = int(time.time())
        claims = {
            "sub": inp.video_uid,
            "exp": now + int(inp.ttl_seconds),
            "nbf": now - 5,
            "iat": now,
        }
        headers = {"kid": settings.CF_STREAM_SIGNING_KEY_ID}
        token = jwt.encode(claims, key_pem, algorithm="RS256", headers=headers)
        iframe = CloudflareService.stream_make_iframe_url(
            inp.video_uid, signed_token=token
        )
        return StreamTokenOut(token=token, iframe_url=iframe)

    # ------------------------------
    # First-party player analytics (Mongo)
    # ------------------------------
    @staticmethod
    async def track_player_event(
        evt: PlayerEventIn, user_id: str | None, ua: str | None
    ) -> None:
        doc = evt.model_dump()
        doc["user_id"] = user_id
        doc["ua"] = ua
        doc["ts"] = int(time.time())
        await db["cf_stream_events"].insert_one(doc)

    @staticmethod
    async def compute_video_stats(video_uid: str) -> dict[str, Any]:
        """
        Robust rollup in Python:
        - Uses viewer_id, falls back to user_id
        - Coerces types
        - Safe divide
        - Always returns JSON (never 500)
        """
        try:
            # Pull the minimal fields we need
            cursor = db["cf_stream_events"].find(
                {"video_uid": video_uid},
                {
                    "viewer_id": 1,
                    "user_id": 1,
                    "position_sec": 1,
                    "duration_sec": 1,
                },
            )
            docs = await cursor.to_list(length=10000)  # plenty for a single video

            per_viewer: dict[str, dict[str, float]] = {}
            for d in docs:
                vkey = (
                    (d.get("viewer_id") or d.get("user_id") or "").strip()
                    if isinstance(d.get("viewer_id") or d.get("user_id"), str)
                    else d.get("viewer_id") or d.get("user_id") or ""
                )
                # If still empty (anonymous/bot), skip—won’t help uniqueness
                if not vkey:
                    continue

                try:
                    pos = float(d.get("position_sec") or 0)
                except (TypeError, ValueError):
                    pos = 0.0
                try:
                    dur = float(d.get("duration_sec") or 0)
                except (TypeError, ValueError):
                    dur = 0.0

                bucket = per_viewer.setdefault(vkey, {"max_pos": 0.0, "max_dur": 0.0})
                if pos > bucket["max_pos"]:
                    bucket["max_pos"] = pos
                if dur > bucket["max_dur"]:
                    bucket["max_dur"] = dur

            unique_viewers = len(per_viewer)
            if unique_viewers == 0:
                return {
                    "video_uid": video_uid,
                    "unique_viewers": 0,
                    "avg_watch_pct": 0.0,
                    "completions": 0,
                }

            watched_pcts: list[float] = []
            completions = 0
            for v in per_viewer.values():
                dur = v["max_dur"]
                pos = v["max_pos"]
                pct = min(1.0, (pos / dur)) if dur > 0 else 0.0
                watched_pcts.append(pct)
                if pct >= 0.95:
                    completions += 1

            avg_watch_pct = (
                sum(watched_pcts) / len(watched_pcts) if watched_pcts else 0.0
            )

            return {
                "video_uid": video_uid,
                "unique_viewers": int(unique_viewers),
                "avg_watch_pct": float(avg_watch_pct),
                "completions": int(completions),
            }
        except Exception as e:
            logger.exception(f"compute_video_stats failed for {video_uid}: {e}")
            return {
                "video_uid": video_uid,
                "unique_viewers": 0,
                "avg_watch_pct": 0.0,
                "completions": 0,
            }


# Exported singleton to match your pattern (e.g., session_service = SessionService())
cloudflare_service = CloudflareService()
