from datetime import datetime
import json
import re
import hashlib
from collections import defaultdict
from typing import Any, Iterable

from bson import ObjectId
from pydantic import ValidationError

from config import db, logger, redis_client
from modules.test_templates.model import (
    TestTemplateCreate,
    TestTemplateInDB,
    TestTemplateUpdate,
)

templates_collection = db.test_templates
questions_collection = db.questions

# ---- simple cache helpers (Jira-style) ----
TTL = 15 * 60  # 15 minutes; payload-specific, safe because edits change the key


def _make_key(prefix: str, identifier: str) -> str:
    h = hashlib.sha1(identifier.encode()).hexdigest()
    return f"{prefix}:{h}"


async def _safe_redis_get(key: str) -> str | None:
    try:
        raw = await redis_client.get(key)
        return raw
    except Exception as e:
        logger.warning(f"Redis get failed for key={key}: {e}")
        return None


async def _safe_redis_set(key: str, value: str, ex: int | None = None) -> None:
    try:
        await redis_client.set(key, value, ex=ex)
    except Exception as e:
        logger.warning(f"Redis set failed for key={key}: {e}")


# ---------------------- label normalization helpers ----------------------


def _clean(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").strip().lower())


def _canonize_keys(d: dict[str, int], pool: Iterable[str]) -> dict[str, int]:
    """Map keys in d to best matches in pool, case/underscore/space-insensitive."""
    pool = list(pool or [])
    by_clean = {_clean(p): p for p in pool}
    out: dict[str, int] = {}
    for k, v in (d or {}).items():
        ck = _clean(k)
        if ck in by_clean:
            out[by_clean[ck]] = int(v or 0)
        else:
            # if not found, keep as-is (allows new labels but may reduce match rate)
            out[k] = int(v or 0)
    return out


# ---------------------- core service ----------------------


class TestTemplateService:
    @staticmethod
    async def create_template(template_data: TestTemplateCreate) -> str:
        """
        Inserts a new private test template into the database.
        """
        insert_data = template_data.model_dump(by_alias=True)

        insert_data["is_common"] = False
        insert_data["created_at"] = datetime.now()
        insert_data["last_modified"] = datetime.now()

        result = await templates_collection.insert_one(insert_data)
        return str(result.inserted_id)

    @staticmethod
    async def get_templates(user_id: str | None) -> dict[str, list[TestTemplateInDB]]:
        """
        Retrieves common templates and private templates for a specific user.
        Returns a dictionary with lists of TestTemplateInDB models.
        """
        common_templates = []
        common_cursor = templates_collection.find({"is_common": True})
        async for doc in common_cursor:
            try:
                # Attempt to validate and create the Pydantic model
                common_templates.append(TestTemplateInDB(**doc))
            except ValidationError as e:
                # If a document fails validation, log the specific error and the document's ID
                doc_id = doc.get("_id", "Unknown ID")
                logger.error(
                    f"Pydantic validation failed for common template _id={doc_id}: {e}"
                )
                # Continue to the next document instead of crashing
                continue

        private_templates = []
        if user_id:
            private_cursor = templates_collection.find(
                {"created_by": user_id, "is_common": False}
            )
            async for doc in private_cursor:
                try:
                    private_templates.append(TestTemplateInDB(**doc))
                except ValidationError as e:
                    doc_id = doc.get("_id", "Unknown ID")
                    logger.error(
                        f"Pydantic validation failed for private template _id={doc_id}: {e}"
                    )
                    continue

        return {"common": common_templates, "private": private_templates}

    @staticmethod
    async def get_template_by_id(template_id: str) -> TestTemplateInDB | None:
        """
        Retrieves a single template by its ID.
        """
        template_doc = await templates_collection.find_one(
            {"_id": ObjectId(template_id)}
        )
        return TestTemplateInDB(**template_doc) if template_doc else None

    @staticmethod
    async def update_template(
        template_id: str, template_data: TestTemplateUpdate
    ) -> bool:
        """
        Updates an existing test template. Only updates fields that are provided.
        """
        update_data = template_data.model_dump(exclude_unset=True, by_alias=True)

        if not update_data:
            return True
        update_data["last_modified"] = datetime.now()

        result = await templates_collection.update_one(
            {"_id": ObjectId(template_id)}, {"$set": update_data}
        )
        return result.modified_count > 0

    @staticmethod
    async def delete_template(template_id: str) -> bool:
        """
        Deletes a template from the database.
        """
        result = await templates_collection.delete_one({"_id": ObjectId(template_id)})
        return result.deleted_count > 0

    # -------------------- STRICT PREVIEW (no relaxations) --------------------

    @staticmethod
    async def preview_template_strict(payload: dict) -> dict:
        """
        Strict feasibility check for a template — and return a single, verified
        'suggested_plan' (increments/decrements per category) that makes it feasible.
        Accepts BOTH legacy snake_case and compact payloads.
        """
        # ---- cache lookup
        try:
            ident = json.dumps(payload, sort_keys=True, default=str)
        except Exception:
            # Fallback: best-effort stringify
            ident = str(payload)
        try:
            ver_doc = await db["questions_meta"].find_one({"_id": "version"})
            ver = (
                str(ver_doc.get("last_updated"))
                if ver_doc and ver_doc.get("last_updated")
                else None
            )
        except Exception:
            ver = None
        if not ver:
            try:
                ver = (
                    f"cnt:{await db['questions'].count_documents({'status': 'Active'})}"
                )
            except Exception:
                ver = "v0"
        cache_key = _make_key("tpl:preview", f"v={ver}|{ident}")

        raw = await _safe_redis_get(cache_key)
        if raw:
            try:
                logger.info("Cache hit for template preview")
                return json.loads(raw)
            except Exception as e:
                logger.warning(f"Cache decode failed for template preview: {e}")

        # ---------- normalize inputs (support compact & legacy) ----------
        if "total" in payload or "quotas" in payload or "topics" in payload:
            # compact
            total_needed = int(payload.get("total", 0))
            selected_topic = payload.get("topics") or []
            selected_author = payload.get("owner") or "All"
            quotas = payload.get("quotas") or {}
            q_types_in: dict[str, int] = quotas.get("question_types") or {}
            q_domains_in: dict[str, int] = quotas.get("domains") or {}
            q_sources_in: dict[str, int] = quotas.get("sources") or {}
            q_imp_in: dict[str, int] = quotas.get("impact_levels") or {}
        else:
            # legacy
            total_needed = int(payload.get("total_questions", 0))
            selected_topic = payload.get("selected_topic") or []
            selected_author = payload.get("selected_author") or "All"
            q_types_in: dict[str, int] = payload.get("question_types") or {}
            q_domains_in: dict[str, int] = payload.get("domains") or {}
            q_sources_in: dict[str, int] = payload.get("sources") or {}
            q_imp_in: dict[str, int] = payload.get("impact_levels") or {}

        # ---------- base filter (Active only; topics & author optional) ----------
        base_filter: dict[str, Any] = {"status": "Active"}
        if selected_topic:
            base_filter["topic"] = {"$in": selected_topic}
        if selected_author and selected_author != "All":
            base_filter["owner"] = selected_author

        # Projection to reduce I/O
        projection = {
            "_id": 1,
            "domain": 1,
            "question_type": 1,
            "source": 1,
            "impact_level": 1,
        }

        # Fetch candidates (5k scale OK with index + projection)
        candidates: list[dict] = await questions_collection.find(
            base_filter, projection
        ).to_list(length=None)
        # deterministic order instead of random
        seed = int(hashlib.sha1(ident.encode()).hexdigest()[:8], 16)

        def _ord(qid):
            return hashlib.sha1((str(qid) + str(seed)).encode()).hexdigest()

        candidates.sort(key=lambda q: _ord(q.get("_id")))

        # ---------- distributions / pools ----------
        def tally(cands: list[dict], key: str) -> dict[str, int]:
            d: dict[str, int] = defaultdict(int)
            for c in cands:
                d[c.get(key, "")] += 1
            return dict(d)

        dist_type = tally(candidates, "question_type")
        dist_domain = tally(candidates, "domain")
        dist_source = tally(candidates, "source")
        dist_impact = tally(candidates, "impact_level")

        # normalize incoming quota keys to observed pools
        q_types = _canonize_keys(q_types_in, dist_type.keys())
        q_domains = _canonize_keys(q_domains_in, dist_domain.keys())
        q_sources = _canonize_keys(q_sources_in, dist_source.keys())
        q_imp = _canonize_keys(q_imp_in, dist_impact.keys())

        # availability per combo
        combo_avail: dict[tuple[str, str, str, str], int] = defaultdict(int)
        for c in candidates:
            key = (
                c.get("domain") or "",
                c.get("question_type") or "",
                c.get("source") or "",
                c.get("impact_level") or "",
            )
            combo_avail[key] += 1

        # ---- strict selector (extracted as function so we can re-run) ----
        def strict_select(
            qt: dict[str, int],
            qd: dict[str, int],
            qs: dict[str, int],
            qi: dict[str, int],
        ) -> tuple[int, dict, dict, dict, dict]:
            selected_ids: set[str] = set()
            counts = {
                "type": {k: 0 for k in qt},
                "domain": {k: 0 for k in qd},
                "source": {k: 0 for k in qs},
                "impact": {k: 0 for k in qi},
            }
            selected_by_combo: dict[tuple[str, str, str, str], int] = defaultdict(int)
            enforce = set()
            if sum((qt or {}).values()) > 0:
                enforce.add("type")
            if sum((qd or {}).values()) > 0:
                enforce.add("domain")
            if sum((qs or {}).values()) > 0:
                enforce.add("source")
            if sum((qi or {}).values()) > 0:
                enforce.add("impact")

            for q in candidates:
                if len(selected_ids) >= total_needed:
                    break
                qid = str(q["_id"])
                if qid in selected_ids:
                    continue

                ok = True
                if "type" in enforce:
                    qt_k = q.get("question_type")
                    if not qt_k or qt_k not in qt or counts["type"][qt_k] >= qt[qt_k]:
                        ok = False
                if ok and "domain" in enforce:
                    dm_k = q.get("domain")
                    if not dm_k or dm_k not in qd or counts["domain"][dm_k] >= qd[dm_k]:
                        ok = False
                if ok and "source" in enforce:
                    sc_k = q.get("source")
                    if not sc_k or sc_k not in qs or counts["source"][sc_k] >= qs[sc_k]:
                        ok = False
                if ok and "impact" in enforce:
                    im_k = q.get("impact_level")
                    if not im_k or im_k not in qi or counts["impact"][im_k] >= qi[im_k]:
                        ok = False

                if ok:
                    selected_ids.add(qid)
                    if "type" in enforce:
                        counts["type"][q.get("question_type", "")] += 1
                    if "domain" in enforce:
                        counts["domain"][q.get("domain", "")] += 1
                    if "source" in enforce:
                        counts["source"][q.get("source", "")] += 1
                    if "impact" in enforce:
                        counts["impact"][q.get("impact_level", "")] += 1
                    key = (
                        q.get("domain") or "",
                        q.get("question_type") or "",
                        q.get("source") or "",
                        q.get("impact_level") or "",
                    )
                    selected_by_combo[key] += 1

            sel_total = len(selected_ids)

            # build matrices
            def make_matrix(
                dist: dict[str, int], req: dict[str, int], sel: dict[str, int]
            ):
                out: dict[str, dict] = {}
                keys = set(dist) | set(req) | set(sel)
                for k in keys:
                    r = int(req.get(k, 0))
                    a = int(dist.get(k, 0))
                    s = int(sel.get(k, 0))
                    out[k] = {
                        "requested": r,
                        "available": a,
                        "selected": s,
                        "shortfall": max(0, r - s),
                    }
                return out

            quotas = {
                "question_types": make_matrix(dist_type, qt, counts["type"]),
                "domains": make_matrix(dist_domain, qd, counts["domain"]),
                "sources": make_matrix(dist_source, qs, counts["source"]),
                "impact_levels": make_matrix(dist_impact, qi, counts["impact"]),
            }
            return sel_total, quotas, counts, selected_by_combo, {}

        # ---- initial strict run ----
        selected_total, quotas, counts_now, selected_by_combo, _ = strict_select(
            q_types, q_domains, q_sources, q_imp
        )
        missing_total = max(0, total_needed - selected_total)
        feasible = selected_total >= total_needed

        # ---------- early return if already feasible ----------
        diagnostics = {
            "base_filter": json.dumps(base_filter, default=str),
            "base_count": len(candidates),
        }
        if feasible:
            result = {
                "feasible": True,
                "total_needed": total_needed,
                "selected_total": selected_total,
                "missing_total": 0,
                "quotas": quotas,
                "diagnostics": diagnostics,
                "suggested_plan": None,
                "fallback_plan": None,
                "unlockers": None,
            }
            await _safe_redis_set(
                cache_key, json.dumps(result, separators=(",", ":")), ex=TTL
            )
            return result

        # ------------ build a verified plan to reach feasibility ------------

        def deficits_from(qq: dict) -> dict[str, dict[str, int]]:
            """Return {cat: {value: shortfall>0}} in priority order."""
            d: dict[str, dict[str, int]] = {
                "domains": {},
                "question_types": {},
                "sources": {},
                "impact_levels": {},
            }
            for cat in d.keys():
                for k, cell in (qq.get(cat) or {}).items():
                    sf = int(cell.get("shortfall", 0))
                    if sf > 0:
                        d[cat][k] = sf
            return d

        # Build a plan with up to 'missing_total' steps (usually 1-3)
        INC = {"domains": {}, "question_types": {}, "sources": {}, "impact_levels": {}}
        DEC = {"domains": {}, "question_types": {}, "sources": {}, "impact_levels": {}}

        def add_delta(bag: dict, cat: str, key: str, n: int):
            if key is None or n <= 0:
                return
            bag[cat][key] = bag[cat].get(key, 0) + n

        # priority of deficit dimensions
        PRIOR = ["domains", "question_types", "sources", "impact_levels"]
        IDX = {"domains": 0, "question_types": 1, "sources": 2, "impact_levels": 3}

        def need_score(
            combo: tuple[str, str, str, str], defs: dict[str, dict[str, int]]
        ) -> int:
            sc = 0
            if combo[0] in defs["domains"]:
                sc += 1
            if combo[1] in defs["question_types"]:
                sc += 1
            if combo[2] in defs["sources"]:
                sc += 1
            if combo[3] in defs["impact_levels"]:
                sc += 1
            return sc

        q_work_types = dict(q_types)
        q_work_domains = dict(q_domains)
        q_work_sources = dict(q_sources)
        q_work_imp = dict(q_imp)

        steps = 0
        sel_after = 0
        # attempt up to the current missing_total steps
        for _ in range(max(1, missing_total)):
            # recompute strict selection on working quotas
            sel_now, qmat_now, counts_now, sel_by_combo_now, _ = strict_select(
                q_work_types, q_work_domains, q_work_sources, q_work_imp
            )
            if sel_now >= total_needed:
                break  # already feasible

            defs_now = deficits_from(qmat_now)

            # (FIX 1) recompute residual capacity per combo using the current selection
            residual_by_combo_now = {
                k: combo_avail.get(k, 0) - int(sel_by_combo_now.get(k, 0))
                for k in combo_avail.keys()
            }

            # (FIX 2) recompute donor slack from the CURRENT quotas
            def recalc_slack_from(qmat: dict, cat_key: str) -> dict[str, int]:
                sm = {}
                for k, cell in (qmat.get(cat_key) or {}).items():
                    sm[k] = int(cell.get("requested", 0)) - int(cell.get("selected", 0))
                return sm

            slack = {
                "domains": recalc_slack_from(qmat_now, "domains"),
                "question_types": recalc_slack_from(qmat_now, "question_types"),
                "sources": recalc_slack_from(qmat_now, "sources"),
                "impact_levels": recalc_slack_from(qmat_now, "impact_levels"),
            }

            # pick primary deficit: by PRIOR order then largest shortfall
            primary_cat = None
            primary_val = None
            for cat in PRIOR:
                if defs_now[cat]:
                    # largest shortfall first
                    primary_val = max(defs_now[cat].items(), key=lambda x: x[1])[0]
                    primary_cat = cat
                    break
            if not primary_cat:
                # there is no per-category shortfall, cannot fix with quota moves
                break

            # choose a target combo with residual capacity that contains the primary_val in its dim
            dim_idx = IDX[primary_cat]
            targets = [
                c
                for c, left in residual_by_combo_now.items()
                if left > 0 and c[dim_idx] == primary_val
            ]
            if not targets:
                # cannot create this dimension with available questions — stop planning
                break

            # rank targets: higher need_score first, then higher residual
            targets.sort(
                key=lambda c: (need_score(c, defs_now), residual_by_combo_now[c]),
                reverse=True,
            )
            chosen = targets[0]

            # determine which categories require +1 to include 'chosen'
            # headroom if requested > selected in that value
            needed_inc: list[tuple[str, str]] = []
            for cat, v in [
                ("domains", chosen[0]),
                ("question_types", chosen[1]),
                ("sources", chosen[2]),
                ("impact_levels", chosen[3]),
            ]:
                cell = (qmat_now.get(cat) or {}).get(v)
                req = int(cell.get("requested", 0)) if cell else 0
                sel = int(cell.get("selected", 0)) if cell else 0
                if sel >= req:
                    needed_inc.append((cat, v))  # must add +1 for this value

            # find donors in each category with slack>0 (and not equal to v)
            donors: list[tuple[str, str | None]] = []
            for cat, v in needed_inc:
                dmap = slack[cat]
                # pick the donor with the largest slack that is not the same value
                viable = [(k, s) for k, s in dmap.items() if k != v and s > 0]
                if not viable:
                    donors.append((cat, None))
                else:
                    viable.sort(key=lambda t: t[1], reverse=True)
                    donors.append((cat, viable[0][0]))

            # if any category cannot supply a donor, try next best target
            if any(d is None for (_, d) in donors):
                # try next best target
                picked = False
                for alt in targets[1:]:
                    chosen = alt
                    # recompute needed/donors for alt
                    needed_inc = []
                    for cat, v in [
                        ("domains", alt[0]),
                        ("question_types", alt[1]),
                        ("sources", alt[2]),
                        ("impact_levels", alt[3]),
                    ]:
                        cell = (qmat_now.get(cat) or {}).get(v)
                        req = int(cell.get("requested", 0)) if cell else 0
                        sel = int(cell.get("selected", 0)) if cell else 0
                        if sel >= req:
                            needed_inc.append((cat, v))
                    donors = []
                    ok_alt = True
                    for cat, v in needed_inc:
                        dmap = slack[cat]
                        viable = [(k, s) for k, s in dmap.items() if k != v and s > 0]
                        if not viable:
                            ok_alt = False
                            break
                        viable.sort(key=lambda t: t[1], reverse=True)
                        donors.append((cat, viable[0][0]))
                    if ok_alt:
                        picked = True
                        break
                if not picked:
                    # no realizable target combo — stop planning
                    break

            # build unit deltas
            unit_inc = {
                "domains": {},
                "question_types": {},
                "sources": {},
                "impact_levels": {},
            }
            unit_dec = {
                "domains": {},
                "question_types": {},
                "sources": {},
                "impact_levels": {},
            }
            for (cat, v), (_, donor) in zip(needed_inc, donors):
                if donor is None:
                    continue
                unit_inc[cat][v] = unit_inc[cat].get(v, 0) + 1
                unit_dec[cat][donor] = unit_dec[cat].get(donor, 0) + 1

            # apply unit deltas to working quotas
            def apply_delta(
                qmap: dict[str, int], inc: dict[str, int], dec: dict[str, int]
            ) -> dict[str, int]:
                qmap = dict(qmap)
                for k, n in (dec or {}).items():
                    qmap[k] = max(0, int(qmap.get(k, 0)) - int(n))
                for k, n in (inc or {}).items():
                    qmap[k] = int(qmap.get(k, 0)) + int(n)
                return qmap

            q_work_domains = apply_delta(
                q_work_domains, unit_inc["domains"], unit_dec["domains"]
            )
            q_work_types = apply_delta(
                q_work_types, unit_inc["question_types"], unit_dec["question_types"]
            )
            q_work_sources = apply_delta(
                q_work_sources, unit_inc["sources"], unit_dec["sources"]
            )
            q_work_imp = apply_delta(
                q_work_imp, unit_inc["impact_levels"], unit_dec["impact_levels"]
            )

            # verify progress with strict selection
            sel_after, qmat_after, _, _, _ = strict_select(
                q_work_types, q_work_domains, q_work_sources, q_work_imp
            )
            if sel_after <= sel_now:
                # roll back this step (should be rare), abort planning
                break

            # commit deltas to global plan and update quotas for next loop
            def bump_quotas(qmat: dict, inc: dict, dec: dict):
                for cat in inc:
                    for k, n in (inc[cat] or {}).items():
                        quotas[cat].setdefault(
                            k,
                            {
                                "requested": 0,
                                "available": 0,
                                "selected": 0,
                                "shortfall": 0,
                            },
                        )
                        quotas[cat][k]["requested"] += n
                for cat in dec:
                    for k, n in (dec[cat] or {}).items():
                        quotas[cat].setdefault(
                            k,
                            {
                                "requested": 0,
                                "available": 0,
                                "selected": 0,
                                "shortfall": 0,
                            },
                        )
                        quotas[cat][k]["requested"] = max(
                            0, quotas[cat][k]["requested"] - n
                        )

            bump_quotas(quotas, unit_inc, unit_dec)

            for cat in unit_inc:
                for k, n in unit_inc[cat].items():
                    add_delta(INC, cat, k, n)
            for cat in unit_dec:
                for k, n in unit_dec[cat].items():
                    add_delta(DEC, cat, k, n)

            steps += 1

            if sel_after >= total_needed:
                # feasible — finalize
                selected_total = sel_after
                quotas = qmat_after
                missing_total = 0
                feasible = True
                break

            # update working state and quotas for next iteration
            selected_total = sel_after
            quotas = qmat_after

        # finalize suggested_plan if feasible
        suggested_plan = None
        if feasible:
            # human summary by dimension
            def summarize(cat: str, inc: dict[str, int], dec: dict[str, int]) -> str:
                inc_items = sorted((inc or {}).items(), key=lambda x: -x[1])
                dec_items = sorted((dec or {}).items(), key=lambda x: -x[1])
                parts = []
                if dec_items:
                    parts.append(", ".join([f"{k} −{n}" for k, n in dec_items]))
                if inc_items:
                    parts.append(", ".join([f"{k} +{n}" for k, n in inc_items]))
                if not parts:
                    return f"{cat.split('_')[0].capitalize()}: no change"
                return f"{cat.split('_')[0].capitalize()}: " + "; ".join(parts)

            human_lines = [
                summarize("domains", INC["domains"], DEC["domains"]),
                summarize(
                    "question_types", INC["question_types"], DEC["question_types"]
                ),
                summarize("sources", INC["sources"], DEC["sources"]),
                summarize("impact_levels", INC["impact_levels"], DEC["impact_levels"]),
            ]
            human_summary = f"Apply {steps} swap(s): " + " | ".join(human_lines)

            # Correctly reflect post-fix counts
            suggested_plan = {
                "will_resolve": True,
                "steps": steps,
                "increments": INC,
                "decrements": DEC,
                "human_summary": human_summary,
                "quotas_after": quotas,
                "feasible_after": True,
                "selected_total_after": sel_after,
                "missing_total_after": max(0, total_needed - sel_after),
            }

        # ---------- guaranteed fallback & unlockers ----------
        fallback_plan = {
            "type": "mirror_selected",
            "guaranteed": True,
            "new_total": selected_total,
            "new_quotas": {
                "domains": {
                    k: int(v.get("selected", 0))
                    for k, v in (quotas.get("domains") or {}).items()
                },
                "question_types": {
                    k: int(v.get("selected", 0))
                    for k, v in (quotas.get("question_types") or {}).items()
                },
                "sources": {
                    k: int(v.get("selected", 0))
                    for k, v in (quotas.get("sources") or {}).items()
                },
                "impact_levels": {
                    k: int(v.get("selected", 0))
                    for k, v in (quotas.get("impact_levels") or {}).items()
                },
            },
        }

        unlockers = {}

        def strict_select_on(cands, qt, qd, qs, qi):
            selected_ids: set[str] = set()
            counts = {
                "type": {k: 0 for k in qt},
                "domain": {k: 0 for k in qd},
                "source": {k: 0 for k in qs},
                "impact": {k: 0 for k in qi},
            }
            enforce = set()
            if sum((qt or {}).values()) > 0:
                enforce.add("type")
            if sum((qd or {}).values()) > 0:
                enforce.add("domain")
            if sum((qs or {}).values()) > 0:
                enforce.add("source")
            if sum((qi or {}).values()) > 0:
                enforce.add("impact")
            for q in cands:
                if len(selected_ids) >= total_needed:
                    break
                qid = str(q["_id"])
                if qid in selected_ids:
                    continue
                ok = True
                t = q.get("question_type")
                d = q.get("domain")
                s = q.get("source")
                im = q.get("impact_level")
                if "type" in enforce and (
                    not t or t not in qt or counts["type"][t] >= qt[t]
                ):
                    ok = False
                if (
                    ok
                    and "domain" in enforce
                    and (not d or d not in qd or counts["domain"][d] >= qd[d])
                ):
                    ok = False
                if (
                    ok
                    and "source" in enforce
                    and (not s or s not in qs or counts["source"][s] >= qs[s])
                ):
                    ok = False
                if (
                    ok
                    and "impact" in enforce
                    and (not im or im not in qi or counts["impact"][im] >= qi[im])
                ):
                    ok = False
                if ok:
                    selected_ids.add(qid)
                    if "type" in enforce:
                        counts["type"][t] += 1
                    if "domain" in enforce:
                        counts["domain"][d] += 1
                    if "source" in enforce:
                        counts["source"][s] += 1
                    if "impact" in enforce:
                        counts["impact"][im] += 1
            return len(selected_ids)

        # author -> All
        if selected_author != "All":
            bf2 = dict(base_filter)
            bf2.pop("owner", None)
            c2 = await questions_collection.find(bf2, projection).to_list(length=None)
            c2.sort(key=lambda q: _ord(q.get("_id")))
            sel2 = strict_select_on(c2, q_types, q_domains, q_sources, q_imp)
            unlockers["author_all"] = {
                "will_resolve": sel2 >= total_needed,
                "selected_total_after": sel2,
            }
        # topics -> All
        if selected_topic:
            bf3 = dict(base_filter)
            bf3.pop("topic", None)
            c3 = await questions_collection.find(bf3, projection).to_list(length=None)
            c3.sort(key=lambda q: _ord(q.get("_id")))
            sel3 = strict_select_on(c3, q_types, q_domains, q_sources, q_imp)
            unlockers["topics_all"] = {
                "will_resolve": sel3 >= total_needed,
                "selected_total_after": sel3,
            }

        # drop dimension candidates
        drop_map = {}
        sel4 = strict_select_on(candidates, q_types, {}, q_sources, q_imp)
        drop_map["domains"] = {
            "will_resolve": sel4 >= total_needed,
            "selected_total_after": sel4,
        }
        sel5 = strict_select_on(candidates, {}, q_domains, q_sources, q_imp)
        drop_map["question_types"] = {
            "will_resolve": sel5 >= total_needed,
            "selected_total_after": sel5,
        }
        sel6 = strict_select_on(candidates, q_types, q_domains, {}, q_imp)
        drop_map["sources"] = {
            "will_resolve": sel6 >= total_needed,
            "selected_total_after": sel6,
        }
        sel7 = strict_select_on(candidates, q_types, q_domains, q_sources, {})
        drop_map["impact_levels"] = {
            "will_resolve": sel7 >= total_needed,
            "selected_total_after": sel7,
        }
        unlockers["drop_dimension"] = drop_map

        result = {
            "feasible": feasible,
            "total_needed": total_needed,
            "selected_total": selected_total,
            "missing_total": max(0, total_needed - selected_total),
            "quotas": quotas,
            "suggested_plan": suggested_plan,
            "fallback_plan": fallback_plan,
            "unlockers": unlockers,
            "diagnostics": diagnostics,
        }

        await _safe_redis_set(
            cache_key, json.dumps(result, separators=(",", ":")), ex=TTL
        )
        return result
