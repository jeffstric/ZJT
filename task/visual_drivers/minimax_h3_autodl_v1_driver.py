"""
MiniMax H3 AutoDL.Art ComfyUI 工作流驱动

AutoDL.Art 将 ComfyUI 工作流包装为两步异步 HTTP API：
  1. 提交任务：POST {base_url}/api/v1/comfyui/comfyui_workflow/{workflow_id}
     → 立即返回 data.task_id（状态 QUEUED）
  2. 轮询结果：GET {base_url}/api/v1/comfyui/comfyui_workflow/result/{task_id}
     → data.status ∈ QUEUED/RUNNING/SUCCESS(completed)/FAILED
     → SUCCESS 后 data.results[].url 为成片地址（短时效，SUCCESS 后由 download_queue
       立即下载转存，超时无法下载）

认证：Authorization 头直接放 Token（裸 token，无 Bearer 前缀），
Token 在 autodl.art 令牌管理页创建，分组必须选 ComfyUI（autodl.api_key）。

参考图/音频必须传公网 URL（平台无上传 API）：本地/局域网素材经
compress_and_upload_image_sync / upload_media_to_cdn_sync 转为七牛 CDN 公网地址。

本文件包含一个基类与三个工作流实现：
- MinimaxH3ReferenceAutodlV1Driver   参考生视频 minimax_h3_zm_u24
  （最多 9 张参考图 ref_image_0~8 + 3 段参考音频 ref_audio_0~2）
- MinimaxH3FirstLastAutodlV1Driver   首尾帧 minimax_h3_lightx2v
  （first_frame + last_frame 双必填——2026-11-08 三重实测证实：仅首帧提交
  报"缺少必填参数：last_frame"、ref_image_0 报"未定义的参数"；已反馈上游
  待 AutoDL 改为可选后可再放开）
- MinimaxH3CharReplaceAutodlV1Driver 视频人物替换 minimax_h3_zm_titim
  （ref_video 必填 + ref_image_0~8 最多 9 张角色图，5-25s，768p 竖/横跟随
  参考视频方向，原声保留；2026-11-16 实测出片：身份/服装跟随参考图、
  动作/字幕/道具保留、耗时 329s@5s、0.11 元/秒）

时长 1-15 秒（人物替换工作流 5-25 秒，各自子类钳制）；分辨率 480p/768p × 竖/横/(1:1)
（人物替换仅 768p 竖/横两档）。
"""
import json
import re
import traceback
from typing import Any, Dict, Optional, Tuple

import requests

from config.config_util import get_config, get_dynamic_config_value
from config.constant import (
    LEGACY_RESOLUTION_EXTRA_CONFIG_KEY,
    VIDEO_RESOLUTION_EXTRA_CONFIG_KEY,
    VIDEO_CHAR_REPLACE_MAX_DURATION_SECONDS,
    VIDEO_CHAR_REPLACE_MIN_DURATION_SECONDS,
)
from config.unified_config import DriverImplementation, TaskTypeId, VideoResolution
from task.pipeline_drivers.h3_prompt_optimize_util import (
    has_quoted_dialogue,
    h3_slot_source_prompt,
)
from utils.image_upload_utils import (
    compress_and_upload_image_sync,
    upload_media_to_cdn_sync,
)
from utils.sentry_util import AlertLevel, SentryUtil

from .base_video_driver import BaseVideoDriver, ImageMode

# ===== 工作流 ID（AutoDL.Art 工作流广场，更换工作流只需换此常量） =====
AUTODL_WORKFLOW_REFERENCE = "minimax_h3_zm_u24"       # H3 多图多音频生视频（升级画质）
AUTODL_WORKFLOW_FIRST_LAST = "minimax_h3_lightx2v"    # H3 首尾帧生视频
AUTODL_WORKFLOW_CHARACTER_REPLACE = "minimax_h3_zm_titim"  # H3 视频多角色动迁替换

AUTODL_API_BASE_DEFAULT = "https://autodl.art"

# 参考图/音频槽位上限（工作流定义）
MAX_REFERENCE_IMAGES = 9
MAX_REFERENCE_AUDIOS = 3

# 时长合法区间（工作流定义 1-15 秒，任务层仍按 4-10 下发）
MIN_DURATION_SECONDS = 1
MAX_DURATION_SECONDS = 15
DEFAULT_DURATION_SECONDS = 5

# 竖/横/(1:1) 判定：ratio → resolution 后缀。任务层支持的 4:3、3:4、2:3、3:2、21:9
# autodl 无对应档位，按方向就近归并（4:3/3:2/21:9 → 横，3:4/2:3 → 竖）。
# 仅 9:16/16:9/1:1 为原生匹配；其余比例成片实际比例与用户所选不一致（归并日志可溯源）。
PORTRAIT_RATIOS = {'9:16', '3:4', '2:3'}
LANDSCAPE_RATIOS = {'16:9', '4:3', '3:2', '21:9'}
SQUARE_RATIOS = {'1:1'}
# 原生匹配比例（不发生归并）
NATIVE_RATIOS = {'9:16', '16:9', '1:1'}

# 平台分辨率标准值 → autodl 画质段（720P 档对应 autodl 768p）
RESOLUTION_TIER_MAP = {
    VideoResolution.P480: '480p',
    VideoResolution.P720: '768p',
}
DEFAULT_RESOLUTION_TIER = '768p'

# 人物替换分辨率：仅 768p 竖/横两档（跟随参考视频方向，端点 ffprobe 探测后
# 写入 extra_config.char_replace_resolution，驱动原样透传）
CHAR_REPLACE_RESOLUTION_EXTRA_KEY = 'char_replace_resolution'
CHAR_REPLACE_RESOLUTION_VALUES = ('768p竖', '768p横')

