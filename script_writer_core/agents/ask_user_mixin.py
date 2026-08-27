"""
AskUserMixin - 向用户提问并等待回答的共享功能

使用方式：
    class MyAgent(BaseAgent, AskUserMixin):
        def __init__(self, ...):
            self.task_manager = ...
            self.task_id = ...

要求子类具备以下属性：
    - self.task_manager: TaskManager 实例
    - self.task_id: str，当前任务 ID
    - self.agent_id: str，智能体标识（用于日志）
"""

import logging
from typing import Dict, Any

from config.unified_config import ASK_USER_MAX_CONSECUTIVE_FAILS

logger = logging.getLogger(__name__)


class AskUserMixin:
    """向用户提问并等待回答的 Mixin"""

    # agent_id → 中文显示名映射
    _DISPLAY_NAME_MAP = {
        "pm_agent": "剧本编排",
        "marketing_pm_agent": "营销智能体",
        "expert_story-writer": "故事写手",
        "expert_character-creator": "角色设计",
        "expert_location-creator": "场景设计",
        "expert_plot-analyzer": "剧情分析",
        "expert_content-compliance-checker": "内容审核",
        "expert_novel-episode-splitter": "剧集拆分",
        "expert_character-image-designer": "角色形象设计",
        "expert_location-prop-image-designer": "场景道具设计",
        "expert_image-understanding": "图片理解",
    }

    def _get_agent_display_name(self) -> str:
        """获取当前智能体的中文显示名"""
        agent_id = getattr(self, 'agent_id', '')
        if agent_id in self._DISPLAY_NAME_MAP:
            return self._DISPLAY_NAME_MAP[agent_id]
        # 兜底：从 agent_id 提取 skill 名称
        if agent_id.startswith("expert_"):
            return agent_id[len("expert_"):]
        return agent_id or "AI"

    def _handle_ask_user(
        self,
        tool_args: Dict[str, Any],
        verification_type: str = "ask_user",
    ) -> Dict[str, Any]:
        """处理 ask_user 工具调用 - 向用户提问并等待响应

        Args:
            tool_args: LLM 传入的工具参数，包含 question, options, context
            verification_type: 写入 agent_verifications 的类型，默认 ask_user；
                系统算力确认门传入 computing_power_confirm

        Returns:
            成功: {"success": True, "user_input": "...", "message": "用户已回答: ..."}
            超时/失败: {"error": "...", "user_input": None}
            已禁用: {"error": "...", "user_input": None, "ask_disabled": True}
        """
        # 检查连续失败次数 - 达到上限后直接返回错误，不创建 verification，节省算力
        fail_count = getattr(self, '_ask_fail_count', 0)
        if fail_count >= ASK_USER_MAX_CONSECUTIVE_FAILS:
            error_msg = (f"ask_user 已连续失败 {fail_count} 次，用户当前可能无法回应。"
                         f"请立即停止工作，不要继续提问，等待用户主动发送消息后再继续。")
            logger.warning(f"{self.agent_id}: {error_msg}")
            return {"error": error_msg, "user_input": None, "ask_disabled": True}

        # 检查必要依赖
        if not getattr(self, 'task_manager', None) or not getattr(self, 'task_id', None):
            error_msg = (
                "ask_user 在当前环境不可用：后台任务（如接口模块生成）没有会话界面，"
                "无法向用户提问，重试也不会成功。请立即停止提问尝试；若存在必须由管理员"
                "确认的事项（如能力覆盖范围、参数规格），把它们整理进任务结束总结并如实"
                "报告\"任务未完成，待管理员补充需求后重新发起\"。"
            )
            logger.warning(f"{self.agent_id}: {error_msg}")
            return {"error": error_msg, "user_input": None, "ask_disabled": True}

        # 提取参数
        question = tool_args.get("question", "")
        options = tool_args.get("options", [])
        context = tool_args.get("context", {})

        if not question:
            return {"error": "question 参数不能为空"}

        if not options or not isinstance(options, list) or len(options) == 0:
            return {"error": "options 参数不能为空，必须提供至少一个选项供用户选择"}

        logger.info(f"{self.agent_id}: Creating user verification request: {question}")

        try:
            # 创建验证请求
            agent_name = self._get_agent_display_name()
            title = tool_args.get("title") or f"{agent_name} 向您提问"
            verification = self.task_manager.create_verification(
                task_id=self.task_id,
                verification_type=verification_type or "ask_user",
                title=title,
                description=question,
                options=options,
                context=context
            )

            # 立即将 verification_request 写入 chat_messages（Agent 后台线程，同步调用）
            if getattr(self, '_conversation_recorder', None) and getattr(self, '_session_id', None):
                try:
                    self._conversation_recorder.append_message(
                        session_id=self._session_id,
                        role="verification",
                        content={
                            "title": title,
                            "description": question,
                            "options": options,
                            "verification_id": verification.verification_id,
                            "verification_type": verification_type or "ask_user",
                            "context": context,
                        },
                        message_type="verification_request",
                        verification_id=verification.verification_id,
                        visibility="ui",
                        source="verification",
                        agent_scope=getattr(self, '_agent_scope', 'pm'),
                        task_id=getattr(self, '_task_id', None),
                    )
                except Exception as e:
                    logger.error(f"{self.agent_id}: Failed to persist verification_request: {e}")

            # 阻塞等待用户响应（最多5分钟）
            result = self.task_manager.wait_for_verification(
                verification=verification,
                timeout=300
            )

            logger.info(f"{self.agent_id}: User responded: {result}")

            # 检查是否超时或出错
            if not result.get("success"):
                status = result.get("status", "")
                if status != "timeout":
                    # 只有非超时的失败才计入连续失败计数
                    self._ask_fail_count = getattr(self, '_ask_fail_count', 0) + 1
                    logger.warning(f"{self.agent_id}: ask_user failed ({self._ask_fail_count}/{ASK_USER_MAX_CONSECUTIVE_FAILS})")
                else:
                    logger.info(f"{self.agent_id}: ask_user 超时，不计入失败计数")
                return {
                    "error": result.get("error", "验证失败"),
                    "user_input": None
                }

            # 成功，重置失败计数
            self._ask_fail_count = 0
            raw_user_input = result.get("user_input", "") or ""

            media_parts = []
            for i, image_url in enumerate(result.get("image_urls") or []):
                thumb = ""
                thumbnail_urls = result.get("thumbnail_urls") or []
                if i < len(thumbnail_urls) and thumbnail_urls[i]:
                    thumb = f" thumb: {thumbnail_urls[i]}"
                media_parts.append(f"[图片{i + 1}]（URL: {image_url}{thumb}）")
            for i, video_url in enumerate(result.get("video_urls") or []):
                media_parts.append(f"[视频{i + 1}]（URL: {video_url}）")
            for i, audio_url in enumerate(result.get("audio_urls") or []):
                media_parts.append(f"[音频{i + 1}]（URL: {audio_url}）")

            user_input_with_media = raw_user_input
            if media_parts:
                user_input_with_media = "\n".join(media_parts) + "\n\n" + raw_user_input

            # 返回用户的回答（附带 verification 元数据，用于写入 conversation_history）
            return {
                "success": True,
                "user_input": user_input_with_media,
                "message": f"用户已回答: {raw_user_input}",
                "image_urls": result.get("image_urls"),
                "video_urls": result.get("video_urls"),
                "audio_urls": result.get("audio_urls"),
                "thumbnail_urls": result.get("thumbnail_urls"),
                "_verification_meta": {
                    "verification_id": verification.verification_id,
                    "question": question,
                    "options": options
                }
            }

        except Exception as e:
            error_msg = f"ask_user 处理失败: {str(e)}"
            logger.error(f"{self.agent_id}: {error_msg}", exc_info=True)
            return {"error": error_msg}
