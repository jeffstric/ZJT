"""
AIGC 显式标识（明水印）管理接口

法规依据：《人工智能生成合成内容标识办法》
- 第 4/17 条：提供显著标识功能（L2：普通图片/视频结果卡按钮按需烧录）
- 第 9 条：用户申请不添加显式标识的，须先通过用户协议明确义务责任，并留痕 >= 6 个月
  （本路由 /explicit-optout 即第 9 条的申请入口 + 留痕写入）

烧录实现在 utils/aigc_explicit_marker.py；烧录会重编码丢原元数据，
内部统一以 extra_fields={'ExplicitLabel':'1'} 重写隐式标识。
"""
import asyncio
import json
import logging
import os
from typing import Optional

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel, Field

from perseids_server.utils.auth_identity import get_auth_user_id
from perseids_server.utils.permission import require_permission
from model.ai_tools import AIToolsModel
from model.media_file_mapping import MediaFileMappingModel
from model.aigc_explicit_opt_out import (
    AigcExplicitOptOutModel,
    OPT_OUT_SOURCE_CHAT_CARD,
    OPT_OUT_SOURCE_USER_SETTINGS,
    OPT_OUT_ACTION_OPT_OUT,
    OPT_OUT_ACTION_RESUME,
)
from utils.aigc_explicit_marker import burn_explicit_label
from utils.project_path import resolve_upload_url_to_local_path, get_project_root
from utils.cdn_util import CDNUtil
from pathlib import Path

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/api/aigc', tags=['aigc'])


class ExplicitLabelRequest(BaseModel):
    ai_tool_id: int = Field(..., description="任务 ID（ai_tools.id）")


class ExplicitOptOutRequest(BaseModel):
    ai_tool_id: Optional[int] = Field(None, description="任务 ID（数字人等任务级申请）")
    scope: Optional[str] = Field(None, description="留空=任务级；'user'=用户级（全局生效）")
    action: Optional[str] = Field('opt_out', description="opt_out=申请关闭 / resume=恢复添加（用户设置开关用）")
    reason: Optional[str] = Field(None, max_length=500, description="申请原因（选填）")


def _media_kind_from_url(url: str) -> str:
    ext = os.path.splitext((url or '').split('?')[0])[1].lower()
    if ext in ('.mp4', '.mov', '.webm', '.avi', '.mkv'):
        return 'video'
    if ext in ('.mp3', '.wav', '.m4a', '.aac', '.flac'):
        return 'audio'
    return 'image'


def _tool_owned_by(tool, user_id: int) -> bool:
    """任务必须属于当前登录用户。属主不符与不存在一样，避免用顺序 id 探出别人的任务。"""
    owner = getattr(tool, 'user_id', None)
    if owner is None:
        return False
    try:
        return int(owner) == int(user_id)
    except (TypeError, ValueError):
        return False


def _upload_rel_path(local_path: str) -> Optional[str]:
    """本地绝对路径 → /upload/ 相对路径（用于 media_file_mapping 查询）。"""
    try:
        root = Path(get_project_root()).resolve()
        rel = Path(local_path).resolve().relative_to(root)
        return '/' + rel.as_posix()
    except (ValueError, OSError):
        return None


@router.post('/explicit-label')
@require_permission("aigc:explicit_label")
async def add_explicit_label(request: Request, body: ExplicitLabelRequest):
    """为任务产物烧录显式标识（L2 按需入口）。

    视频/音频重编码可能耗时较长（大视频数分钟），前端按钮需 loading 提示。
    烧录后自动重传 CDN（mapping 存在时），返回最新 result_url。
    """
    user_id = get_auth_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="登录状态失效，请重新登录")
    user_id = int(user_id)

    tool = await asyncio.to_thread(AIToolsModel.get_by_id, body.ai_tool_id)
    if not tool or not _tool_owned_by(tool, user_id):
        raise HTTPException(status_code=404, detail="任务不存在")
    result_url = getattr(tool, 'result_url', None) or ''
    if not result_url.startswith(('/upload/', 'http://', 'https://')):
        raise HTTPException(status_code=400, detail="该任务产物无可烧录的本地文件")

    local_path = await asyncio.to_thread(resolve_upload_url_to_local_path, result_url)
    if not local_path or not os.path.isfile(local_path):
        raise HTTPException(status_code=404, detail="产物文件不存在或已清理")

    produce_id = str(body.ai_tool_id)
    ok = await asyncio.to_thread(
        burn_explicit_label, local_path, produce_id, None, user_id)
    if not ok:
        raise HTTPException(status_code=500, detail="显式标识烧录失败，请稍后重试")

    # 烧录后本地文件已变更：重传 CDN 覆盖旧对象（mapping 存在且已上云时）
    upload_rel = await asyncio.to_thread(_upload_rel_path, local_path)
    if upload_rel:
        mapping = await asyncio.to_thread(MediaFileMappingModel.get_by_local_path,
                                          upload_rel.lstrip('/'))
        if mapping and mapping.cloud_path:
            try:
                CDNUtil.trigger_cdn_upload(mapping.id, upload_rel.lstrip('/'))
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[aigc] 烧录后 CDN 重传触发失败 ai_tool={body.ai_tool_id}: {e}")

    logger.info(f"[aigc] 显式标识烧录完成 ai_tool={body.ai_tool_id} user={user_id} url={result_url[:100]}")
    return {'success': True, 'result_url': result_url,
            'message': '已在内容中添加 AI 生成标识'}


