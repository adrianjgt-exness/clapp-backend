from fastapi import APIRouter, HTTPException, Query, status, Body
from typing import Any

from config import logger
from modules.test_templates.model import (
    TestTemplateCreate,
    TestTemplateInDB,
    TestTemplateUpdate,
    TemplatePreviewResponse,
)
from modules.test_templates.service import TestTemplateService

router = APIRouter(prefix="/tests-templates", tags=["Test Templates"])


@router.get("", response_model=dict[str, list[TestTemplateInDB]])
async def get_test_templates(user_id: str | None = Query(None)):
    """
    Retrieves all common templates, and private templates for the given user_id.
    """
    try:
        templates = await TestTemplateService.get_templates(user_id)
        return templates
    except Exception as e:
        logger.error(f"Error getting all templates: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve templates.",
        )


@router.post("", status_code=status.HTTP_201_CREATED, response_model=dict)
async def create_template(template_data: TestTemplateCreate):
    """
    Creates a new test template.
    """
    try:
        template_id = await TestTemplateService.create_template(template_data)
        return {"templateId": template_id, "message": "Template created successfully"}
    except Exception as e:
        logger.error(f"Error creating template: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create template.",
        )


@router.get("/{template_id}", response_model=TestTemplateInDB)
async def get_template_by_id(template_id: str):
    """
    Retrieves a single template by its ID.
    """
    try:
        template = await TestTemplateService.get_template_by_id(template_id)
        if not template:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Template not found"
            )
        return template
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Error getting template {template_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve template.",
        )


@router.put("/{template_id}", status_code=status.HTTP_200_OK, response_model=dict)
async def update_template(template_id: str, template_data: TestTemplateUpdate):
    """
    Updates an existing template.
    """
    try:
        success = await TestTemplateService.update_template(template_id, template_data)
        if not success:
            logger.warning(f"Update for template {template_id} resulted in no changes.")
        return {"message": "Template updated successfully"}
    except Exception as e:
        logger.error(f"Error updating template {template_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update template.",
        )


@router.delete("/{template_id}", status_code=status.HTTP_200_OK, response_model=dict)
async def delete_template(template_id: str):
    """
    Deletes a template by its ID.
    """
    try:
        success = await TestTemplateService.delete_template(template_id)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Template not found"
            )
        return {"message": "Template deleted successfully."}
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Error deleting template {template_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete template.",
        )


# ----------------------- Preview (accepts BOTH shapes) -----------------------


def _to_int(n: Any) -> int:
    try:
        v = int(n)
        return v if v >= 0 else 0
    except Exception:
        return 0


def _to_int_map(obj: dict[str, Any] | None) -> dict[str, int]:
    out: dict[str, int] = {}
    for k, v in (obj or {}).items():
        out[str(k)] = _to_int(v)
    return out


def _normalize_preview_body(body: dict[str, Any]) -> dict[str, Any]:
    """
    Normalize incoming request body to the legacy snake_case shape expected by
    TestTemplateService.preview_template_strict().
    Supports:
      - Compact: { total, topics, owner?, quotas{question_types,domains,sources,impact_levels} }
      - Legacy:  { total_questions, selected_topic, selected_author, question_types, domains, sources, impact_levels }
    """
    # If compact shape, convert to legacy
    if "total" in body or "quotas" in body or "topics" in body:
        quotas = body.get("quotas") or {}
        owner = body.get("owner")
        return {
            "total_questions": _to_int(body.get("total")),
            "selected_topic": list(body.get("topics") or []),
            "selected_author": (str(owner) if owner and owner != "All" else "All"),
            "question_types": _to_int_map(quotas.get("question_types")),
            "domains": _to_int_map(quotas.get("domains")),
            "sources": _to_int_map(quotas.get("sources")),
            "impact_levels": _to_int_map(quotas.get("impact_levels")),
        }

    # Otherwise assume legacy and coerce types
    return {
        "total_questions": _to_int(
            body.get("total_questions")
            if "total_questions" in body
            else body.get("total")
        ),
        "selected_topic": list(body.get("selected_topic") or []),
        "selected_author": (
            str(body.get("selected_author"))
            if body.get("selected_author")
            not in (
                None,
                "",
            )
            else "All"
        ),
        "question_types": _to_int_map(body.get("question_types")),
        "domains": _to_int_map(body.get("domains")),
        "sources": _to_int_map(body.get("sources")),
        "impact_levels": _to_int_map(body.get("impact_levels")),
    }


@router.post("/preview", response_model=TemplatePreviewResponse)
async def preview_template(body: dict[str, Any] = Body(...)):
    """
    Strict, no-relaxation feasibility preview for a template.
    Accepts BOTH compact and legacy payloads. Normalizes to legacy shape
    before calling the service, preventing 422 from Pydantic request models.
    """
    try:
        payload = _normalize_preview_body(body)
        data = await TestTemplateService.preview_template_strict(payload)
        return TemplatePreviewResponse(**data)
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Error previewing template: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to preview template.",
        )
