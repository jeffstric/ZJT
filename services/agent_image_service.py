"""智能体 CLI 直接生图服务。

用户从首页「智能体连接」弹窗复制 CLI 连接信息（base_url + agent_token 的 JSON 块）后，
把粘贴文本直接交给本服务即可生图，无需手动拆 token：

1. 从粘贴文本提取 agent_token（配平提取 JSON 块 → json.loads）
2. agent_token 经 AgentAuthService.exchange_token 换 auth_token（复用现有认证链）
3. 模型解析：显式 model 参数（模型名/key/short_key/任务id）→ 用户 CLI 媒体偏好
   （storyboard_cli surface）→ 平台默认文生图模型
4. 提交：文生图走 mcp_tool.generate_text_to_image，带参考图走 mcp_tool.edit_image
   （与平台前端文生图/图生图同一提交链路，算力扣费一致）
5. 状态查询：按 project_id 查 ai_tools 表（含用户归属校验）

文档：docs/backend/agent_image_generation_api.md
"""
import json
from typing import Any, Dict, List, Optional

from config.constant import (
    AGENT_CLI_IMAGE_MAX_COUNT,
    AGENT_CLI_IMAGE_POLL_INTERVAL_SECONDS,
    DEFAULT_TEXT_TO_IMAGE_TASK_ID,
    AIToolStatus,
    MediaGenerationSurface,
)
from config.unified_config import UnifiedConfigRegistry, TaskCategory, TaskProvider
from model.ai_tools import AIToolsModel as AIToolModel
from model.world import WorldModel
from services.agent_auth_service import AgentAuthError, AgentAuthService
from services.media_generation_preference_service import MediaGenerationPreferenceService


