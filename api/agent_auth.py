"""Agent auth API."""
import asyncio
import time
from typing import Optional

from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from config.constant import (
    AGENT_CLI_CONNECTION_INFO_MAX_CHARS,
    AGENT_CLI_IMAGE_POLL_INTERVAL_SECONDS,
    AGENT_CLI_IMAGE_WAIT_TIMEOUT_SECONDS,
    AIToolStatus,
)
from model.user_tokens import UserTokensModel
from services.agent_auth_service import AgentAuthError, AgentAuthService
from services.agent_image_service import (
    AgentImageGenerationError,
    AgentImageGenerationService,
)

router = APIRouter(prefix="/api/agent-auth", tags=["agent-auth"])


class AgentTokenExchangeRequest(BaseModel):
    token: Optional[str] = None
    device_uuid: Optional[str] = None


class AgentImageGenerationRequest(BaseModel):
    """智能体 CLI 直接生图请求。

    connection_info：首页「智能体连接」弹窗复制的完整文本（服务端自动提取 agent_token）；
    agent_token：已有明文 agent_token 时可直接传，二者至少提供一个。
    """
    connection_info: Optional[str] = Field(
        None, max_length=AGENT_CLI_CONNECTION_INFO_MAX_CHARS,
        description="首页复制的连接信息，最长 8192 字符",
    )
    agent_token: Optional[str] = None
    prompt: str
    model: Optional[str] = Field(
        None, description="模型名/key/short_key/任务id，如 moss；缺省用用户 CLI 偏好→平台默认"
    )
    world_id: Optional[int] = Field(None, description="世界ID；缺省取用户最近更新的第一个世界")
    mode: str = Field("auto", description="auto | text_to_image | image_edit；auto 按有无参考图自动分流")
    reference_image: Optional[str] = Field(
        None, description="图生图参考图 URL，多张英文逗号分隔；有值时走图片编辑"
    )
    ratio: Optional[str] = Field(
        None, description="图片比例，如 9:16 / 16:9 / 1:1。缺省时用世界生图偏好，没有偏好则为 9:16；显式传入不会被偏好覆盖"
    )
    image_size: Optional[str] = Field(None, description="分辨率档位 1K/2K/3K/4K，按模型支持范围")
    count: Optional[int] = Field(
        None, description="生成张数 1-4。缺省时用世界生图偏好，没有偏好则为 1；显式传入不会被偏好覆盖"
    )
    wait: bool = Field(False, description="true 时同步等待生成完成（受 wait_timeout 限制）")
    wait_timeout: int = Field(
        AGENT_CLI_IMAGE_WAIT_TIMEOUT_SECONDS, ge=5, le=600,
        description="同步等待上限（秒）",
    )


class AgentImageStatusRequest(BaseModel):
    """智能体 CLI 生图结果轮询请求（凭据字段与生图请求一致）。"""
    connection_info: Optional[str] = Field(
        None, max_length=AGENT_CLI_CONNECTION_INFO_MAX_CHARS,
    )
    agent_token: Optional[str] = None
    project_id: int


def _auth_header_token(token: Optional[str]) -> str:
    token = (token or "").strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    return token


@router.post("/exchange")
async def exchange_agent_token(request: AgentTokenExchangeRequest):
    raw_token = (request.token or "").strip()
    if not raw_token:
        return JSONResponse(
            status_code=401,
            content={"success": False, "error_code": "missing_agent_token", "error": "agent token is required"},
        )

    try:
        result = await asyncio.to_thread(
            AgentAuthService.exchange_token,
            raw_token,
            request.device_uuid,
        )
    except AgentAuthError as exc:
        return JSONResponse(status_code=exc.status_code, content=exc.to_dict())

    return JSONResponse(result)


def _image_error_response(exc: AgentImageGenerationError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=exc.to_dict())


