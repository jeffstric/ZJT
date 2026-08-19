"""
Grok 慧梦(huimengi)网关 v1 版本驱动实现
异步 API - 创建任务后轮询状态

复用 SeedanceHuimengiV1Driver 的通用网关逻辑（提交/轮询/校验/错误处理/测试模式），
仅重写 build_create_request 以适配 grok-video-channel 的参数集。

huimengi 网关接口形态与 Seedance 系列一致：
- 请求体：扁平 { model: "grok-video-channel", params: {...} } 结构
- 创建路径：POST /api/v1/tasks
- 查询路径：GET  /api/v1/tasks/{task_id}
- 提交响应：扁平 { task_id, status }
- 查询响应：扁平 { id, status, result: { video_url, ... }, error_message, ... }

params 字段与 Seedance 系列的差异：
- prompt 必填（文生/图生均必填），上游限制 5-20000 字符
- ratio：2:3 | 3:2 | 1:1 | 16:9 | 9:16（网关默认 16:9，这里始终显式下发）
- duration：6-15 秒；任务档位 6/10/15，非法值回退默认 10
- resolution：720p | 480p（固定 720p，前端 Grok 无分辨率选择）
- image_url：单张参考图公网 URL（首帧模式，传后走图生视频）
- reference_images：参考图公网 URL 列表，最多 7 张（多参模式）
- 不支持：尾帧、参考音视频、generate_audio、human_review
"""
from typing import Dict, Any

from .base_video_driver import ImageMode
from .seedance_huimengi_v1_driver import SeedanceHuimengiV1Driver
from config.unified_config import DriverImplementation, TaskTypeId
from utils.image_upload_utils import compress_and_upload_image_sync


