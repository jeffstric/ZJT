"""
qwenimage2.1 的图片驱动（实现类 RunninghubAiAppImageV1Driver）。

用户可见模型名是 qwenimage2.1，任务常量是 TaskTypeId.QWEN_2_1_IMAGE。
本文件只是 RunningHub 实现方，不作为模型标识。
对接 RunningHub ai-app 工作流（默认 app id 2113539132868874242），
同一工作流同时支持两种模式：
- 图片编辑：nodeId 17-22 传入 1-6 张图（不足补 "None"，工作流节点 16
  easy makeImageList 的 skip_empty=true 会自动忽略 None），开启
  「原图无偏移」（nodeId 25）。该开关会让采样画布跟随图 1（对齐到 32），
  节点 28 的比例和百万像素不会改编辑出图尺寸。因此上传前把图 1
  覆盖裁切到所选画布，既保持无偏移，又让 1K/2K/4K 生效。
  「使用图片尺寸」（nodeId 29）保持关闭。
- 文生图：图片槽全填 "None"，关闭节点 25/29（文档要求文生图必须关闭，
  否则画面偏移或报错），通过节点 28 显式指定 aspect_ratio + megapixels。
"""
import asyncio
import json
import math
import os
import tempfile
import traceback
from typing import Dict, Any, List, Optional, Tuple

from PIL import Image, ImageOps

from .base_video_driver import BaseVideoDriver
from config.config_util import get_config, get_dynamic_config_value
from utils.sentry_util import SentryUtil, AlertLevel
from utils.file_storage import RunningHubFileStorage
from utils.image_upload_utils import download_url_to_temp, ensure_fresh_image_url
from utils.runninghub_error import is_upstream_congested_error
from .exceptions import ImageExpiredError


