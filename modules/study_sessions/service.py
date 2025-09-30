from datetime import datetime

from bson import ObjectId

from config import db, logger

questions_collection = db.questions
study_session_results_collection = db.study_session_results


class StudySessionService:
    @staticmethod
    async def start_session() -> list:
        """Randomly select 20 questions, return limited fields"""
        try:
            # First, find 30 random questions (buffer for filtering)
            pipeline = [
                {"$match": {"question_type": {"$ne": "Open-ended"}}},
                {"$sample": {"size": 30}},
                {
                    "$project": {
                        "stem": 1,
                        "answers": 1,
                        "gkb_link": 1,
                        "question_type": 1,
                    }
                },
            ]
            cursor = await questions_collection.aggregate(pipeline)
            questions = await cursor.to_list(length=30)

            # Normalize True/False questions server-side
            normalized_questions = []
            for q in questions:
                logger.info(
                    f"Checking question {q['_id']} with type {q.get('question_type')}"
                )
                normalized_q = {
                    "question_id": str(q["_id"]),
                    "stem": q.get("stem"),
                    "answers": q.get("answers"),
                    "gkb_link": q.get("gkb_link"),
                    "question_type": q.get("question_type"),
                }
                if q.get("question_type") == "True/False":
                    normalized_q["answers"] = {"A": "True", "B": "False"}

                logger.info(
                    f"Sending question {normalized_q['question_id']} with type {normalized_q.get('question_type')}"
                )
                normalized_questions.append(normalized_q)

            # Limit strictly to 20
            return normalized_questions[:20]
        except Exception:
            logger.exception("Failed to start study session")
            raise

    @staticmethod
    async def submit_session(user_id: str, answers: list) -> dict:
        """Evaluate answers, calculate score, and store result"""
        try:
            score = 0
            result_answers = []

            for ans in answers:
                question = await questions_collection.find_one(
                    {"_id": ObjectId(ans.question_id)}
                )
                if not question:
                    continue

                correct_answer = question.get("correct_answer")
                # Handle multiple answers (list vs list) or single answer (str vs str)
                if isinstance(ans.selected_option, list):
                    # User selected multiple options
                    if isinstance(correct_answer, list):
                        is_correct = set(ans.selected_option) == set(correct_answer)
                    else:
                        # Mismatch in DB structure: treat as incorrect
                        is_correct = False
                else:
                    # User selected a single option
                    if isinstance(correct_answer, list):
                        # Correct answer expects multiple, but user gave one
                        is_correct = False
                    else:
                        is_correct = ans.selected_option == correct_answer

                result_answers.append(
                    {
                        "question_id": ans.question_id,
                        "selected_option": ans.selected_option,
                        "correct": is_correct,
                        "time_spent_seconds": ans.time_spent_seconds,
                    }
                )

                if is_correct:
                    score += 1

            result_doc = {
                "user_id": user_id,
                "answers": result_answers,
                "score": score,
                "date_completed": datetime.now(),
            }

            await study_session_results_collection.insert_one(result_doc)

            return {
                "score": score,
                "total_questions": len(answers),
                "date_completed": result_doc["date_completed"],
            }
        except Exception:
            logger.exception("Failed to submit study session")
            raise
