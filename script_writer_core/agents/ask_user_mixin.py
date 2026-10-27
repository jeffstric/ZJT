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

import json
import logging
import re
from typing import Any, Dict, List, Optional

from config.unified_config import ASK_USER_MAX_CONSECUTIVE_FAILS
from script_writer_core.agents.power_budget import PowerBudgetExhaustedError

logger = logging.getLogger(__name__)

# LLM 输出退化残片特征：question 值结束后紧跟的半截参数语法
# （实测形态：`, "parameter name="options" string="false">`）
_DEGRADED_TAIL_RE = re.compile(r",?\s*\"parameter name=")

# question 内嵌 ```json 代码块（ask_user 结构化确认卡负载）。
# ⚠️ 只匹配显式 json 围栏：此前 (?:json)? 可选导致 python/mermaid/text 等
# 任意语言围栏也被捕获并按 JSON 校验，合法 ask_user 被整卡打回重写。
# 容忍围栏与语言名之间的空白（``` json）与大小写；语言名后必须换行。
_JSON_BLOCK_RE = re.compile(r"```[\t ]*json[\t ]*\r?\n([\s\S]*?)```", re.IGNORECASE)

# 输出退化残片检测（比 _DEGRADED_TAIL_RE 宽，用于报错打回而非清洗）：
# 覆盖 `</think_never_used_HASH>` 伪闭合标签与 `<parameter name=` 尖括号形态
# （2026-09-29 会话 50687e18 实测：`, "parameter name=` 引号形态之外的漏网变体）
_DEGRADED_FRAG_RE = re.compile(r"</think[^>]*>|<parameter\s+name=|\"\s*parameter\s+name=")


def _strip_degraded_tail(question: str) -> str:
    """截断 question 尾部的 LLM 输出退化残片（无残片则原样返回）。"""
    if not question:
        return question
    m = _DEGRADED_TAIL_RE.search(question)
    if m:
        cleaned = question[:m.start()].rstrip()
        # 残片起点前的孤立收尾引号（LLM 提前闭合字符串的痕迹）一并去掉
        if cleaned.endswith('"'):
            cleaned = cleaned[:-1].rstrip()
        logger.warning(
            "[ask_user] question 含输出退化残片，已截断 %d 字符",
            len(question) - len(cleaned),
        )
        return cleaned
    return question


# 编号列表项粘连换行（会话 0aa4dc0a 事故，2026-10-21）：LLM 生成的 question 偶发把
# 编号列表全部挤在一行且项间无分隔（"…如下：1. 匹配音色…2. 试听链接…"），前端
# 裸音频 URL 转 <audio> 播放器的正则要求扩展名后紧跟空白/结尾，列表粘连既会让
# 试听链接不渲染播放器、列表也不换行。仅在标点（冒号/句号/括号/问号）后粘连时
# 补换行——数字紧跟数字的歧义形态（"…mp33. …"，前端扩展名后允许数字终止可正确处理）
# 与中文字母正常行文（"第4季度"无点号）不在此强拆；CJK 结尾（"文案4. "）同样补换行。
_GLUED_LIST_ITEM_RE = re.compile(r'([：:。！？!?）)\u4e00-\u9fff])(\d{1,2}[.、](?=\s))')


def _normalize_question_list_layout(question: str) -> str:
    """编号列表项与上文粘连时强制换行（"：1. " → "：\\n1. "），无粘连原样返回。"""
    if not question:
        return question
    normalized = _GLUED_LIST_ITEM_RE.sub(r'\1\n\2', question)
    if normalized != question:
        logger.info("[ask_user] question 编号列表粘连，已强制换行: %s",
                    question[:120])
    return normalized