# 查询状态归一（大小写不敏感：文档示例为 QUEUED/RUNNING/SUCCESS/FAILED，
# 工作流页输出示例出现过小写 completed，统一 upper 处理）
_SUCCESS_STATES = {'SUCCESS', 'COMPLETED'}
_FAILURE_STATES = {'FAILED', 'ERROR', 'CANCELLED', 'CANCELED'}
_RUNNING_STATES = {'QUEUED', 'RUNNING', 'PENDING'}

# 注入侧写进提示词尾部的音色说明句（与 RunningHub 参考生驱动同源的兜底剥除逻辑）
_VOICE_NOTE_LINE_RE = re.compile(r"\n*参考音频说明：[^\n]*")


class MinimaxH3AutodlV1Driver(BaseVideoDriver):
    """
    MiniMax H3 AutoDL.Art ComfyUI 工作流驱动基类

    两个工作流共用同一套提交/轮询协议，差异只在请求体素材槽位，
    由子类实现 build_create_request。
    """

    def __init__(self, driver_type: int, workflow_id: str, impl_name: str):
        """
        Args:
            driver_type: 任务类型（对应 TaskTypeId / ai_tools.type）
            workflow_id: AutoDL.Art 工作流 ID
            impl_name: 实现方名称，需与 IMPLEMENTATION_TO_ID 映射一致
        """
        super().__init__(driver_name=impl_name, driver_type=driver_type)

        # 加载配置（autodl.api_key / autodl.base_url 支持后台热更新）
        self._api_key = get_dynamic_config_value("autodl", "api_key", default="")
        self._base_url = get_dynamic_config_value(
            "autodl", "base_url", default=AUTODL_API_BASE_DEFAULT
        )
        # 去除尾部斜杠，避免路径拼接出现双斜杠
        self._base_url = (self._base_url or AUTODL_API_BASE_DEFAULT).rstrip("/")
        self._timeout = get_dynamic_config_value("timeout", "request_timeout", default=30)

        self._workflow_id = workflow_id
        self._config = get_config()

        # 测试模式配置
        self._test_mode_enabled = get_dynamic_config_value("test_mode", "enabled", default=False)
        self._mock_video_url = get_dynamic_config_value("test_mode", "mock_videos", default={}).get("image_to_video")

        self._validate_required({
            "AutoDL.Art API Token": self._api_key,
        })

    # ==================== 报警 / 辅助方法 ====================

    def _send_alert(self, alert_type: str, message: str, context: Optional[Dict[str, Any]] = None):
        SentryUtil.send_alert(
            alert_type=alert_type,
            message=message,
            level=AlertLevel.ERROR,
            context=context
        )

    def _extract_http_error_body(self, http_error) -> Optional[dict]:
        """
        从 HTTPError 中提取响应体 JSON

        基类 _request 在 raise_for_status() 时会丢弃响应体，这里重新解析。
        """
        try:
            response = getattr(http_error, "response", None)
            if response is None:
                return None
            return response.json()
        except (ValueError, AttributeError):
            return None

    def _auth_headers(self) -> Dict[str, str]:
        """autodl 认证头：Authorization 直接放 Token（裸 token，无 Bearer 前缀）"""
        return {
            "Content-Type": "application/json",
            "Authorization": self._api_key,
        }

    def _parse_extra_config(self, ai_tool) -> Dict[str, Any]:
        """解析 extra_config JSON"""
        if not ai_tool.extra_config:
            return {}
        try:
            config = ai_tool.extra_config if isinstance(ai_tool.extra_config, dict) else json.loads(ai_tool.extra_config)
            return config if isinstance(config, dict) else {}
        except (json.JSONDecodeError, TypeError):
            self.logger.warning(f"无法解析 extra_config: {ai_tool.extra_config}")
            return {}

    @staticmethod
    def _split_reference_paths(raw) -> list:
        """解析参考音频路径（ai_tools 落库格式为逗号分隔 URL 字符串）。"""
        if not raw:
            return []
        if isinstance(raw, list):
            return [str(item).strip() for item in raw if str(item).strip()]
        return [item.strip() for item in str(raw).split(",") if item.strip()]

    def _get_resolution_tier(self, extra_config: Dict[str, Any]) -> str:
        """
        从 extra_config 读取平台分辨率标准值并映射为 autodl 画质段（480p/768p）

        取不到时默认 768p（对应平台 720P 档）。
        """
        resolution = (
            extra_config.get(VIDEO_RESOLUTION_EXTRA_CONFIG_KEY)
            or extra_config.get(LEGACY_RESOLUTION_EXTRA_CONFIG_KEY)
        )
        tier = RESOLUTION_TIER_MAP.get(resolution)
        if tier:
            return tier
        if resolution:
            self.logger.warning(f"AutoDL 驱动收到未知分辨率 {resolution}，回落 {DEFAULT_RESOLUTION_TIER}")
        return DEFAULT_RESOLUTION_TIER

    @staticmethod
    def _build_resolution_value(tier: str, ratio: Optional[str]) -> str:
        """
        画质段 + 比例方向 → autodl resolution 参数值

        可选值形如：480p竖 / 768p竖 / 480p横 / 768p横 / 480p(1:1) / 768p(1:1)
        """
        if ratio in SQUARE_RATIOS:
            return f"{tier}(1:1)"
        if ratio in LANDSCAPE_RATIOS:
            return f"{tier}横"
        # 竖屏（含 9:16/3:4/2:3 及缺省）
        return f"{tier}竖"

    def _clamp_duration(self, ai_tool) -> int:
        """时长钳制到工作流合法区间 1-15 秒（任务层下发 4-10）"""
        try:
            duration = int(ai_tool.duration or DEFAULT_DURATION_SECONDS)
        except (TypeError, ValueError):
            duration = DEFAULT_DURATION_SECONDS
        return max(MIN_DURATION_SECONDS, min(MAX_DURATION_SECONDS, duration))

    def _to_public_image_url(self, image_path: str, description: str) -> Tuple[Optional[str], Optional[str]]:
        """
        图片转公网 URL（本地/局域网压缩后上传七牛 CDN，外网 URL 原样返回）

        Returns:
            (cdn_url, None) 或 (None, error_message)
        """
        success, url, error = compress_and_upload_image_sync(
            image_path, self._config, max_size_mb=10.0, is_local=True
        )
        if not success:
            return None, f"{description}处理失败: {error}"
        return url, None

    def _to_public_media_url(self, media_path: str, description: str) -> Tuple[Optional[str], Optional[str]]:
        """
        音频转公网 URL（本地/局域网上传七牛 CDN，外网 URL 原样返回；不压缩）

        Returns:
            (cdn_url, None) 或 (None, error_message)
        """
        success, url, error = upload_media_to_cdn_sync(media_path, self._config)
        if not success:
            return None, f"{description}处理失败: {error}"
        return url, None

    def _resolve_prompt_and_audios(self, ai_tool, extra_config: Dict[str, Any]) -> Tuple[str, list]:
        """
        解析提示词与参考音频（口径与 RunningHub 参考生驱动一致）

        - 提示词优先使用 pipeline 优化结果（Ref2VA 改写），原文备份在 extra_config.original_prompt
        - 无对白镜头不上传参考音频：MiniMax 的音色参考必须绑定说话内容，
          台词有无优先取优化步骤的 LLM 语义判断（extra_config.h3_prompt_optimize.has_dialogue），
          旧任务/优化禁用/回退原文时回退正则引号判断
        - 无对白且文本中残留音色说明句时剥掉（避免诱导模型让角色发声）
        """
        prompt_meta = extra_config.get("h3_prompt_optimize") if isinstance(extra_config, dict) else None
        if isinstance(prompt_meta, dict) and prompt_meta.get("optimized_prompt"):
            prompt_text = str(prompt_meta.get("optimized_prompt") or "")
        else:
            prompt_text = ai_tool.prompt or ""

        audios = self._split_reference_paths(self.get_audio_path(ai_tool))
        if len(audios) > MAX_REFERENCE_AUDIOS:
            self.logger.warning(
                f"AutoDL 参考生视频最多支持{MAX_REFERENCE_AUDIOS}个参考音频，已忽略多余的音频"
            )
            audios = audios[:MAX_REFERENCE_AUDIOS]

        llm_flag = prompt_meta.get("has_dialogue") if isinstance(prompt_meta, dict) else None
        has_dialogue = llm_flag if isinstance(llm_flag, bool) else has_quoted_dialogue(
            h3_slot_source_prompt(extra_config, getattr(ai_tool, "prompt", None) or "")
        )
        if audios and not has_dialogue:
            self.logger.info(
                f"AutoDL 参考生视频镜头无对白（has_dialogue={llm_flag}），"
                f"跳过 {len(audios)} 个参考音频"
            )
            audios = []
        if not has_dialogue and "参考音频说明" in prompt_text:
            prompt_text = _VOICE_NOTE_LINE_RE.sub("", prompt_text).strip()
            self.logger.info("AutoDL 参考生视频无对白，已剥除提示词中的参考音频说明句")

        return prompt_text, audios

    # ==================== 响应校验 ====================

    def _validate_submit_response(self, result: Any) -> tuple[bool, Optional[str]]:
        """
        验证提交任务响应格式

        成功结构：{"code": "Success", "data": {"task_id": ...}, "msg": "", "request_id": ...}
        业务失败：{"code": "<非Success>", "msg": "..."}（格式有效，submit 内走错误分支）
        """
        if not isinstance(result, dict):
            return False, f"响应不是字典类型，实际类型: {type(result)}"

        if result.get("code") == "Success":
            data = result.get("data")
            if not isinstance(data, dict) or not data.get("task_id"):
                return False, f"code=Success 但缺少 data.task_id，实际字段: {list(result.keys())}"
            return True, None

        # 非 Success：带 msg 视为格式有效的业务错误
        if result.get("msg"):
            return True, None
        return False, f"未知响应结构，实际字段: {list(result.keys())}"

    def _validate_status_response(self, result: Any) -> tuple[bool, Optional[str]]:
        """
        验证查询任务响应格式

        成功结构：{"code": "Success", "data": {"status": ..., "results": [...], ...}}
        """
        if not isinstance(result, dict):
            return False, f"响应不是字典类型，实际类型: {type(result)}"

        if result.get("code") == "Success":
            data = result.get("data")
            if not isinstance(data, dict) or not data.get("status"):
                return False, f"code=Success 但缺少 data.status，实际字段: {list(result.keys())}"
            return True, None

        if result.get("msg"):
            return True, None
        return False, f"未知响应结构，实际字段: {list(result.keys())}"

    def _extract_task_id(self, result: Any) -> Optional[str]:
        """提取任务 ID（data.task_id）"""
        if isinstance(result, dict):
            data = result.get("data")
            if isinstance(data, dict):
                task_id = data.get("task_id")
                if task_id:
                    return str(task_id)
        return None

    # ==================== 请求构建 ====================

    def _build_base_payload(self, ai_tool, extra_config: Dict[str, Any], prompt: str) -> Dict[str, Any]:
        """构建两工作流共用的基础字段：prompt / duration / resolution"""
        ratio = getattr(ai_tool, "ratio", None) or '9:16'
        if ratio not in NATIVE_RATIOS:
            # 工作流只有 竖/横/(1:1) 六档：4:3/3:2/21:9 归并为横、3:4/2:3 归并为竖，
            # 成片实际比例与用户所选不一致（如 16:9 档实测 1344×768），留 warning 便于客诉溯源。
            self.logger.warning(
                f"AutoDL 工作流无 {ratio} 档位，已按方向归并（成片比例将与所选不一致）"
            )
        return {
            "prompt": prompt,
            "duration": self._clamp_duration(ai_tool),
            "resolution": self._build_resolution_value(
                self._get_resolution_tier(extra_config),
                ratio,
            ),
        }

    def build_check_query(self, project_id: str) -> Dict[str, Any]:
        """构建查询任务状态的请求参数"""
        return {
            "url": f"{self._base_url}/api/v1/comfyui/comfyui_workflow/result/{project_id}",
            "method": "GET",
            "json": None,
            "headers": self._auth_headers(),
        }

    # ==================== 提交任务 ====================

    def submit_task(self, ai_tool) -> Dict[str, Any]:
        """
        提交 AutoDL.Art ComfyUI 工作流任务（异步 API，返回 task_id 用于轮询）
        """
        task_id = ai_tool.id

        try:
            # 1. 构建请求参数（子类按工作流填充素材槽位）
            request_params = self.build_create_request(ai_tool)

            # build_create_request 可能返回错误（如素材缺失/上传失败）
            if "success" in request_params and not request_params["success"]:
                return request_params

            # 测试模式：返回 mock 数据，避免实际 API 调用和费用
            if self._test_mode_enabled:
                mock_project_id = f"test-{self._workflow_id}-{ai_tool.id}"
                self.logger.info(f"[TEST MODE] 返回模拟task_id: {mock_project_id}")
                return {
                    "success": True,
                    "project_id": mock_project_id
                }

            # 2. 发送请求
            try:
                result = self._request(
                    url=request_params["url"],
                    method=request_params["method"],
                    json=request_params["json"],
                    headers=request_params["headers"],
                    timeout=self._timeout
                )
            except requests.exceptions.HTTPError as http_error:
                # 4xx/5xx：autodl 错误体为 {"code": ..., "msg": ...}
                status_code = getattr(getattr(http_error, "response", None), "status_code", None)
                error_body = self._extract_http_error_body(http_error)
                if isinstance(error_body, dict) and error_body.get("msg"):
                    error_msg = str(error_body.get("msg"))
                    if status_code == 429:
                        # 限流：友好提示 + 允许重试，不发 Sentry
                        self.logger.warning(f"AutoDL 提交限流(429): {error_msg}")
                        return {
                            "success": False,
                            "error": "上游限流，请稍后重试",
                            "error_type": "USER",
                            "retry": True
                        }
                    # 400 参数错误 / 401 Token 无效等：用户错误，不重试
                    return {
                        "success": False,
                        "error": f"任务提交失败: {error_msg}",
                        "error_type": "USER",
                        "retry": False
                    }
                # 无法解析错误体，按系统错误处理
                self._send_alert(
                    alert_type="API_HTTP_ERROR",
                    message=f"AutoDL submit_task HTTP 错误: {str(http_error)}",
                    context={"task_id": task_id, "status_code": status_code,
                             "workflow_id": self._workflow_id}
                )
                return {
                    "success": False,
                    "error": "服务异常，请联系技术支持",
                    "error_type": "SYSTEM",
                    "error_detail": str(http_error),
                    "retry": False
                }
            except (ConnectionError, TimeoutError) as network_error:
                self.logger.warning(f"Network error during AutoDL task submission: {str(network_error)}")
                return {
                    "success": False,
                    "error": "网络连接异常，请稍后重试",
                    "error_type": "USER",
                    "retry": True
                }

            self.logger.info(
                f"AutoDL {self._workflow_id} 提交响应: code={result.get('code') if isinstance(result, dict) else result}"
            )

            # 3. 验证响应格式
            is_valid, error_msg = self._validate_submit_response(result)
            if not is_valid:
                self._send_alert(
                    alert_type="INVALID_RESPONSE_FORMAT",
                    message=f"AutoDL {self._workflow_id} 响应格式错误: {error_msg}",
                    context={"task_id": task_id, "response": result}
                )
                return {
                    "success": False,
                    "error": "服务异常，请联系技术支持",
                    "error_type": "SYSTEM",
                    "error_detail": f"API响应格式错误: {error_msg}",
                    "retry": False
                }

            # 4. 业务错误（code != Success）
            if isinstance(result, dict) and result.get("code") != "Success":
                error_msg = str(result.get("msg") or result.get("code") or "任务提交失败")
                self.logger.warning(f"AutoDL {self._workflow_id} 提交失败: {error_msg}")
                return {
                    "success": False,
                    "error": f"任务提交失败: {error_msg}",
                    "error_type": "USER",
                    "retry": False
                }

            # 5. 提取任务 ID
            project_id = self._extract_task_id(result)
            if not project_id:
                return {
                    "success": False,
                    "error": "服务异常，请联系技术支持",
                    "error_type": "SYSTEM",
                    "error_detail": "AutoDL API 未返回任务ID",
                    "retry": False
                }

            return {
                "success": True,
                "project_id": project_id
            }

        except Exception as e:
            error_msg = str(e)
            self.logger.error(f"AutoDL submit_task error: {error_msg}")
            self.logger.error(traceback.format_exc())

            if "timeout" in error_msg.lower() or "connection" in error_msg.lower():
                return {
                    "success": False,
                    "error": "网络连接异常，请稍后重试",
                    "error_type": "USER",
                    "retry": True
                }

            self._send_alert(
                alert_type="UNEXPECTED_EXCEPTION",
                message=f"AutoDL submit_task 异常: {error_msg}",
                context={"task_id": task_id, "traceback": traceback.format_exc()}
            )
            return {
                "success": False,
                "error": "服务异常，请联系技术支持",
                "error_type": "SYSTEM",
                "error_detail": error_msg,
                "retry": False
            }

    # ==================== 查询状态 ====================

    def check_status(self, project_id: str) -> Dict[str, Any]:
        """
        检查 AutoDL.Art 任务状态

        autodl 状态值（data.status，大小写归一）:
            QUEUED（排队中）/ RUNNING（执行中）→ 轮询等待
            SUCCESS / completed → 成功，results[0].url 为成片地址（短时效）
            FAILED → 失败
        """
        try:
            self.logger.info(f"Checking AutoDL {self._workflow_id} task status: project_id={project_id}")

            # 测试模式：返回 mock 数据
            if self._test_mode_enabled and self._mock_video_url:
                self.logger.info(f"[TEST MODE] 返回模拟视频结果: {self._mock_video_url}")
                return {
                    "status": "SUCCESS",
                    "result_url": self._mock_video_url
                }

            # 1. 构建请求并发送
            request_params = self.build_check_query(project_id)

            try:
                result = self._request(**request_params)
            except requests.exceptions.HTTPError as http_error:
                status_code = getattr(getattr(http_error, "response", None), "status_code", None)
                if status_code == 429:
                    # 限流：保持 RUNNING，等待下次轮询
                    self.logger.warning("AutoDL 状态查询限流(429)，稍后重试")
                    return {
                        "status": "RUNNING",
                        "message": "上游限流，稍后将重试"
                    }
                if status_code == 404:
                    # 任务刚提交可能存在上游传播延迟，按处理中等待（任务过期检查负责终态兜底）
                    self.logger.warning(f"AutoDL 状态查询 404（可能仍在传播）: project_id={project_id}")
                    return {
                        "status": "RUNNING",
                        "message": "任务查询暂不可用，稍后将重试"
                    }
                if isinstance(status_code, int) and 500 <= status_code < 600:
                    # 上游 5xx 为临时故障（网关抖动/服务重启）：判死会误退款且上游任务可能
                    # 仍在跑（AutoDL 持续计费），保持 RUNNING 继续轮询，任务过期检查兜底终态。
                    self.logger.warning(
                        f"AutoDL 状态查询上游 {status_code}（临时故障），保持轮询: project_id={project_id}"
                    )
                    return {
                        "status": "RUNNING",
                        "message": "上游服务暂时不可用，稍后将重试"
                    }
                self._send_alert(
                    alert_type="API_HTTP_ERROR",
                    message=f"AutoDL check_status HTTP 错误: {str(http_error)}",
                    context={"project_id": project_id, "status_code": status_code}
                )
                return {
                    "status": "FAILED",
                    "error": "服务异常，请联系技术支持",
                    "error_type": "SYSTEM",
                    "error_detail": str(http_error)
                }
            except (ConnectionError, TimeoutError) as network_error:
                self.logger.warning(f"Network error during AutoDL status check: {str(network_error)}")
                return {
                    "status": "RUNNING",
                    "message": "网络连接异常，稍后将重试"
                }

            # 2. 验证响应格式
            is_valid, validation_error = self._validate_status_response(result)
            if not is_valid:
                self._send_alert(
                    alert_type="INVALID_RESPONSE_FORMAT",
                    message=f"AutoDL check_status 响应格式错误: {validation_error}",
                    context={"project_id": project_id, "response": result}
                )
                return {
                    "status": "FAILED",
                    "error": "服务异常，请联系技术支持",
                    "error_type": "SYSTEM",
                    "error_detail": f"API响应格式错误: {validation_error}"
                }

            # 3. 查询业务错误（code != Success：任务不存在/Token 失效等，非用户输入问题）
            if isinstance(result, dict) and result.get("code") != "Success":
                error_msg = str(result.get("msg") or "查询任务状态失败")
                self.logger.warning(f"AutoDL 状态查询失败: {error_msg}")
                return {
                    "status": "FAILED",
                    "error": f"查询任务状态失败: {error_msg}",
                    "error_type": "SYSTEM"
                }

            # 4. 状态映射（大小写归一）
            data = result.get("data") if isinstance(result, dict) else {}
            raw_status = str(data.get("status", ""))
            status_upper = raw_status.upper()
            self.logger.info(f"AutoDL {self._workflow_id} 任务状态: {raw_status}")

            if status_upper in _SUCCESS_STATES:
                # 成片地址在 data.results[]（取首个带 url 的视频项）
                result_url = None
                for item in (data.get("results") or []):
                    if isinstance(item, dict) and item.get("url"):
                        result_url = item["url"]
                        break
                if not result_url:
                    self._send_alert(
                        alert_type="INVALID_RESPONSE_FORMAT",
                        message="AutoDL 任务成功但缺少结果地址",
                        context={"project_id": project_id, "response": result}
                    )
                    return {
                        "status": "FAILED",
                        "error": "任务成功但未返回视频地址",
                        "error_type": "SYSTEM"
                    }
                # ⚠️ 结果 URL 短时效：SUCCESS 后由 download_queue 立即下载转存
                return {
                    "status": "SUCCESS",
                    "result_url": result_url
                }

            if status_upper in _FAILURE_STATES:
                # 失败原因：data.message / data.msg 回退默认文案
                data_obj = data if isinstance(data, dict) else {}
                fail_reason = data_obj.get("message") or data_obj.get("msg")
                if not isinstance(fail_reason, str) or not fail_reason:
                    fail_reason = "任务失败"
                # 容错：过滤掉误填为 URL 的失败原因
                if fail_reason.startswith(("http://", "https://")):
                    fail_reason = "任务失败"
                return {
                    "status": "FAILED",
                    "error": fail_reason,
                    "error_type": "USER"
                }

            if status_upper in _RUNNING_STATES:
                return {
                    "status": "RUNNING",
                    "message": "任务处理中..."
                }

            # 未知状态：不判死，继续轮询（任务过期检查负责终态兜底）
            self.logger.warning(f"AutoDL 返回未知状态 {raw_status}，继续等待")
            return {
                "status": "RUNNING",
                "message": f"任务状态: {raw_status}"
            }

        except Exception as e:
            self.logger.error(f"Unexpected exception in AutoDL check_status: {str(e)}")
            self.logger.error(traceback.format_exc())

            self._send_alert(
                alert_type="UNEXPECTED_EXCEPTION",
                message=f"AutoDL check_status 发生未预期异常: {str(e)}",
                context={"project_id": project_id, "traceback": traceback.format_exc()}
            )
            return {
                "status": "FAILED",
                "error": "服务异常，请联系技术支持",
                "error_type": "SYSTEM",
                "error_detail": f"未预期异常: {str(e)}"
            }


