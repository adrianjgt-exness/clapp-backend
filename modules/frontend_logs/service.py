from fastapi import Request

from config import logger


class OktaService:
    @staticmethod
    async def log_from_frontend(request: Request) -> dict:
        try:
            body = await request.json()
            message = body.get("message", "")
            meta = body.get("meta", {})

            # The structured data to be added to the log record
            log_extra_data = {"source": "FRONTEND", "meta": meta}

            # The first argument is the simple string message.
            # The dictionary is passed to the 'extra' parameter.
            logger.info(message, extra=log_extra_data)

            return {"status": "ok"}
        except Exception as e:
            logger.exception(f"Error with frontend logging: {e}")
            raise
