from datetime import datetime

from bson import ObjectId

from .model import TestResultCreate
from config import db, logger
from modules.questions.service import QuestionService
from modules.tests.model import TestInDB as TestModel
from utils.serialization import serialize_document

# Database collections
tests_collection = db.tests
test_results_collection = db.test_results
questions_collection = db.questions
users_collection = db.users


class TestSessionService:
    @staticmethod
    async def get_test_for_session(test_id: str, user_id: str) -> dict:
        """
        Fetches the test data required to start a session.
        - Verifies the user is invited.
        - Verifies the test is currently open.
        - Verifies the user has not already completed this test.
        - Assembles questions based on the test's template.
        - Returns the questions and test duration.
        """
        now = datetime.now().date()

        test_doc = await tests_collection.find_one({"_id": ObjectId(test_id)})
        if not test_doc:
            raise ValueError("Test not found.")

        test = TestModel(**test_doc)

        # Validations
        if user_id not in test.invited_users:
            raise PermissionError("You are not invited to take this test.")

        if not (test.open_date <= now <= test.close_date):
            raise ValueError("This test is not currently open.")

        existing_result = await test_results_collection.find_one(
            {"user_id": user_id, "test_id": test_id}
        )
        if existing_result:
            raise ValueError("You have already completed this test.")

        assembled_questions = await QuestionService.assemble_questions_for_test(test_id)

        if not assembled_questions:
            raise ValueError(
                "Failed to assemble questions for this test. The question pool might be empty."
            )

        return {
            "title": test.test_name,
            "duration_seconds": (
                (test.template_details.get("test_duration", 0) * 60)
                if test.template_details
                else 0
            ),
            "questions": assembled_questions,
        }

    @staticmethod
    def build_final_question_ids(
        session_question_ids: list[str],
        answers: list[dict],
        reported_questions: list[str] | None,
    ) -> list[str]:
        """
        Canonicalize the set of questions that should count for this attempt:
        - Remove any original questions that were reported.
        - Include any answered replacements (not in the original session list).
        - Deduplicate.
        """
        reported_set = set(reported_questions or [])
        base = [qid for qid in (session_question_ids or []) if qid not in reported_set]

        answered_ids = []
        for a in answers or []:
            qid = a.get("question_id")
            if qid and qid not in answered_ids:
                answered_ids.append(qid)

        # Include replacements answered by the user (they won't be in the original session list)
        for qid in answered_ids:
            if qid not in base:
                base.append(qid)

        return base

    @staticmethod
    async def submit_test_results(session_data: TestResultCreate) -> str:
        """
        Processes submitted answers, calculates detailed scores and analytics,
        and saves the comprehensive result to the database.
        - Excludes reported originals from scoring/aggregation.
        - Deduplicates answers by question_id.
        """
        # Normalize answers: drop reported originals & deduplicate ---
        reported_set = set(getattr(session_data, "reported_questions", []) or [])
        filtered_answers = []
        seen = set()
        for ans in session_data.answers or []:
            qid = ans.question_id
            if not qid:
                continue
            if qid in reported_set:
                # Do not score reported originals
                continue
            if qid in seen:
                # Deduplicate in case the same question_id appears twice
                continue
            seen.add(qid)
            filtered_answers.append(ans)

        question_ids_str = [ans.question_id for ans in filtered_answers]
        if not question_ids_str:
            # Legit submission with zero scorable questions (e.g., all reported): persist a zeroed result
            final_result_data = {
                "user_id": session_data.user_id,
                "test_id": session_data.test_id,
                "started_at": session_data.started_at,
                "submitted_at": datetime.now(),
                "time_spent_seconds": session_data.time_spent_seconds,
                "score_percent": 0.0,
                "points_earned": 0,
                "points_total": 0,
                "topic_performance": {},
                "impact_level_performance": {},
                "detailed_answers": [],
                "flagged_questions": session_data.flagged_questions,
                "reported_questions": list(reported_set),
                "final_question_ids": [],
            }
            result = await test_results_collection.insert_one(final_result_data)
            logger.info(
                f"Saved zeroed test result for user {session_data.user_id} for test {session_data.test_id}"
            )
            return str(result.inserted_id)

        # --- 1) Fetch question docs once ---
        # Convert to ObjectIds where possible (ignore if non-hex string ids ever appear)
        question_ids_obj = []
        for id_str in question_ids_str:
            try:
                question_ids_obj.append(ObjectId(id_str))
            except Exception:
                # If your IDs are not ObjectId, adapt: fetch by alternate key instead.
                pass

        questions_list = []
        if question_ids_obj:
            questions_cursor = questions_collection.find(
                {"_id": {"$in": question_ids_obj}}
            )
            questions_list = await questions_cursor.to_list(
                length=len(question_ids_obj)
            )
        # Map by stringified _id for quick access
        questions_map = {str(q["_id"]): q for q in questions_list}

        # --- 2) Scoring & analytics over the normalized set only ---
        total_points_earned = 0
        total_points_possible = 0
        topic_performance: dict = {}
        impact_level_performance: dict = {}
        detailed_answers: list = []

        # Helper to pick the "highest" impact level when summarizing by topic
        impact_order = {"Critical": 4, "High": 3, "Medium": 2, "Low": 1}

        for submitted_answer in filtered_answers:
            question_id = submitted_answer.question_id
            question_doc = questions_map.get(question_id)
            if not question_doc:
                # If doc not found (e.g., string IDs not ObjectId), try a direct lookup by custom id if applicable
                # Fallback: skip to avoid crashing scoring
                logger.warning(f"Missing question doc for {question_id}; skipping.")
                continue

            q_topic = question_doc.get("topic", "Uncategorized")
            q_impact = question_doc.get("impact_level", "Low")
            q_points = int(question_doc.get("points", 1))

            correct_answer = question_doc.get("correct_answer", [])
            correct_answer_list = (
                correct_answer if isinstance(correct_answer, list) else [correct_answer]
            )
            user_answer_list = (
                submitted_answer.selected_options
                if isinstance(submitted_answer.selected_options, list)
                else [submitted_answer.selected_options]
            )

            points_earned = 0
            status = "incorrect"

            correct_set = set(correct_answer_list)
            user_set = set(user_answer_list)
            total_correct = len(correct_set)

            # Exact match full credit
            if user_set == correct_set:
                status = "correct"
                points_earned = q_points
            # Partial credit (configurable)
            elif total_correct > 0 and len(user_set & correct_set) > 0:
                status = "partial"
                ratio = len(user_set & correct_set) / total_correct
                points_earned = round(min(q_points, ratio * q_points), 2)

            total_points_earned += points_earned
            total_points_possible += q_points

            if q_topic not in topic_performance:
                topic_performance[q_topic] = {
                    "pointsEarned": 0,
                    "pointsTotal": 0,
                    "questionsCount": 0,
                    "impactLevel": q_impact,  # for UI chip
                }
            tp = topic_performance[q_topic]
            tp["pointsEarned"] += points_earned
            tp["pointsTotal"] += q_points
            tp["questionsCount"] += 1
            # Pick the highest impact level encountered for this topic
            if impact_order.get(q_impact, 0) > impact_order.get(
                tp.get("impactLevel", "Low"), 0
            ):
                tp["impactLevel"] = q_impact

            # Impact-level aggregation
            if q_impact not in impact_level_performance:
                impact_level_performance[q_impact] = {
                    "pointsEarned": 0,
                    "pointsTotal": 0,
                    "questionsCount": 0,
                }
            il = impact_level_performance[q_impact]
            il["pointsEarned"] += points_earned
            il["pointsTotal"] += q_points
            il["questionsCount"] += 1

            detailed_answers.append(
                {
                    "id": question_id,
                    "stem": question_doc.get("stem"),
                    "topic": q_topic,
                    "impactLevel": q_impact,
                    "userAnswer": user_answer_list,
                    "correctAnswer": correct_answer_list,
                    "status": status,
                    "pointsEarned": points_earned,
                    "pointsTotal": q_points,
                    "explanation": question_doc.get("explanation"),
                    "confluenceLink": question_doc.get("confluence_link"),
                }
            )

        score_percent = (
            (total_points_earned / total_points_possible * 100)
            if total_points_possible > 0
            else 0
        )

        final_result_data = {
            "user_id": session_data.user_id,
            "test_id": session_data.test_id,
            "started_at": session_data.started_at,
            "submitted_at": datetime.now(),
            "time_spent_seconds": session_data.time_spent_seconds,
            "score_percent": round(score_percent, 2),
            "points_earned": total_points_earned,
            "points_total": total_points_possible,
            "topic_performance": topic_performance,
            "impact_level_performance": impact_level_performance,
            "detailed_answers": detailed_answers,
            "flagged_questions": session_data.flagged_questions,
            "reported_questions": list(reported_set),
            "final_question_ids": [
                da["id"] for da in detailed_answers
            ],  # canonical set used by details endpoint
        }

        result = await test_results_collection.insert_one(final_result_data)
        logger.info(
            f"Detailed test result saved for user {session_data.user_id} for test {session_data.test_id}"
        )
        return str(result.inserted_id)

    @staticmethod
    async def get_detailed_result(result_id: str, user_id: str) -> dict:
        result_doc = await test_results_collection.find_one(
            {"_id": ObjectId(result_id), "user_id": user_id}
        )
        if not result_doc:
            raise ValueError(
                "Test result not found or you do not have permission to view it."
            )

        test_doc = await tests_collection.find_one(
            {"_id": ObjectId(result_doc["test_id"])}
        )
        if not test_doc:
            raise ValueError("Original test not found.")

        test = TestModel(**test_doc)

        assigner_doc = await users_collection.find_one(
            {"_id": ObjectId(test.created_by)}
        )
        assigner_name = assigner_doc.get("name", "N/A") if assigner_doc else "N/A"

        passing_score = (
            test.template_details.get("passing_score", 70)
            if test.template_details
            else 70
        )

        topic_perf_list = [
            {
                "topic": k,
                **v,
                "percentage": (
                    round(v["pointsEarned"] / v["pointsTotal"] * 100)
                    if v["pointsTotal"] > 0
                    else 0
                ),
            }
            for k, v in result_doc.get("topic_performance", {}).items()
        ]
        impact_perf_list = [
            {
                "level": k,
                **v,
                "percentage": (
                    round(v["pointsEarned"] / v["pointsTotal"] * 100)
                    if v["pointsTotal"] > 0
                    else 0
                ),
            }
            for k, v in result_doc.get("impact_level_performance", {}).items()
        ]

        # Single source of truth for total questions
        total_questions = len(result_doc.get("final_question_ids", [])) or len(
            result_doc.get("detailed_answers", [])
        )

        response_payload = {
            "testInfo": {
                "id": result_doc["test_id"],
                "title": test.test_name,
                "type": test_doc.get("test_type", "General"),
                "completedDate": result_doc["submitted_at"],
                "timeTaken": f"{round(result_doc['time_spent_seconds'] / 60)} min",
                "timeAllocated": (
                    f"{test.template_details.get('test_duration', 0)} min"
                    if test.template_details
                    else "N/A"
                ),
                "totalQuestions": total_questions,
                "assignedBy": assigner_name,
            },
            "performance": {
                "totalScore": result_doc.get("score_percent", 0),
                "pointsEarned": result_doc.get("points_earned", 0),
                "pointsTotal": result_doc.get("points_total", 0),
                "passingScore": passing_score,
                "passed": result_doc.get("score_percent", 0) >= passing_score,
                "percentileRank": 78,  # Placeholder
                "teamAverage": 72.4,  # Placeholder
                "roleAverage": 76.8,  # Placeholder
                "previousAttempts": [],  # Placeholder
            },
            "topicPerformance": topic_perf_list,
            "impactLevelPerformance": impact_perf_list,
            "questions": result_doc.get("detailed_answers", []),
        }

        return serialize_document(response_payload)

    @staticmethod
    async def get_test_results_summary(test_id: str) -> dict:
        """
        Fetches and aggregates all results for a given test, combining
        test data, user data, and result data.
        """
        # 1. Fetch the main test document
        test_doc = await tests_collection.find_one({"_id": ObjectId(test_id)})
        if not test_doc:
            raise ValueError("Test not found.")

        test = TestModel(**test_doc)

        # 2. Fetch all results for this test
        results_cursor = test_results_collection.find({"test_id": test_id})
        results_list = await results_cursor.to_list(length=None)
        results_map = {res["user_id"]: res for res in results_list}

        # 3. Fetch details for all invited users
        invited_user_ids_str = test.invited_users
        if not invited_user_ids_str:
            return {"test_details": {}, "participants": []}

        invited_user_ids = [ObjectId(uid) for uid in invited_user_ids_str]
        users_cursor = users_collection.find({"_id": {"$in": invited_user_ids}})
        users_list = await users_cursor.to_list(length=len(invited_user_ids))
        users_map = {str(u["_id"]): u for u in users_list}

        # 4. Aggregate the data for each participant
        participants_data = []
        for user_id_str in test.invited_users:
            user_details = users_map.get(user_id_str)
            user_result = results_map.get(user_id_str)

            if not user_details:
                continue

            if user_result:
                participants_data.append(
                    {
                        "id": user_id_str,
                        "name": user_details.get("name", "N/A"),
                        "role": user_details.get("user_role", "N/A"),
                        "score": user_result.get("score_percent", 0),
                        "status": "Completed",
                        "completedAt": user_result.get("submitted_at"),
                        "timeSpent": round(
                            user_result.get("time_spent_seconds", 0) / 60
                        ),
                    }
                )
            else:
                participants_data.append(
                    {
                        "id": user_id_str,
                        "name": user_details.get("name", "N/A"),
                        "role": user_details.get("user_role", "N/A"),
                        "score": 0,
                        "status": "Not Started",
                        "completedAt": None,
                        "timeSpent": 0,
                    }
                )

        # 5. Assemble the final response payload
        return {
            "test_details": {
                "id": test_id,
                "title": test.test_name,
                "type": test_doc.get("test_type", "General"),
                "status": (
                    "Closed" if datetime.now().date() > test.close_date else "Open"
                ),
                "openDate": test.open_date,
                "closeDate": test.close_date,
                "duration": (
                    test.template_details.get("test_duration", 0)
                    if test.template_details
                    else 0
                ),
                "totalQuestions": (
                    test.template_details.get("total_questions", 0)
                    if test.template_details
                    else 0
                ),
                "passingScore": (
                    test.template_details.get("passing_score", 80)
                    if test.template_details
                    else 80
                ),
                "createdBy": test.created_by,
            },
            "participants": serialize_document(participants_data),
        }