class MinimaxH3ReferenceAutodlV1Driver(MinimaxH3AutodlV1Driver):
    """
    MiniMax H3 参考生视频（AutoDL.Art 工作流 minimax_h3_zm_u24）

    请求体素材槽位：
    - ref_image_0（必填）~ ref_image_8：最多 9 张参考图（JPG/PNG/WebP 公网 URL）
    - ref_audio_0 ~ ref_audio_2：最多 3 段参考音频（MP3/WAV/FLAC 公网 URL）
    - 参考视频：工作流不支持视频槽，丢弃并记日志
    """

    def __init__(self):
        super().__init__(
            driver_type=TaskTypeId.MINIMAX_H3_REFERENCE_TO_VIDEO,
            workflow_id=AUTODL_WORKFLOW_REFERENCE,
            impl_name=DriverImplementation.MINIMAX_H3_REFERENCE_AUTODL_V1,
        )

    def validate_input_compatibility(self, ai_tool) -> Tuple[bool, Optional[str]]:
        """zm_u24 无参考视频槽：带视频任务切到本实现会静默丢视频参考，判不兼容。

        解析异常不在这里吞掉。候选选择见到钩子抛错会跳过本实现，
        避免把带视频的任务误判成兼容后静默丢掉参考视频。
        """
        raw_video = self.get_video_path(ai_tool)
        if raw_video and str(raw_video).strip():
            return False, "AutoDL 参考生工作流无参考视频槽，带参考视频的任务不适用"
        return True, None

    def build_create_request(self, ai_tool) -> Dict[str, Any]:
        """构建 zm_u24 提交请求（参考图/音频逐槽转公网 URL）"""
        extra_config = self._parse_extra_config(ai_tool)

        # 1. 解析图片模式：参考生视频走多参考图模式
        image_info = self.get_all_images_by_mode(ai_tool)
        img_mode = image_info['mode']
        reference_images = image_info.get('reference_images', [])

        # 兼容：若误用了首尾帧模式，将首尾帧作为参考图补救（与 RunningHub 参考生驱动一致）
        if not reference_images and img_mode in (ImageMode.FIRST_LAST_FRAME, ImageMode.FIRST_LAST_WITH_REF):
            first_frame = image_info.get('first_frame')
            last_frame = image_info.get('last_frame')
            if first_frame:
                reference_images = [first_frame]
                if last_frame:
                    reference_images.append(last_frame)
                self.logger.warning(f"AutoDL 参考生视频收到 {img_mode} 模式，已将首尾帧作为参考图处理")

        if not reference_images:
            return {
                "success": False,
                "error": "AutoDL 参考生视频任务需要至少1张参考图",
                "error_type": "USER",
                "retry": False
            }

        if len(reference_images) > MAX_REFERENCE_IMAGES:
            self.logger.warning(
                f"AutoDL 参考生视频最多支持{MAX_REFERENCE_IMAGES}张参考图，已忽略多余的图"
            )
            reference_images = reference_images[:MAX_REFERENCE_IMAGES]

        # 2. 逐张转公网 URL（本地/局域网压缩上传 CDN）
        payload = self._build_base_payload(ai_tool, extra_config, "")
        for idx, image_path in enumerate(reference_images):
            url, error = self._to_public_image_url(image_path, f"参考图{idx + 1}")
            if error:
                return {
                    "success": False,
                    "error": error,
                    "error_type": "USER",
                    "retry": False
                }
            payload[f"ref_image_{idx}"] = url

        # 3. 提示词 + 参考音频（无对白镜头自动跳过音频，口径同 RunningHub 参考生驱动）
        prompt_text, audios = self._resolve_prompt_and_audios(ai_tool, extra_config)
        payload["prompt"] = prompt_text
        for idx, audio_path in enumerate(audios):
            url, error = self._to_public_media_url(audio_path, f"参考音频{idx + 1}")
            if error:
                return {
                    "success": False,
                    "error": error,
                    "error_type": "USER",
                    "retry": False
                }
            payload[f"ref_audio_{idx}"] = url

        # 4. 参考视频：zm_u24 无视频槽，丢弃（正常提交路径走不到这里——带视频任务在
        # validate_input_compatibility 已判不兼容，不会被切到本实现；仅默认实现被管理员
        # 手动切到 AutoDL 时可能发生，warning 留痕便于排查"成片怎么没用上参考视频"）
        raw_video = self.get_video_path(ai_tool)
        if raw_video and str(raw_video).strip():
            self.logger.warning("AutoDL 参考生视频工作流不支持参考视频，已忽略视频输入（成片将不含视频参考）")

        return {
            "url": f"{self._base_url}/api/v1/comfyui/comfyui_workflow/{self._workflow_id}",
            "method": "POST",
            "json": payload,
            "headers": self._auth_headers(),
        }


