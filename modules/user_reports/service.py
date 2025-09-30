import asyncio
from datetime import datetime

from bson import ObjectId
from pymongo import ReturnDocument

from .model import UserReport, UserReportAdminUpdate, UserReportAnswer, UserReportCreate
from config import db, logger, settings
from modules.jira.service import jira_service
from modules.users.service import UserService

# It is highly recommended to create indexes on fields that will be frequently
# used in queries to ensure good performance.
#
# Recommended to create these indexes via the MongoDB shell:
# db.user_reports.createIndex({ "user_id": 1 })
# db.user_reports.createIndex({ "report_type": 1 })
# db.user_reports.createIndex({ "jira_key": 1 })

user_reports_collection = db.user_reports


class UserReportService:
    """
    Service layer for all business logic related to user reports.
    """

    @staticmethod
    async def create_report(user_id: str, report_data: UserReportCreate) -> UserReport:
        """Creates a new user report in the database."""
        report_doc = {
            "user_id": user_id,
            "description": report_data.description,
            "report_type": None,
            "jira_key": None,
            "comment": None,
            "created_at": datetime.now(),
            "updated_at": datetime.now(),
        }
        result = await user_reports_collection.insert_one(report_doc)
        created_report = await user_reports_collection.find_one(
            {"_id": result.inserted_id}
        )
        if created_report:
            created_report["_id"] = str(created_report["_id"])
        return UserReport.model_validate(created_report)

    @staticmethod
    async def get_reports(
        page: int,
        limit: int,
        user_id: str | None = None,
        report_type: str | None = None,
        jira_key: str | None = None,
    ) -> dict:
        """
        lists user reports, and enriches them with the status and summary
        of any linked Jira issues.
        """
        query = {}
        if user_id:
            query["user_id"] = user_id
        if report_type:
            query["report_type"] = report_type
        if jira_key:
            query["jira_key"] = jira_key

        skip = (page - 1) * limit
        total_count_task = user_reports_collection.count_documents(query)
        reports_cursor = (
            user_reports_collection.find(query)
            .sort("created_at", -1)
            .skip(skip)
            .limit(limit)
        )

        total_count, reports_docs = await asyncio.gather(
            total_count_task, reports_cursor.to_list(length=limit)
        )

        # --- JIRA ENRICHMENT LOGIC ---
        # 1. Collect all unique Jira keys from the reports
        jira_keys = {doc["jira_key"] for doc in reports_docs if doc.get("jira_key")}

        jira_issues_map = {}
        if jira_keys:
            # 2. Make a single bulk call to Jira
            keys_str = ", ".join(f'"{key}"' for key in jira_keys)
            jql = f"key in ({keys_str})"
            try:
                jira_issues = await jira_service.search_all_issues(jql)
                # 3. Create a map of jira_key -> {status, summary, url}
                for issue in jira_issues:
                    jira_issues_map[issue["key"]] = {
                        "status": issue["fields"]["status"]["name"],
                        "summary": issue["fields"]["summary"],
                        "url": f"{settings.JIRA_BASE_URL}/browse/{issue['key']}",
                    }
            except Exception as e:
                logger.error(f"Failed to fetch Jira issue details: {e}")

        # 4. Enrich reports with Jira data
        reports = []
        for doc in reports_docs:
            doc["_id"] = str(doc["_id"])
            if doc.get("jira_key") in jira_issues_map:
                jira_info = jira_issues_map[doc["jira_key"]]
                doc["jira_status"] = jira_info["status"]
                doc["jira_summary"] = jira_info["summary"]
                doc["jira_url"] = jira_info["url"]
            reports.append(UserReport.model_validate(doc))

        return {"reports": reports, "total_count": total_count}

    @staticmethod
    async def admin_update_report(
        report_id: str, update_data: UserReportAdminUpdate
    ) -> UserReport | None:
        """Allows an admin to update a report's type or add a comment."""
        update_fields = dict()
        update_fields["updated_at"] = datetime.now()

        if update_data.report_type:
            update_fields["report_type"] = update_data.report_type
            update_fields["status"] = "Acknowledged"

        if update_data.comment:
            update_fields["comment"] = update_data.comment

        if not update_fields:
            return await user_reports_collection.find_one({"_id": ObjectId(report_id)})

        updated_report = await user_reports_collection.find_one_and_update(
            {"_id": ObjectId(report_id)},
            {"$set": update_fields},
            return_document=ReturnDocument.AFTER,
        )
        if updated_report:
            updated_report["_id"] = str(updated_report["_id"])
            return UserReport.model_validate(updated_report)
        return None

    @staticmethod
    async def answer_question(
        report_id: str, answer_data: UserReportAnswer
    ) -> UserReport | None:
        """Sets a report's status to 'Resolved' and adds the answer as a comment."""
        update_doc = {
            "$set": {
                "report_type": "question",
                "comment": answer_data.answer,
                "status": "Resolved",
                "updated_at": datetime.utcnow(),
            }
        }
        updated_report = await user_reports_collection.find_one_and_update(
            {"_id": ObjectId(report_id)},
            update_doc,
            return_document=ReturnDocument.AFTER,
        )
        if updated_report:
            updated_report["_id"] = str(updated_report["_id"])
            return UserReport.model_validate(updated_report)
        return None

    @staticmethod
    async def link_to_jira(report_ids: list[str], jira_key: str) -> dict:
        """
        Links reports to an existing Jira issue, appends user emails to the
        description, and automatically updates the report_type based on the
        Jira issue type.
        """
        object_ids = [ObjectId(rid) for rid in report_ids]

        # Get user emails to add to the Jira ticket
        reports_cursor = user_reports_collection.find({"_id": {"$in": object_ids}})
        user_ids = {doc["user_id"] async for doc in reports_cursor}

        user_emails = []
        for uid in user_ids:
            user = await UserService.get_user_by_id(uid)
            if user and hasattr(user, "email") and user.email:
                user_emails.append(user.email)

        # Update the Jira issue description
        if user_emails:
            text_to_append = "This issue affects the following users:\n" + "\n".join(
                f"- {email}" for email in user_emails
            )
            await jira_service.append_to_description(jira_key, text_to_append)

        # 1. Fetch the Jira issue details
        new_report_type = None
        try:
            jira_issue = await jira_service.get_issue(jira_key)
            jira_issue_type_name = (
                jira_issue.get("fields", {}).get("issuetype", {}).get("name")
            )

            # 2. Map Jira issue type to our application's report_type
            type_map = {"Bug": "bug", "Story": "feature"}
            new_report_type = type_map.get(jira_issue_type_name)

            if new_report_type:
                logger.info(
                    f"Jira issue {jira_key} is a '{jira_issue_type_name}'. Mapping to report_type '{new_report_type}'."
                )
        except Exception as e:
            logger.error(
                f"Could not fetch Jira issue {jira_key} to determine type: {e}"
            )

        # 3. Prepare the database update
        update_fields = {
            "jira_key": jira_key,
            "status": "In Progress",
            "updated_at": datetime.now(),
        }
        if new_report_type:
            update_fields["report_type"] = new_report_type

        # Update the reports in our database
        update_result = await user_reports_collection.update_many(
            {"_id": {"$in": object_ids}},
            {"$set": update_fields},
        )
        return {"modified_count": update_result.modified_count}

    @staticmethod
    async def create_new_jira_issue(report_ids: list[str]) -> str:
        """Creates a new Jira issue from a list of reports, including reporter emails in the description."""
        if not report_ids:
            raise ValueError("At least one report ID is required.")

        first_report_doc = await user_reports_collection.find_one(
            {"_id": ObjectId(report_ids[0])}
        )
        if not first_report_doc:
            raise ValueError(f"Report with ID {report_ids[0]} not found.")

        # Determine Jira issue type and summary
        report_type = first_report_doc.get("report_type", "bug")
        issue_type_map = {"feature": "Story", "question": "Task"}
        jira_issue_type = issue_type_map.get(report_type, "Bug")
        summary = f"User Report: {first_report_doc['description'][:80]}"

        # Construct initial description with user emails
        object_ids = [ObjectId(rid) for rid in report_ids]
        reports_cursor = user_reports_collection.find({"_id": {"$in": object_ids}})
        user_ids = {doc["user_id"] async for doc in reports_cursor}
        user_emails = [
            user.email
            for uid in user_ids
            if (user := await UserService.get_user_by_id(uid))
            and hasattr(user, "email")
        ]

        description = f"Issue created from user report(s): {', '.join(report_ids)}."
        if user_emails:
            description += "\n\nReported by:\n" + "\n".join(
                f"- {email}" for email in user_emails
            )

        # Call the Jira client to create the issue
        new_issue = await jira_service.create_issue(
            summary=summary, description=description, issue_type=jira_issue_type
        )
        new_jira_key = new_issue["key"]

        # Link the reports to the newly created Jira key
        await UserReportService.link_to_jira(report_ids, new_jira_key)
        logger.info(
            f"Successfully created Jira issue {new_jira_key} via JiraService and linked {len(report_ids)} reports."
        )
        return new_jira_key

    @staticmethod
    async def create_jira_issue_from_reports(
        report_ids: list[str], issue_type: str, summary: str, description: str
    ) -> str:
        """
        Creates a new Jira issue with custom details and links the specified reports.
        """
        if not report_ids:
            raise ValueError("At least one report ID is required.")

        # 1. Create the new issue in Jira with the provided details
        new_issue = await jira_service.create_issue(
            summary=summary, description=description, issue_type=issue_type
        )
        new_jira_key = new_issue["key"]
        logger.info(
            f"Created new Jira issue {new_jira_key} from user reports dashboard."
        )

        # 2. Link the reports to this newly created issue
        await UserReportService.link_to_jira(report_ids, new_jira_key)
        logger.info(f"Linked {len(report_ids)} reports to new issue {new_jira_key}.")

        return new_jira_key
