"""
RunningHub 音频生成驱动
使用 RunningHub OpenAPI v2 异步生成音频
"""
import logging
import traceback
from typing import Dict, Any, Optional

from .base_async_driver import BaseAsyncDriver
from api.clients.runninghub_client import RunningHubClient

logger = logging.getLogger(__name__)


class RunningHubAudioConfig:
    """RunningHub 音频生成配置常量"""
    APP_ID = "2055657238609571841"
    STYLE_NODE_ID = "23"
    TEXT_NODE_ID = "24"
    FINAL_STATUSES = ("SUCCESS", "FAILED", "ERROR", "CANCELED", "CANCELLED")

    # 音色提示词 LLM 生成配置
    AUDIO_STYLE_LLM_MAX_TOKENS = 256
    AUDIO_STYLE_LLM_TEMPERATURE = 0.7
    AUDIO_STYLE_DEFAULT_PROMPT = '声音自然清晰，语气平稳，适合角色旁白'


class RunningHubAudioDriver(BaseAsyncDriver):
    """
    RunningHub 音频生成驱动

    使用 RunningHub AI App 异步生成音频。
    对应的 App ID 和节点 ID 在 RunningHubAudioConfig 中配置。
    """

    def __init__(self):
        super().__init__("runninghub_audio")
        self._client = RunningHubClient()

    @property
    def impl_id(self) -> int:
        from config.unified_config import AsyncTaskImplementationId
        return AsyncTaskImplementationId.RUNNINGHUB_AUDIO

    async def submit_with_slot_management(
        self,
        user_id: int,
        style_prompt: str,
        text: str
    ) -> Dict[str, Any]:
        """使用统一槽位管理的音频提交"""
        params = {
            'style_prompt': style_prompt,
            'text': text
        }

        async def do_submit():
            return await self.submit_task(style_prompt=style_prompt, text=text)

        return await super().submit_with_slot_management(
            user_id=user_id,
            params=params,
            submit_fn=do_submit
        )

    async def submit_task(
        self,
        style_prompt: str,
        text: str,
    ) -> Dict[str, Any]:
        """
        提交音频生成任务到 RunningHub (async，供 scheduler 使用)
        """
        try:
            node_info_list = [
                {
                    'nodeId': RunningHubAudioConfig.STYLE_NODE_ID,
                    'fieldName': 'prompt',
                    'fieldValue': style_prompt,
                    'description': 'prompt'
                },
                {
                    'nodeId': RunningHubAudioConfig.TEXT_NODE_ID,
                    'fieldName': 'prompt',
                    'fieldValue': text,
                    'description': 'prompt'
                }
            ]

            submit_response = await self._client.run_ai_app_v2(
                app_id=RunningHubAudioConfig.APP_ID,
                node_info_list=node_info_list,
                instance_type='default',
                use_personal_queue='false'
            )

            return self._parse_submit_response(submit_response)

        except (ConnectionError, TimeoutError, Exception) as e:
            return self._handle_submit_error(e)

    def submit_task_sync(
        self,
        style_prompt: str,
        text: str,
    ) -> Dict[str, Any]:
        """
        提交音频生成任务到 RunningHub (sync，供 MCP 工具直接调用)
        """
        try:
            node_info_list = [
                {
                    'nodeId': RunningHubAudioConfig.STYLE_NODE_ID,
                    'fieldName': 'prompt',
                    'fieldValue': style_prompt,
                    'description': 'prompt'
                },
                {
                    'nodeId': RunningHubAudioConfig.TEXT_NODE_ID,
                    'fieldName': 'prompt',
                    'fieldValue': text,
                    'description': 'prompt'
                }
            ]

            submit_response = self._client.run_ai_app_v2_sync(
                app_id=RunningHubAudioConfig.APP_ID,
                node_info_list=node_info_list,
                instance_type='default',
                use_personal_queue='false'
            )

            return self._parse_submit_response(submit_response)

        except (ConnectionError, TimeoutError, Exception) as e:
            return self._handle_submit_error(e)

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
            logger.error(f"RunningHub audio submit connection error: {e}")
            return {
                'success': False,
                'error': '网络连接异常，请稍后重试',
                'error_type': 'USER',
                'retry': True
            }
        if isinstance(e, TimeoutError):
            logger.error(f"RunningHub audio submit timeout: {e}")
            return {
                'success': False,
                'error': '请求超时，请稍后重试',
                'error_type': 'USER',
                'retry': True
            }
        logger.error(f"RunningHub audio submit error: {e}\n{traceback.format_exc()}")
        return {
            'success': False,
            'error': f'提交音频生成任务失败: {str(e)}',
            'error_type': 'SYSTEM',
            'error_detail': traceback.format_exc(),
            'retry': False
        }

    async def check_status(self, project_id: str) -> Dict[str, Any]:
        """
        查询 RunningHub 音频生成任务状态

        Args:
            project_id: RunningHub 任务 ID

        Returns:
            Dict[str, Any]: 结果字典
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

            if remote_status in RunningHubAudioConfig.FINAL_STATUSES:
                error_message = (
                    query_response.get('errorMessage')
                    or str(query_response.get('failedReason') or '音频生成失败')
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
            logger.error(f"RunningHub audio check connection error: {e}")
            return {
                'status': 'FAILED',
                'error': '网络连接异常，请稍后重试',
                'error_type': 'USER',
                'retry': True
            }
        except TimeoutError as e:
            logger.error(f"RunningHub audio check timeout: {e}")
            return {
                'status': 'FAILED',
                'error': '请求超时，请稍后重试',
                'error_type': 'USER',
                'retry': True
            }
        except Exception as e:
            logger.error(f"RunningHub audio check error: {e}\n{traceback.format_exc()}")
            return {
                'status': 'FAILED',
                'error': f'查询音频状态失败: {str(e)}',
                'error_type': 'SYSTEM',
                'error_detail': traceback.format_exc()
            }

    @staticmethod
    def _extract_result_url(response_data: Dict[str, Any]) -> Optional[str]:
        """从 RunningHub v2 响应中提取结果 URL"""
        for item in response_data.get('results') or []:
            result_url = item.get('url')
            if result_url:
                return result_url
        return None
