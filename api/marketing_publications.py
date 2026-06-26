"""Marketing publication and inspiration APIs."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Header, HTTPException, Path as ApiPath, Query
from pydantic import BaseModel, Field

from config.constant import AI_TOOL_STATUS_COMPLETED
from model.ai_tools import AIToolsModel
from model.marketing_publications import (
    MarketingPublicationModel,
    PublicationStatus,
)
from services.marketing_publication_asset_service import (
    MarketingPublicationAssetService,
    PublicationAssetError,
)

router = APIRouter(tags=["marketing-publications"])


class CreatePublicationRequest(BaseModel):
    ai_tool_id: int
    title: Optional[str] = None
    description: Optional[str] = None
    tags: List[str] = Field(default_factory=list)


class ReviewPublicationRequest(BaseModel):
    review_note: Optional[str] = None


def _request_user_id(user_id: Optional[int]) -> int:
    if user_id is None:
        raise HTTPException(status_code=401, detail="login required")
    return int(user_id)


def _default_title(prompt: Optional[str]) -> str:
    text = (prompt or "").strip()
    return text[:30] or "AI creation"


def _infer_media_type(result_url: Optional[str]) -> str:
    ext = Path(urlparse(result_url or "").path).suffix.lower()
    return "video" if ext in (".mp4", ".webm", ".mov", ".avi", ".mkv") else "image"


def _as_url_list(value: Any) -> List[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item]
    return [part.strip() for part in str(value).split(",") if part.strip()]


def _build_template_media(params: Dict[str, Any], result_url: Optional[str]) -> List[Dict[str, str]]:
    """Return input media for remix, never the generated output itself."""
    result = result_url or params.get("result_url")
    media: List[Dict[str, str]] = []

    for url in _as_url_list(params.get("reference_images")):
        if url == result:
            continue
        media.append({"type": "image", "serverUrl": url, "thumbnailUrl": url})

    for url in _as_url_list(params.get("video_urls")):
        if url == result:
            continue
        media.append({"type": "video", "serverUrl": url, "thumbnailUrl": url})

    return media


@router.post("/api/marketing-publications")
async def create_marketing_publication(
    request: CreatePublicationRequest,
    user_id: int = Header(None, alias="X-User-Id"),
):
    owner_user_id = _request_user_id(user_id)
    ai_tool = AIToolsModel.get_by_id(request.ai_tool_id)
    if not ai_tool:
        raise HTTPException(status_code=404, detail="ai tool not found")
    if int(ai_tool.user_id) != owner_user_id:
        raise HTTPException(status_code=403, detail="no permission to publish this work")
    if ai_tool.status != AI_TOOL_STATUS_COMPLETED or not ai_tool.result_url:
        raise HTTPException(status_code=400, detail="ai tool not completed")

    active = MarketingPublicationModel.get_active_by_ai_tool_id(ai_tool.id)
    if active:
        raise HTTPException(status_code=400, detail="this work already has an active publication")

    title = (request.title or _default_title(ai_tool.prompt)).strip()[:255]
    media_type = _infer_media_type(ai_tool.result_url)
    publication_id = MarketingPublicationModel.create_pending(
        ai_tool_id=ai_tool.id,
        owner_user_id=owner_user_id,
        media_type=media_type,
        title=title,
        description=request.description,
        tags=[tag.strip() for tag in request.tags if tag and tag.strip()],
        result_url=None,
        cover_url=None,
        prompt_snapshot=ai_tool.prompt,
        params_snapshot={},
    )

    try:
        promoted = MarketingPublicationAssetService.promote_assets(ai_tool, publication_id)
    except PublicationAssetError as exc:
        MarketingPublicationModel.cancel(publication_id, owner_user_id)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    MarketingPublicationModel.update_assets(
        publication_id=publication_id,
        result_url=promoted["result_url"],
        cover_url=promoted["cover_url"],
        params_snapshot=promoted["params_snapshot"],
    )
    publication = MarketingPublicationModel.get_by_id(publication_id)
    return {"success": True, "data": publication.to_dict() if publication else {"id": publication_id, "status": PublicationStatus.PENDING}}


@router.get("/api/marketing-publications/my")
async def list_my_marketing_publications(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user_id: int = Header(None, alias="X-User-Id"),
):
    owner_user_id = _request_user_id(user_id)
    return {
        "success": True,
        "data": MarketingPublicationModel.list_by_owner(owner_user_id, page=page, page_size=page_size),
    }


@router.post("/api/marketing-publications/{publication_id}/cancel")
async def cancel_marketing_publication(
    publication_id: int = ApiPath(...),
    user_id: int = Header(None, alias="X-User-Id"),
):
    owner_user_id = _request_user_id(user_id)
    affected = MarketingPublicationModel.cancel(publication_id, owner_user_id)
    if affected <= 0:
        raise HTTPException(status_code=400, detail="publication cannot be cancelled")
    return {"success": True}


@router.get("/api/marketing-inspirations")
async def list_marketing_inspirations(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    media_type: Optional[str] = Query(None),
):
    if media_type and media_type not in ("image", "video"):
        raise HTTPException(status_code=400, detail="invalid media_type")
    return {
        "success": True,
        "data": MarketingPublicationModel.list_public(page=page, page_size=page_size, media_type=media_type),
    }


@router.get("/api/marketing-inspirations/{publication_id}/template")
async def get_marketing_inspiration_template(publication_id: int = ApiPath(...)):
    publication = MarketingPublicationModel.get_by_id(publication_id)
    if not publication or publication.status != PublicationStatus.APPROVED:
        raise HTTPException(status_code=404, detail="inspiration not found")
    data = publication.to_dict()
    params = data.get("params_snapshot") or {}
    return {
        "success": True,
        "data": {
            "id": publication.id,
            "prompt": publication.prompt_snapshot,
            "params": params,
            "media": _build_template_media(params, getattr(publication, "result_url", None)),
        },
    }


@router.post("/api/marketing-inspirations/{publication_id}/remix-count")
async def increment_marketing_inspiration_remix(publication_id: int = ApiPath(...)):
    MarketingPublicationModel.increment_remix_count(publication_id)
    return {"success": True}


@router.get("/api/admin/marketing-publications")
async def admin_list_marketing_publications(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None),
    media_type: Optional[str] = Query(None),
    auth_token: str = Header(None, alias="Authorization"),
):
    from api.admin import require_admin

    await require_admin(auth_token)
    return {
        "code": 0,
        "data": MarketingPublicationModel.list_admin(
            page=page,
            page_size=page_size,
            status=status,
            media_type=media_type,
        ),
    }


async def _admin_review(publication_id: int, status: str, request: ReviewPublicationRequest, auth_token: str):
    from api.admin import require_admin

    admin = await require_admin(auth_token)
    publication = MarketingPublicationModel.get_by_id(publication_id)
    if not publication:
        raise HTTPException(status_code=404, detail="publication not found")
    MarketingPublicationModel.update_review_status(
        publication_id=publication_id,
        status=status,
        reviewer_user_id=admin.id,
        review_note=request.review_note,
    )
    return {"code": 0, "message": "success"}


@router.post("/api/admin/marketing-publications/{publication_id}/approve")
async def admin_approve_marketing_publication(
    request: ReviewPublicationRequest,
    publication_id: int = ApiPath(...),
    auth_token: str = Header(None, alias="Authorization"),
):
    return await _admin_review(publication_id, PublicationStatus.APPROVED, request, auth_token)


@router.post("/api/admin/marketing-publications/{publication_id}/reject")
async def admin_reject_marketing_publication(
    request: ReviewPublicationRequest,
    publication_id: int = ApiPath(...),
    auth_token: str = Header(None, alias="Authorization"),
):
    return await _admin_review(publication_id, PublicationStatus.REJECTED, request, auth_token)


@router.post("/api/admin/marketing-publications/{publication_id}/hide")
async def admin_hide_marketing_publication(
    request: ReviewPublicationRequest,
    publication_id: int = ApiPath(...),
    auth_token: str = Header(None, alias="Authorization"),
):
    return await _admin_review(publication_id, PublicationStatus.HIDDEN, request, auth_token)
