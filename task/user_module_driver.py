"""用户模块媒体驱动 - 把已激活用户模块接入核心任务链路。

该驱动的实例不直接调用供应商 API，而是把 ``ai_tools`` 任务翻译为用户模块
媒体作业（module_job），由 UserModuleService + Supervisor 执行：

- ``submit_task``（异步）：创建 module_job 并触发分发，``project_id`` 存 job_id；
- ``check_status``（同步）：只读 module_job 表翻译状态，不发 RPC。作业的实际
  轮询/回调推进由 scheduler 的 ``process_user_module_jobs``（每 3 秒）和
  webhook 回调独立完成，与 ai_tasks 调度天然解耦。

驱动参数（module_id / operation / task_id / impl_name）由绑定时生成的
ImplementationConfig.driver_params 注入；无参实例化仅用于可用性探测，
不触网、不读库。
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

from task.visual_drivers.base_video_driver import BaseVideoDriver

from config.constant import (
    IMAGE_UPLOAD_SYNC_WRAPPER_TIMEOUT,
    USER_MODULE_OPERATION_MEDIA_KINDS,
)

logger = logging.getLogger(__name__)

# module_job 状态 → 驱动协议状态
_RUNNING_JOB_STATUSES = {"queued", "submitted", "running", "paused", "incompatible"}


def _http_urls(values) -> List[str]:
    """过滤出完整的 http/https URL（MediaRef.url 仅接受该格式）。"""
    if not values:
        return []
    if isinstance(values, str):
        try:
            values = json.loads(values)
        except (TypeError, json.JSONDecodeError):
            values = [v.strip() for v in values.split(",") if v.strip()]
    result = []
    for value in values:
        if isinstance(value, str) and value.lower().startswith(("http://", "https://")):
            result.append(value)
    return result


class UserModuleMediaDriver(BaseVideoDriver):
    """用户模块通用媒体驱动。

    一个实例服务于一个绑定（module_id + operation），由 driver_params 注入；
    实例本身无状态，可被工厂反复创建。
    """

    def __init__(
        self,
        module_id: str = "",
        operation: str = "",
        task_id: int = 0,
        impl_name: str = "",
    ):
        self.module_id = module_id
        self.operation = operation
        self.binding_task_id = int(task_id or 0)
        self._config_cache: Optional[Dict[str, Any]] = None
        resolved_impl = impl_name or f"user_module:{module_id}:{operation}"
        super().__init__(resolved_impl, self.binding_task_id)

    # ------------------------------------------------------------------ #
    # 参数映射
    # ------------------------------------------------------------------ #

    def _parse_extra_config(self, ai_tool) -> Dict[str, Any]:
        if not getattr(ai_tool, "extra_config", None):
            return {}
        raw = ai_tool.extra_config
        if isinstance(raw, dict):
            return raw
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, json.JSONDecodeError):
            self.logger.warning("无法解析 extra_config: %s", raw)
            return {}

    def _collect_media_urls(self, ai_tool) -> Dict[str, List[str]]:
        """按图片模式收集 http 引用 URL，返回 {first, last, reference, direct}。"""
        collected: Dict[str, List[str]] = {"first": [], "last": [], "reference": [], "direct": []}
        try:
            frames = self.get_all_images_by_mode(ai_tool)
            collected["first"] = _http_urls(frames.get("first_frame"))
            collected["last"] = _http_urls(frames.get("last_frame"))
            collected["reference"] = _http_urls(frames.get("reference_images"))
        except Exception:
            self.logger.warning("解析图片模式失败，退化为直接读取 image_path/reference_images")
        collected["direct"] = _http_urls(getattr(ai_tool, "image_path", None))
        return collected

    def _build_inputs(self, media_kind: str, urls: List[str]) -> List[Dict[str, Any]]:
        """把任务携带的图片/视频引用转换为 MediaRef 列表（仅完整 http URL）。"""
        from module_runtime.protocol import MediaRef

        inputs = []
        for url in urls[:32]:
            inputs.append(MediaRef(media_kind=media_kind, url=url).model_dump(mode="json"))
        return inputs

    def _build_parameters(self, ai_tool, urls: Dict[str, List[str]]) -> Dict[str, Any]:
        """非媒体引用的标量参数原样透传，由模块按自身契约处理。"""
        parameters: Dict[str, Any] = {}
        for field in ("ratio", "duration", "image_size"):
            value = getattr(ai_tool, field, None)
            if value not in (None, ""):
                parameters[field] = value
        parameters.update(self._parse_extra_config(ai_tool))
        self._normalize_resolution_key(parameters)
        self._apply_media_parameter_compat(parameters, urls)
        self._apply_ratio_alias(parameters)
        return parameters

    @staticmethod
    def _apply_ratio_alias(parameters: Dict[str, Any]) -> None:
        """比例冗余键：核心标准键是 ratio（简式如 "16:9"），供应商模块契约常声明
        aspect_ratio。值保持简式，模块侧按前缀+大小写不敏感匹配映射到自己的枚举文本
        （见生成合同「平台标准参数键与取参规则」）。不覆盖 extra_config 显式传入值。"""
        ratio = parameters.get("ratio")
        if ratio:
            parameters.setdefault("aspect_ratio", ratio)

    @staticmethod
    def _normalize_resolution_key(parameters: Dict[str, Any]) -> None:
        """核心把分辨率存为 extra_config.video_resolution（legacy 为 resolution）或
        文生图链路的 ai_tools.image_size，统一规范化为模块契约的 resolution 键。"""
        from config.constant import (
            LEGACY_RESOLUTION_EXTRA_CONFIG_KEY,
            VIDEO_RESOLUTION_EXTRA_CONFIG_KEY,
        )

        resolution = parameters.pop(VIDEO_RESOLUTION_EXTRA_CONFIG_KEY, None)
        legacy = parameters.pop(LEGACY_RESOLUTION_EXTRA_CONFIG_KEY, None)
        # 文生图把档位存 ai_tools.image_size（如 "1K"）；保留原键，仅在其余来源缺省时补 resolution
        image_size = parameters.get("image_size")
        value = resolution or legacy or image_size
        if value:
            # 模块 request_schema 契约的分辨率键名（与 legacy 键同名）
            parameters["resolution"] = value

    def _apply_media_parameter_compat(self, parameters: Dict[str, Any], urls: Dict[str, List[str]]) -> None:
        """媒体引用兼容映射：部分模块按参数名（而非 inputs）接收引用。

        核心按 media-driver/v1 契约把引用放 inputs；同时把 URL 以通用参数名冗余
        写入 parameters，保证只读参数的模块也能拿到图片。不覆盖显式传入的值。
        """
        if self.operation in ("text_to_image", "image_edit"):
            single = urls["direct"] or urls["first"]
            if single:
                parameters.setdefault("image_url", single[0])
            if len(single) > 1 and self.operation == "image_edit":
                parameters.setdefault("reference_images", single[1:])
            return
        if urls["first"]:
            parameters.setdefault("first_frame_image", urls["first"][0])
        if urls["last"]:
            parameters.setdefault("last_frame_image", urls["last"][0])
        if urls["reference"]:
            parameters.setdefault("reference_images", urls["reference"])
        if not urls["first"] and not urls["last"] and not urls["reference"] and urls["direct"]:
            parameters.setdefault("image_url", urls["direct"][0])

    async def _ensure_public_urls(self, urls: List[str]) -> List[str]:
        """把本地/局域网媒体 URL 上传 CDN 图床，确保外部供应商可访问。

        与其他核心驱动（如 kling_duomi_v1）的 ensure_public_urls 逻辑一致；
        使用异步版本避免跨线程包装。上传失败或超时回退原始 URL。
        """
        if not urls:
            return urls
        try:
            from utils.image_upload_utils import upload_local_images_to_cdn

            cdn_urls = await asyncio.wait_for(
                upload_local_images_to_cdn(urls, self._upload_config()),
                timeout=IMAGE_UPLOAD_SYNC_WRAPPER_TIMEOUT,
            )
        except Exception:
            self.logger.exception("上传媒体到 CDN 图床失败，使用原始 URL")
            return urls
        if not cdn_urls:
            return urls
        # 单项失败可能返回 None，回填原始 URL
        return [cdn or url for cdn, url in zip(cdn_urls, urls)]

    async def _publicize_media_urls(self, urls: Dict[str, List[str]]) -> Dict[str, str]:
        """把四类媒体引用统一公网化并原位回填，返回 原URL→公网URL 映射。

        历史缺陷：只回填 first/last/reference；image_edit 场景 direct 与 first
        收集到同一张局域网图，direct 残留内网地址进入 parameters.image_url，
        外部供应商拉不到图（真实事故：runninghub.qweniamgeeidtv2，module_job
        aitool-1129 提交成功但 RunningHub 拉图失败）。现按去重全集一次转换，
        四类统一按映射回填。
        """
        unique: List[str] = []
        seen = set()
        for key in ("first", "last", "reference", "direct"):
            for url in urls.get(key) or ():
                if url not in seen:
                    seen.add(url)
                    unique.append(url)
        if not unique:
            return {}
        public = await self._ensure_public_urls(unique)
        if len(public) < len(unique):
            # upload_local_images_to_cdn 会丢弃空项导致结果变短；按位兜底防错位
            public = list(public) + unique[len(public):]
        url_map = {raw: converted for raw, converted in zip(unique, public)}
        for key in list(urls):
            urls[key] = [url_map.get(url, url) for url in urls[key]]
        return url_map

    @staticmethod
    def _remap_parameter_urls(
        parameters: Dict[str, Any], url_map: Dict[str, str]
    ) -> Dict[str, Any]:
        """按公网化映射替换 parameters 中重复携带的媒体 URL。

        extra_config 原样透传，可能重复携带 image_path 的局域网地址；已知映射的
        一律替换为公网 URL，防止内网地址泄漏给外部供应商模块。
        """
        if not url_map:
            return parameters

        def _remap(value: Any) -> Any:
            if isinstance(value, str):
                return url_map.get(value, value)
            if isinstance(value, list):
                return [_remap(item) for item in value]
            return value

        return {key: _remap(value) for key, value in parameters.items()}

    def _upload_config(self) -> Dict[str, Any]:
        if self._config_cache is None:
            from config.config_util import get_config

            self._config_cache = get_config()
        return self._config_cache

    # ------------------------------------------------------------------ #
    # BaseVideoDriver 协议实现
    # ------------------------------------------------------------------ #

    async def submit_task(self, ai_tool) -> Dict[str, Any]:
        """创建用户模块媒体作业；project_id 返回 module_job.job_id。"""
        from services.user_module_service import UserModuleServiceError, get_user_module_service

        if not self.module_id or not self.operation:
            return {
                "success": False,
                "error": "用户模块驱动配置不完整",
                "error_type": "SYSTEM",
                "error_detail": f"缺少绑定参数: module_id={self.module_id}, operation={self.operation}",
                "retry": False,
            }

        media_kind = USER_MODULE_OPERATION_MEDIA_KINDS.get(self.operation)
        if not media_kind:
            return {
                "success": False,
                "error": f"不支持的用户模块能力: {self.operation}",
                "error_type": "SYSTEM",
                "retry": False,
            }

        urls = self._collect_media_urls(ai_tool)
        # 全类别统一公网化（含 direct），否则 parameters.image_url 会泄漏局域网地址
        url_map = await self._publicize_media_urls(urls)
        ordered = urls["first"] + urls["last"] + urls["reference"] or urls["direct"]
        parameters = self._remap_parameter_urls(self._build_parameters(ai_tool, urls), url_map)

        try:
            service = get_user_module_service()
            job = await service.create_media_job(
                module_id=self.module_id,
                requester_id=str(ai_tool.user_id),
                operation=self.operation,
                media_kind=media_kind,
                prompt=ai_tool.prompt,
                inputs=self._build_inputs(media_kind, ordered),
                parameters=parameters,
                # 幂等键保证调度层重试提交时复用同一作业，不会重复扣费/生成
                idempotency_key=f"aitool-{ai_tool.id}",
            )
        except UserModuleServiceError as exc:
            retry = exc.code in {"SUPERVISOR_NOT_CONFIGURED", "MODULE_UNAVAILABLE"}
            return {
                "success": False,
                "error": f"模块任务创建失败: {exc}",
                "error_type": "USER" if exc.code in {"MODULE_UNAVAILABLE", "OPERATION_NOT_FOUND"} else "SYSTEM",
                "error_detail": f"[{exc.code}] {exc}",
                "retry": retry,
            }
        except Exception as exc:  # noqa: BLE001 - 转换为驱动错误协议
            self.logger.exception("创建模块任务异常")
            return {
                "success": False,
                "error": "模块任务创建异常，请稍后重试",
                "error_type": "SYSTEM",
                "error_detail": str(exc),
                "retry": True,
            }

        # 立即分发加速首跳；失败不致命，scheduler 每 3 秒兜底捞 queued 作业
        try:
            await service.dispatch_job(job.job_id)
        except Exception:
            self.logger.warning("模块任务即时分发失败，等待调度器兜底: %s", job.job_id, exc_info=True)

        return {"success": True, "project_id": job.job_id}

    def check_status(self, project_id: str) -> Dict[str, Any]:
        """翻译 module_job 状态；只读数据库，轮询推进由模块调度器独立完成。"""
        from model.user_modules import ModuleJobsModel, ModuleJobStatus

        job = ModuleJobsModel.get(project_id)
        if not job:
            return {
                "status": "FAILED",
                "error": "模块任务记录不存在",
                "error_type": "SYSTEM",
            }

        if job.status == ModuleJobStatus.SUCCEEDED:
            result_url = self._extract_result_url(job)
            if not result_url:
                return {
                    "status": "FAILED",
                    "error": "模块任务成功但未返回可用的媒体 URL",
                    "error_type": "SYSTEM",
                }
            return {"status": "SUCCESS", "result_url": result_url}

        if job.status in _RUNNING_JOB_STATUSES:
            return {"status": "RUNNING"}

        # failed / timed_out / cancelled 等终态
        error_message = "模块任务失败"
        if isinstance(job.error, dict):
            error_message = str(job.error.get("message") or job.error.get("code") or error_message)
        elif job.error:
            error_message = str(job.error)
        if job.status == ModuleJobStatus.TIMED_OUT:
            error_message = "模块任务执行超时"
        return {
            "status": "FAILED",
            "error": error_message,
            "error_type": "USER" if job.status == ModuleJobStatus.FAILED else "SYSTEM",
        }

    @staticmethod
    def _extract_result_url(job) -> Optional[str]:
        result = job.result or {}
        outputs = result.get("outputs") or []
        for output in outputs:
            if isinstance(output, dict) and output.get("url"):
                return output["url"]
        return None

    def build_create_request(self, ai_tool) -> Dict[str, Any]:
        # 用户模块经 Supervisor RPC 提交，不走 HTTP 请求构造；占位满足基类抽象
        return {"url": "", "method": "POST", "json": {}, "headers": {}}

    def build_check_query(self, project_id: str) -> Dict[str, Any]:
        return {"url": "", "method": "GET", "json": {}, "headers": {}}
