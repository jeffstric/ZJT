"""
系统状态 API 路由
"""
from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse, Response
import logging
import time
from typing import Optional, Tuple

import httpx

from model.users import UsersModel
from model.user_tokens import UserTokensModel
from config.unified_config import UnifiedConfigRegistry
from config.config_util import get_config_value, get_dynamic_config_value
from config.version import get_app_version
from config.strategy.edition_strategy import IS_COMMUNITY_EDITION
from config.constant import Edition, ExternalLinks

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/system", tags=["system"])

# 微信群二维码代理内存缓存: (url, content, content_type, expire_at)
_wx_group_qr_cache: Optional[Tuple[str, bytes, str, float]] = None


def _get_wx_group_qr_url() -> str:
    return (
        get_config_value(
            'wx_group_guide',
            'qr_url',
            default=ExternalLinks.WX_GROUP_QR_URL,
        )
        or ExternalLinks.WX_GROUP_QR_URL
    )


def _is_wx_group_guide_enabled() -> bool:
    return bool(get_config_value('wx_group_guide', 'enabled', default=True))


@router.get("/status")
async def get_system_status():
    """
    获取系统状态
    返回系统是否已初始化（是否有用户）
    """
    try:
        total_users = UsersModel.get_total_count()
        
        return {
            "code": 0,
            "data": {
                "initialized": total_users > 0,
                "total_users": total_users
            }
        }
    except Exception as e:
        logger.error(f"Failed to get system status: {e}")
        return {
            "code": 1,
            "message": str(e)
        }


@router.get("/task-configs")
async def get_task_configs(authorization: str = Header(None)):
    """
    获取所有任务类型配置

    返回前端需要的完整配置信息，包括：
    - 任务列表（支持的比例、尺寸、时长等）
    - 分类信息
    - 供应商信息

    前端可以根据此接口动态渲染模型选择器、参数配置等组件

    支持可选的 Authorization 头。如果传入有效token，
    返回的 computing_power 将根据用户实现方偏好返回对应实现方的算力。
    """
    try:
        user_id = None
        user_prefs = {}

        # 如果传入了 Authorization 头，获取用户ID和偏好
        if authorization:
            if authorization.startswith("Bearer "):
                authorization = authorization[7:]
            user_id = UserTokensModel.get_user_id_by_token(authorization)
            if user_id:
                user_prefs = UsersModel.get_all_preferences(user_id)

        frontend_config = UnifiedConfigRegistry.get_frontend_config(user_id, user_prefs)
        return {
            "code": 0,
            "data": frontend_config
        }
    except Exception as e:
        logger.error(f"Failed to get task configs: {e}")
        return {
            "code": 1,
            "message": str(e)
        }


@router.get("/server-config")
async def get_server_config():
    """
    获取服务器公开配置

    返回前端需要的公开配置信息，如 is_local、备案号等
    """
    try:
        is_local = get_config_value('server', 'is_local', default=False)
        footer = get_config_value('server', 'footer', default={})
        version = get_app_version()
        max_image_size_mb = get_dynamic_config_value('upload', 'max_image_size_mb', default=10)
        max_video_size_mb = get_dynamic_config_value('upload', 'max_video_size_mb', default=50)
        max_video_duration_seconds = get_dynamic_config_value('upload', 'max_video_duration_seconds', default=15)
        enable_vue_error_output = get_config_value('frontend', 'enable_vue_error_output', default=False)
        email_enabled = get_dynamic_config_value('email', 'enabled', default=False)

        # 官方微信群引导（YAML 配置，默认开启）
        wx_group_guide_enabled = _is_wx_group_guide_enabled()
        wx_group_qr_url = _get_wx_group_qr_url()

        # CAPTCHA 配置（仅暴露前端需要的公开字段，不暴露 access_key_secret）
        captcha_enabled = get_dynamic_config_value('captcha', 'enabled', default=False)
        captcha_prefix = ''
        captcha_scene_id = ''
        if captcha_enabled:
            captcha_config = get_config_value('captcha', default={})
            aliyun_config = captcha_config.get('aliyun', {}) if isinstance(captcha_config, dict) else {}
            captcha_prefix = aliyun_config.get('prefix', '')
            captcha_scene_id = aliyun_config.get('scene_id', '')

        return {
            "code": 0,
            "data": {
                "is_local": is_local,
                "version": version,
                "max_image_size_mb": max_image_size_mb,
                "max_video_size_mb": max_video_size_mb,
                "max_video_duration_seconds": max_video_duration_seconds,
                "is_enterprise": not IS_COMMUNITY_EDITION,
                "shared_space": not Edition.is_space_isolated(),
                "enable_vue_error_output": enable_vue_error_output,
                "email_enabled": email_enabled,
                "captcha_enabled": captcha_enabled,
                "captcha_prefix": captcha_prefix,
                "captcha_scene_id": captcha_scene_id,
                "wx_group_guide_enabled": wx_group_guide_enabled,
                "wx_group_qr_url": wx_group_qr_url,
                # HTTPS 页面下前端应改用该同源代理路径，避免 HTTP 图被混合内容拦截
                "wx_group_qr_proxy_path": ExternalLinks.WX_GROUP_QR_PROXY_PATH,
                "footer": {
                    "copyright": footer.get('copyright', ''),
                    "icp_number": footer.get('icp_number', ''),
                    "icp_url": footer.get('icp_url', 'https://beian.miit.gov.cn/'),
                    "police_number": footer.get('police_number', ''),
                    "police_url": footer.get('police_url', '')
                }
            }
        }
    except Exception as e:
        logger.error(f"Failed to get server config: {e}")
        return {
            "code": 1,
            "message": str(e)
        }


