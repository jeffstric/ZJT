"""
MiniMax H3 参考生视频 RunningHub v1 版本驱动实现

支持多参考图（最多 9 张）+ 参考视频（最多 2 个）+ 参考音频（最多 2 个）生成视频，
通过 RunningHub AI-App 接口调用「MiniMax H3 多参生视频」工作流。
webapp_id: 2086470155902734337

提示词优化：提交前由 param_prepare 的 h3_prompt_optimize 步骤按 Ref2VA 规范改写，
驱动优先读取 extra_config.h3_prompt_optimize.optimized_prompt，回退 ai_tool.prompt。

参数注入节点 nodeId：
  - 参考图1~9   → nodeId 137/139/142/147/149/150/151/152/153 fieldName=image (LoadImage)
                  顺序填入，未使用的节点 fieldValue 留空，避免 RunningHub 用节点默认值
  - 参考音频1~2 → nodeId 155/163 fieldName=audio (LoadAudio)，独立参考音频，未用留空
  - 参考视频1~2 → nodeId 158/164 fieldName=video (VHS_LoadVideo)，未用留空
  - 提示词      → nodeId 138 fieldName=value         (文本)
  - 时长(秒)    → nodeId 132 fieldName=value         (INTConstant)
  - 比例        → nodeId 115 fieldName=aspect_ratio  (ResolutionSelector，带括号完整文本，带 fieldData)
  - 分辨率      → nodeId 115 fieldName=megapixels    (ResolutionSelector，0.4/0.9)
"""
import json
from typing import Dict, Any, Optional, Tuple
import traceback
from .base_video_driver import BaseVideoDriver, ImageMode
from config.config_util import get_config, get_dynamic_config_value
from config.unified_config import TaskTypeId, VideoResolution
from config.constant import VIDEO_RESOLUTION_EXTRA_CONFIG_KEY, LEGACY_RESOLUTION_EXTRA_CONFIG_KEY
from utils.sentry_util import SentryUtil, AlertLevel
from utils.file_storage import RunningHubFileStorage
from utils.runninghub_error import is_upstream_congested_error
from .exceptions import ImageExpiredError


# 参考图固定 nodeId 列表（对应工作流中的图1~图9 LoadImage 节点，顺序敏感）
REFERENCE_IMAGE_NODE_IDS = ["137", "139", "142", "147", "149", "150", "151", "152", "153"]

# 最大参考图数量
MAX_REFERENCE_IMAGES = 9

# 参考音频固定 nodeId 列表（LoadAudio，独立参考音频，非参考视频音轨）
REFERENCE_AUDIO_NODE_IDS = ["155", "163"]

# 最大参考音频数量
MAX_REFERENCE_AUDIOS = 2

# 参考视频固定 nodeId 列表（VHS_LoadVideo）
REFERENCE_VIDEO_NODE_IDS = ["158", "164"]

# 最大参考视频数量
MAX_REFERENCE_VIDEOS = 2

# 比例 → ResolutionSelector(nodeId=115) aspect_ratio COMBO 完整文本
RATIO_TO_ASPECT_RATIO_VALUE = {
    '1:1': '1:1 (Square)',
    '16:9': '16:9 (Widescreen)',
    '9:16': '9:16 (Portrait Widescreen)',
    '4:3': '4:3 (Standard)',
    '3:4': '3:4 (Portrait Standard)',
    '2:3': '2:3 (Portrait Photo)',
    '3:2': '3:2 (Photo)',
    '21:9': '21:9 (Ultrawide)',
}

# 默认分辨率（megapixels），对应 720P
DEFAULT_MEGAPIXELS = VideoResolution.MINIMAX_H3_DRIVER_VALUES[VideoResolution.P720]

# aspect_ratio 节点的 fieldData（COMBO 元数据，按工作流定义原样传入）
ASPECT_RATIO_FIELD_DATA = (
    '["COMBO", {"default": "1:1 (Square)", "options": '
    '["1:1 (Square)", "2:3 (Portrait Photo)", "3:2 (Photo)", '
    '"3:4 (Portrait Standard)", "4:3 (Standard)", '
    '"9:16 (Portrait Widescreen)", "16:9 (Widescreen)", "21:9 (Ultrawide)"], '
    '"tooltip": "The aspect ratio for the output dimensions.", "multiselect": false}]'
)


