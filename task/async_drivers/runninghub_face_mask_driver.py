"""
RunningHub 人脸遮盖视频生成驱动
使用 RunningHub OpenAPI v2 异步生成人脸遮盖区域的视频
"""
import logging
import traceback
from typing import Dict, Any, Optional

from .base_async_driver import BaseAsyncDriver
from api.clients.runninghub_client import RunningHubClient
from config.config_util import get_config, get_dynamic_config_value
from utils.file_storage import RunningHubFileStorage

logger = logging.getLogger(__name__)


class RunningHubFaceMaskConfig:
    """RunningHub 人脸遮盖视频生成配置常量"""
    APP_ID = "2059109399586762753"
    VIDEO_NODE_ID = "3"
    VIDEO_FIELD_NAME = "video"
    FINAL_STATUSES = ("SUCCESS", "FAILED", "ERROR", "CANCELED", "CANCELLED")


class RunningHubFaceMaskDriver(BaseAsyncDriver):
    """
    RunningHub 人脸遮盖视频生成驱动

    使用 RunningHub AI App 异步生成人脸遮盖视频。
    流程：上传视频到 RunningHub 媒体服务器 → 提交 AI App 任务 → 轮询结果
    """

    @property
    def impl_id(self) -> int:
        from config.unified_config import AsyncTaskImplementationId
        return AsyncTaskImplementationId.RUNNINGHUB_FACE_MASK

    def __init__(self):
        super().__init__("runninghub_face_mask")
        self._client = RunningHubClient()

        host = get_dynamic_config_value("runninghub", "host", default="https://www.runninghub.cn")
        api_key = get_dynamic_config_value("runninghub", "api_key", default="")
        self._config = get_config()
        self._storage = RunningHubFileStorage(
            host=host,
            api_key=api_key,
            config=self._config,
            logger=self.logger
        )

    async def submit_task(self, video_path: str, **kwargs) -> Dict[str, Any]:
        """
        提交人脸遮盖视频生成任务到 RunningHub

        步骤：
        1. 上传视频到 RunningHub 媒体服务器
        2. 用返回的 fileName 构建 nodeInfoList 提交 AI App 任务

        Args:
            video_path: 本地文件路径或 URL

        Returns:
            {'success': True, 'project_id': taskId} 或 {'success': False, 'error': ...}
        """
        try:
            upload_result = await self._storage.upload_file(
                key="",
                file_path=video_path
            )
            if not upload_result.success:
                return {
                    'success': False,
                    'error': f'视频上传失败: {upload_result.error}',
                    'error_type': 'USER',
                    'retry': False
                }

            uploaded_filename = upload_result.key

            node_info_list = [
                {
                    'nodeId': RunningHubFaceMaskConfig.VIDEO_NODE_ID,
                    'fieldName': RunningHubFaceMaskConfig.VIDEO_FIELD_NAME,
                    'fieldValue': uploaded_filename,
                    'description': 'video'
                }
            ]

            submit_response = await self._client.run_ai_app_v2(
                app_id=RunningHubFaceMaskConfig.APP_ID,
                node_info_list=node_info_list,
                instance_type='default',
                use_personal_queue='false'
            )

            return self._parse_submit_response(submit_response)

        except (ConnectionError, TimeoutError, Exception) as e:
            return self._handle_submit_error(e)

    async def check_status(self, project_id: str) -> Dict[str, Any]:
        """
        查询 RunningHub 人脸遮盖视频任务状态

        Args:
            project_id: RunningHub 任务 ID

        Returns:
            RUNNING: {"status": "RUNNING"}
            SUCCESS: {"status": "SUCCESS", "result_url": "..."}
            FAILED:  {"status": "FAILED", "error": "...", "error_type": "USER"|"SYSTEM"}
        """
        try:
            query_response = await self._client.query_v2_task(project_id)
            remote_status = query_response.get('status')

            if remote_status == 'SUCCESS':
                result_url = self._extract_result_url(query_response)
                if result_url:
                    return {
                        'status': 'SUCCESS',
                        'result_url': result_url
                    }
                else:
                    return {
                        'status': 'FAILED',
                        'error': '任务成功但未返回结果 URL',
                        'error_type': 'SYSTEM',
                        'error_detail': f"Response: {query_response}"
                    }

            if remote_status in RunningHubFaceMaskConfig.FINAL_STATUSES:
                error_message = (
                    query_response.get('errorMessage')
                    or str(query_response.get('failedReason') or '人脸遮盖视频生成失败')
                )
                return {
                    'status': 'FAILED',
                    'error': error_message,
                    'error_type': 'USER'
                }

            return {
                'status': 'RUNNING'
            }

        except ConnectionError as e:
            logger.error(f"RunningHub face mask check connection error: {e}")
            return {
                'status': 'FAILED',
                'error': '网络连接异常，请稍后重试',
                'error_type': 'USER',
                'retry': True
            }
        except TimeoutError as e:
            logger.error(f"RunningHub face mask check timeout: {e}")
            return {
                'status': 'FAILED',
                'error': '请求超时，请稍后重试',
                'error_type': 'USER',
                'retry': True
            }
        except Exception as e:
            logger.error(f"RunningHub face mask check error: {e}\n{traceback.format_exc()}")
            return {
                'status': 'FAILED',
                'error': f'查询人脸遮盖视频状态失败: {str(e)}',
                'error_type': 'SYSTEM',
                'error_detail': traceback.format_exc()
            }

    @staticmethod
    def _parse_submit_response(submit_response: Dict[str, Any]) -> Dict[str, Any]:
        """解析提交响应"""
        runninghub_task_id = submit_response.get('taskId')
        if not runninghub_task_id:
            error_message = submit_response.get('errorMessage') or 'RunningHub 未返回任务 ID'
            return {
                'success': False,
                'error': error_message,
                'error_code': submit_response.get('errorCode', ''),
                'error_type': 'SYSTEM',
                'error_detail': f"RunningHub response: {submit_response}",
                'retry': False
            }

        return {
            'success': True,
            'project_id': runninghub_task_id
        }

    @staticmethod
    def _handle_submit_error(e: Exception) -> Dict[str, Any]:
        """处理提交异常"""
        if isinstance(e, ConnectionError):
            logger.error(f"RunningHub face mask submit connection error: {e}")
            return {
                'success': False,
                'error': '网络连接异常，请稍后重试',
                'error_type': 'USER',
                'retry': True
            }
        if isinstance(e, TimeoutError):
            logger.error(f"RunningHub face mask submit timeout: {e}")
            return {
                'success': False,
                'error': '请求超时，请稍后重试',
                'error_type': 'USER',
                'retry': True
            }
        logger.error(f"RunningHub face mask submit error: {e}\n{traceback.format_exc()}")
        return {
            'success': False,
            'error': f'提交人脸遮盖视频任务失败: {str(e)}',
            'error_type': 'SYSTEM',
            'error_detail': traceback.format_exc(),
            'retry': False
        }

    @staticmethod
    def _extract_result_url(response_data: Dict[str, Any]) -> Optional[str]:
        """从 RunningHub v2 响应中提取结果 URL"""
        for item in response_data.get('results') or []:
            result_url = item.get('url')
            if result_url:
                return result_url
        return None