@router.get("/wx-group-qr")
async def proxy_wx_group_qr():
    """
    代理拉取官方微信群二维码图片（同源返回）。

    用途：站点以 HTTPS 访问时，浏览器会拦截页面内的 HTTP 图片（混合内容）。
    前端在 HTTPS 下将 img src 指向本接口，由后端异步拉取远端 HTTP 图再回传。
    """
    global _wx_group_qr_cache

    if not _is_wx_group_guide_enabled():
        return JSONResponse(
            status_code=404,
            content={"code": 1, "message": "微信群引导未启用"},
        )

    qr_url = _get_wx_group_qr_url()
    if not qr_url:
        return JSONResponse(
            status_code=404,
            content={"code": 1, "message": "未配置微信群二维码地址"},
        )

    # 同源相对路径无需代理，直接 404 提示改用原路径（前端应不会请求到这里）
    if qr_url.startswith('/'):
        return JSONResponse(
            status_code=400,
            content={"code": 1, "message": "相对路径二维码请直接使用原地址，无需代理"},
        )

    now = time.time()
    cache = _wx_group_qr_cache
    if (
        cache
        and cache[0] == qr_url
        and cache[3] > now
        and cache[1]
    ):
        return Response(
            content=cache[1],
            media_type=cache[2],
            headers={"Cache-Control": f"public, max-age={ExternalLinks.WX_GROUP_QR_PROXY_CACHE_TTL}"},
        )

    timeout = httpx.Timeout(
        connect=ExternalLinks.WX_GROUP_QR_PROXY_CONNECT_TIMEOUT,
        read=ExternalLinks.WX_GROUP_QR_PROXY_READ_TIMEOUT,
        write=ExternalLinks.WX_GROUP_QR_PROXY_READ_TIMEOUT,
        pool=ExternalLinks.WX_GROUP_QR_PROXY_CONNECT_TIMEOUT,
    )
    max_bytes = ExternalLinks.WX_GROUP_QR_PROXY_MAX_BYTES

    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.get(qr_url)
            resp.raise_for_status()
            content = resp.content
            if not content:
                return JSONResponse(
                    status_code=502,
                    content={"code": 1, "message": "远程二维码内容为空"},
                )
            if len(content) > max_bytes:
                return JSONResponse(
                    status_code=502,
                    content={"code": 1, "message": "远程二维码文件过大"},
                )
            content_type = (resp.headers.get("content-type") or "image/jpeg").split(";")[0].strip()
            if not content_type.startswith("image/"):
                # 部分图床未正确返回类型，默认 jpeg
                content_type = "image/jpeg"

            _wx_group_qr_cache = (
                qr_url,
                content,
                content_type,
                now + ExternalLinks.WX_GROUP_QR_PROXY_CACHE_TTL,
            )
            return Response(
                content=content,
                media_type=content_type,
                headers={"Cache-Control": f"public, max-age={ExternalLinks.WX_GROUP_QR_PROXY_CACHE_TTL}"},
            )
    except httpx.TimeoutException:
        logger.warning(f"代理微信群二维码超时: {qr_url}")
        return JSONResponse(
            status_code=504,
            content={"code": 1, "message": "拉取二维码超时，请稍后重试"},
        )
    except httpx.HTTPError as e:
        logger.warning(f"代理微信群二维码失败: {qr_url}, err={e}")
        return JSONResponse(
            status_code=502,
            content={"code": 1, "message": "拉取二维码失败，请稍后重试"},
        )
    except Exception as e:
        logger.error(f"代理微信群二维码异常: {e}")
        return JSONResponse(
            status_code=500,
            content={"code": 1, "message": "系统异常"},
        )