class AgentImageGenerationError(Exception):
    """生图接口业务错误（error_code 供调用方程序化处理）"""

    def __init__(self, status_code: int, error_code: str, message: str, payload: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.message = message
        self.payload = payload or {}

    def to_dict(self) -> Dict[str, Any]:
        result = {"success": False, "error_code": self.error_code, "error": self.message}
        if self.payload:
            result.update(self.payload)
        return result


def _extract_balanced_json_objects(text: str) -> List[Dict[str, Any]]:
    """从文本中提取所有括号配平的顶层 {...} JSON 对象。

    连接信息是「提示文案 + 多行 JSON」的混合文本，JSON 前后有中文说明，
    逐字符扫描并用引号状态机处理字符串内的花括号与转义。
    """
    objects: List[Dict[str, Any]] = []
    i, n = 0, len(text)
    while i < n:
        if text[i] != '{':
            i += 1
            continue
        depth = 0
        in_string = False
        escaped = False
        for j in range(i, n):
            ch = text[j]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == '\\':
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    candidate = text[i:j + 1]
                    try:
                        parsed = json.loads(candidate)
                    except (json.JSONDecodeError, ValueError):
                        break
                    if isinstance(parsed, dict):
                        objects.append(parsed)
                    i = j + 1
                    break
        else:
            # 括号不配平：跳过这个 '{' 继续扫描
            i += 1
    return objects


def extract_agent_token(connection_text: str) -> Optional[str]:
    """从粘贴的连接信息文本中提取 agent_token。

    兼容键名 agent_token / token；返回第一个命中的非空值。
    """
    for obj in _extract_balanced_json_objects(connection_text or ''):
        for key in ('agent_token', 'token'):
            value = obj.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _resolve_model_config(model: Optional[str], mode: str) -> Dict[str, Any]:
    """显式模型参数 → 统一任务配置。

    支持任务 id 数字、key / short_key / name / model_name 反查
    （UnifiedConfigRegistry.matches_identifier 口径）。
    校验所选模型支持当前生图模式（moss 仅文生图，带参考图提交会被拒绝）。
    """
    candidate = str(model or '').strip()
    if not candidate:
        return {}
    matched = None
    try:
        candidate_id = int(candidate)
        matched = UnifiedConfigRegistry.get_by_id(candidate_id)
    except (TypeError, ValueError):
        matched = None
    if matched is None:
        for config in UnifiedConfigRegistry.get_all():
            if config.matches_identifier(candidate):
                matched = config
                break
    if matched is None:
        raise AgentImageGenerationError(
            400, 'model_not_found', f'未找到生图模型: {model}'
        )
    if not matched.enabled:
        raise AgentImageGenerationError(
            400, 'model_disabled', f'生图模型 {matched.get_model_name()} 已禁用'
        )
    categories = {matched.category, *(matched.categories or [])}
    if mode == 'image_edit':
        supported = TaskCategory.IMAGE_EDIT in categories
    else:
        supported = TaskCategory.TEXT_TO_IMAGE in categories
    if not supported:
        mode_label = '图片编辑（图生图）' if mode == 'image_edit' else '文生图'
        raise AgentImageGenerationError(
            400,
            'model_mode_unsupported',
            f'模型 {matched.get_model_name()} 不支持{mode_label}'
            + ('（该模型仅支持文生图，请去掉参考图或更换模型）' if mode == 'image_edit' else ''),
            payload={'model_key': matched.key, 'model_id': int(matched.id)},
        )
    return {
        'task_id': int(matched.id),
        'model_key': matched.key,
        'model_name': matched.get_model_name(),
        'provider': matched.provider,
    }


def _default_model_task_id(user_id: int, world_id: int, mode: str) -> Optional[int]:
    """未显式指定模型时：读用户 CLI 媒体偏好（storyboard_cli surface）→ 平台默认。"""
    try:
        profile = MediaGenerationPreferenceService.get_profile(
            str(user_id), str(world_id),
            MediaGenerationSurface.STORYBOARD_CLI,
            'image', mode, initialize=False,
        )
    except Exception:
        profile = None
    if isinstance(profile, dict):
        task_id = profile.get('task_id')
        try:
            config = UnifiedConfigRegistry.get_by_id(int(task_id))
        except (TypeError, ValueError):
            config = None
        if config is not None:
            return int(config.id)
    return int(DEFAULT_TEXT_TO_IMAGE_TASK_ID)


def _resolve_world(user_id: int, world_id: Optional[int]) -> int:
    """world_id 显式传入时校验归属；缺省取用户最近更新的第一个世界。"""
    if world_id not in (None, ''):
        world = WorldModel.get_by_id(int(world_id))
        if not world:
            raise AgentImageGenerationError(404, 'world_not_found', f'世界不存在: {world_id}')
        world_user_id = getattr(world, 'user_id', None)
        if world_user_id not in (None, '') and int(world_user_id) != int(user_id):
            raise AgentImageGenerationError(403, 'world_forbidden', '世界不属于当前用户')
        return int(world_id)

    page = WorldModel.list_by_user(user_id=int(user_id), page=1, page_size=1)
    items = (page or {}).get('data') or []
    if not items:
        raise AgentImageGenerationError(
            400, 'world_required', '未指定 world_id 且当前用户没有可用世界，请先创建世界或显式传入 world_id'
        )
    return int(getattr(items[0], 'id', 0) or items[0].get('id'))


def _normalize_reference_urls(reference_image: Optional[str]) -> List[str]:
    """参考图参数 → URL 列表（逗号分隔，去空去重，保持顺序）。"""
    urls: List[str] = []
    for part in str(reference_image or '').split(','):
        url = part.strip()
        if url and url not in urls:
            urls.append(url)
    return urls


# AIToolStatus 数值 → 枚举名（如 2 → 'COMPLETED'）
_STATUS_CODE_TO_NAME = {
    value: name for name, value in vars(AIToolStatus).items()
    if not name.startswith('_') and isinstance(value, int)
}


def _status_label(status_code: int) -> str:
    """ai_tools 状态码 → 可读状态名（枚举名，如 PENDING / COMPLETED / FAILED）。"""
    return _STATUS_CODE_TO_NAME.get(int(status_code), str(status_code))


class AgentImageGenerationService:
    """智能体 CLI 直接生图编排（同步实现，调用方用 asyncio.to_thread 包装）。"""

    def exchange_connection(self, connection_text: Optional[str], agent_token: Optional[str]) -> Dict[str, Any]:
        """粘贴文本 / 显式 token 二选一 → exchange 换 auth_token 与 user_id。"""
        token = (agent_token or '').strip()
        if not token and connection_text:
            token = extract_agent_token(connection_text) or ''
        if not token:
            raise AgentImageGenerationError(
                400, 'missing_agent_token',
                '连接信息中未找到 agent_token：请粘贴首页「智能体连接」复制的完整信息，或直接传 agent_token'
            )
        try:
            exchange = AgentAuthService.exchange_token(token)
        except AgentAuthError as exc:
            raise AgentImageGenerationError(
                exc.status_code, exc.error_code, exc.message,
            ) from exc
        if not exchange.get('success'):
            raise AgentImageGenerationError(
                401, 'invalid_agent_token', 'agent token 无效或已过期'
            )
        return exchange

    def resolve_model(
        self,
        user_id: int,
        world_id: int,
        *,
        model: Optional[str],
        mode: str,
    ) -> Dict[str, Any]:
        """模型解析：显式 model → 用户 CLI 偏好 → 平台默认。返回统一描述。"""
        explicit = _resolve_model_config(model, mode) if model not in (None, '') else {}
        if explicit:
            return explicit
        task_id = _default_model_task_id(user_id, world_id, mode)
        config = UnifiedConfigRegistry.get_by_id(task_id)
        if config is None:
            raise AgentImageGenerationError(
                500, 'default_model_missing', f'默认生图模型（id={task_id}）不存在'
            )
        return {
            'task_id': int(config.id),
            'model_key': config.key,
            'model_name': config.get_model_name(),
            'provider': config.provider,
        }

    def generate(
        self,
        user_id: int,
        auth_token: str,
        *,
        prompt: str,
        model: Optional[str] = None,
        world_id: Optional[int] = None,
        mode: str = 'auto',
        reference_image: Optional[str] = None,
        ratio: Optional[str] = None,
        image_size: Optional[str] = None,
        count: int = 1,
    ) -> Dict[str, Any]:
        """提交生图任务（文生图 / 图生图），返回 project_ids 与轮询指引。"""
        if not prompt or not str(prompt).strip():
            raise AgentImageGenerationError(400, 'prompt_required', '提示词 prompt 不能为空')
        if mode not in ('auto', 'text_to_image', 'image_edit'):
            raise AgentImageGenerationError(
                400, 'invalid_mode', "mode 必须为 auto / text_to_image / image_edit"
            )
        try:
            count = int(count)
        except (TypeError, ValueError):
            count = 0
        if count < 1 or count > AGENT_CLI_IMAGE_MAX_COUNT:
            raise AgentImageGenerationError(
                400, 'invalid_count', f'count 必须为 1-{AGENT_CLI_IMAGE_MAX_COUNT} 之间的整数'
            )

        reference_urls = _normalize_reference_urls(reference_image)
        if mode == 'auto':
            mode = 'image_edit' if reference_urls else 'text_to_image'
        elif mode == 'text_to_image' and reference_urls:
            raise AgentImageGenerationError(
                400, 'reference_not_allowed', 'mode=text_to_image 时不能携带参考图，请用 mode=auto 或 image_edit'
            )
        elif mode == 'image_edit' and not reference_urls:
            raise AgentImageGenerationError(
                400, 'reference_required', 'mode=image_edit 时必须携带 reference_image 参考图'
            )

        resolved_world_id = _resolve_world(user_id, world_id)
        model_info = self.resolve_model(user_id, resolved_world_id, model=model, mode=mode)

        # 与平台前端文生图/图生图同一提交链路（同步函数，调用方需 to_thread 包装）
        from script_writer_core.mcp_tool import edit_image, generate_text_to_image

        if mode == 'text_to_image':
            result = generate_text_to_image(
                user_id=str(user_id),
                world_id=str(resolved_world_id),
                auth_token=auth_token,
                prompt=str(prompt).strip(),
                aspect_ratio=ratio or '9:16',
                count=count,
                image_size=image_size,
                task_type=model_info['task_id'],
            )
        else:
            result = edit_image(
                user_id=str(user_id),
                world_id=str(resolved_world_id),
                auth_token=auth_token,
                prompt=str(prompt).strip(),
                image_url=','.join(reference_urls),
                aspect_ratio=ratio or '9:16',
                count=count,
                image_size=image_size,
                task_type=model_info['task_id'],
            )

        if not isinstance(result, dict) or not result.get('success'):
            error = (result or {}).get('error') if isinstance(result, dict) else str(result)
            raise AgentImageGenerationError(
                400, 'submission_failed', error or '生图任务提交失败'
            )

        project_ids = result.get('project_ids') or []
        if not project_ids:
            raise AgentImageGenerationError(
                502, 'missing_project_ids', '生图请求成功但未返回任务ID，请联系技术支持'
            )

        return {
            'success': True,
            'mode': mode,
            'world_id': resolved_world_id,
            'project_ids': [int(pid) for pid in project_ids],
            'status': 'submitted',
            'task_type': model_info['task_id'],
            'model_used': model_info['model_name'],
            'model_key': model_info['model_key'],
            'provider': model_info.get('provider'),
            'computing_power_per_image': result.get('computing_power_required'),
            'computing_power_total': result.get('computing_power_total'),
            'image_size_used': result.get('image_size_used'),
            'poll_hint': {
                'interval_seconds': AGENT_CLI_IMAGE_POLL_INTERVAL_SECONDS,
                'endpoint': 'POST /api/agent-auth/image-status',
                'body': {'project_id': int(project_ids[0])},
                'note': '用同一 agent_token 换取的连接信息轮询；或请求时传 wait=true 由服务端同步等待',
            },
        }

    def get_project_status(self, project_id: int, user_id: int) -> Dict[str, Any]:
        """按 project_id 查询 ai_tools 任务状态（归属校验：非本人任务一律 not_found 防枚举）。"""
        tool = AIToolModel.get_by_id(int(project_id))
        if not tool or int(getattr(tool, 'user_id', 0) or 0) != int(user_id):
            raise AgentImageGenerationError(404, 'project_not_found', f'任务不存在: {project_id}')
        status_code = int(getattr(tool, 'status', 0) or 0)
        label = _status_label(status_code)
        terminal = status_code in (
            AIToolStatus.COMPLETED, AIToolStatus.FAILED,
        )
        result: Dict[str, Any] = {
            'success': True,
            'project_id': int(project_id),
            'status_code': status_code,
            'status': label,
            'terminal': terminal,
        }
        if terminal and status_code == AIToolStatus.COMPLETED:
            result['result_url'] = getattr(tool, 'result_url', None)
        if getattr(tool, 'message', None):
            result['message'] = tool.message
        return result