@router.post('/explicit-optout')
@require_permission("aigc:explicit_label")
async def request_explicit_opt_out(request: Request, body: ExplicitOptOutRequest):
    """申请不添加显式标识（标识办法第 9 条）。

    ⚠️ 前置条件：前端确认弹窗须展示协议义务内容（发布 AI 内容须主动声明、
    不得恶意删除标识等，对应第 8/10 条）并取得用户确认后再调用本接口。
    申请记录（提供对象信息）依法留存 >= 6 个月。
    """
    user_id = get_auth_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="登录状态失效，请重新登录")
    user_id = int(user_id)

    if not body.ai_tool_id and (body.scope or '') != 'user':
        raise HTTPException(status_code=400, detail="需指定 ai_tool_id 或 scope='user'")

    ai_tool_id = body.ai_tool_id
    produce_id = None
    content_type = None
    if ai_tool_id:
        tool = await asyncio.to_thread(AIToolsModel.get_by_id, ai_tool_id)
        if not tool or not _tool_owned_by(tool, user_id):
            raise HTTPException(status_code=404, detail="任务不存在")
        produce_id = str(ai_tool_id)
        content_type = _media_kind_from_url(getattr(tool, 'result_url', '') or '')

    ip = (request.client.host if request.client else None)
    user_agent = request.headers.get('user-agent')
    action = body.action if body.action in (OPT_OUT_ACTION_OPT_OUT, OPT_OUT_ACTION_RESUME) \
        else OPT_OUT_ACTION_OPT_OUT
    source = OPT_OUT_SOURCE_USER_SETTINGS if (body.scope or '') == 'user' \
        else OPT_OUT_SOURCE_CHAT_CARD
    detail = json.dumps({'reason': body.reason, 'scope': body.scope}, ensure_ascii=False)

    await asyncio.to_thread(
        AigcExplicitOptOutModel.create,
        user_id, ai_tool_id, produce_id, content_type,
        source, ip, user_agent, detail, action,
    )
    user_scope = (body.scope or '') == 'user'
    if action == OPT_OUT_ACTION_RESUME:
        logger.info(f"[aigc] 显式标识恢复添加 user={user_id} ai_tool={ai_tool_id} scope={body.scope}")
        if user_scope:
            message = '已恢复：后续内容将重新添加 AI 生成标识'
        else:
            message = '已恢复：该任务的内容将重新添加 AI 生成标识'
        return {'success': True, 'opt_out': False, 'message': message}
    logger.info(f"[aigc] 显式标识关闭申请留痕 user={user_id} ai_tool={ai_tool_id} scope={body.scope}")
    if user_scope:
        message = ('已记录申请：后续生成的图片、视频、数字人、语音合成不再添加画面/音频提示，'
                   '文件元数据标识将保留')
    else:
        message = '已记录申请：该任务不再添加画面/音频提示，文件元数据标识将保留'
    return {'success': True, 'opt_out': True, 'message': message}


@router.get('/explicit-optout/status')
@require_permission("aigc:explicit_label")
async def get_explicit_optout_status(request: Request):
    """查询当前用户的明水印全局关闭状态（用户设置开关回显用）。"""
    user_id = get_auth_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="登录状态失效，请重新登录")
    opt_out = await asyncio.to_thread(AigcExplicitOptOutModel.has_opt_out_user, int(user_id))
    return {'success': True, 'opt_out': bool(opt_out)}