class MinimaxH3FirstLastAutodlV1Driver(MinimaxH3AutodlV1Driver):
    """
    MiniMax H3 首尾帧图生视频（AutoDL.Art 工作流 minimax_h3_lightx2v）

    请求体素材槽位：
    - first_frame（必填）：首帧图片公网 URL
    - last_frame（必填）：尾帧图片公网 URL（2026-11-08 三重实测证实上游强校验：
      事故 ai_tools 13442 仅首帧提交报"缺少必填参数：last_frame"；直接探测
      first_frame 单独同报错、ref_image_0 报"未定义的参数"。曾据 zm_u24 单图
      测试误判"尾帧可选"并短暂放开，已回滚。上游改为可选后可再放开）
    - 无音频槽（lightx2v 工作流不收参考音频，audio_path 输入忽略）
    """

    def __init__(self):
        super().__init__(
            driver_type=TaskTypeId.MINIMAX_H3_IMAGE_TO_VIDEO,
            workflow_id=AUTODL_WORKFLOW_FIRST_LAST,
            impl_name=DriverImplementation.MINIMAX_H3_FIRST_LAST_AUTODL_V1,
        )

    def validate_input_compatibility(self, ai_tool) -> Tuple[bool, Optional[str]]:
        """
        lightx2v 首尾帧双必填（上游强校验，见类 docstring），任务 34 尾帧可选
        （supports_last_frame=True）：单首帧任务切到本实现必然 USER 失败，
        提前判不兼容换下一个候选（未锁定时自动落回 RunningHub 实现）。
        （无首帧属参数错误，RunningHub 实现同样失败，不在此拦，留给驱动报准确错误。）
        """
        image_info = self.get_all_images_by_mode(ai_tool)
        if image_info.get('first_frame') and not image_info.get('last_frame'):
            return False, "AutoDL 首尾帧工作流要求尾帧必填，当前任务仅有首帧"
        return True, None

    def build_create_request(self, ai_tool) -> Dict[str, Any]:
        """构建 lightx2v 提交请求（首尾帧转公网 URL，双必填）"""
        extra_config = self._parse_extra_config(ai_tool)

        image_info = self.get_all_images_by_mode(ai_tool)
        first_frame = image_info.get('first_frame')
        last_frame = image_info.get('last_frame')

        if not first_frame:
            return {
                "success": False,
                "error": "首尾帧模式需要至少1张首帧图片",
                "error_type": "USER",
                "retry": False
            }
        # 上游强校验：first_frame / last_frame 均为必填（缺尾帧提前给用户明确错误，
        # 优于提交后才收到上游 400 参数错误）
        if not last_frame:
            return {
                "success": False,
                "error": "AutoDL 首尾帧工作流需要同时提供首帧和尾帧图片，请补充尾帧后重试",
                "error_type": "USER",
                "retry": False
            }

        first_url, first_error = self._to_public_image_url(first_frame, "首帧图片")
        if first_error:
            return {
                "success": False,
                "error": first_error,
                "error_type": "USER",
                "retry": False
            }
        last_url, last_error = self._to_public_image_url(last_frame, "尾帧图片")
        if last_error:
            return {
                "success": False,
                "error": last_error,
                "error_type": "USER",
                "retry": False
            }

        # lightx2v 无音频槽：提示词沿用 pipeline 优化结果，音频输入忽略
        prompt_text, _audios = self._resolve_prompt_and_audios(ai_tool, extra_config)
        if _audios:
            self.logger.info("AutoDL 首尾帧工作流不支持参考音频，已忽略音频输入")

        payload = self._build_base_payload(ai_tool, extra_config, prompt_text)
        payload["first_frame"] = first_url
        payload["last_frame"] = last_url

        return {
            "url": f"{self._base_url}/api/v1/comfyui/comfyui_workflow/{self._workflow_id}",
            "method": "POST",
            "json": payload,
            "headers": self._auth_headers(),
        }