class RunninghubAiAppImageV1Driver(BaseVideoDriver):
    """qwenimage2.1 图片驱动（图片编辑 + 文生图）"""

    # 工作流固定 app id；可通过动态配置 runninghub.ai_app_image_webapp_id 覆盖
    DEFAULT_WEBAPP_ID = "2113539132868874242"

    # ai_tool.ratio（"1:1" 等标准比例）→ 工作流节点 28 的 aspect_ratio 枚举值
    ASPECT_RATIO_MAPPING = {
        '1:1': '1:1 (Square)',
        '2:3': '2:3 (Portrait Photo)',
        '3:2': '3:2 (Photo)',
        '3:4': '3:4 (Portrait Standard)',
        '4:3': '4:3 (Standard)',
        '9:16': '9:16 (Portrait Widescreen)',
        '16:9': '16:9 (Widescreen)',
        '21:9': '21:9 (Ultrawide)',
    }

    # 与 ComfyUI ResolutionSelector 相同的宽高比分子。百万像素按 1024² 计，
    # 再对齐到 32：Qwen-Image-2.1 的编辑 latent 会把图 1 四舍五入到 32 的倍数。
    RATIO_FACTORS = {
        '1:1': (1, 1),
        '2:3': (2, 3),
        '3:2': (3, 2),
        '3:4': (3, 4),
        '4:3': (4, 3),
        '9:16': (9, 16),
        '16:9': (16, 9),
        '21:9': (21, 9),
    }
    CANVAS_MULTIPLE = 32
    MEGAPIXEL_UNIT = 1024 * 1024

    # 工作流图片槽位（nodeId 17-22），最多 6 张参考图
    IMAGE_NODE_IDS = ['17', '18', '19', '20', '21', '22']

    def __init__(self):
        super().__init__(driver_name="runninghub_ai_app_image_v1", driver_type=52)

        # 加载配置
        self._api_key = get_dynamic_config_value("runninghub", "api_key", default="")
        self._host = get_dynamic_config_value("runninghub", "host", default="")
        self._webapp_id = get_dynamic_config_value(
            "runninghub", "ai_app_image_webapp_id", default=self.DEFAULT_WEBAPP_ID
        )
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
        """发送报警信息"""
        SentryUtil.send_alert(
            alert_type=alert_type,
            message=message,
            level=AlertLevel.ERROR,
            context=context
        )

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

    def _map_aspect_ratio(self, ratio: str) -> str:
        """标准比例 → 工作流 aspect_ratio 枚举值，未知比例回落 1:1"""
        key = (ratio or '1:1').strip()
        mapped = self.ASPECT_RATIO_MAPPING.get(key)
        if not mapped:
            self.logger.warning(f"未知的图片比例 '{ratio}'，使用默认比例 1:1")
            mapped = self.ASPECT_RATIO_MAPPING['1:1']
        return mapped

    @staticmethod
    def _map_megapixels(image_size: str) -> str:
        """分辨率档位（1K/2K/4K）→ 工作流节点 28 的 megapixels（百万像素值）"""
        size = (image_size or '').strip().upper()
        if size.endswith('K'):
            size = size[:-1]
        try:
            mp = int(size)
        except (TypeError, ValueError):
            return '2'
        # 限制在 1-4 百万像素范围内
        return str(min(max(mp, 1), 4))

    def target_canvas(self, ratio: str, image_size: str) -> Tuple[int, int]:
        """所选比例 + 1K/2K/4K → 对齐到 32 的像素宽高。

        算法与 ComfyUI ResolutionSelector 一致：总像素 = megapixels × 1024²，
        按宽高比开方后取最近的 32 倍数。4K 的 1:1 是 2048×2048，16:9 是 2720×1536。
        """
        megapixels = int(self._map_megapixels(image_size))
        factors = self.RATIO_FACTORS.get((ratio or '1:1').strip())
        if not factors:
            self.logger.warning(f"未知的图片比例 '{ratio}'，画布回落 1:1")
            factors = self.RATIO_FACTORS['1:1']
        w_ratio, h_ratio = factors
        scale = math.sqrt(megapixels * self.MEGAPIXEL_UNIT / (w_ratio * h_ratio))
        multiple = self.CANVAS_MULTIPLE
        width = max(multiple, int(round(w_ratio * scale / multiple) * multiple))
        height = max(multiple, int(round(h_ratio * scale / multiple) * multiple))
        return width, height

    @staticmethod
    def fit_image_to_canvas(src_path: str, dest_path: str, width: int, height: int) -> None:
        """把图片覆盖裁切到精确画布。宽高比已一致时只做缩放，不拉伸。"""
        with Image.open(src_path) as raw:
            img = ImageOps.exif_transpose(raw)
            img.load()
            if img.mode not in ('RGB', 'RGBA'):
                img = img.convert('RGBA' if 'A' in img.getbands() else 'RGB')
            src_w, src_h = img.size
            scale = max(width / src_w, height / src_h)
            resized_w = max(width, int(round(src_w * scale)))
            resized_h = max(height, int(round(src_h * scale)))
            resized = img.resize((resized_w, resized_h), Image.Resampling.LANCZOS)
            left = max(0, (resized_w - width) // 2)
            top = max(0, (resized_h - height) // 2)
            cropped = resized.crop((left, top, left + width, top + height))
            if cropped.mode == 'RGBA':
                cropped.save(dest_path, format='PNG')
            else:
                cropped.convert('RGB').save(dest_path, format='PNG')

    async def _materialize_reference(self, url: str) -> Tuple[str, bool]:
        """解析图 1 到本地路径。第二个返回值表示该文件是本次下载的，用完要删。"""
        local = self._storage.resolve_to_local_file(url)
        if isinstance(local, str) and local and os.path.isfile(local):
            return local, False
        fresh_url = await ensure_fresh_image_url(url, self._config, os.getcwd())
        downloaded = await download_url_to_temp(fresh_url, os.getcwd())
        if not downloaded or not os.path.isfile(downloaded):
            raise RuntimeError("图片下载失败，无法按所选分辨率缩放")
        return downloaded, True

    async def _fit_first_reference(self, url: str, ratio: str, image_size: str) -> str:
        """把图 1 做成所选画布的临时文件。调用方负责删除返回路径。"""
        width, height = self.target_canvas(ratio, image_size)
        self.logger.info(
            f"图片编辑按所选分辨率缩放图1: ratio={ratio} size={image_size} canvas={width}x{height}"
        )
        local, owned = await self._materialize_reference(url)
        dest_path = None
        try:
            fd, dest_path = tempfile.mkstemp(suffix='.png')
            os.close(fd)
            await asyncio.to_thread(
                self.fit_image_to_canvas, local, dest_path, width, height
            )
            return dest_path
        except Exception:
            if dest_path and os.path.isfile(dest_path):
                try:
                    os.remove(dest_path)
                except OSError:
                    pass
            raise
        finally:
            if owned and local and os.path.isfile(local):
                try:
                    os.remove(local)
                except OSError:
                    self.logger.warning("清理下载的参考图临时文件失败")

    def _validate_submit_response(self, result: Any) -> tuple[bool, Optional[str]]:
        """
        验证 submit_task API 响应格式

        期望的正确响应格式:
        {
            "taskId": "2113539...",
            "status": "RUNNING",
            "errorCode": "",
            "errorMessage": "",
        }
        """
        if not isinstance(result, dict):
            return False, f"响应不是字典类型，实际类型: {type(result)}"

        if "taskId" not in result:
            return False, f"响应缺少 'taskId' 字段，实际字段: {list(result.keys())}"

        if "status" not in result:
            return False, f"响应缺少 'status' 字段，实际字段: {list(result.keys())}"

        return True, None

    async def build_create_request(self, ai_tool) -> Dict[str, Any]:
        """
        构建创建 AI App 图片任务的完整请求参数

        Args:
            ai_tool: AITool 对象
                - prompt: 提示词（编辑模式为修改指令，文生图为完整画面描述）
                - image_path: 参考图 URL（逗号分隔，可为空 = 文生图模式）
                - ratio: 图片比例（文生图写入节点 28；编辑时同时决定图 1 画布）
                - image_size: 分辨率档位 1K/2K/4K（文生图写入节点 28；编辑时同时决定图 1 画布）

        Returns:
            Dict[str, Any]: 请求参数字典
        """
        # 参考图列表（可选，最多 6 张）
        image_urls: List[str] = []
        if ai_tool.image_path:
            image_urls = [u.strip() for u in str(ai_tool.image_path).split(',') if u.strip()]
        image_urls = image_urls[:len(self.IMAGE_NODE_IDS)]

        # 编辑时图 1 决定采样画布（原图无偏移）。先缩到所选比例和百万像素，
        # 其余参考图保持原尺寸。文生图没有参考图，尺寸只走节点 28。
        upload_sources = list(image_urls)
        fitted_path = None
        image_field_values: List[str] = []
        try:
            if image_urls:
                fitted_path = await self._fit_first_reference(
                    image_urls[0],
                    getattr(ai_tool, 'ratio', None),
                    getattr(ai_tool, 'image_size', None),
                )
                upload_sources[0] = fitted_path
                self.logger.info(f"准备上传 {len(upload_sources)} 张图片到 RunningHub 图床")
                uploaded = []
                for source in upload_sources:
                    result = await self._storage.upload_file("", source)
                    if result.success:
                        uploaded.append(result.url if result.url else result.key)
                    else:
                        # 上传失败直接报错，不再静默用原始过期 URL 导致下游 401 假象
                        raise RuntimeError(f"图片上传到 RunningHub 失败: {result.error}")
                image_field_values = uploaded

            has_image = bool(image_field_values)

            node_info_list = []

            # 图片槽位：nodeId 17-22，无图填 "None"（工作流 skip_empty 自动忽略）
            for idx, node_id in enumerate(self.IMAGE_NODE_IDS):
                node_info_list.append({
                    "nodeId": node_id,
                    "fieldName": "image",
                    "fieldValue": image_field_values[idx] if idx < len(image_field_values) else "None",
                    "description": f"图{idx + 1}（文生图时不填）"
                })

            # 提示词
            node_info_list.append({
                "nodeId": "23",
                "fieldName": "value",
                "fieldValue": ai_tool.prompt or "",
                "description": "提示词"
            })

            # 使用反推（本地大模型润色提示词）：固定关闭
            node_info_list.append({
                "nodeId": "24",
                "fieldName": "value",
                "fieldValue": "false",
                "description": "使用反推"
            })

            # 原图无偏移：编辑模式开启；文生图必须关闭（否则画面偏移或报错）
            node_info_list.append({
                "nodeId": "25",
                "fieldName": "value",
                "fieldValue": "true" if has_image else "false",
                "description": "原图无偏移（文生图需关闭）"
            })

            # 使用图片尺寸保持关闭。编辑出图尺寸由图 1 的像素决定（上面已按所选
            # 分辨率缩放），文生图则由节点 28 的比例和百万像素决定。
            node_info_list.append({
                "nodeId": "29",
                "fieldName": "value",
                "fieldValue": "false",
                "description": "使用图片尺寸"
            })
            node_info_list.append({
                "nodeId": "28",
                "fieldName": "aspect_ratio",
                "fieldValue": self._map_aspect_ratio(getattr(ai_tool, 'ratio', None)),
                "description": "图片比例"
            })
            node_info_list.append({
                "nodeId": "28",
                "fieldName": "megapixels",
                "fieldValue": self._map_megapixels(getattr(ai_tool, 'image_size', None)),
                "description": "自定义尺寸 多少 100万像素"
            })

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
        finally:
            if fitted_path and os.path.isfile(fitted_path):
                try:
                    os.remove(fitted_path)
                except OSError:
                    self.logger.warning("清理缩放后的图1临时文件失败")

    def build_check_query(self, project_id: str) -> Dict[str, Any]:
        """
        构建查询任务状态的完整请求参数

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
        提交 AI App 图片任务（图片编辑 / 文生图）

        Args:
            ai_tool: AITool 对象

        Returns:
            Dict[str, Any]: 提交结果
        """
        try:
            mode = "image_edit" if ai_tool.image_path else "text_to_image"
            self.logger.info(f"Submitting RunningHubAiAppImage task: ai_tool_id={ai_tool.id}, mode={mode}")

            # 构建请求参数
            request_params = await self.build_create_request(ai_tool)

            # 调用统一请求方法
            try:
                result = self._request(**request_params)
            except (ConnectionError, TimeoutError) as network_error:
                self.logger.warning(f"Network error during RunningHubAiAppImage task submission: {str(network_error)}")
                return {
                    "success": False,
                    "error": "网络连接异常，请稍后重试",
                    "error_type": "USER",
                    "retry": True
                }

            # 验证响应格式
            is_valid, validation_error = self._validate_submit_response(result)
            if not is_valid:
                self._send_alert(
                    alert_type="INVALID_RESPONSE_FORMAT",
                    message=f"RunningHubAiAppImage submit_task 响应格式错误: {validation_error}",
                    context={
                        "api": "run_ai_app_image",
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

            # 检查业务错误
            error_code = result.get("errorCode", "")
            error_message = result.get("errorMessage", "")
            if error_code or error_message:
                # 上游并发超限/限流(api queue limit reached / TASK_QUEUE_MAXED 等)：自动延迟重试，不直接判失败
                if is_upstream_congested_error(error_code):
                    self.logger.warning(
                        f"RunningHubAiAppImage upstream congested, will auto-retry: "
                        f"errorCode={error_code}, errorMessage={error_message}"
                    )
                    return self._build_upstream_congested_result()
                self.logger.warning(
                    f"RunningHubAiAppImage API returned error: errorCode={error_code}, errorMessage={error_message}"
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
                    "error_detail": "RunningHubAiAppImage API未返回任务ID",
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
            self.logger.error(f"Unexpected exception in RunningHubAiAppImage submit_task: {str(e)}")
            self.logger.error(traceback.format_exc())

            self._send_alert(
                alert_type="UNEXPECTED_EXCEPTION",
                message=f"RunningHubAiAppImage submit_task 发生未预期异常: {str(e)}",
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
        检查 AI App 图片任务状态

        Args:
            project_id: 任务ID

        Returns:
            Dict[str, Any]: 状态检查结果
        """
        try:
            self.logger.info(f"Checking RunningHubAiAppImage task status: project_id={project_id}")

            # 查询状态
            status_params = self.build_check_query(project_id)

            try:
                status_result = self._request(**status_params)
            except (ConnectionError, TimeoutError) as network_error:
                self.logger.warning(f"Network error during RunningHubAiAppImage status check: {str(network_error)}")
                return {
                    "status": "RUNNING",
                    "message": "网络连接异常，稍后将重试"
                }

            # 验证状态响应格式
            if not isinstance(status_result, dict) or "code" not in status_result:
                self._send_alert(
                    alert_type="INVALID_RESPONSE_FORMAT",
                    message="RunningHubAiAppImage status API 响应格式异常",
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

            # 映射状态
            if task_status == "SUCCESS":
                # 获取输出结果
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
                    # 上游任务已 SUCCESS：outputs 网络抖动/超时不应把已完成任务
                    # 判成终态失败。preserve_retry_count 让调度层单独安排结果获取
                    # 重试，不消耗生成阶段的 max_retry_count；任务过期仍作最终兜底。
                    self.logger.warning(
                        f"Outputs fetch transient failure for task {project_id}: {str(e)}"
                    )
                    return {
                        "status": "RUNNING",
                        "message": "任务已完成，获取结果中...",
                        "preserve_retry_count": True,
                    }

                # 从 outputs 中提取文件 URL
                result_url = None
                error_code = outputs_result.get("code")
                if error_code != 0:
                    try:
                        numeric_code = int(error_code)
                    except (TypeError, ValueError):
                        numeric_code = None
                    transient = (
                        is_upstream_congested_error(error_code)
                        or numeric_code == 429
                        or (numeric_code is not None and 500 <= numeric_code < 600)
                    )
                    self.logger.warning(
                        f"Outputs API returned code={error_code} "
                        f"for task {project_id}: {outputs_result.get('msg', '')}"
                    )
                    if transient:
                        return {
                            "status": "RUNNING",
                            "message": "任务已完成，获取结果中...",
                            "preserve_retry_count": True,
                        }
                    return {
                        "status": "FAILED",
                        "error": "获取结果失败",
                        "error_type": "SYSTEM",
                        "error_detail": f"获取输出失败: code={error_code}, msg={outputs_result.get('msg', '')}",
                    }

                outputs_data = outputs_result.get("data", [])
                if outputs_data:
                    for item in outputs_data:
                        file_url = item.get("fileUrl")
                        if file_url:
                            result_url = file_url
                            break

                # code==0 但无 fileUrl（含 data 为空）：接口成功而确实无产物，
                # 保持 SUCCESS + None 走「任务成功但未返回结果URL」终态语义
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
            self.logger.error(f"Unexpected exception in RunningHubAiAppImage check_status: {str(e)}")
            self.logger.error(traceback.format_exc())

            self._send_alert(
                alert_type="UNEXPECTED_EXCEPTION",
                message=f"RunningHubAiAppImage check_status 发生未预期异常: {str(e)}",
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
