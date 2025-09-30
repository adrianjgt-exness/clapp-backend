# app/config/google_drive_config.py
import asyncio
from io import BytesIO
import json
from typing import Any, AsyncGenerator

from fastapi import HTTPException, UploadFile
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

from .logger import logger
from .settings import settings


def _build_service() -> Any:
    """Return an authenticated Google Drive resource using a service account."""
    if not settings.GOOGLE_CREDENTIALS_JSON:
        raise ValueError("Google Drive service account JSON credentials missing")

    info = json.loads(settings.GOOGLE_CREDENTIALS_JSON)

    creds = service_account.Credentials.from_service_account_info(
        info,
        scopes=settings.SCOPES,
    )
    return build("drive", "v3", credentials=creds)


class GoogleDriveService:
    """Thin async wrapper for common Drive operations."""

    _service: Any

    def __init__(self):
        try:
            self._service = _build_service()
            logger.info("Google Drive service ready")
        except Exception as exc:
            logger.exception("Drive init failed: %s", exc)
            raise HTTPException(500, "Google Drive unavailable")

    # ---------- uploads ----------

    def _upload_sync(self, data: bytes, filename: str, mime: str) -> str:
        meta = {"name": filename, "parents": [settings.GOOGLE_DRIVE_FOLDER_ID]}
        media = MediaIoBaseUpload(BytesIO(data), mime, resumable=True)

        file_info = (
            self._service.files()
            .create(
                body=meta,
                media_body=media,
                fields="id, webViewLink",
                supportsAllDrives=True,
            )
            .execute()
        )

        link = file_info["webViewLink"]
        logger.info("Uploaded %s (%s)", filename, link)
        return link

    async def upload_files(self, files: list[UploadFile]) -> list[str]:
        links: list[str] = []
        for f in files:
            data = await f.read()
            try:
                link = await asyncio.to_thread(
                    self._upload_sync,
                    data,
                    f.filename or "untitled",
                    f.content_type or "application/octet-stream",
                )
                links.append(link)
            except Exception as exc:
                logger.exception("Drive upload failed for %s: %s", f.filename, exc)
        return links

    # ---------- downloads ----------

    async def _stream_file(self, file_id: str) -> AsyncGenerator[bytes, None]:
        request = self._service.files().get_media(
            fileId=file_id, supportsAllDrives=True
        )
        buf = BytesIO()
        dl = MediaIoBaseDownload(buf, request)

        done = False
        while not done:
            status, done = await asyncio.to_thread(dl.next_chunk)
            if status:
                logger.info("Download %.0f%%", status.progress() * 100)

        buf.seek(0)
        yield buf.read()

    async def get_file_content(self, file_id: str) -> AsyncGenerator[bytes, None]:
        """Public name your services call."""
        return self._stream_file(file_id)


# exported singleton
google_drive_service = GoogleDriveService()
