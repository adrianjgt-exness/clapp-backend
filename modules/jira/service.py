import asyncio
import re
from typing import Any

from fastapi import HTTPException, status
import httpx

from .model import JiraIssueEdit
from config import logger, settings


# === Merge helpers for Jira Data Center (plain text descriptions) ===
AFFECTED_HEADER = "This issue affects the following users:"
EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)


def _merge_affected_users_block(current_desc: str, text_to_append: str) -> str:
    """
    If `text_to_append` contains the AFFECTED_HEADER, merge the emails under that header
    into the existing block in `current_desc` (idempotent, case-insensitive).
    Otherwise, append `text_to_append` with tidy spacing.
    """
    current_desc = current_desc or ""
    text_to_append = text_to_append or ""

    # If there's no special header in the appended text, just append it.
    if AFFECTED_HEADER.lower() not in text_to_append.lower():
        if not text_to_append:
            return current_desc
        sep = "\n\n" if current_desc and not current_desc.endswith("\n") else "\n"
        return f"{current_desc}{sep}{text_to_append}"

    # Extract incoming emails from the provided block
    incoming = {e.strip().lower() for e in EMAIL_RE.findall(text_to_append)}
    if not incoming:
        return current_desc

    lines = current_desc.splitlines()
    # Find existing header (exact match ignoring case/whitespace)
    header_idx = next(
        (
            i
            for i, ln in enumerate(lines)
            if ln.strip().lower() == AFFECTED_HEADER.lower()
        ),
        None,
    )

    if header_idx is None:
        # No existing block: append a fresh block
        block = [AFFECTED_HEADER] + [f"- {e}" for e in sorted(incoming)]
        if current_desc and not current_desc.endswith("\n"):
            current_desc += "\n"
        if current_desc and not current_desc.endswith("\n\n"):
            current_desc += "\n"
        return (current_desc + "\n".join(block)).rstrip() + "\n"

    # Collect existing emails after header until a non-bullet or blank line
    existing = set()
    i = header_idx + 1
    while i < len(lines):
        ln = lines[i].strip()
        if not ln or not ln.startswith("-"):
            break
        existing.update(e.lower() for e in EMAIL_RE.findall(ln))
        i += 1

    merged = sorted(existing | incoming)
    new_block = [AFFECTED_HEADER] + [f"- {e}" for e in merged]
    return ("\n".join(lines[:header_idx] + new_block + lines[i:])).rstrip() + "\n"


