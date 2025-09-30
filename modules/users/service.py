from datetime import datetime, timezone

from bson import ObjectId
from fastapi import HTTPException

from .model import UserListItem, UserOrganizationalUnit, UserProfile
from config import db, logger
from modules.hibob.model import HibobEmployee
from utils.serialization import serialize_document


users_collection = db.users


class UserService:
    @staticmethod
    async def get_user_by_email(email: str) -> UserProfile | None:
        """
        Finds a user by their email address.
        This is the primary method to link an Okta identity to an app user.
        """
        logger.info(f"[USER_SVC] Looking up user by email: {email}")
        user_data = await users_collection.find_one({"email": email})
        if user_data:
            serialized_data = serialize_document(user_data)
            return UserProfile(**serialized_data)
        return None

    @staticmethod
    async def get_all_users() -> list[UserProfile]:
        """Brings all users from the database (for admins)."""
        cursor = users_collection.find().sort("name", 1)
        users = []
        async for doc in cursor:
            serialized_doc = serialize_document(doc)
            users.append(UserProfile(**serialized_doc))
        return users

    @staticmethod
    async def get_user_list() -> list[UserListItem]:
        """
        Brings a simplified list of users (id, name, role) for test creation.
        Uses a projection for efficiency.
        """
        cursor = users_collection.find({}, {"name": 1, "user_role": 1}).sort("name", 1)
        users = []
        async for doc in cursor:
            serialized_doc = serialize_document(doc)
            users.append(UserListItem(**serialized_doc))
        return users

    @staticmethod
    async def update_user_role(user_id: str, new_role: str, is_admin: bool):
        """Updates a user's role and/or admin status."""
        result = await users_collection.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {"user_role": new_role, "is_admin": is_admin}},
        )
        return result.modified_count > 0

    @staticmethod
    async def get_user_by_id(user_id: str) -> UserProfile | None:
        """Returns a user document by their MongoDB _id."""
        if not ObjectId.is_valid(user_id):
            logger.warning(f"[USER_SVC] Invalid ObjectId format for user_id: {user_id}")
            return None

        user_data = await users_collection.find_one({"_id": ObjectId(user_id)})
        if user_data:
            serialized_data = serialize_document(user_data)
            return UserProfile(**serialized_data)
        return None

    @staticmethod
    async def update_or_create_user(
        user_email: str,
        hibob_employee: HibobEmployee | None,
    ) -> UserProfile:
        """
        Finds or creates a user, syncing HiBob data and updating timestamps.
        - `registered_at` is set once upon creation.
        - `last_login_at` is updated on every login.
        """
        # Guard clause: HiBob data is mandatory for this operation.
        if not hibob_employee:
            logger.error(f"[USER_SVC] HiBob data is missing for {user_email}.")
            existing_user = await users_collection.find_one({"email": user_email})
            if existing_user:
                logger.warning(
                    f"Returning existing user {user_email} without an update."
                )
                return UserProfile(**serialize_document(existing_user))
            else:
                raise HTTPException(
                    status_code=424,
                    detail="Cannot provision new user: required employee data from HiBob was not found.",
                )

        logger.info(f"[USER_SVC] Upserting user {user_email} with HiBob data.")

        # Prepare a payload of all fields to be synced from HiBob.
        hibob_payload = {
            "name": hibob_employee.display_name,
            "job_title": hibob_employee.job_title,
            "picture": hibob_employee.photo,
            "hris_employee_id": hibob_employee.hris_employee_id,
            "employee_number": hibob_employee.employee_number,
            "team": (
                UserOrganizationalUnit(**hibob_employee.team.model_dump()).model_dump()
                if hibob_employee.team
                else None
            ),
            "department": (
                UserOrganizationalUnit(
                    **hibob_employee.department.model_dump()
                ).model_dump()
                if hibob_employee.department
                else None
            ),
            "division": UserOrganizationalUnit(
                **hibob_employee.division.model_dump()
            ).model_dump(),
            "user_role": hibob_employee.department.name,
        }

        # Find user by email to decide whether to update or create
        existing_user_doc = await users_collection.find_one({"email": user_email})

        if existing_user_doc:
            # --- UPDATE PATH ---
            logger.info(f"User '{user_email}' found. Updating profile and timestamps.")

            update_payload = hibob_payload.copy()
            # Always update the last login time
            update_payload["last_login_at"] = datetime.now(timezone.utc)

            # If user exists but lacks a registration date (legacy data), set it now.
            if not existing_user_doc.get("registered_at"):
                update_payload["registered_at"] = datetime.now(timezone.utc)

            await users_collection.update_one(
                {"_id": existing_user_doc["_id"]}, {"$set": update_payload}
            )
            updated_doc = await users_collection.find_one(
                {"_id": existing_user_doc["_id"]}
            )
            return UserProfile.model_validate(serialize_document(updated_doc))
        else:
            # --- CREATE PATH ---
            logger.info(f"User '{user_email}' not found. Creating new user.")

            now_timestamp = datetime.now(timezone.utc)
            new_user_data = {
                "email": user_email,
                **hibob_payload,
                "is_admin": False,
                # Set both timestamps on creation
                "registered_at": now_timestamp,
                "last_login_at": now_timestamp,
            }

            result = await users_collection.insert_one(new_user_data)
            created_doc = await users_collection.find_one({"_id": result.inserted_id})
            if not created_doc:
                raise HTTPException(
                    status_code=500,
                    detail="Failed to retrieve new user after creation.",
                )

            return UserProfile.model_validate(serialize_document(created_doc))

    @staticmethod
    async def get_distinct_user_roles() -> list[str]:
        """
        Fetches a list of unique, non-null user roles from the users collection,
        sorted alphabetically.
        """
        logger.info("[USER_SVC] Fetching distinct user roles.")
        # This query ensures we only get roles that are not null or empty
        query = {"user_role": {"$ne": None, "$exists": True}}

        # Use the .distinct() method for efficiency
        roles = await users_collection.distinct("user_role", query)

        # Sort the list for consistent ordering in the UI
        roles.sort()

        return roles