def _validate_question_payload(question: str) -> Optional[str]:
    """校验 question 携带的结构化负载，返回错误文案（打回让 LLM 重新生成）或 None。

    设计取向：不做修复式清洗——格式坏到无法解析就直接报错让模型重写，
    避免残缺脚本导致前端确认卡渲染降级（用户面对原始 JSON 无按钮可点，
    2026-09-29 会话 50687e18：estimated_consumption 字段值未加引号 + 尾部退化残片）。

    校验两项：
    1. 退化残片：`</think...>` 伪标签 / `<parameter name=` 半截参数语法；
    2. ```json 代码块必须能被 json.loads 直接解析。
    """
    if not question:
        return None
    m = _DEGRADED_FRAG_RE.search(question)
    if m:
        return (
            "question 中混入了模型输出退化残片（</think...> 标签或 <parameter name=...> "
            "半截参数语法），这是你生成参数时的格式错误，不是用户能看到的内容。"
            "请重新调用 ask_user：完整重写 question，确保以纯文本+合法 json 代码块组成，"
            "禁止包含任何 XML/HTML 标签残片。"
        )
    for i, block in enumerate(_JSON_BLOCK_RE.findall(question), 1):
        body = block.strip()
        if not body:
            continue
        try:
            json.loads(body)
        except json.JSONDecodeError as e:
            return (
                f"question 中第 {i} 个 json 代码块不是合法 JSON（{e.msg}，"
                f"第 {e.lineno} 行第 {e.colno} 列附近）。常见原因：字段值含中文/单位/括号"
                "却没有加引号、自造了模板外的估算字段。请输出能被 JSON.parse 直接解析的"
                "合法 JSON 后重新调用 ask_user，不要在 JSON 里写任何模板未定义的字段。"
            )
    return None


# 选项对象中可提取展示文案的字段，按优先级排列
_OPTION_TEXT_KEYS = ("label", "option", "text", "value", "name", "title", "content")


def _normalize_ask_options(options: Any) -> List[str]:
    """把 LLM 返回的 options 归一化为字符串列表。

    工具 schema 要求 options 为 string 数组，但模型偶尔会返回
    {"label": ..., "description": ...} 等对象（事故：前端渲染成
    [object Object]，用户无法作答，导致连续 5 分钟超时）。
    这里兼容提取对象中的文案字段；取不到文案的元素丢弃，
    归一化后为空由调用方报错让模型按正确格式重试。
    """
    if isinstance(options, str):
        # 模型偶尔把整个数组塞进字符串，尝试解析
        try:
            options = json.loads(options)
        except (TypeError, ValueError):
            return []

    if not isinstance(options, list):
        return []

    normalized: List[str] = []
    for item in options:
        text = None
        if isinstance(item, str):
            text = item.strip()
        elif isinstance(item, dict):
            for key in _OPTION_TEXT_KEYS:
                value = item.get(key)
                if isinstance(value, str) and value.strip():
                    text = value.strip()
                    break
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    text = str(value)
                    break
        elif isinstance(item, (int, float)) and not isinstance(item, bool):
            text = str(item)
        if text:
            normalized.append(text)
    return normalized


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

        # 单次任务算力预算：超限后立即返回，不创建提问、不进入 5 分钟等待，
        # 掐断无人应答时「提问→超时→LLM 重试→再提问」的空转扣费循环
        budget = getattr(self, 'power_budget', None)
        if budget is not None:
            try:
                budget.check()
            except PowerBudgetExhaustedError as e:
                logger.warning(f"{self.agent_id}: {e.message}")
                return {
                    "error": f"{e.message}。请立即停止工作，不要继续提问或执行任何消耗算力的操作。",
                    "user_input": None,
                    "ask_disabled": True,
                }

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

        # 清洗 LLM 输出退化残片：question 尾部偶发混入格式损坏 token（实测形如
        # `, "parameter name="options" string="false">` ——LLM 写长转义 JSON 时输出
        # 退化，恰好不破坏 arguments 整体 JSON 解析，残片随 question 透到前端渲染）。
        question = _strip_degraded_tail(question)

        # 编号列表粘连强制换行（0aa4dc0a）：保证前端裸媒体 URL 转换与列表渲染正常
        question = _normalize_question_list_layout(question)

        # 负载质量校验：清洗覆盖不了的残片新形态 + ```json 块非法 → 直接报错打回，
        # 让 LLM 重新生成（不做修复式兜底：残缺 JSON 会让前端确认卡渲染降级成
        # 原始文本，用户无按钮可点只能等 5 分钟超时，会话 50687e18 实测）。
        payload_error = _validate_question_payload(question)
        if payload_error:
            logger.warning("%s: [ask_user] question 负载校验失败，打回重写: %s",
                           self.agent_id, payload_error[:120])
            return {"error": payload_error, "user_input": None}

        # 选项归一化（develop 16dc760c）：LLM 偶尔把 options 写成对象数组（前端
        # 渲染成 [object Object] 导致用户无法作答、连续 5 分钟超时），兼容提取
        # 文案字段；归一化后为空报错让模型按字符串数组格式重试。
        options = _normalize_ask_options(options)
        if not options:
            return {
                "error": "options 参数无效：必须是字符串数组且至少一项，"
                         "例如 [\"选项一\", \"选项二\"]，不要传对象、空数组或无法解析的内容"
            }

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