class JiraService:
    """
    Service for all interactions with the Jira API,
    with built-in rate-limit retries on HTTP 429.
    """

    def __init__(self):
        """Initializes the httpx client with Jira credentials."""
        if not all(
            [settings.JIRA_BASE_URL, settings.JIRA_USER, settings.JIRA_USER_PASSWORD]
        ):
            logger.error(
                "Jira settings (JIRA_BASE_URL, JIRA_USER, JIRA_API_TOKEN) are incomplete."
            )
            raise ValueError(
                "Jira integration is not configured. Please check your environment variables."
            )
        self.base_url = f"{settings.JIRA_BASE_URL}/rest/api/2"
        self.auth = (settings.JIRA_USER, settings.JIRA_USER_PASSWORD)
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            auth=self.auth,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            verify=False,
            timeout=httpx.Timeout(connect=5.0, read=20.0, write=10.0, pool=5.0),
        )
        logger.info("JiraService initialized.")

    async def _request_with_rate_limit(
        self, method: str, url: str, **kwargs
    ) -> httpx.Response:
        """
        Wrap any HTTP call, retry on 429 up to max_retries with exponential backoff.
        """
        max_retries = getattr(settings, "JIRA_MAX_RETRIES", 3)
        base_backoff = getattr(settings, "JIRA_BACKOFF_SECONDS", 2)

        for attempt in range(1, max_retries + 1):
            response = await self.client.request(method, url, **kwargs)
            if response.status_code != 429:
                return response

            # Rate limit hit
            retry_after = response.headers.get("Retry-After")
            if retry_after and retry_after.isdigit():
                wait = int(retry_after)
            else:
                wait = base_backoff * attempt
            logger.warning(
                f"429 Rate limit on {method} {url}. "
                f"Retrying in {wait}s (attempt {attempt}/{max_retries})"
            )
            await asyncio.sleep(wait)

        # Last attempt without catching 429
        return await self.client.request(method, url, **kwargs)

    async def _handle_response(self, response: httpx.Response, success_code: int = 200):
        """
        Private helper to handle API responses and errors.
        It now safely handles non-JSON error responses.
        """
        # Check for success codes (200 OK, 201 Created, 204 No Content)
        if response.status_code in [success_code, 201, 204]:
            if response.status_code == 204 or not response.content:
                return None
            return response.json()

        # Handle error responses
        error_details = ""
        try:
            # First, try to parse the error as JSON
            error_details = response.json()
        except Exception:
            # If that fails, it's likely HTML or plain text
            error_details = response.text

        logger.error(
            f"Jira API error. Status: {response.status_code}. Details: {error_details}"
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Error from Jira API: Status {response.status_code}",
        )

    async def get_first_issue(self, jql: str) -> dict[str, Any] | None:
        """
        Fetch only the first issue matching this JQL (maxResults=1).
        """
        payload = {
            "jql": jql,
            "fields": [
                "summary",
                "status",
                "issuetype",
                "description",
                "created",
                "customfield_10006",
                "assignee",
            ],
            "startAt": 0,
            "maxResults": 1,
        }
        try:
            response = await self._request_with_rate_limit(
                "POST", "/search", json=payload
            )
            data = await self._handle_response(response)
            issues = data.get("issues", []) if data else []
            return issues[0] if issues else None
        except httpx.ConnectError as e:
            logger.error(f"Connection to Jira failed while fetching first issue: {e}")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Could not connect to Jira. Original error: {e}",
            )
        except Exception as e:
            logger.error(f"Failed to fetch first issue: {e}", exc_info=True)
            raise

    async def search_all_issues(
        self, jql: str, *, max_results: int = 100
    ) -> list[dict[str, Any]]:
        """
        Fetch *all* issues matching this JQL by paging through Jira.
        max_results: number per page (Jira caps you at 1000, but 100–500 is safer).
        """
        all_issues: list[dict[str, Any]] = []
        start_at = 0
        try:
            while True:
                logger.info(
                    f"Jira paging: startAt={start_at}, maxResults={max_results}"
                )
                payload = {
                    "jql": jql,
                    "fields": [
                        "summary",
                        "status",
                        "issuetype",
                        "description",
                        "created",
                        "customfield_10006",
                        "assignee",
                    ],
                    "startAt": start_at,
                    "maxResults": max_results,
                }

                response = await self._request_with_rate_limit(
                    "POST", "/search", json=payload
                )
                data = await self._handle_response(response)
                batch = data.get("issues", []) if data else []
                all_issues.extend(batch)

                if len(batch) < max_results:
                    break

                start_at += max_results
            logger.info(f"Total issues fetched: {len(all_issues)}")
            return all_issues

        except httpx.ConnectError as e:
            logger.error(f"Connection to Jira failed: {e}")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Could not connect to Jira. SSL/TLS verification may have failed. Original error: {e}",
            )

    async def get_issue(self, issue_key: str) -> dict[str, Any]:
        """
        Retrieves the full details of a single Jira issue.
        """
        logger.info(f"Fetching details for Jira issue: {issue_key}")
        try:
            response = await self._request_with_rate_limit("GET", f"/issue/{issue_key}")
            return await self._handle_response(response) or {}
        except httpx.ConnectError as e:
            logger.error(
                f"Connection to Jira failed while getting issue {issue_key}: {e}"
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Could not connect to Jira. Original error: {e}",
            )

    async def create_issue(
        self, summary: str, description: str, issue_type: str = "Task"
    ) -> dict[str, Any]:
        """Creates a new issue in Jira."""
        logger.info(f"Creating Jira issue: {summary}")
        payload = {
            "fields": {
                "project": {"key": "CLAPP"},
                "summary": summary,
                "description": description,
                "issuetype": {"name": issue_type},
            }
        }
        response = await self._request_with_rate_limit("POST", "/issue", json=payload)
        return await self._handle_response(response, success_code=201) or {}

    async def edit_issue(self, issue_key: str, update_data: JiraIssueEdit) -> None:
        """
        Edits an existing Jira issue.
        """
        logger.info(f"Editing Jira issue: {issue_key}")
        # Only include fields that are not None
        fields_to_update = update_data.model_dump(exclude_unset=True)

        if not fields_to_update:
            raise HTTPException(status_code=400, detail="No fields provided to update.")

        payload = {"fields": fields_to_update}
        response = await self._request_with_rate_limit(
            "PUT", f"/issue/{issue_key}", json=payload
        )
        await self._handle_response(response, success_code=204)
        logger.info(f"Successfully edited issue {issue_key}.")

    async def get_transitions(self, issue_key: str) -> list[dict[str, Any]]:
        """
        Retrieves the available transitions for an issue.
        """
        logger.info(f"Fetching transitions for issue: {issue_key}")
        response = await self._request_with_rate_limit(
            "GET", f"/issue/{issue_key}/transitions"
        )
        data = await self._handle_response(response)
        return data.get("transitions", []) if data else []

    async def transition_issue(self, issue_key: str, transition_id: int) -> None:
        """
        Transitions an issue to a new status.
        """
        logger.info(
            f"Transitioning issue {issue_key} with transition ID {transition_id}"
        )
        payload = {"transition": {"id": transition_id}}
        response = await self._request_with_rate_limit(
            "POST", f"/issue/{issue_key}/transitions", json=payload
        )
        await self._handle_response(response, success_code=204)
        logger.info(f"Successfully transitioned issue {issue_key}.")

    async def append_to_description(self, issue_key: str, text_to_append: str) -> None:
        """
        Appends text to an existing Jira issue's description.
        If the text contains the 'affected users' header, it MERGES the emails
        into the existing block (deduped), instead of blindly appending.
        """
        logger.info(
            f"Appending/merging text into description of Jira issue {issue_key}"
        )

        # 1. Get current issue to read the description
        response = await self._request_with_rate_limit(
            "GET", f"/issue/{issue_key}?fields=description"
        )
        issue_data = await self._handle_response(response)

        if not issue_data:
            raise HTTPException(
                status_code=404,
                detail=f"Issue {issue_key} not found.",
            )

        current_description = issue_data.get("fields", {}).get("description") or ""

        # 2. Merge or append depending on content
        new_description_text = _merge_affected_users_block(
            current_description, text_to_append
        )

        # 3. Update only if there is a change
        if new_description_text != current_description:
            await self.edit_issue(
                issue_key, JiraIssueEdit(description=new_description_text)
            )
            logger.info(f"Successfully updated description for issue {issue_key}")
        else:
            logger.info(f"No description change necessary for {issue_key}")

    async def add_comment(self, issue_key: str, comment: str) -> dict[str, Any]:
        """
        Adds a comment to a Jira issue.

        :param issue_key: Key of the issue (e.g., SUPP-123)
        :param comment: Text of the comment to add
        :return: The created comment object
        """
        try:
            logger.info(f"Adding comment to Jira issue {issue_key}")
            response = await self._request_with_rate_limit(
                "POST", f"/issue/{issue_key}/comment", json={"body": comment}
            )
            data = await self._handle_response(response, success_code=201)
            logger.info(f"Successfully added comment to issue {issue_key}")
            return data or {}
        except httpx.ConnectError as e:
            logger.error(
                f"Connection to Jira failed while adding comment to {issue_key}: {e}",
                exc_info=True,
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Could not connect to Jira to add comment. Original error: {e}",
            )
        except Exception:
            logger.error(f"Failed to add comment to {issue_key}", exc_info=True)
            raise


# Create a singleton instance
jira_service = JiraService()
