from fastapi import HTTPException
import httpx
from pydantic import EmailStr, ValidationError

from .model import HibobEmployee
from config import logger
from config.settings import settings

HIBOB_API_BASE_URL = "https://medium.exness.io/api/v1"


class HibobService:
    @staticmethod
    async def find_employee_by_email(
        email: EmailStr,
    ) -> list[HibobEmployee]:
        """
        Calls the HiBob API to find employees by their email address.
        """
        if not settings.HR_MEDIUM_API_KEY:
            logger.error("[HIBOB_SVC] HR_MEDIUM_API_KEY is not configured.")
            raise HTTPException(
                status_code=500, detail="HiBob API key is not configured."
            )

        url = f"{HIBOB_API_BASE_URL}/employees/find/"
        headers = {
            "accept": "application/json",
            "X-API-Key": settings.HR_MEDIUM_API_KEY,
        }
        params = {"search_query": email}

        async with httpx.AsyncClient() as client:
            try:
                logger.info(f"[HIBOB_SVC] Searching for employee with email: {email}")
                response = await client.get(url, headers=headers, params=params)
                response.raise_for_status()

                # The API returns a list directly, so we parse it as such
                response_data = response.json()
                employees = [
                    HibobEmployee.model_validate(item) for item in response_data
                ]

                logger.info(
                    f"[HIBOB_SVC] Found {len(employees)} employee(s) for email: {email}"
                )
                return employees

            except ValidationError as e:
                logger.error(
                    f"[HIBOB_SVC] Pydantic validation error parsing HiBob response: {e}"
                )
                raise HTTPException(
                    status_code=500, detail="Failed to parse response from HiBob API."
                )
            except httpx.HTTPStatusError as e:
                logger.error(
                    f"[HIBOB_SVC] HTTP error calling HiBob API: {e.response.status_code} - {e.response.text}"
                )
                raise HTTPException(
                    status_code=e.response.status_code,
                    detail=f"Error from HiBob API: {e.response.text}",
                )
            except Exception as e:
                logger.error(f"[HIBOB_SVC] An unexpected error occurred: {str(e)}")
                raise HTTPException(
                    status_code=500,
                    detail="An unexpected error occurred while communicating with HiBob API.",
                )
