from datetime import date, datetime, time

from bson import ObjectId

from config import db
from modules.test_templates.model import TestTemplateInDB
from modules.tests.model import TestCreate, TestFinalizeRequest, TestInDB, TestUpdate

tests_collection = db.tests
templates_collection = db.test_templates
test_results_collection = db.test_results


class TestService:
    @staticmethod
    async def create_draft(test_data: TestCreate) -> str:
        """
        Creates a new test document in the database with a 'draft' status.
        Uses the TestCreate model for data validation.
        """
        insert_data = test_data.model_dump()

        for key in [
            "open_date",
            "close_date",
            "questions_from_date",
            "questions_to_date",
        ]:
            if isinstance(insert_data[key], date):
                insert_data[key] = datetime.combine(insert_data[key], time.min)
        insert_data["status"] = "draft"
        insert_data["created_at"] = datetime.now()
        insert_data["last_updated_at"] = datetime.now()
        insert_data["invited_users"] = []
        insert_data["template_details"] = None

        result = await tests_collection.insert_one(insert_data)
        return str(result.inserted_id)

    @staticmethod
    async def get(page: int, page_size: int, created_by: str | None) -> list[TestInDB]:
        """
        Retrieves a paginated list of tests, with an optional filter for the creator.
        Returns a list of TestInDB models.
        """
        query = {}
        if created_by:
            query["created_by"] = created_by

        skip = (page - 1) * page_size
        cursor = tests_collection.find(query).skip(skip).limit(page_size)

        # Convert each document from the database into a TestInDB model
        return [TestInDB(**doc) async for doc in cursor]

    @staticmethod
    async def get_assigned_tests_for_user(user_id: str) -> list[dict]:
        """
        Retrieves all finalized tests a user is invited to, and enriches them
        with the user's completion status and score from the test_results collection.
        This version uses a safer, multi-query approach to avoid aggregation errors.
        """
        if not user_id:
            return []

        # 1. Fetch all tests the user is assigned to.
        assigned_tests_cursor = tests_collection.find(
            {"invited_users": user_id, "status": "finalized"}
        )
        assigned_tests = await assigned_tests_cursor.to_list(length=None)

        if not assigned_tests:
            return []

        # 2. Fetch all of the user's results in a single query.
        results_cursor = test_results_collection.find({"user_id": user_id})
        results_list = await results_cursor.to_list(length=None)

        # 3. Create a simple map for easy lookup: {test_id: result_document}
        results_map = {result["test_id"]: result for result in results_list}

        # 4. Combine the data in Python.
        enriched_tests = []
        for test in assigned_tests:
            test_id_str = str(test["_id"])
            user_result = results_map.get(test_id_str)

            enriched_test = {
                "_id": test_id_str,
                "test_name": test.get("test_name"),
                "open_date": test.get("open_date"),
                "close_date": test.get("close_date"),
                "template_details": test.get("template_details"),
                "created_by": test.get("created_by"),
            }

            if user_result:
                enriched_test["completion_status"] = "Completed"
                enriched_test["score"] = user_result.get("score_percent")
                enriched_test["result_id"] = str(user_result.get("_id"))
            else:
                enriched_test["completion_status"] = "Open"
                enriched_test["score"] = None
                enriched_test["result_id"] = None

            enriched_tests.append(enriched_test)

        return enriched_tests

    @staticmethod
    async def get_by_id(test_id: str) -> TestInDB | None:
        """
        Retrieves a single test by its ID.
        Returns a TestInDB model or None if not found.
        """
        test_doc = await tests_collection.find_one({"_id": ObjectId(test_id)})
        return TestInDB(**test_doc) if test_doc else None

    @staticmethod
    async def update(test_id: str, test_data: TestUpdate) -> bool:
        """
        Updates the basic information of a test using the TestUpdate model.
        Only the fields provided in the request will be updated.
        """
        # model_dump(exclude_unset=True) ensures we only update fields that were actually sent
        update_data = test_data.model_dump(exclude_unset=True, by_alias=True)

        if not update_data:
            return True

        for key in [
            "open_date",
            "close_date",
            "questions_from_date",
            "questions_to_date",
        ]:
            if key in update_data and isinstance(update_data[key], date):
                update_data[key] = datetime.combine(update_data[key], time.min)

        update_data["last_updated_at"] = datetime.now()

        result = await tests_collection.update_one(
            {"_id": ObjectId(test_id)}, {"$set": update_data}
        )
        return result.modified_count > 0

    @staticmethod
    async def save_invitations(test_id: str, invited_users: list[str]) -> bool:
        """
        Saves the list of invited user IDs to a test.
        """
        result = await tests_collection.update_one(
            {"_id": ObjectId(test_id)},
            {
                "$set": {
                    "invited_users": invited_users,
                    "last_updated_at": datetime.now(),
                }
            },
        )
        return result.modified_count > 0

    @staticmethod
    async def finalize(test_id: str, finalize_data: TestFinalizeRequest) -> bool:
        """
        Applies a template to the test, updates its status to 'finalized',
        and correctly saves the template details without overwriting other fields.
        """
        template_doc = await templates_collection.find_one(
            {"_id": ObjectId(finalize_data.template_id)}
        )

        if not template_doc:
            return False

        update_payload = {
            "status": "finalized",
            "template_details": TestTemplateInDB(**template_doc).model_dump(
                by_alias=True
            ),
            "last_updated_at": datetime.now(),
        }

        result = await tests_collection.update_one(
            {"_id": ObjectId(test_id)}, {"$set": update_payload}
        )

        return result.modified_count > 0

    @staticmethod
    async def delete(test_id: str) -> bool:
        """
        Deletes a test from the database.
        """
        result = await tests_collection.delete_one({"_id": ObjectId(test_id)})
        return result.deleted_count > 0

    @staticmethod
    async def count_open_tests_for_user(user_id: str) -> int:
        """
        Counts the number of "Open" tests a specific user is invited to.
        An "Open" test is finalized, and the current date is between its open and close dates.
        """
        now = datetime.now()
        query = {
            "invited_users": user_id,
            "status": "finalized",
            "open_date": {"$lte": now},
            "close_date": {"$gte": now},
        }
        # This also needs to be updated to exclude completed tests
        results_cursor = test_results_collection.find(
            {"user_id": user_id}, {"test_id": 1}
        )
        completed_test_ids_str = [res["test_id"] async for res in results_cursor]
        completed_test_ids = [ObjectId(id_str) for id_str in completed_test_ids_str]

        if completed_test_ids:
            query["_id"] = {"$nin": completed_test_ids}

        count = await tests_collection.count_documents(query)
        return count
