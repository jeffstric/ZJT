"""
本站公告 API 路由

用户侧（/api/announcements）：登录用户拉取公告列表/未读数、标记已读。
管理侧（/api/admin/announcements）：管理员创建/编辑/发布/下线/删除公告、上传公告图片。

与 api/notifications.py（远程拉取的全局公告轮询）相互独立，互不影响。
"""
import asyncio
import os
import logging
from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, Header, Path, Query, UploadFile, File
from pydantic import BaseModel

from config.constant import AnnouncementConstants
from model.users import UsersModel
from model.user_tokens import UserTokensModel
from model.announcements import AnnouncementsModel, AnnouncementStatus
from services.announcement_service import AnnouncementService
from utils.project_path import get_upload_subdir, generate_upload_filename, build_upload_url

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/announcements", tags=["announcements"])
admin_router = APIRouter(prefix="/api/admin/announcements", tags=["announcements"])

# content_type -> 扩展名兜底映射（原始文件名无扩展名时使用）
_CONTENT_TYPE_EXT = {
    'image/jpeg': '.jpg',
    'image/png': '.png',
    'image/gif': '.gif',
    'image/webp': '.webp',
}


# ============ 认证辅助（同 api/notifications.py 风格） ============

def _get_current_user(auth_token: str = None) -> Optional[int]:
    """从 token 获取当前用户 ID，失败返回 None"""
    if not auth_token:
        return None
    if auth_token.startswith("Bearer "):
        auth_token = auth_token[7:]
    try:
        return UserTokensModel.get_user_id_by_token(auth_token)
    except Exception:
        return None


def _require_admin(auth_token: str = None):
    """验证管理员权限，失败抛出异常"""
    user_id = _get_current_user(auth_token)
    if not user_id:
        raise ValueError("未登录")
    user = UsersModel.get_by_id(user_id)
    if not user or user.role != 'admin':
        raise ValueError("权限不足")
    return user


# ============ 请求模型 ============

class AnnouncementCreateRequest(BaseModel):
    title: str
    content: str = ""
    link_url: Optional[str] = None
    link_text: Optional[str] = None
    images: List[str] = []
    level: str = "info"
    status: str = AnnouncementStatus.DRAFT  # draft / published
    publish_at: Optional[str] = None
    expire_at: Optional[str] = None


class AnnouncementUpdateRequest(BaseModel):
    title: str
    content: str = ""
    link_url: Optional[str] = None
    link_text: Optional[str] = None
    images: List[str] = []
    level: str = "info"
    publish_at: Optional[str] = None
    expire_at: Optional[str] = None


# ============ 用户侧接口 ============

@router.get("")
async def list_announcements(
    limit: int = Query(AnnouncementConstants.DEFAULT_LIST_LIMIT, ge=1, le=100),
    authorization: str = Header(None, alias="Authorization"),
):
    """当前用户的有效公告列表（published 且在发布窗口内，带 per-user 已读标记）"""
    try:
        user_id = await asyncio.to_thread(_get_current_user, authorization)
        if not user_id:
            return {"code": 1, "message": "未登录"}
        items = await asyncio.to_thread(AnnouncementService.list_for_user, user_id, limit)
        return {"code": 0, "data": {"items": items}}
    except Exception as e:
        logger.error(f"List announcements failed: {e}")
        return {"code": 1, "message": str(e)}


@router.get("/unread-count")
async def get_unread_count(authorization: str = Header(None, alias="Authorization")):
    """当前用户未读公告数（铃铛徽标轮询）"""
    try:
        user_id = await asyncio.to_thread(_get_current_user, authorization)
        if not user_id:
            return {"code": 1, "message": "未登录"}
        count = await asyncio.to_thread(AnnouncementService.get_unread_count, user_id)
        return {"code": 0, "data": {"count": count}}
    except Exception as e:
        logger.error(f"Get unread count failed: {e}")
        return {"code": 1, "message": str(e)}


