"""
GPT Image 2 通用供应商 v1 版本驱动实现
基于zjt api 平台，使用 OpenAI 标准格式
支持文生图和图片编辑（图生图）

API 文档: https://platform.openai.com/docs/api-reference/images/create
"""
from typing import Dict, Any, Optional
import traceback
import base64
import os
import re
import requests
from .base_video_driver import BaseVideoDriver
from config.config_util import get_config, get_dynamic_config_value
from utils.sentry_util import SentryUtil, AlertLevel
from utils.network_utils import is_local_file_path
from utils.image_upload_utils import try_map_url_to_local_file, upload_local_images_to_cdn_sync
from utils.media_cache import get_cache_manager


class GptImageCommonV1Driver(BaseVideoDriver):
    """
    GPT Image 2 通用供应商 v1 版本驱动（基类）
    使用 OpenAI 标准 API 格式进行图片生成/编辑
    
    特点：
    - 同步接口，直接返回结果，无需轮询
    - 支持 base64 编码的图片输入
    - 支持图片编辑（图生图）
    
    注意：这是基类，不应该直接实例化，应该使用具体的站点类
    """

    # 尺寸映射：image_size + ratio -> OpenAI size 格式
    # 支持 1K、2K、4K 分辨率
    SIZE_MAPPING = {
        '1k': {
            '1:1': '1024x1024',
            '3:2': '1536x1024',
            '2:3': '1024x1536',
            '16:9': '1536x1024',
            '9:16': '1024x1536',
        },
        '2k': {
            '1:1': '2048x2048',
            '3:2': '2048x1152',
            '2:3': '1152x2048',
            '16:9': '2048x1152',
            '9:16': '1152x2048',
        },
        '4k': {
            '1:1': '2048x2048',
            '3:2': '3840x2160',
            '2:3': '2160x3840',
            '16:9': '3840x2160',
            '9:16': '2160x3840',
        }
    }

    # 默认模型
    DEFAULT_MODEL = "gpt-image-2"

    def __init__(self, site_id: str):
        """
        初始化驱动（基类）

        Args:
            site_id: API 聚合站点ID（如 site_1, site_2, ... site_5）
                     对应配置 api_aggregator.site_X
        """
        self._site_id = site_id
        driver_name = f"gpt_image_common_{site_id}"
        super().__init__(driver_name=driver_name, driver_type=25)

        # 从 api_aggregator.{site_id} 加载配置
        self._api_key = get_dynamic_config_value("api_aggregator", site_id, "api_key", default="")
        self._base_url = get_dynamic_config_value("api_aggregator", site_id, "base_url", default="")
        self._site_name = get_dynamic_config_value("api_aggregator", site_id, "name", default=site_id)
        self._timeout = get_dynamic_config_value("timeout", "sync_request_timeout", default=300) * 2

        self._is_local = get_dynamic_config_value("server", "is_local", default=False)
        self._config = get_config()

        self._validate_required({
            f"API Aggregator {site_id} API Key": self._api_key,
            f"API Aggregator {site_id} Base URL": self._base_url,
        })

    def _send_alert(self, alert_type: str, message: str, context: Optional[Dict[str, Any]] = None):
        """
        发送报警信息

        Args:
            alert_type: 报警类型
            message: 报警消息
            context: 上下文信息（可选）
        """
        SentryUtil.send_alert(
            alert_type=alert_type,
            message=message,
            level=AlertLevel.ERROR,
            context=context
        )

    def _read_local_file_as_base64(self, file_path: str) -> tuple[str, str]:
        """
        读取本地文件并转换为 base64 编码

        Args:
            file_path: 本地文件路径

        Returns:
            tuple[str, str]: (base64_data, mime_type)
        """
        try:
            ext = os.path.splitext(file_path)[1].lower()
            mime_types = {
                '.jpg': 'image/jpeg',
                '.jpeg': 'image/jpeg',
                '.png': 'image/png',
                '.gif': 'image/gif',
                '.webp': 'image/webp'
            }
            mime_type = mime_types.get(ext, 'image/jpeg')

            with open(file_path, 'rb') as f:
                file_content = f.read()
            base64_data = base64.b64encode(file_content).decode('utf-8')
            return base64_data, mime_type

        except Exception as e:
            self.logger.error(f"Failed to read local file: {file_path}, error: {str(e)}")
            raise

    def _download_image_as_base64(self, image_url: str) -> tuple[str, str]:
        """
        下载图片并转换为 base64 编码

        Args:
            image_url: 图片 URL

        Returns:
            tuple[str, str]: (base64_data, mime_type)
        """
        try:
            response = requests.get(image_url, timeout=30)
            response.raise_for_status()

            content_type = response.headers.get('Content-Type', 'image/jpeg')
            if 'png' in content_type.lower():
                mime_type = 'image/png'
            elif 'gif' in content_type.lower():
                mime_type = 'image/gif'
            elif 'webp' in content_type.lower():
                mime_type = 'image/webp'
            else:
                mime_type = 'image/jpeg'

            base64_data = base64.b64encode(response.content).decode('utf-8')
            return base64_data, mime_type

        except Exception as e:
            self.logger.error(f"Failed to download image: {image_url}, error: {str(e)}")
            raise

    def _map_size(self, image_size: str, ratio: str) -> str:
        """
        根据分辨率和比例映射为 OpenAI size 格式

        Args:
            image_size: 分辨率，如 "1k", "2k", "4k"
            ratio: 前端传入的比例，如 "1:1", "16:9", "9:16"

        Returns:
            OpenAI size 格式
        """
        # 标准化 image_size
        image_size = (image_size or '1k').lower()
        
        # 获取对应分辨率的映射
        size_dict = self.SIZE_MAPPING.get(image_size)
        if not size_dict:
            self.logger.warning(f"未知的分辨率 '{image_size}'，使用默认分辨率 1k")
            size_dict = self.SIZE_MAPPING['1k']
        
        # 获取对应比例的尺寸
        size = size_dict.get(ratio)
        if not size:
            self.logger.warning(f"未知的比例 '{ratio}'，使用默认比例 1:1")
            size = size_dict.get('1:1', '1024x1024')
        
        return size

    def _prepare_image_data(self, image_path: str) -> tuple[str, str]:
        """
        准备图片数据（本地文件或URL）

        Args:
            image_path: 图片路径或URL

        Returns:
            tuple[str, str]: (base64_data, mime_type)
        """
        if is_local_file_path(image_path):
            self.logger.info(f"检测到本地文件路径: {image_path}")
            return self._read_local_file_as_base64(image_path)
        else:
            # URL，尝试映射到本地文件
            local_file = try_map_url_to_local_file(image_path, self._config)
            if local_file:
                self.logger.info(f"URL映射到本地文件: {image_path} -> {local_file}")
                return self._read_local_file_as_base64(local_file)
            else:
                self.logger.info(f"通过HTTP下载图片: {image_path}")
                return self._download_image_as_base64(image_path)

    def _prepare_image_file(self, image_path: str) -> tuple[bytes, str, str]:
        """
        准备图片文件用于 multipart/form-data 上传

        Args:
            image_path: 图片路径或URL

        Returns:
            tuple[bytes, str, str]: (文件内容, 文件名, MIME类型)
        """
        # 确定实际文件路径
        if is_local_file_path(image_path):
            actual_path = image_path
            self.logger.info(f"准备上传本地文件: {image_path}")
        else:
            # URL，尝试映射到本地文件
            local_file = try_map_url_to_local_file(image_path, self._config)
            if local_file:
                actual_path = local_file
                self.logger.info(f"URL映射到本地文件: {image_path} -> {local_file}")
            else:
                # 下载远程图片
                self.logger.info(f"下载远程图片用于上传: {image_path}")
                response = requests.get(image_path, timeout=30)
                response.raise_for_status()

                # 从 URL 提取文件名
                from urllib.parse import urlparse
                parsed = urlparse(image_path)
                filename = os.path.basename(parsed.path) or "image.png"

                # 从 Content-Type 获取 MIME 类型
                content_type = response.headers.get('Content-Type', 'image/png')
                if 'jpeg' in content_type or 'jpg' in content_type:
                    mime_type = 'image/jpeg'
                elif 'webp' in content_type:
                    mime_type = 'image/webp'
                else:
                    mime_type = 'image/png'

                return response.content, filename, mime_type

        # 读取本地文件
        ext = os.path.splitext(actual_path)[1].lower()
        mime_types = {
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.gif': 'image/gif',
            '.webp': 'image/webp'
        }
        mime_type = mime_types.get(ext, 'image/png')
        filename = os.path.basename(actual_path)

        with open(actual_path, 'rb') as f:
            file_content = f.read()

        return file_content, filename, mime_type

    def build_create_request(self, ai_tool) -> Dict[str, Any]:
        """
        创建 GPT Image 任务的完整请求参数

        Args:
            ai_tool: AITool 对象

        Returns:
            Dict[str, Any]: 请求参数字典
        """
        # 获取分辨率和比例
        image_size = getattr(ai_tool, 'image_size', None) or '1k'
        ratio = ai_tool.ratio or '1:1'
        
        # 映射到 OpenAI size 格式
        size = self._map_size(image_size, ratio)

        # 构建请求体（仅用于文生图，不包含 image 字段）
        payload = {
            "model": self.DEFAULT_MODEL,
            "prompt": ai_tool.prompt or "",
            "n": 1,
            "size": size,
        }

        return {
            "url": f"{self._base_url}/v1/images/generations",
            "method": "POST",
            "json": payload,
            "headers": {
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Authorization": f"Bearer {self._api_key}"
            }
        }

    def build_edit_request(self, ai_tool) -> Dict[str, Any]:
        """
        构建图片编辑请求参数（multipart/form-data 格式）

        Args:
            ai_tool: AITool 对象
                - prompt: 文本描述
                - image_path: 输入图片路径（支持多张，逗号分隔）
                - ratio: 图片比例
                - image_size: 图片分辨率

        Returns:
            Dict[str, Any]: 请求参数字典，包含 files 和 data
        """
        # 获取分辨率和比例
        image_size = getattr(ai_tool, 'image_size', None) or '1k'
        ratio = ai_tool.ratio or '1:1'
        size = self._map_size(image_size, ratio)

        # 解析图片路径列表
        image_paths = [path.strip() for path in ai_tool.image_path.split(',') if path.strip()]
        if not image_paths:
            raise ValueError("图片编辑模式需要至少一张输入图片")

        # 准备文件上传列表
        files = []
        for i, img_path in enumerate(image_paths):
            try:
                file_content, filename, mime_type = self._prepare_image_file(img_path)
                # multipart/form-data 中多个同名字段会作为数组
                files.append(('image', (filename, file_content, mime_type)))
                self.logger.info(f"已准备上传图片 [{i+1}/{len(image_paths)}]: {filename}")
            except Exception as e:
                self.logger.error(f"准备图片文件失败: {img_path}, error: {str(e)}")
                raise

        # 构建表单数据
        form_data = {
            "prompt": ai_tool.prompt or "",
            "model": 'gpt-image-2-all',
            "n": "1",
            "size": size,
        }

        return {
            "url": f"{self._base_url}/v1/images/edits",
            "method": "POST",
            "files": files,
            "data": form_data,
            "headers": {
                "Authorization": f"Bearer {self._api_key}"
            }
        }

    def build_check_query(self, project_id: str) -> Dict[str, Any]:
        """
        构建查询任务状态的完整请求参数

        注意：这是同步接口，此方法仅用于接口兼容
        """
        return {
            "url": "",
            "method": "GET",
            "json": None,
            "headers": {}
        }

    def _truncate_response_for_log(self, response: dict, max_b64_length: int = 100) -> dict:
        """
        截断响应中的 base64 数据用于日志输出，避免日志过长

        Args:
            response: API 响应
            max_b64_length: base64 数据最大显示长度

        Returns:
            截断后的响应副本
        """
        import copy
        truncated = copy.deepcopy(response)
        
        # 处理 data 数组中的 b64_json
        if "data" in truncated and isinstance(truncated["data"], list):
            for item in truncated["data"]:
                if isinstance(item, dict) and "b64_json" in item:
                    b64_data = item["b64_json"]
                    if isinstance(b64_data, str) and len(b64_data) > max_b64_length:
                        item["b64_json"] = f"{b64_data[:max_b64_length]}...[truncated {len(b64_data)} chars]"
        
        return truncated

    def _extract_image_from_response(self, response: dict) -> Optional[str]:
        """
        从 OpenAI API 响应中提取图片 URL 或 base64 数据

        支持两种格式：
        1. images/generations 格式：{ "data": [{ "url": "..." }] }
        2. chat completions 格式：{ "choices": [{ "message": { "content": "..." } }] }

        Args:
            response: API 响应

        Returns:
            Optional[str]: 图片 URL 或 data URL
        """
        try:
            # 1. 尝试处理 images/generations 格式
            data = response.get("data", [])
            if data and isinstance(data, list) and len(data) > 0:
                first_item = data[0]
                if isinstance(first_item, dict):
                    # 优先获取 url 字段
                    if "url" in first_item:
                        return first_item["url"]
                    # 其次获取 b64_json 字段
                    if "b64_json" in first_item:
                        return f"data:image/png;base64,{first_item['b64_json']}"

            # 2. 尝试处理 chat completions 格式
            choices = response.get("choices", [])
            if choices and isinstance(choices, list) and len(choices) > 0:
                first_choice = choices[0]
                if isinstance(first_choice, dict):
                    message = first_choice.get("message", {})
                    if isinstance(message, dict):
                        content = message.get("content", "")
                        if content:
                            # content 可能包含图片 URL 或 base64 数据
                            if isinstance(content, str):
                                if content.startswith("http"):
                                    return content
                                elif content.startswith("data:"):
                                    return content
                                else:
                                    # 可能是 markdown 格式的图片链接
                                    import re
                                    url_match = re.search(r'!\[.*?\]\((.*?)\)', content)
                                    if url_match:
                                        return url_match.group(1)
                                    # 直接返回 content（可能是 URL）
                                    return content

            return None

        except Exception as e:
            self.logger.error(f"Failed to extract image from response: {str(e)}")
            return None

    def _save_base64_to_cache(self, data_url: str, task_id: str) -> Optional[str]:
        """
        将 data URL (base64) 保存到本地缓存

        Args:
            data_url: data URL 格式的数据
            task_id: 任务ID

        Returns:
            本地URL路径，失败返回None
        """
        try:
            cache_manager = get_cache_manager()
            return cache_manager.save_data_url_to_cache(data_url, int(task_id))
        except Exception as e:
            self.logger.error(f"保存 base64 到缓存失败: {str(e)}")
            return None

    def submit_task(self, ai_tool) -> Dict[str, Any]:
        """
        提交 GPT Image 2 图片生成/编辑任务

        注意：这是同步接口，会直接返回结果

        Args:
            ai_tool: AITool 对象
                - prompt: 提示词
                - ratio: 图片比例
                - image_path: 输入图片路径（可选，用于图片编辑）

        Returns:
            Dict[str, Any]: 提交结果
        """
        try:
            # 判断是文生图还是图片编辑
            is_edit_mode = bool(ai_tool.image_path and ai_tool.image_path.strip())
            mode_str = "图片编辑" if is_edit_mode else "文生图"
            self.logger.info(f"Submitting GPT Image 2 task ({mode_str}): prompt='{ai_tool.prompt[:50] if ai_tool.prompt else ''}...', ratio={ai_tool.ratio}")

            # 根据模式构建请求参数
            if is_edit_mode:
                # 图片编辑模式：使用 multipart/form-data
                request_params = self.build_edit_request(ai_tool)
            else:
                # 文生图模式：使用 JSON
                request_params = self.build_create_request(ai_tool)

            # 调用 API（同步接口）
            try:
                result = self._request(timeout=self._timeout, **request_params)
            except Exception as network_error:
                # 捕获所有网络相关异常（包括 requests.exceptions.ReadTimeout, ConnectionError 等）
                error_str = str(network_error).lower()
                if "timeout" in error_str or "connection" in error_str or "timed out" in error_str:
                    self.logger.warning(f"Network error during GPT Image 2 task submission: {str(network_error)}")
                    return {
                        "success": False,
                        "error": "网络连接异常，请稍后重试",
                        "error_type": "USER",
                        "retry": True
                    }
                # 其他异常重新抛出
                raise

            # 截断 base64 数据后输出日志
            truncated_result = self._truncate_response_for_log(result)
            self.logger.info(f"GPT Image 2 API response: {truncated_result}")

            # 检查是否有错误
            if "error" in result:
                error_info = result.get("error", {})
                error_msg = error_info.get("message", "未知错误")
                self.logger.warning(f"GPT Image 2 API returned error: {error_msg}")
                return {
                    "success": False,
                    "error": f"任务提交失败: {error_msg}",
                    "error_type": "USER",
                    "retry": False
                }

            # 提取图片
            image_data = self._extract_image_from_response(result)
            if not image_data:
                self._send_alert(
                    alert_type="INVALID_RESPONSE_FORMAT",
                    message="GPT Image 2 API 未返回图片数据",
                    context={
                        "api": "images/generations",
                        "response_keys": list(result.keys()) if isinstance(result, dict) else str(type(result)),
                        "ai_tool_id": ai_tool.id
                    }
                )
                return {
                    "success": False,
                    "error": "服务异常，图片生成失败",
                    "error_type": "SYSTEM",
                    "error_detail": "API 未返回图片数据",
                    "retry": False
                }

            # 如果是 data URL (base64)，保存到本地缓存
            result_url = image_data
            if image_data.startswith("data:"):
                cached_url = self._save_base64_to_cache(image_data, str(ai_tool.id))
                if not cached_url:
                    self.logger.error(f"保存 base64 到缓存失败")
                    return {
                        "success": False,
                        "error": "服务异常，图片保存失败",
                        "error_type": "SYSTEM",
                        "error_detail": "无法保存生成的图片到缓存",
                        "retry": False
                    }
                result_url = cached_url

            # 同步接口：直接返回成功结果
            return {
                "success": True,
                "sync_mode": True,
                "result_url": result_url
            }

        except Exception as e:
            self.logger.error(f"Unexpected exception in GPT Image 2 submit_task: {str(e)}")
            self.logger.error(traceback.format_exc())

            self._send_alert(
                alert_type="UNEXPECTED_EXCEPTION",
                message=f"GPT Image 2 submit_task 发生未预期异常: {str(e)}",
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
        检查 GPT Image 2 任务状态

        注意：这是同步接口，此方法仅用于接口兼容

        Args:
            project_id: 任务ID

        Returns:
            Dict[str, Any]: 状态检查结果
        """
        return {
            "status": "SUCCESS",
            "message": "同步接口已完成"
        }


# ============ 具体站点实现类 ============

class GptImageCommonSite0V1Driver(GptImageCommonV1Driver):
    """GPT Image Common Site 0 v1 版本驱动

    固定YWAPI官方站点，base_url为 https://yw.perseids.cn
    对应配置 api_aggregator.site_0
    """

    def __init__(self):
        super().__init__(site_id="site_0")


class GptImageCommonSite1V1Driver(GptImageCommonV1Driver):
    """GPT Image Common Site 1 v1 版本驱动"""

    def __init__(self):
        super().__init__(site_id="site_1")


class GptImageCommonSite2V1Driver(GptImageCommonV1Driver):
    """GPT Image Common Site 2 v1 版本驱动"""

    def __init__(self):
        super().__init__(site_id="site_2")


class GptImageCommonSite3V1Driver(GptImageCommonV1Driver):
    """GPT Image Common Site 3 v1 版本驱动"""

    def __init__(self):
        super().__init__(site_id="site_3")


class GptImageCommonSite4V1Driver(GptImageCommonV1Driver):
    """GPT Image Common Site 4 v1 版本驱动"""

    def __init__(self):
        super().__init__(site_id="site_4")


class GptImageCommonSite5V1Driver(GptImageCommonV1Driver):
    """GPT Image Common Site 5 v1 版本驱动"""

    def __init__(self):
        super().__init__(site_id="site_5")
