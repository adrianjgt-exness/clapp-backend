from collections import Counter, defaultdict
from datetime import datetime
import json
import random
from typing import Any

from bson import ObjectId

from .model import Question
from config import db, logger
from utils.serialization import serialize_document

questions_collection = db.questions
tests_collection = db.tests
statistics_collection = db.question_statistics
question_reports_collection = db.question_reports


class QuestionService:
    @staticmethod
    async def add_questions(questions: list[Question]):
        """Insert new questions into MongoDB"""
        try:
            questions_data = []
            for question in questions:
                question_data = question.model_dump()
                if question_data.get("confluence_link") is not None:
                    question_data["confluence_link"] = str(
                        question_data["confluence_link"]
                    )
                questions_data.append(question_data)

            if not questions_data:
                return []

            result = await questions_collection.insert_many(questions_data)
            return [str(_id) for _id in result.inserted_ids]
        except Exception as e:
            logger.exception(
                "Error adding questions to MongoDB",
                extra={"source": "questions.add", "meta": {"error": str(e)}},
            )
            raise

    @staticmethod
    async def get_questions(page: int = 1, page_size: int = 50):
        """Retrieve paginated questions from MongoDB, excluding the changelog."""
        try:
            skip = (page - 1) * page_size
            projection = {"changelog": 0}

            # total count for all questions (without projection)
            total = await questions_collection.count_documents({})

            questions_cursor = (
                questions_collection.find({}, projection)
                .sort([("date_of_creation", -1), ("_id", 1)])
                .skip(skip)
                .limit(page_size)
            )
            questions = [doc async for doc in questions_cursor]
            return serialize_document(questions), total
        except Exception as e:
            logger.exception(
                "Error getting page of questions",
                extra={
                    "source": "questions.list",
                    "meta": {"page": page, "page_size": page_size, "error": str(e)},
                },
            )
            raise

    @staticmethod
    async def get_my_questions(owner_id: str, page: int = 1, page_size: int = 50):
        """Retrieve paginated questions from MongoDB for a specific owner, excluding the changelog."""
        try:
            skip = (page - 1) * page_size
            projection = {"changelog": 0}
            q = {"owner": owner_id}

            total = await questions_collection.count_documents(q)

            questions_cursor = (
                questions_collection.find(q, projection)
                .sort([("date_of_creation", -1), ("_id", 1)])
                .skip(skip)
                .limit(page_size)
            )
            questions = [doc async for doc in questions_cursor]
            return serialize_document(questions), total
        except Exception as e:
            logger.exception(
                "Error getting questions for owner",
                extra={
                    "source": "questions.list.mine",
                    "meta": {"owner_id": owner_id, "page": page, "error": str(e)},
                },
            )
            raise

    @staticmethod
    async def get_question_changelog(question_id: str) -> list:
        """
        Retrieve the changelog for a specific question by its ID.
        """
        try:
            logger.warning(
                "Retrieving changelog for a question",
                extra={"source": "questions.changelog", "meta": {"id": question_id}},
            )
            question_doc = await questions_collection.find_one(
                {"_id": ObjectId(question_id)}, {"changelog": 1, "_id": 0}
            )

            if not question_doc or "changelog" not in question_doc:
                # Return an empty list if no question is found or it has no changelog
                return []

            return serialize_document(question_doc.get("changelog", []))
        except Exception as e:
            logger.exception(
                "Error retrieving changelog",
                extra={
                    "source": "questions.changelog",
                    "meta": {"id": question_id, "error": str(e)},
                },
            )
            raise

    @staticmethod
    async def get_active_questions_count():
        """Counts the total number of questions with 'Active' status."""
        try:
            # This query efficiently counts documents matching the filter
            count = await questions_collection.count_documents({"status": "Active"})
            return count
        except Exception as e:
            logger.exception(
                "Error counting active questions",
                extra={"source": "questions.count", "meta": {"error": str(e)}},
            )
            raise

    @staticmethod
    async def update_question(question_id: str, updated_data: Question):
        """
        Update a question, increment its version, and log the changes.
        """
        try:
            # 1. Fetch the current document to compare against
            existing_doc = await questions_collection.find_one(
                {"_id": ObjectId(question_id)}
            )
            if not existing_doc:
                raise Exception("Document not found.")

            # 2. Prepare the incoming update data
            updated_dict = updated_data.model_dump(exclude_unset=True)
            if (
                "confluence_link" in updated_dict
                and updated_dict["confluence_link"] is not None
            ):
                updated_dict["confluence_link"] = str(updated_dict["confluence_link"])

            # Remove 'version' from the dictionary to avoid conflict.
            updated_dict.pop("version", None)

            # 3. Identify what has changed
            changes = []
            for field, new_value in updated_dict.items():
                old_value = existing_doc.get(field)
                if old_value != new_value:
                    changes.append(
                        {
                            "field": field,
                            "old_value": old_value,
                            "new_value": new_value,
                        }
                    )

            # If nothing actually changed, no need to update
            if not changes:
                return {"_id": question_id, "message": "No changes detected."}

            # 4. Create the new changelog entry
            update_time = datetime.utcnow()
            new_changelog_entry = {
                "version": existing_doc.get("version", 1),
                "updated_at": update_time,
                "changes": changes,
            }

            # 5. Build the atomic update payload for MongoDB
            updated_dict["last_updated_at"] = update_time

            logger.warning(
                "Updating question",
                extra={
                    "source": "questions.update",
                    "meta": {
                        "id": question_id,
                        "fields": list(updated_dict.keys()),
                        "changes_len": len(changes),
                    },
                },
            )

            update_payload = {
                "$set": updated_dict,
                "$inc": {"version": 1},
                "$push": {"changelog": new_changelog_entry},
            }

            # 6. Execute the update
            result = await questions_collection.update_one(
                {"_id": ObjectId(question_id)}, update_payload
            )

            if result.modified_count == 0:
                # This case is less likely now but kept for safety
                raise Exception("No document was updated.")

            return {"_id": question_id, "message": "Question updated successfully"}
        except Exception as e:
            logger.exception(
                "Error updating question",
                extra={
                    "source": "questions.update",
                    "meta": {"id": question_id, "error": str(e)},
                },
            )
            raise

    @staticmethod
    async def get_question_statistics(filters: dict):
        """
        Retrieves question statistics.
        It first checks for a recent, cached version of the statistics.
        If the underlying question data has changed or no cache exists,
        it recalculates the statistics and stores a new version.
        """
        try:
            # 1. Find the most recently cached statistics for the given filters
            cached_stats = await statistics_collection.find_one(
                {"filters": filters}, sort=[("calculated_at", -1)]
            )

            recalculate = True
            if cached_stats:
                last_calculated_at = cached_stats["calculated_at"]

                # 2. Check if any question has been updated since the last calculation
                latest_question_update = await questions_collection.find_one(
                    {"last_updated_at": {"$gt": last_calculated_at}},
                    projection={"_id": 1},
                )

                if not latest_question_update:
                    recalculate = False
                    logger.warning(
                        "Returning cached statistics",
                        extra={"source": "stats", "meta": {"filters": filters}},
                    )
                    return serialize_document(cached_stats)

            if recalculate:
                logger.warning(
                    "Recalculating statistics",
                    extra={"source": "stats", "meta": {"filters": filters}},
                )

                # 3. Build the MongoDB query from the frontend filters
                query: dict[str, Any] = {}
                for key, value in filters.items():
                    if value not in [None, "all", ""]:
                        query[key] = value

                questions = [doc async for doc in questions_collection.find(query)]
                total_questions = len(questions)

                # 4. Calculate new statistics (using placeholders)
                new_stats_data = {
                    "overview": {
                        "totalQuestions": total_questions,
                        "activeQuestions": sum(
                            1 for q in questions if q.get("status") == "Active"
                        ),
                        "hiddenQuestions": sum(
                            1 for q in questions if q.get("status") == "Hidden"
                        ),
                        "archivedQuestions": sum(
                            1 for q in questions if q.get("status") == "Archived"
                        ),
                        "averageSuccessRate": 0,  # Placeholder
                        "totalAttempts": 0,  # Placeholder
                        "questionsWithComments": 0,  # Placeholder
                        "lastQuestionAdded": (
                            (lambda dt: dt.isoformat() if dt is not None else "")(
                                max(
                                    (
                                        q.get("date_of_creation")
                                        for q in questions
                                        if isinstance(
                                            q.get("date_of_creation"), datetime
                                        )
                                    ),
                                    default=None,
                                )
                            )
                        ),
                    },
                    "performance": {
                        "myTopPerforming": [],  # Placeholder
                        "myPoorPerforming": [],  # Placeholder
                    },
                    "qualityIssues": {
                        "myPendingComments": [],  # Placeholder
                        "myBrokenLinks": [],  # Placeholder
                        "myUnusedQuestions": [],  # Placeholder
                    },
                    "trends": {"monthlyPerformance": []},  # Placeholder
                    "distribution": {
                        "myByDomain": [],  # Placeholder
                        "myByDifficulty": [],  # Placeholder
                        "myByType": [],  # Placeholder
                    },
                }

                # 5. Store the new statistics document
                stats_to_insert = {
                    "filters": filters,
                    "calculated_at": datetime.utcnow(),
                    "statistics": new_stats_data,
                }
                await statistics_collection.insert_one(stats_to_insert)

                # Use the serialization helper before returning the new stats
                return serialize_document(stats_to_insert)

        except Exception as e:
            logger.exception(
                "Error getting question statistics",
                extra={
                    "source": "stats",
                    "meta": {"filters": filters, "error": str(e)},
                },
            )
            raise

    @staticmethod
    async def assemble_questions_for_test(test_id: str) -> list:
        """
        Gathers questions for a given test based on its template details.
        This is the core logic for building a test.
        """
        test_doc = await tests_collection.find_one({"_id": ObjectId(test_id)})
        if not test_doc or "template_details" not in test_doc:
            raise ValueError("Test or template details not found.")

        template = test_doc["template_details"]

        # --- High-level template summary log
        def _sum_quota(qdict: dict) -> int:
            try:
                return sum(int(v) for v in qdict.values())
            except Exception:
                return 0

        total_needed = int(template.get("total_questions", 0))
        domain_q = template.get("domains", {}) or {}
        type_q = template.get("question_types", {}) or {}
        source_q = template.get("sources", {}) or {}
        impact_q = template.get("impact_levels", {}) or {}

        logger.warning(
            "Test assembly start",
            extra={
                "source": "assemble",
                "meta": {
                    "test_id": str(test_id),
                    "total_needed": total_needed,
                    "date_from": str(test_doc.get("questions_from_date")),
                    "date_to": str(test_doc.get("questions_to_date")),
                    "selected_topic": template.get("selected_topic"),
                    "selected_author": template.get("selected_author"),
                    "sum_domain_quota": _sum_quota(domain_q),
                    "sum_type_quota": _sum_quota(type_q),
                    "sum_source_quota": _sum_quota(source_q),
                    "sum_impact_quota": _sum_quota(impact_q),
                },
            },
        )

        # --- Progressive filter diagnostics: status → date → topic → author → reuse
        base_status: dict[str, Any] = {"status": "Active"}
        cnt_status = await questions_collection.count_documents(base_status)

        date_filter: dict[str, Any] = {}
        if test_doc.get("questions_from_date"):
            date_filter["$gte"] = test_doc["questions_from_date"]
        if test_doc.get("questions_to_date"):
            date_filter["$lte"] = test_doc["questions_to_date"]

        f_date: dict[str, Any] = dict(base_status)
        if date_filter:
            f_date["date_of_creation"] = date_filter
        cnt_date = await questions_collection.count_documents(f_date)

        f_topic: dict[str, Any] = dict(f_date)
        if template.get("selected_topic"):
            f_topic["topic"] = {"$in": template["selected_topic"]}
        cnt_topic = await questions_collection.count_documents(f_topic)

        f_author: dict[str, Any] = dict(f_topic)
        if template.get("selected_author") and template["selected_author"] != "All":
            f_author["owner"] = template["selected_author"]
        cnt_author = await questions_collection.count_documents(f_author)

        # Probe: how many are marked as used in this test (do NOT filter by this)
        f_reuse_probe: dict[str, Any] = dict(f_author)
        f_reuse_probe["tests_used_in"] = {"$in": [str(test_doc["_id"])]}
        cnt_marked_this_test = await questions_collection.count_documents(f_reuse_probe)

        logger.warning(
            "Filter diagnostics",
            extra={
                "source": "assemble",
                "meta": {
                    "count_status_active": cnt_status,
                    "count_after_date": cnt_date,
                    "count_after_topic": cnt_topic,
                    "count_after_author": cnt_author,
                    "count_marked_this_test": cnt_marked_this_test,
                    "final_filter": json.dumps(f_author, default=str),
                },
            },
        )

        # ----- Build base filters (parametric so we can relax) -----
        def build_filter(
            include_topic: bool = True, include_author: bool = True
        ) -> dict[str, Any]:
            f: dict[str, Any] = {"status": "Active"}

            if date_filter:
                f["date_of_creation"] = date_filter

            if include_topic and template.get("selected_topic"):
                f["topic"] = {"$in": template["selected_topic"]}

            if (
                include_author
                and template.get("selected_author")
                and template["selected_author"] != "All"
            ):
                f["owner"] = template["selected_author"]

            # NOTE: no DB-level reuse guard here
            return f

        relaxed_dimensions: list[str] = []
        final_questions: list[dict[str, Any]] = []
        selected_ids: set[str] = set()
        counts = {
            "domain": {k: 0 for k in domain_q},
            "type": {k: 0 for k in type_q},
            "source": {k: 0 for k in source_q},
            "impact": {k: 0 for k in impact_q},
        }

        # Reason tallies across all stages
        skip_reasons = Counter()

        # Helper: tallies per-field distribution (for diagnostics)
        def _tally(cands: list[dict[str, Any]], key: str) -> dict[Any, int]:
            d: dict[Any, int] = defaultdict(int)
            for _q in cands:
                d[_q.get(key)] = d.get(_q.get(key), 0) + 1
            return dict(d)

        # Helper to enforce quotas strictly as allow-lists when present.
        async def fill_from_candidates(
            candidates: list[dict[str, Any]], enforce: set[str], stage_note: str
        ):
            """
            enforce contains any of: {"source", "type", "domain", "impact"}
            BUT only dimensions with non-empty quotas are actually enforced.
            """
            before = len(final_questions)

            # Only enforce dimensions that have quotas configured
            enforce_effective: set[str] = set()
            if "domain" in enforce and domain_q:
                enforce_effective.add("domain")
            if "type" in enforce and type_q:
                enforce_effective.add("type")
            if "source" in enforce and source_q:
                enforce_effective.add("source")
            if "impact" in enforce and impact_q:
                enforce_effective.add("impact")

            for q in candidates:
                if len(final_questions) >= total_needed:
                    break

                q_id = str(q["_id"])
                if q_id in selected_ids:
                    skip_reasons["duplicate"] += 1
                    continue

                q_domain = q.get("domain")
                q_type = q.get("question_type")
                q_source = q.get("source")
                q_impact = q.get("impact_level")

                ok = True

                # Domain
                if "domain" in enforce_effective:
                    if q_domain not in domain_q:
                        ok = False
                        skip_reasons["domain_not_in_quota"] += 1
                    elif counts["domain"][q_domain] >= domain_q[q_domain]:
                        ok = False
                        skip_reasons["domain_quota_full"] += 1

                # Type
                if ok and "type" in enforce_effective:
                    if q_type not in type_q:
                        ok = False
                        skip_reasons["type_not_in_quota"] += 1
                    elif counts["type"][q_type] >= type_q[q_type]:
                        ok = False
                        skip_reasons["type_quota_full"] += 1

                # Source
                if ok and "source" in enforce_effective:
                    if q_source not in source_q:
                        ok = False
                        skip_reasons["source_not_in_quota"] += 1
                    elif counts["source"][q_source] >= source_q[q_source]:
                        ok = False
                        skip_reasons["source_quota_full"] += 1

                # Impact
                if ok and "impact" in enforce_effective:
                    if q_impact not in impact_q:
                        ok = False
                        skip_reasons["impact_not_in_quota"] += 1
                    elif counts["impact"][q_impact] >= impact_q[q_impact]:
                        ok = False
                        skip_reasons["impact_quota_full"] += 1

                if ok:
                    final_questions.append(q)
                    selected_ids.add(q_id)
                    if "domain" in enforce_effective:
                        counts["domain"][q_domain] += 1
                    if "type" in enforce_effective:
                        counts["type"][q_type] += 1
                    if "source" in enforce_effective:
                        counts["source"][q_source] += 1
                    if "impact" in enforce_effective:
                        counts["impact"][q_impact] += 1

            gained = len(final_questions) - before
            if len(final_questions) < total_needed:
                logger.warning(
                    "Stage finished (still short)",
                    extra={
                        "source": "assemble.stage",
                        "meta": {
                            "test_id": str(test_id),
                            "stage": stage_note,
                            "enforce_effective": sorted(list(enforce_effective)),
                            "selected_this_stage": gained,
                            "selected_total": len(final_questions),
                            "needed_total": total_needed,
                            "skip_reasons": dict(skip_reasons),
                            "counts_domain": counts["domain"],
                            "counts_type": counts["type"],
                            "counts_source": counts["source"],
                            "counts_impact": counts["impact"],
                        },
                    },
                )
            else:
                logger.warning(
                    "Stage finished (completed target)",
                    extra={
                        "source": "assemble.stage",
                        "meta": {
                            "test_id": str(test_id),
                            "stage": stage_note,
                            "selected_this_stage": gained,
                            "selected_total": len(final_questions),
                        },
                    },
                )

        # Relaxation plan (mirrors report/replace order)
        quota_stages = [
            {
                "enforce": {"source", "type", "domain", "impact"},
                "note": "strict quotas",
            },
            {"enforce": {"type", "domain", "impact"}, "note": "drop source quota"},
            {"enforce": {"domain", "impact"}, "note": "drop question_type quota"},
            {"enforce": {"impact"}, "note": "drop domain quota"},
            {"enforce": set(), "note": "drop impact quota (no quotas)"},
        ]

        # topic/author relaxation after quota stages
        topic_author_stages = [
            {
                "include_topic": False,
                "include_author": True,
                "note": "drop topic filter",
            },
            {
                "include_topic": False,
                "include_author": False,
                "note": "drop author filter",
            },
        ]

        # ----- Phase 1: quotas with original topic/author filters -----
        base_filter = build_filter(include_topic=True, include_author=True)
        base_cnt = await questions_collection.count_documents(base_filter)
        base_candidates = await questions_collection.find(base_filter).to_list(
            length=None
        )
        random.shuffle(base_candidates)
        logger.warning(
            "Phase 1: base candidates fetched",
            extra={
                "source": "assemble",
                "meta": {
                    "test_id": str(test_id),
                    "base_filter_count": base_cnt,
                    "base_filter": json.dumps(base_filter, default=str),
                    "dist_domain": _tally(base_candidates, "domain"),
                    "dist_type": _tally(base_candidates, "question_type"),
                    "dist_source": _tally(base_candidates, "source"),
                    "dist_impact": _tally(base_candidates, "impact_level"),
                },
            },
        )

        for stage in quota_stages:
            if len(final_questions) >= total_needed:
                break
            relaxed_dimensions.append(stage["note"])
            await fill_from_candidates(base_candidates, stage["enforce"], stage["note"])

        # ----- Phase 2: widen DB filter (topic, then author), repeat quota stages quickly -----
        if len(final_questions) < total_needed:
            for tf in topic_author_stages:
                if len(final_questions) >= total_needed:
                    break
                relaxed_dimensions.append(tf["note"])
                f = build_filter(
                    include_topic=tf["include_topic"],
                    include_author=tf["include_author"],
                )
                widen_cnt = await questions_collection.count_documents(f)
                cands = await questions_collection.find(f).to_list(length=None)
                random.shuffle(cands)

                logger.warning(
                    "Phase 2: widened candidates fetched",
                    extra={
                        "source": "assemble",
                        "meta": {
                            "test_id": str(test_id),
                            "stage_note": tf["note"],
                            "filter_count": widen_cnt,
                            "filter": json.dumps(f, default=str),
                            "dist_domain": _tally(cands, "domain"),
                            "dist_type": _tally(cands, "question_type"),
                            "dist_source": _tally(cands, "source"),
                            "dist_impact": _tally(cands, "impact_level"),
                        },
                    },
                )

                for stage in quota_stages:
                    if len(final_questions) >= total_needed:
                        break
                    await fill_from_candidates(
                        cands, stage["enforce"], f"{tf['note']} -> {stage['note']}"
                    )

        # ----- Phase 3: absolute fallback (ignore all quotas; keep status/date only) -----
        if len(final_questions) < total_needed:
            relaxed_dimensions.append("final fallback: ignore all quotas")
            f = build_filter(include_topic=False, include_author=False)
            fallback_cnt = await questions_collection.count_documents(f)
            cands = await questions_collection.find(f).to_list(length=None)
            random.shuffle(cands)

            logger.warning(
                "Phase 3: fallback candidates fetched",
                extra={
                    "source": "assemble",
                    "meta": {
                        "test_id": str(test_id),
                        "filter_count": fallback_cnt,
                        "filter": json.dumps(f, default=str),
                    },
                },
            )

            before = len(final_questions)
            for q in cands:
                if len(final_questions) >= total_needed:
                    break
                q_id = str(q["_id"])
                if q_id not in selected_ids:
                    final_questions.append(q)
                    selected_ids.add(q_id)
                else:
                    skip_reasons["duplicate"] += 1
            gained = len(final_questions) - before

            logger.warning(
                "Phase 3 finished",
                extra={
                    "source": "assemble.stage",
                    "meta": {
                        "test_id": str(test_id),
                        "selected_this_stage": gained,
                        "selected_total": len(final_questions),
                        "needed_total": total_needed,
                        "skip_reasons": dict(skip_reasons),
                    },
                },
            )

        # ----- Final check -----
        if len(final_questions) < total_needed:
            msg = (
                f"Could not assemble enough questions. Needed {total_needed}, "
                f"got {len(final_questions)}. "
                f"Tried relaxations: {', '.join(relaxed_dimensions)}"
            )
            logger.error(
                "Test Assembly Failed",
                extra={
                    "source": "assemble",
                    "meta": {
                        "test_id": str(test_id),
                        "message": msg,
                        "selected_total": len(final_questions),
                        "needed_total": total_needed,
                        "relaxed_dimensions": relaxed_dimensions,
                        "skip_reasons": dict(skip_reasons),
                        "quota_counts": {
                            "domain": counts["domain"],
                            "type": counts["type"],
                            "source": counts["source"],
                            "impact": counts["impact"],
                        },
                        "sum_domain_quota": _sum_quota(domain_q),
                        "sum_type_quota": _sum_quota(type_q),
                        "sum_source_quota": _sum_quota(source_q),
                        "sum_impact_quota": _sum_quota(impact_q),
                    },
                },
            )
            raise ValueError(msg)

        # mark usage & return
        question_ids = [str(q["_id"]) for q in final_questions]
        await QuestionService.log_test_usage_in_questions(question_ids, test_id)

        logger.warning(
            "Test assembly success",
            extra={
                "source": "assemble",
                "meta": {
                    "test_id": str(test_id),
                    "selected_total": len(final_questions),
                    "relaxed_dimensions": relaxed_dimensions,
                },
            },
        )
        return serialize_document(final_questions)

    @staticmethod
    async def log_test_usage_in_questions(question_ids: list[str], test_id: str):
        """
        Updates questions to log that they have been used in a specific test.
        """
        if not question_ids:
            return
        await questions_collection.update_many(
            {"_id": {"$in": [ObjectId(qid) for qid in question_ids]}},
            {"$addToSet": {"tests_used_in": str(test_id)}},
        )
        logger.warning(
            "Marked questions as used in test",
            extra={
                "source": "questions.usage",
                "meta": {"test_id": str(test_id), "count": len(question_ids)},
            },
        )

    @staticmethod
    async def _create_question_report(
        question_id: str,
        test_id: str,
        reported_by: str,
        report_comment: str,
    ) -> str:
        """
        Creates a question report document and returns its id as string.
        """
        report_doc = {
            "question_id": ObjectId(question_id),
            "test_id": test_id,
            "reported_by": reported_by,
            "comment": report_comment,
            "status": "Open",
            "created_at": datetime.utcnow(),
        }
        result = await question_reports_collection.insert_one(report_doc)
        logger.warning(
            "Question report created",
            extra={
                "source": "questions.report",
                "meta": {
                    "report_id": str(result.inserted_id),
                    "question_id": question_id,
                    "test_id": test_id,
                },
            },
        )
        return str(result.inserted_id)

    @staticmethod
    async def _get_question(question_id: str) -> dict | None:
        return await questions_collection.find_one({"_id": ObjectId(question_id)})

    @staticmethod
    def _strict_filter_from_question(q: dict) -> dict:
        """
        Build the strict filter based on the reported question's metadata.
        """
        return {
            "status": "Active",
            "topic": q.get("topic"),
            "impact_level": q.get("impact_level"),
            "question_type": q.get("question_type"),
            "domain": q.get("domain"),
            "source": q.get("source"),
        }

    @staticmethod
    def _apply_exclusions(
        base: dict[str, Any], exclude_object_ids: list[ObjectId], test_id: str
    ) -> dict[str, Any]:
        """
        Apply exclusion list and ensure the candidate hasn't been used in this test.
        """
        f: dict[str, Any] = dict(base)
        # Exclude ids
        if exclude_object_ids:
            f["_id"] = {"$nin": exclude_object_ids}
        # Ensure not used in this test (when field exists)
        f["tests_used_in"] = {"$nin": [test_id]}
        return f

    @staticmethod
    async def _find_random(filters: dict[str, Any]) -> dict | None:
        """
        Driver-safe random pick without aggregate(): count -> random skip -> limit(1).
        Works across Motor versions.
        """
        count = await questions_collection.count_documents(filters)
        logger.warning(
            "Random find: filter count",
            extra={
                "source": "questions.random",
                "meta": {
                    "filter_count": count,
                    "filters": json.dumps(filters, default=str),
                },
            },
        )
        if count == 0:
            return None
        # random index [0, count-1]
        idx = random.randint(0, count - 1)
        cursor = questions_collection.find(filters).skip(idx).limit(1)
        docs = [doc async for doc in cursor]
        return docs[0] if docs else None

    @staticmethod
    async def _progressive_find(
        base_filters: dict[str, Any],
        exclude_object_ids: list[ObjectId],
        test_id: str,
    ) -> tuple[dict | None, list[str]]:
        """
        Try strict match first; then relax in order:
        source -> question_type -> domain -> impact_level -> topic
        Returns (doc, relaxed_dimensions).
        """
        relaxation_order = [
            "source",
            "question_type",
            "domain",
            "impact_level",
            "topic",
        ]

        # Strict first
        strict_filters = QuestionService._apply_exclusions(
            base_filters, exclude_object_ids, test_id
        )
        logger.warning(
            "Progressive find: strict",
            extra={
                "source": "questions.replace",
                "meta": {"filters": json.dumps(strict_filters, default=str)},
            },
        )
        doc = await QuestionService._find_random(strict_filters)
        if doc:
            return doc, []

        relaxed_dims: list[str] = []
        for dim in relaxation_order:
            relaxed_dims.append(dim)
            # Drop relaxed dimensions from filter
            f = {k: v for k, v in base_filters.items() if k not in relaxed_dims}
            f = QuestionService._apply_exclusions(f, exclude_object_ids, test_id)
            logger.warning(
                "Progressive find: relaxed",
                extra={
                    "source": "questions.replace",
                    "meta": {
                        "dropped": list(relaxed_dims),
                        "filters": json.dumps(f, default=str),
                    },
                },
            )
            doc = await QuestionService._find_random(f)
            if doc:
                return doc, relaxed_dims[:]

        return None, relaxed_dims

    @staticmethod
    async def report_and_replace_question(
        original_question_id: str,
        test_id: str,
        reported_by: str,
        report_comment: str,
        exclude_question_ids: list[str] | None = None,
    ) -> dict:
        """
        End-to-end flow:
        1) Hide the reported question (status -> 'Hidden')
        2) Create a question report with the user's comment
        3) Find a replacement with strict filters, then relax in order:
           source -> question_type -> domain -> impact_level -> topic
        4) Return a structured payload. If none found, replacement_found=False with guidance.
        """
        try:
            # Load original question (for metadata & validation)
            original = await QuestionService._get_question(original_question_id)
            if not original:
                raise ValueError("Original question not found.")

            # Hide the original question (idempotent if already hidden/archived)
            await questions_collection.update_one(
                {"_id": ObjectId(original_question_id)},
                {"$set": {"status": "Hidden", "last_updated_at": datetime.utcnow()}},
            )
            logger.warning(
                "Question hidden due to user report",
                extra={
                    "source": "questions.replace",
                    "meta": {"question_id": original_question_id},
                },
            )

            report_id = await QuestionService._create_question_report(
                original_question_id, test_id, reported_by, report_comment
            )

            # Build strict filters from the original
            base_filters = QuestionService._strict_filter_from_question(original)

            # Build exclusion list: provided IDs + the original
            exclude_ids = (exclude_question_ids or []) + [original_question_id]
            exclude_object_ids = []
            for qid in exclude_ids:
                try:
                    exclude_object_ids.append(ObjectId(qid))
                except Exception:
                    # If any are not valid ObjectIds, ignore silently (frontend may pass string ids for other stores)
                    pass

            # Progressive search for a replacement
            replacement_doc, relaxed = await QuestionService._progressive_find(
                base_filters, exclude_object_ids, test_id
            )

            if not replacement_doc:
                payload = {
                    "reported_question_id": original_question_id,
                    "report_id": report_id,
                    "replacement_found": False,
                    "relaxed_dimensions": relaxed,
                    "message": "No replacements available. Finish the test and raise a dispute.",
                }
                logger.warning(
                    "No replacement found",
                    extra={
                        "source": "questions.replace",
                        "meta": payload,
                    },
                )
                return payload

            await QuestionService.log_test_usage_in_questions(
                [str(replacement_doc["_id"])], test_id
            )

            # Shape response for frontend consumption
            replacement_out = {
                **serialize_document(replacement_doc),
                "isReplacement": True,
                "reporting_disabled": True,
            }

            payload = {
                "reported_question_id": original_question_id,
                "report_id": report_id,
                "replacement_found": True,
                "relaxed_dimensions": relaxed,
                "replacement": replacement_out,
            }
            logger.warning(
                "Replacement selected",
                extra={
                    "source": "questions.replace",
                    "meta": {
                        "reported_question_id": original_question_id,
                        "replacement_id": str(replacement_doc["_id"]),
                        "relaxed_dimensions": relaxed,
                    },
                },
            )
            return payload

        except Exception as e:
            logger.exception(
                "Error in report_and_replace_question",
                extra={
                    "source": "questions.replace",
                    "meta": {
                        "original_question_id": original_question_id,
                        "test_id": test_id,
                        "error": str(e),
                    },
                },
            )
            raise