@router.post("/read-all")
async def mark_all_read(authorization: str = Header(None, alias="Authorization")):
    """标记当前用户全部有效公告为已读"""
    try:
        user_id = await asyncio.to_thread(_get_current_user, authorization)
        if not user_id:
            return {"code": 1, "message": "未登录"}
        affected = await asyncio.to_thread(AnnouncementService.mark_all_read, user_id)
        return {"code": 0, "data": {"updated_count": affected}}
    except Exception as e:
        logger.error(f"Mark all announcements read failed: {e}")
        return {"code": 1, "message": str(e)}


@router.post("/{announcement_id}/read")
async def mark_read(
    announcement_id: int = Path(..., description="公告ID"),
    authorization: str = Header(None, alias="Authorization"),
):
    """标记单条公告为已读（当前用户）"""
    try:
        user_id = await asyncio.to_thread(_get_current_user, authorization)
        if not user_id:
            return {"code": 1, "message": "未登录"}
        result = await asyncio.to_thread(AnnouncementService.mark_read, user_id, announcement_id)
        if not result.get('success'):
            return {"code": 1, "message": result.get('message', '标记失败')}
        return {"code": 0, "data": {"updated": True}}
    except Exception as e:
        logger.error(f"Mark announcement {announcement_id} read failed: {e}")
        return {"code": 1, "message": str(e)}


# ============ 管理侧接口 ============

@admin_router.post("")
async def admin_create_announcement(
    req: AnnouncementCreateRequest,
    authorization: str = Header(None, alias="Authorization"),
):
    """管理员创建公告（可直接以 published 状态发布）"""
    try:
        admin = await asyncio.to_thread(_require_admin, authorization)
        result = await asyncio.to_thread(AnnouncementService.create, admin.id, req.model_dump())
        if not result.get('success'):
            return {"code": 1, "message": result.get('message', '创建失败')}
        return {"code": 0, "data": {"id": result.get('id')}}
    except ValueError as e:
        return {"code": 1, "message": str(e)}
    except Exception as e:
        logger.error(f"Admin create announcement failed: {e}")
        return {"code": 1, "message": str(e)}


@admin_router.get("/list")
async def admin_list_announcements(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    authorization: str = Header(None, alias="Authorization"),
):
    """管理员分页查看全部公告（含草稿/已下线）"""
    try:
        await asyncio.to_thread(_require_admin, authorization)
        result = await asyncio.to_thread(
            AnnouncementsModel.list_admin, page=page, page_size=page_size
        )
        return {
            "code": 0,
            "data": {
                "items": [item.to_dict() for item in result["items"]],
                "total": result["total"],
                "page": result["page"],
                "page_size": result["page_size"],
            }
        }
    except ValueError as e:
        return {"code": 1, "message": str(e)}
    except Exception as e:
        logger.error(f"Admin list announcements failed: {e}")
        return {"code": 1, "message": str(e)}


@admin_router.put("/{announcement_id}")
async def admin_update_announcement(
    announcement_id: int,
    req: AnnouncementUpdateRequest,
    authorization: str = Header(None, alias="Authorization"),
):
    """管理员编辑公告内容（状态走 publish/offline 接口）"""
    try:
        await asyncio.to_thread(_require_admin, authorization)
        result = await asyncio.to_thread(
            AnnouncementService.update, announcement_id, req.model_dump()
        )
        if not result.get('success'):
            return {"code": 1, "message": result.get('message', '更新失败')}
        return {"code": 0, "data": {"updated": True}}
    except ValueError as e:
        return {"code": 1, "message": str(e)}
    except Exception as e:
        logger.error(f"Admin update announcement {announcement_id} failed: {e}")
        return {"code": 1, "message": str(e)}


@admin_router.post("/{announcement_id}/publish")
async def admin_publish_announcement(
    announcement_id: int,
    authorization: str = Header(None, alias="Authorization"),
):
    """管理员发布公告（draft/offline -> published）"""
    return await _admin_set_status(announcement_id, AnnouncementStatus.PUBLISHED, authorization)


