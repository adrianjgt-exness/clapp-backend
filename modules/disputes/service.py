from datetime import datetime
from typing import AsyncGenerator

from bson import ObjectId
from fastapi import UploadFile

from config import db, google_drive_service, logger
from modules.disputes.model import Dispute, DisputeStatus


disputes_collection = db.disputes


class DisputeService:
    # ───────────────────────────────────────────────────────── public API ──
    @staticmethod
    async def create_dispute(dispute: Dispute) -> str:
        data = dispute.model_dump()
        result = await disputes_collection.insert_one(data)
        logger.info(f"Dispute stored: {result.inserted_id}")
        return str(result.inserted_id)

    @staticmethod
    async def list_disputes(
        status: DisputeStatus | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> list[dict]:
        query = {"status": status.value} if status else {}
        skip = (page - 1) * page_size
        cursor = (
            disputes_collection.find(query)
            .sort("date_of_creation", -1)
            .skip(skip)
            .limit(page_size)
        )
        docs = []
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            docs.append(doc)
        return docs

    @staticmethod
    async def get_status_counts() -> dict[str, int]:
        pipeline = [{"$group": {"_id": "$status", "count": {"$sum": 1}}}]
        counts: dict[str, int] = {}
        cursor = await disputes_collection.aggregate(pipeline)
        async for doc in cursor:
            counts[doc["_id"]] = doc["count"]
        # Ensure zeroes for missing statuses
        for st in DisputeStatus:
            counts.setdefault(st.value, 0)
        return counts

    @staticmethod
    async def take_ownership(dispute_id: str, resolver_id: str) -> dict:
        return await DisputeService._update_status(
            dispute_id,
            new_status=DisputeStatus.IN_PROGRESS,
            resolver_id=resolver_id,
        )

    @staticmethod
    async def resolve_dispute(
        dispute_id: str, resolver_id: str, resolution: str
    ) -> dict:
        return await DisputeService._update_status(
            dispute_id,
            new_status=DisputeStatus.RESOLVED,
            resolver_id=resolver_id,
            resolution=resolution,
        )

    # ─────────────────────────────────────────────────────── helpers ──
    @staticmethod
    async def _update_status(
        dispute_id: str,
        *,
        new_status: DisputeStatus,
        resolver_id: str,
        resolution: str | None = None,
    ) -> dict:
        update_payload = {
            "$set": {
                "status": new_status.value,
                "resolver_id": resolver_id,
                "date_updated": datetime.utcnow(),
            }
        }
        if resolution is not None:
            update_payload["$set"]["resolution"] = resolution

        result = await disputes_collection.update_one(
            {"_id": ObjectId(dispute_id)}, update_payload
        )
        logger.info(
            f"Dispute {dispute_id} -> {new_status.value} "
            f"(matched={result.matched_count}, modified={result.modified_count})"
        )
        return {
            "matched_count": result.matched_count,
            "modified_count": result.modified_count,
        }

    @staticmethod
    async def upload_dispute_attachments(files: list[UploadFile]) -> list[str]:
        """
        Handles the business logic for uploading dispute attachments.
        This method acts as a pass-through to the dedicated Google Drive service.
        """
        if not files:
            return []

        # 3. Delegate the upload task to the GoogleDriveService
        file_links = await google_drive_service.upload_files(files)
        return file_links

    @staticmethod
    async def get_dispute_attachment(file_id: str) -> AsyncGenerator[bytes, None]:
        """
        Streams the content of a dispute attachment from Google Drive.
        """
        return await google_drive_service.get_file_content(file_id)