class MinimaxH3ReferenceRunninghubV1Driver(BaseVideoDriver):
    """
    MiniMax H3 参考生视频 RunningHub v1 版本驱动
    支持多参考图（最多 9 张）生成视频
    """

    def __init__(self):
        super().__init__(driver_name="minimax_h3_reference_runninghub_v1", driver_type=TaskTypeId.MINIMAX_H3_REFERENCE_TO_VIDEO)

        # 加载配置
        self._api_key = get_dynamic_config_value("runninghub", "api_key", default="")
        self._host = get_dynamic_config_value("runninghub", "host", default="")
        # MiniMax H3 多参生视频工作流 webapp ID（自有账号复制版应用，节点结构与原公共应用 2084224746308325377 一致）
        self._webapp_id = "2086470155902734337"
        self._timeout = get_dynamic_config_value("timeout", "request_timeout", default=30)

        # 是否为本地环境
        self._is_local = get_dynamic_config_value("server", "is_local", default=False)
        self._config = get_config()

        # 初始化 RunningHub 文件存储
        self._storage = RunningHubFileStorage(
            host=self._host,
            api_key=self._api_key,
            config=self._config,
            logger=self.logger
        )

        self._validate_required({
            "RunningHub API Key": self._api_key,
            "RunningHub Host": self._host,
        })

    def _send_alert(self, alert_type: str, message: str, context: Optional[Dict[str, Any]] = None):
        """
        发送报警信息

        Args:
            alert_type: 报警类型，如 "INVALID_RESPONSE_FORMAT", "UNEXPECTED_EXCEPTION"
            message: 报警消息
            context: 上下文信息（可选）
        """
        SentryUtil.send_alert(
            alert_type=alert_type,
            message=message,
            level=AlertLevel.ERROR,
            context=context
        )

    def _validate_submit_response(self, result: Any) -> tuple[bool, Optional[str]]:
        """
        验证 submit_task API 响应格式

        Args:
            result: API 响应结果

        Returns:
            tuple[bool, Optional[str]]: (是否有效, 错误信息)
        """
        if not isinstance(result, dict):
            return False, f"响应不是字典类型，实际类型: {type(result)}"

        if "taskId" not in result:
            return False, f"响应缺少 'taskId' 字段，实际字段: {list(result.keys())}"

        if "status" not in result:
            return False, f"响应缺少 'status' 字段，实际字段: {list(result.keys())}"

        return True, None

    def _ratio_to_aspect_ratio_value(self, ratio: str) -> str:
        """
        将视频比例映射为 RunningHub 工作流 aspect_ratio 节点的完整文本值

        Args:
            ratio: 视频比例，如 "9:16", "16:9"

        Returns:
            str: aspect_ratio 完整文本，如 "9:16 (Portrait Widescreen)"
        """
        return RATIO_TO_ASPECT_RATIO_VALUE.get(ratio, '9:16 (Portrait Widescreen)')  # 默认 9:16

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

    def _get_megapixels(self, extra_config: Dict[str, Any]) -> str:
        """
        从 extra_config 读取分辨率并映射为 ResolutionSelector 的 megapixels 值

        Args:
            extra_config: 解析后的额外配置字典

        Returns:
            str: megapixels 值（"0.4" / "0.9"），取不到时默认 720P（"0.9"）
        """
        resolution = (
            extra_config.get(VIDEO_RESOLUTION_EXTRA_CONFIG_KEY)
            or extra_config.get(LEGACY_RESOLUTION_EXTRA_CONFIG_KEY)
        )
        if not resolution:
            return DEFAULT_MEGAPIXELS
        return VideoResolution.MINIMAX_H3_DRIVER_VALUES.get(
            str(resolution).upper(), DEFAULT_MEGAPIXELS
        )

    async def _upload_image_to_runninghub(self, image_path: str, description: str) -> str:
        """
        上传图片到 RunningHub 图床并返回可用的 fieldValue

        Args:
            image_path: 图片路径（本地路径或 URL）
            description: 图片描述（用于日志）

        Returns:
            str: 上传后的图片标识（download_url 或 fileName）

        Raises:
            RuntimeError: 上传失败时抛出
        """
        self.logger.info(f"准备上传{description}到 RunningHub 图床: {image_path}")
        result = await self._storage.upload_file("", image_path)
        if result.success:
            uploaded_path = result.url if result.url else result.key
            self.logger.info(f"{description}上传完成，使用标识: {uploaded_path}")
            return uploaded_path
        else:
            raise RuntimeError(f"{description}上传到 RunningHub 失败: {result.error}")

    @staticmethod
    def _split_reference_paths(raw) -> list:
        """解析参考音频/视频路径（ai_tools 落库格式为逗号分隔 URL 字符串）。"""
        if not raw:
            return []
        if isinstance(raw, list):
            return [str(item).strip() for item in raw if str(item).strip()]
        return [item.strip() for item in str(raw).split(",") if item.strip()]

    async def _upload_reference_media(self, media_path: str, description: str) -> str:
        """
        上传参考音频/视频到 RunningHub 并返回 fileName（LoadAudio/VHS_LoadVideo 节点引用标识，
        与数字人 H3 驱动的音频节点取值一致）

        Args:
            media_path: 音频/视频路径（本地路径或 URL）
            description: 媒体描述（用于日志）

        Returns:
            str: 上传后的文件标识（fileName 优先，回退 download_url）

        Raises:
            RuntimeError: 上传失败时抛出
        """
        self.logger.info(f"准备上传{description}到 RunningHub: {media_path}")
        result = await self._storage.upload_file("", media_path)
        if result.success:
            uploaded_path = result.key if result.key else result.url
            self.logger.info(f"{description}上传完成，使用 fileName: {uploaded_path}")
            return uploaded_path
        else:
            raise RuntimeError(f"{description}上传到 RunningHub 失败: {result.error}")

    async def build_create_request(self, ai_tool) -> Dict[str, Any]:
        """
        构建创建 MiniMax H3 参考生视频任务的完整请求参数

        多参考资产模式（节点映射）：
        - 参考图1~9 → nodeId 137/139/142/147/149/150/151/152/153 (image，LoadImage)
                      顺序填入，未使用的节点 fieldValue 留空（避免 RunningHub 用节点默认值）
        - 参考音频1~2 → nodeId 155/163 (audio，LoadAudio)，独立参考音频，未用留空
        - 参考视频1~2 → nodeId 158/164 (video，VHS_LoadVideo)，未用留空
        - 提示词 → nodeId 138 (value，文本)
        - 时长（秒）→ nodeId 132 (value，INTConstant)
        - 比例 → nodeId 115 (aspect_ratio，带括号完整文本，带 fieldData)
        - 分辨率 → nodeId 115 (megapixels)

        Args:
            ai_tool: AITool 对象

        Returns:
            Dict[str, Any]: 请求参数字典
        """
        # 解析图片模式：参考生视频走多参考图模式
        image_info = self.get_all_images_by_mode(ai_tool)
        img_mode = image_info['mode']
        reference_images = image_info.get('reference_images', [])

        self.logger.info(
            f"MiniMax H3 参考生视频驱动图片模式: {img_mode}, 参考图: {len(reference_images)}张"
        )

        # 兼容：若误用了首尾帧模式，尝试从 image_path 补救
        if not reference_images and img_mode in (ImageMode.FIRST_LAST_FRAME, ImageMode.FIRST_LAST_WITH_REF):
            first_frame = image_info.get('first_frame')
            last_frame = image_info.get('last_frame')
            if first_frame:
                reference_images = [first_frame]
                if last_frame:
                    reference_images.append(last_frame)
                self.logger.warning(
                    f"MiniMax H3 参考生视频收到 {img_mode} 模式，已将首尾帧作为参考图处理"
                )

        if not reference_images:
            raise ValueError("MiniMax H3 参考生视频任务需要至少1张参考图")

        # 超出最大数量截断
        if len(reference_images) > MAX_REFERENCE_IMAGES:
            self.logger.warning(
                f"MiniMax H3 参考生视频最多支持{MAX_REFERENCE_IMAGES}张参考图，已忽略多余的图"
            )
            reference_images = reference_images[:MAX_REFERENCE_IMAGES]

        # 逐个上传参考图
        uploaded_images = []
        for idx, image_path in enumerate(reference_images):
            uploaded = await self._upload_image_to_runninghub(image_path, f"参考图{idx + 1}")
            uploaded_images.append(uploaded)

        # 参考音频/参考视频（可选，独立映射 LoadAudio / VHS_LoadVideo 节点，超量截断）
        reference_audios = self._split_reference_paths(getattr(ai_tool, "audio_path", None))
        if len(reference_audios) > MAX_REFERENCE_AUDIOS:
            self.logger.warning(
                f"MiniMax H3 参考生视频最多支持{MAX_REFERENCE_AUDIOS}个参考音频，已忽略多余的音频"
            )
            reference_audios = reference_audios[:MAX_REFERENCE_AUDIOS]
        reference_videos = self._split_reference_paths(getattr(ai_tool, "video_path", None))
        if len(reference_videos) > MAX_REFERENCE_VIDEOS:
            self.logger.warning(
                f"MiniMax H3 参考生视频最多支持{MAX_REFERENCE_VIDEOS}个参考视频，已忽略多余的视频"
            )
            reference_videos = reference_videos[:MAX_REFERENCE_VIDEOS]
        uploaded_audios = []
        for idx, audio_path in enumerate(reference_audios):
            uploaded_audios.append(await self._upload_reference_media(audio_path, f"参考音频{idx + 1}"))
        uploaded_videos = []
        for idx, video_path in enumerate(reference_videos):
            uploaded_videos.append(await self._upload_reference_media(video_path, f"参考视频{idx + 1}"))

        # 获取时长
        duration = ai_tool.duration or 5

        # 获取比例并映射为 aspect_ratio 完整文本（带括号）
        ratio = ai_tool.ratio or '9:16'
        aspect_ratio_value = self._ratio_to_aspect_ratio_value(ratio)

        # 从 extra_config 解析分辨率并映射为 megapixels
        extra_config = self._parse_extra_config(ai_tool)
        megapixels_value = self._get_megapixels(extra_config)

        # 构建提示词：优先使用 pipeline 优化结果（Ref2VA 改写），原文已备份在 extra_config.original_prompt
        prompt_meta = extra_config.get("h3_prompt_optimize") if isinstance(extra_config, dict) else None
        if isinstance(prompt_meta, dict) and prompt_meta.get("optimized_prompt"):
            prompt_text = str(prompt_meta.get("optimized_prompt") or "")
        else:
            prompt_text = ai_tool.prompt or ""

        # 构建 nodeInfoList
        # - nodeId 137/139/142/147/149/150/151/152/153 image  参考图1~9
        #   顺序填入上传后的图标识，未使用的节点 fieldValue 留空（避免 RunningHub 用节点默认值）
        # - nodeId 155/163 audio         参考音频1~2（LoadAudio，fileName，未用留空）
        # - nodeId 158/164 video         参考视频1~2（VHS_LoadVideo，fileName，未用留空）
        # - nodeId 138 value           提示词（文本）
        # - nodeId 132 value           时长（秒，INTConstant）
        # - nodeId 115 aspect_ratio    比例（带括号完整文本，带 fieldData）
        # - nodeId 115 megapixels      分辨率（0.4/0.9）
        node_info_list = []
        for idx, node_id in enumerate(REFERENCE_IMAGE_NODE_IDS):
            field_value = uploaded_images[idx] if idx < len(uploaded_images) else ""
            node_info_list.append({
                "nodeId": node_id,
                "fieldName": "image",
                "fieldValue": field_value,
                "description": f"图{idx + 1}"
            })

        for idx, node_id in enumerate(REFERENCE_AUDIO_NODE_IDS):
            field_value = uploaded_audios[idx] if idx < len(uploaded_audios) else ""
            node_info_list.append({
                "nodeId": node_id,
                "fieldName": "audio",
                "fieldValue": field_value,
                "description": f"参考音频{idx + 1}"
            })

        for idx, node_id in enumerate(REFERENCE_VIDEO_NODE_IDS):
            field_value = uploaded_videos[idx] if idx < len(uploaded_videos) else ""
            node_info_list.append({
                "nodeId": node_id,
                "fieldName": "video",
                "fieldValue": field_value,
                "description": f"参考视频{idx + 1}"
            })

        node_info_list.append({
            "nodeId": "138",
            "fieldName": "value",
            "fieldValue": prompt_text,
            "description": "提示词"
        })
        node_info_list.append({
            "nodeId": "132",
            "fieldName": "value",
            "fieldValue": str(duration),
            "description": "视频秒数"
        })
        node_info_list.append({
            "nodeId": "115",
            "fieldName": "aspect_ratio",
            "fieldData": ASPECT_RATIO_FIELD_DATA,
            "fieldValue": aspect_ratio_value,
            "description": "长宽比"
        })
        node_info_list.append({
            "nodeId": "115",
            "fieldName": "megapixels",
            "fieldValue": megapixels_value,
            "description": "视频分辨率"
        })

        self.logger.info(
            f"MiniMax H3 参考生视频请求参数: duration={duration}s, ratio={ratio}(aspect_ratio={aspect_ratio_value}), "
            f"megapixels={megapixels_value}, ref_images={len(uploaded_images)}张, "
            f"ref_audios={len(uploaded_audios)}个, ref_videos={len(uploaded_videos)}个, prompt_len={len(prompt_text)}"
        )

        return {
            "url": f"{self._host}/openapi/v2/run/ai-app/{self._webapp_id}",
            "method": "POST",
            "json": {
                "nodeInfoList": node_info_list,
                "instanceType": "default",
                "usePersonalQueue": "false"
            },
            "headers": {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}"
            }
        }

    def build_check_query(self, project_id: str) -> Dict[str, Any]:
        """
        构建查询 MiniMax H3 参考生视频任务状态的完整请求参数

        Args:
            project_id: 任务ID

        Returns:
            Dict[str, Any]: 请求参数字典
        """
        return {
            "url": f"{self._host}/task/openapi/status",
            "method": "POST",
            "json": {
                "apiKey": self._api_key,
                "taskId": project_id
            },
            "headers": {
                "Content-Type": "application/json",
                "Accept": "application/json"
            }
        }

    async def submit_task(self, ai_tool) -> Dict[str, Any]:
        """
        提交 MiniMax H3 参考生视频任务

        Args:
            ai_tool: AITool 对象
                - prompt: 提示词
                - reference_images: 参考图URL列表（JSON 数组字符串，最多 9 张）
                - duration: 视频时长（秒）
                - ratio: 视频比例

        Returns:
            Dict[str, Any]: 提交结果
        """
        try:
            self.logger.info(
                f"Submitting MiniMax H3 参考生视频 task: prompt='{ai_tool.prompt[:50] if ai_tool.prompt else ''}...', "
                f"duration={ai_tool.duration}"
            )

            # 构建请求参数
            request_params = await self.build_create_request(ai_tool)

            # 调用统一请求方法
            try:
                result = self._request(**request_params)
            except (ConnectionError, TimeoutError) as network_error:
                # 网络异常，允许重试
                self.logger.warning(f"Network error during MiniMax H3 参考生视频 task submission: {str(network_error)}")
                return {
                    "success": False,
                    "error": "网络连接异常，请稍后重试",
                    "error_type": "USER",
                    "retry": True
                }

            self.logger.info(f"MiniMax H3 参考生视频 API response: {result}")

            # 验证响应格式
            is_valid, validation_error = self._validate_submit_response(result)
            if not is_valid:
                # 格式错误，发送报警，不重试
                self._send_alert(
                    alert_type="INVALID_RESPONSE_FORMAT",
                    message=f"MiniMax H3 参考生视频 submit_task 响应格式错误: {validation_error}",
                    context={
                        "api": "create_minimax_h3_reference_to_video",
                        "response": result,
                        "ai_tool_id": ai_tool.id
                    }
                )
                return {
                    "success": False,
                    "error": "服务异常，请联系技术支持",
                    "error_type": "SYSTEM",
                    "error_detail": f"API响应格式错误: {validation_error}",
                    "retry": False
                }

            # 检查业务错误（通过 errorCode 或 errorMessage 判断）
            error_code = result.get("errorCode", "")
            error_message = result.get("errorMessage", "")
            if error_code or error_message:
                # 上游并发超限/限流：自动延迟重试
                if is_upstream_congested_error(error_code):
                    self.logger.warning(
                        f"MiniMax H3 参考生视频 upstream congested, will auto-retry: "
                        f"errorCode={error_code}, errorMessage={error_message}"
                    )
                    return self._build_upstream_congested_result()
                self.logger.warning(
                    f"MiniMax H3 参考生视频 API returned error: errorCode={error_code}, errorMessage={error_message}"
                )
                return {
                    "success": False,
                    "error": f"任务提交失败: {error_message or error_code}",
                    "error_type": "USER",
                    "retry": False
                }

            task_id = result.get("taskId")
            if not task_id:
                return {
                    "success": False,
                    "error": "服务异常，请联系技术支持",
                    "error_type": "SYSTEM",
                    "error_detail": "MiniMax H3 参考生视频 API未返回任务ID",
                    "retry": False
                }

            return {
                "success": True,
                "project_id": task_id
            }

        except ImageExpiredError as e:
            # 第三方图床签名过期，无法恢复：友好提示用户重新上传
            self.logger.warning(f"输入图片已过期: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "error_type": "USER",
                "retry": False
            }

        except Exception as e:
            # 非网络异常，发送报警，不重试
            self.logger.error(f"Unexpected exception in MiniMax H3 参考生视频 submit_task: {str(e)}")
            self.logger.error(traceback.format_exc())

            self._send_alert(
                alert_type="UNEXPECTED_EXCEPTION",
                message=f"MiniMax H3 参考生视频 submit_task 发生未预期异常: {str(e)}",
                context={
                    "exception": str(e),
                    "traceback": traceback.format_exc(),
                    "ai_tool_id": ai_tool.id
                }
            )

            return {
                "success": False,
                "error": "服务异常，请联系技术支持",
                "error_type": "SYSTEM",
                "error_detail": f"未预期异常: {str(e)}",
                "retry": False
            }

    def check_status(self, project_id: str) -> Dict[str, Any]:
        """
        检查 MiniMax H3 参考生视频任务状态

        Args:
            project_id: 任务ID

        Returns:
            Dict[str, Any]: 状态检查结果
        """
        try:
            self.logger.info(f"Checking MiniMax H3 参考生视频 task status: project_id={project_id}")

            # 第一次调用：查询状态
            status_params = self.build_check_query(project_id)

            try:
                status_result = self._request(**status_params)
            except (ConnectionError, TimeoutError) as network_error:
                # 网络异常，允许重试
                self.logger.warning(f"Network error during MiniMax H3 参考生视频 status check: {str(network_error)}")
                return {
                    "status": "RUNNING",
                    "message": "网络连接异常，稍后将重试"
                }

            # 验证状态响应格式
            if not isinstance(status_result, dict) or "code" not in status_result:
                self._send_alert(
                    alert_type="INVALID_RESPONSE_FORMAT",
                    message="MiniMax H3 参考生视频 status API 响应格式异常",
                    context={
                        "api": "check_status",
                        "response": status_result,
                        "project_id": project_id
                    }
                )
                return {
                    "status": "FAILED",
                    "error": "服务异常，请联系技术支持",
                    "error_type": "SYSTEM",
                    "error_detail": "RunningHub 响应格式错误"
                }

            if status_result.get("code") != 0:
                error_msg = status_result.get("msg", "查询状态失败")
                return {
                    "status": "FAILED",
                    "error": error_msg,
                    "error_type": "USER"
                }

            task_status = status_result.get("data", "")

            # 映射 RunningHub 状态到统一状态
            if task_status == "SUCCESS":
                # 第二次调用：获取输出结果
                outputs_params = {
                    "url": f"{self._host}/task/openapi/outputs",
                    "method": "POST",
                    "json": {
                        "apiKey": self._api_key,
                        "taskId": project_id
                    },
                    "headers": {
                        "Content-Type": "application/json",
                        "Accept": "application/json"
                    }
                }

                try:
                    outputs_result = self._request(**outputs_params)
                except Exception as e:
                    self.logger.error(f"Failed to get outputs: {str(e)}")
                    return {
                        "status": "FAILED",
                        "error": "获取结果失败",
                        "error_type": "SYSTEM",
                        "error_detail": f"获取输出失败: {str(e)}"
                    }

                # 从 outputs 中提取视频 URL
                result_url = None
                if outputs_result.get("code") == 0:
                    outputs_data = outputs_result.get("data", [])
                    if outputs_data:
                        for item in outputs_data:
                            file_url = item.get("fileUrl")
                            if file_url:
                                result_url = file_url
                                break

                return {
                    "status": "SUCCESS",
                    "result_url": result_url
                }
            elif task_status == "FAILED":
                return {
                    "status": "FAILED",
                    "error": "任务失败",
                    "error_type": "USER"
                }
            else:
                # PENDING, RUNNING 或其他状态
                return {
                    "status": "RUNNING",
                    "message": "任务处理中..."
                }

        except Exception as e:
            # 非网络异常，发送报警
            self.logger.error(f"Unexpected exception in MiniMax H3 参考生视频 check_status: {str(e)}")
            self.logger.error(traceback.format_exc())

            self._send_alert(
                alert_type="UNEXPECTED_EXCEPTION",
                message=f"MiniMax H3 参考生视频 check_status 发生未预期异常: {str(e)}",
                context={
                    "exception": str(e),
                    "traceback": traceback.format_exc(),
                    "project_id": project_id
                }
            )

            return {
                "status": "FAILED",
                "error": "服务异常，请联系技术支持",
                "error_type": "SYSTEM",
                "error_detail": f"未预期异常: {str(e)}"
            }