@admin_router.post("/{announcement_id}/offline")
async def admin_offline_announcement(
    announcement_id: int,
    authorization: str = Header(None, alias="Authorization"),
):
    """管理员下线公告（published -> offline）"""
    return await _admin_set_status(announcement_id, AnnouncementStatus.OFFLINE, authorization)


@admin_router.delete("/{announcement_id}")
async def admin_delete_announcement(
    announcement_id: int,
    authorization: str = Header(None, alias="Authorization"),
):
    """管理员删除公告（级联清理已读记录）"""
    try:
        admin = await asyncio.to_thread(_require_admin, authorization)
        result = await asyncio.to_thread(
            AnnouncementService.delete, admin.id, announcement_id
        )
        if not result.get('success'):
            return {"code": 1, "message": result.get('message', '删除失败')}
        return {"code": 0, "data": {"deleted": True}}
    except ValueError as e:
        return {"code": 1, "message": str(e)}
    except Exception as e:
        logger.error(f"Admin delete announcement {announcement_id} failed: {e}")
        return {"code": 1, "message": str(e)}


@admin_router.post("/upload-image")
async def admin_upload_announcement_image(
    file: UploadFile = File(..., description="公告图片（jpg/png/gif/webp，≤10MB）"),
    authorization: str = Header(None, alias="Authorization"),
):
    """管理员上传公告图片，保存到 upload/announcement/<yyyyMM>/，返回相对 URL"""
    try:
        await asyncio.to_thread(_require_admin, authorization)
        url = await asyncio.to_thread(_save_announcement_image, file)
        return {"code": 0, "data": {"url": url}}
    except ValueError as e:
        return {"code": 1, "message": str(e)}
    except Exception as e:
        logger.error(f"Admin upload announcement image failed: {e}")
        return {"code": 1, "message": str(e)}


async def _admin_set_status(announcement_id: int, status: str, authorization: str):
    """管理员公告状态变更公共处理"""
    try:
        await asyncio.to_thread(_require_admin, authorization)
        result = await asyncio.to_thread(
            AnnouncementService.update_status, announcement_id, status
        )
        if not result.get('success'):
            return {"code": 1, "message": result.get('message', '状态更新失败')}
        return {"code": 0, "data": {"status": status}}
    except ValueError as e:
        return {"code": 1, "message": str(e)}
    except Exception as e:
        logger.error(f"Admin set announcement {announcement_id} status {status} failed: {e}")
        return {"code": 1, "message": str(e)}


def _save_announcement_image(file: UploadFile) -> str:
    """同步保存公告图片到 upload/announcement/<yyyyMM>/，返回相对 URL（/upload/...）"""
    content_type = (file.content_type or "").lower()
    if not content_type.startswith("image/"):
        raise ValueError("仅支持图片文件")

    original_name = file.filename or "image"
    ext = os.path.splitext(original_name)[1].lower()
    if ext not in AnnouncementConstants.ALLOWED_IMAGE_EXTS:
        ext = _CONTENT_TYPE_EXT.get(content_type, '')
    if ext not in AnnouncementConstants.ALLOWED_IMAGE_EXTS:
        raise ValueError("不支持的图片格式，仅支持 jpg/png/gif/webp")

    content = file.file.read()
    if not content:
        raise ValueError("图片内容为空")
    if len(content) > AnnouncementConstants.MAX_IMAGE_SIZE:
        raise ValueError("图片大小超过限制（10MB）")

    date_dir = datetime.now().strftime("%Y%m")
    asset_dir = get_upload_subdir(AnnouncementConstants.UPLOAD_CATEGORY, date_dir)
    info = generate_upload_filename(AnnouncementConstants.UPLOAD_CATEGORY, ext)
    file_path = os.path.join(asset_dir, info.filename)
    with open(file_path, "wb") as f:
        f.write(content)

    # 相对 URL：同源页面直接可用，且自动享受 /upload/ CDN 中间件加速
    return build_upload_url(AnnouncementConstants.UPLOAD_CATEGORY, date_dir, info.filename)