class MinimaxH3CharReplaceAutodlV1Driver(MinimaxH3AutodlV1Driver):
    """
    MiniMax H3 视频人物替换（AutoDL.Art 工作流 minimax_h3_zm_titim，任务类型 54）

    用参考图里的角色替换引导视频中的角色：动作、位置、节奏、镜头与原声全部
    跟随参考视频，只换被点名主体的身份（服装/配饰同样跟随参考图）。

    请求体素材槽位：
    - ref_video（必填）：参考视频公网 URL（MP4/WebM；成片时长=duration，
      截取视频前 N 秒，短于 duration 的尾段由模型自由发挥）
    - ref_image_0（必填）~ ref_image_8：最多 9 张角色参考图（JPG/PNG/WebP 公网 URL）
    - prompt（选填）：指定谁换谁/保留什么/替换后走向（上游内置替换提示词，
      不支持完全自定义）
    - video_subject_to_replace（选填）：检测主体类型，必须英文，默认 person
    - duration：5-25 整数；resolution：仅 768p竖 / 768p横（跟随参考视频方向，
      端点 ffprobe 探测后写入 extra_config.resolution）
    """

    def __init__(self):
        super().__init__(
            driver_type=TaskTypeId.VIDEO_CHARACTER_REPLACE,
            workflow_id=AUTODL_WORKFLOW_CHARACTER_REPLACE,
            impl_name=DriverImplementation.MINIMAX_H3_CHAR_REPLACE_AUTODL_V1,
        )

    def _clamp_duration(self, ai_tool) -> int:
        """时长钳制到人物替换工作流合法区间 5-25 秒（覆盖基类 1-15）"""
        try:
            duration = int(ai_tool.duration or DEFAULT_DURATION_SECONDS)
        except (TypeError, ValueError):
            duration = DEFAULT_DURATION_SECONDS
        return (
            max(VIDEO_CHAR_REPLACE_MIN_DURATION_SECONDS,
                min(VIDEO_CHAR_REPLACE_MAX_DURATION_SECONDS, duration))
        )

    def _build_resolution_value(self, extra_config: Dict[str, Any]) -> str:
        """
        人物替换分辨率：端点 ffprobe 探测参考视频方向后写入
        extra_config.char_replace_resolution（'768p竖' / '768p横'），此处原样透传；
        缺省按视频方向兜底为 768p竖（上游默认值）。
        """
        resolution = extra_config.get(CHAR_REPLACE_RESOLUTION_EXTRA_KEY)
        if resolution in CHAR_REPLACE_RESOLUTION_VALUES:
            return resolution
        if resolution:
            self.logger.warning(
                f"人物替换收到未知 resolution {resolution}，回落 768p竖"
            )
        return '768p竖'

    def validate_input_compatibility(self, ai_tool) -> Tuple[bool, Optional[str]]:
        """zm_titim 参考视频必填：无视频任务切到本实现必然 USER 失败，提前判不兼容。

        参考图缺失同理（至少 1 张角色图）。此任务类型仅本一个实现方，
        钩子主要防管理员误挂载/误切默认实现，以及重试候选选择时的兜底。
        """
        raw_video = self.get_video_path(ai_tool)
        if not raw_video or not str(raw_video).strip():
            return False, "人物替换工作流需要参考视频，当前任务无视频输入"
        if not self.get_reference_images(ai_tool):
            return False, "人物替换工作流需要至少 1 张角色参考图"
        return True, None

    def build_create_request(self, ai_tool) -> Dict[str, Any]:
        """构建 zm_titim 提交请求（参考视频 + 角色图逐槽转公网 URL）"""
        extra_config = self._parse_extra_config(ai_tool)

        # 1. 参考视频（必填）：转公网 URL（不压缩，口径同音频媒体上传）
        raw_video = self.get_video_path(ai_tool)
        if not raw_video or not str(raw_video).strip():
            return {
                "success": False,
                "error": "视频人物替换需要上传参考视频",
                "error_type": "USER",
                "retry": False
            }
        video_url, video_error = self._to_public_media_url(str(raw_video).strip(), "参考视频")
        if video_error:
            return {
                "success": False,
                "error": video_error,
                "error_type": "USER",
                "retry": False
            }

        # 2. 角色参考图（至少 1 张，最多 9 张）：ai_tools.reference_images JSON 数组
        images = self.get_reference_images(ai_tool)
        if not images:
            return {
                "success": False,
                "error": "视频人物替换需要至少 1 张角色参考图",
                "error_type": "USER",
                "retry": False
            }
        if len(images) > MAX_REFERENCE_IMAGES:
            self.logger.warning(
                f"AutoDL 人物替换最多支持{MAX_REFERENCE_IMAGES}张参考图，已忽略多余的图"
            )
            images = images[:MAX_REFERENCE_IMAGES]

        # 3. 提示词（选填）：上游已内置替换提示词，用户 prompt 仅用于指定谁换谁/
        #    保留什么等增量描述，不走 H3 提示词优化 pipeline（无音频槽，无对白概念）
        payload = {
            "prompt": (ai_tool.prompt or "").strip()[:2048],
            "duration": self._clamp_duration(ai_tool),
            "resolution": self._build_resolution_value(extra_config),
            "ref_video": video_url,
        }

        for idx, image_path in enumerate(images):
            url, error = self._to_public_image_url(image_path, f"角色参考图{idx + 1}")
            if error:
                return {
                    "success": False,
                    "error": error,
                    "error_type": "USER",
                    "retry": False
                }
            payload[f"ref_image_{idx}"] = url

        # 4. 检测主体类型（选填，必须英文）：extra_config.params.subject 透传，
        #    空则不上传（上游默认检测 person）
        params = extra_config.get("params") if isinstance(extra_config.get("params"), dict) else {}
        subject = str(params.get("subject") or "").strip()
        if subject:
            payload["video_subject_to_replace"] = subject

        return {
            "url": f"{self._base_url}/api/v1/comfyui/comfyui_workflow/{self._workflow_id}",
            "method": "POST",
            "json": payload,
            "headers": self._auth_headers(),
        }