@router.post("/generate-image")
async def generate_image_with_agent_connection(request: AgentImageGenerationRequest):
    """智能体 CLI 直接生图：粘贴首页「智能体连接」的 CLI 信息即可调用。

    流程：connection_info 提取 agent_token → exchange 换 auth_token → 解析世界与模型
    → 走平台文生图/图生图同一提交链路（算力扣费一致）→ 返回 project_ids。
    wait=true 时同步轮询 ai_tools 到终态（上限 wait_timeout 秒，超时返回 submitted）。
    """
    service = AgentImageGenerationService()

    try:
        exchange = await asyncio.to_thread(
            service.exchange_connection, request.connection_info, request.agent_token
        )
    except AgentImageGenerationError as exc:
        return _image_error_response(exc)

    user_id = int(exchange["user_id"])
    auth_token = str(exchange.get("auth_token") or "")

    try:
        result = await asyncio.to_thread(
            service.generate,
            user_id,
            auth_token,
            prompt=request.prompt,
            model=request.model,
            world_id=request.world_id,
            mode=request.mode,
            reference_image=request.reference_image,
            ratio=request.ratio,
            image_size=request.image_size,
            count=request.count,
        )
    except AgentImageGenerationError as exc:
        return _image_error_response(exc)

    if not request.wait:
        return JSONResponse(result)

    # wait=true：同步轮询首个 project 到终态（生图 count>1 时各 project 几乎同批完成，
    # 以首个为代表；未终态的仍可事后用 /image-status 查询）
    project_id = result["project_ids"][0]
    deadline = time.monotonic() + min(request.wait_timeout, 600)
    while True:
        try:
            status = await asyncio.to_thread(
                service.get_project_status, project_id, user_id
            )
        except AgentImageGenerationError as exc:
            return _image_error_response(exc)
        if status.get("terminal"):
            status_code = status["status_code"]
            result["result"] = status
            if status_code == AIToolStatus.COMPLETED:
                result["status"] = "completed"
            elif status_code == AIToolStatus.CANCELLED:
                result["status"] = "cancelled"
                result["success"] = False
                result["error"] = status.get("message") or "任务已取消"
            else:
                result["status"] = "failed"
                result["success"] = False
                result["error"] = status.get("message") or "图片生成失败"
            return JSONResponse(result)
        if time.monotonic() >= deadline:
            result["status"] = "submitted"
            result["wait_timeout"] = True
            result["last_status"] = status
            return JSONResponse(result)
        await asyncio.sleep(AGENT_CLI_IMAGE_POLL_INTERVAL_SECONDS)


@router.post("/image-status")
async def get_agent_image_status(request: AgentImageStatusRequest):
    """智能体 CLI 轮询生图结果：agent_token（或连接信息）+ project_id → ai_tools 状态。"""
    service = AgentImageGenerationService()
    try:
        # 轮询只取 user_id。exchange 会往 user_tokens 插入 24 小时登录会话，不能按轮询间隔重复签发
        identity = await asyncio.to_thread(
            service.identify_connection, request.connection_info, request.agent_token
        )
    except AgentImageGenerationError as exc:
        return _image_error_response(exc)

    user_id = int(identity["user_id"])
    try:
        status = await asyncio.to_thread(service.get_project_status, request.project_id, user_id)
    except AgentImageGenerationError as exc:
        return _image_error_response(exc)
    return JSONResponse(status)


@router.post("/storyboard-connection")
async def create_storyboard_agent_connection(
    auth_token: Optional[str] = Header(None, alias="Authorization"),
):
    token = _auth_header_token(auth_token)
    if not token:
        return JSONResponse(
            status_code=401,
            content={"success": False, "error_code": "missing_auth_token", "error": "Authorization is required"},
        )

    user_id = await asyncio.to_thread(UserTokensModel.get_user_id_by_token, token)
    if not user_id:
        return JSONResponse(
            status_code=401,
            content={"success": False, "error_code": "invalid_auth_token", "error": "Authorization is invalid or expired"},
        )

    try:
        result = await asyncio.to_thread(
            AgentAuthService.create_storyboard_agent_token,
            int(user_id),
        )
    except AgentAuthError as exc:
        return JSONResponse(status_code=exc.status_code, content=exc.to_dict())

    result["user_id"] = int(user_id)
    return JSONResponse(result)