class GrokHuimengiV1Driver(SeedanceHuimengiV1Driver):
    """Grok 视频驱动（huimengi 网关）

    使用 huimengi 官方模型名 grok-video-channel，网关接口（扁平 {model, params}、
    状态轮询）与 Seedance 系列完全一致，复用基类的提交/查询/错误处理逻辑。
    """

    # huimengi 官方模型名
    MODEL_NAME = "grok-video-channel"

    # 时长档位（任务级 supported_durations），非法值回退默认
    SUPPORTED_DURATIONS = (6, 10, 15)
    DEFAULT_DURATION = 10

    # 分辨率固定 720p（网关支持 720p/480p，前端 Grok 无分辨率选择）
    RESOLUTION = "720p"

    # 多参考图上限（网关限制 7 张）
    MAX_REFERENCE_IMAGES = 7

    # prompt 上游字符数限制
    PROMPT_MIN_CHARS = 5
    PROMPT_MAX_CHARS = 20000

    def __init__(self):
        super().__init__(
            driver_type=TaskTypeId.GROK_IMAGE_TO_VIDEO,
            model_name=self.MODEL_NAME,
            impl_name=DriverImplementation.GROK_HUIMENGI_V1
        )

    def build_create_request(self, ai_tool) -> Dict[str, Any]:
        """
        构建 huimengi Grok 创建任务请求（图生视频 / 文生视频）

        图片模式（image_url 与 reference_images 互斥）：
        - 无任何图片：文生视频，params 只放 prompt + 控制字段
        - first_last_frame / first_last_with_ref：首帧 → params.image_url（网关仅支持
          单张，尾帧/参考图忽略，与任务 supports_last_frame=False 一致）
        - multi_reference：params.reference_images[]，最多 7 张
        - 首帧模式缺首帧但有参考图时，降级使用参考图列表

        build_create_request 可能返回错误字典（success=False），由 submit_task 透传。

        Args:
            ai_tool: AITool 对象

        Returns:
            Dict[str, Any]: 请求参数字典或错误字典
        """
        # 1. 解析 extra_config 和图片模式
        extra_config = self._parse_extra_config(ai_tool)
        all_images_info = self.get_all_images_by_mode(ai_tool)
        img_mode = all_images_info['mode']
        first_frame = all_images_info.get('first_frame')
        last_frame = all_images_info.get('last_frame')
        reference_images = all_images_info.get('reference_images', [])

        # 2. prompt 校验（grok 网关文生/图生均必填，5-20000 字符）
        prompt = (ai_tool.prompt or "").strip()
        if not prompt:
            return {
                "success": False,
                "error": "请输入视频描述提示词",
                "error_type": "USER",
                "retry": False
            }
        if len(prompt) < self.PROMPT_MIN_CHARS:
            return {
                "success": False,
                "error": f"提示词过短，Grok 视频要求至少 {self.PROMPT_MIN_CHARS} 个字符",
                "error_type": "USER",
                "retry": False
            }
        if len(prompt) > self.PROMPT_MAX_CHARS:
            self.logger.warning(
                f"grok huimengi 提示词超长({len(prompt)} 字符)，截断为 {self.PROMPT_MAX_CHARS}"
            )
            prompt = prompt[:self.PROMPT_MAX_CHARS]

        # 3. 决定图片字段（image_url 单张 与 reference_images 列表互斥）
        single_image = None       # 首帧 → params.image_url
        ref_image_list = []       # 多参 → params.reference_images

        if img_mode == ImageMode.MULTI_REFERENCE:
            if reference_images:
                ref_image_list = reference_images[:self.MAX_REFERENCE_IMAGES]
                if len(reference_images) > self.MAX_REFERENCE_IMAGES:
                    self.logger.warning(
                        f"grok huimengi 最多支持 {self.MAX_REFERENCE_IMAGES} 张参考图，已截取"
                    )
            elif first_frame:
                single_image = first_frame
        elif img_mode in (ImageMode.FIRST_LAST_FRAME, ImageMode.FIRST_LAST_WITH_REF):
            if first_frame:
                single_image = first_frame
                if last_frame:
                    self.logger.warning("grok huimengi 仅支持单张首帧，已忽略尾帧")
                if img_mode == ImageMode.FIRST_LAST_WITH_REF and reference_images:
                    self.logger.warning(
                        f"grok huimengi 首帧与参考图互斥，已忽略 {len(reference_images)} 张参考图"
                    )
            elif reference_images:
                ref_image_list = reference_images[:self.MAX_REFERENCE_IMAGES]
        else:
            # 未知模式：按可用图片降级处理，避免静默丢失图片输入
            self.logger.warning(f"未知的 image_mode: {img_mode}，按可用图片降级处理")
            if first_frame:
                single_image = first_frame
            elif reference_images:
                ref_image_list = reference_images[:self.MAX_REFERENCE_IMAGES]

        # 4. 构建 params 通用控制字段
        params: Dict[str, Any] = {"prompt": prompt}

        # 比例：透传（网关支持 2:3|3:2|1:1|16:9|9:16，为任务支持集的超集）
        ratio = extra_config.get('ratio') or getattr(ai_tool, 'ratio', None) or '9:16'
        params["ratio"] = ratio

        # 时长：取合法档位（6/10/15），异常值回退默认，并做 [6,15] 边界防御
        duration = getattr(ai_tool, 'duration', None)
        try:
            duration = int(duration) if duration is not None else self.DEFAULT_DURATION
        except (TypeError, ValueError):
            duration = self.DEFAULT_DURATION
        if duration not in self.SUPPORTED_DURATIONS:
            self.logger.warning(
                f"grok huimengi 时长 {duration} 不在支持档位 {self.SUPPORTED_DURATIONS}，"
                f"回退默认 {self.DEFAULT_DURATION}"
            )
            duration = self.DEFAULT_DURATION
        params["duration"] = max(6, min(15, duration))

        params["resolution"] = self.RESOLUTION

        # 5. 上传图片到 CDN（网关要求公网 URL）并填充图片字段
        if single_image:
            success, processed_url, error = compress_and_upload_image_sync(
                single_image, self._config, max_size_mb=10.0, is_local=True
            )
            if not success:
                self.logger.error(f"处理首帧图片失败: {error}")
                return {
                    "success": False,
                    "error": f"处理图片失败: {error}",
                    "error_type": "USER",
                    "retry": False
                }
            params["image_url"] = processed_url
        elif ref_image_list:
            processed_refs = []
            for ref_img in ref_image_list:
                success, new_url, error = compress_and_upload_image_sync(
                    ref_img, self._config, max_size_mb=10.0, is_local=True
                )
                if success:
                    processed_refs.append(new_url)
                else:
                    self.logger.warning(f"处理参考图失败，跳过: {error}")
            if not processed_refs:
                return {
                    "success": False,
                    "error": "参考图片处理失败，请更换图片后重试",
                    "error_type": "USER",
                    "retry": False
                }
            params["reference_images"] = processed_refs
        else:
            self.logger.info("文生视频模式: 无图片输入")

        # 6. 组装 payload（huimengi 扁平 { model, params } 结构）
        payload: Dict[str, Any] = {
            "model": self._model,
            "params": params,
        }

        self.logger.info(
            f"使用模型: {self._model}, driver_type: {self.driver_type}, 模式: {img_mode}, "
            f"params keys: {list(params.keys())}"
        )

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}"
        }

        return {
            "url": f"{self._base_url}/api/v1/tasks",
            "method": "POST",
            "json": payload,
            "headers": headers,
            "timeout": self._timeout
        }
