"""ask_user question 负载质量校验测试。

设计取向（会话 50687e18 事故，2026-09-29）：不做修复式清洗——question 携带的
```json 代码块无法解析、或混入模型输出退化残片时，直接报错打回让 LLM 重新生成。
残缺 JSON 会让前端确认卡渲染降级成原始文本，用户无按钮可点只能等 5 分钟超时。

覆盖路径：
  - 合法 json 块 → 通过；
  - 字段值未加引号（事故真实形态：estimated_consumption: 约 6 算力(...)）→ 报错；
  - 新形态退化残片（</think_never_used_HASH><parameter name=...>）→ 报错；
  - 旧形态残片（, "parameter name=）→ 被既有清洗截断后校验通过；
  - 集成路径：question 非法时 _handle_ask_user 提前返回 error，不创建 verification。
"""

from script_writer_core.agents.ask_user_mixin import (
    AskUserMixin,
    _strip_degraded_tail,
    _validate_question_payload,
)

# 会话 50687e18 / chat_messages 22856 的真实事故样本（截取要害）：
# estimated_consumption 值未加引号 → JSON 非法；尾部混入 </think...><parameter 残片
_ACCIDENT_QUESTION = (
    "已为您生成以下视频脚本，请确认：\n```json\n"
    "{\n"
    '  "type": "article_to_video_script",\n'
    '  "clips": [{"index": 1, "duration_seconds": 15, "prompt": "卧室助眠场景"}]\n'
    "}\n"
    "```\n"
    "```json\n"
    "{\n"
    '  "estimated_total_seconds": 30,\n'
    '  "estimated_consumption": 约 6 算力（Seedance 2.5 每15秒约3算力）\n'
    "}\n"
    "```\n"
    "请确认是否按此脚本生成视频？"
    "</think_never_used_51bce0c785ca2f68081bfa7d91973934>"
    '<parameter name="options" string="false">["确认生成", "修改脚本", "取消"]'
)

_LEGAL_QUESTION = (
    "请确认以下视频脚本：\n```json\n"
    "{\n"
    '  "type": "article_to_video_script",\n'
    '  "video_title": "助眠技巧",\n'
    '  "clips": [{"index": 1, "duration_seconds": 10, '
    '"prompt": "彩铅手绘治愈风格……旁白口播：\u201c一点动静就惊醒\u201d"}]\n'
    "}\n```"
)

# dfd1c1d5 已修复的旧形态（引号开头），应继续被静默清洗而非报错
_OLD_FORM_QUESTION = '请确认脚本。", "parameter name="options" string="false">'


def test_legal_json_passes():
    assert _validate_question_payload(_LEGAL_QUESTION) is None


def test_unquoted_value_reports_error():
    # 只保留非法 json 块（去掉残片部分，单测各路径独立）
    head = _ACCIDENT_QUESTION.split("</think_never_used")[0]
    error = _validate_question_payload(head)

    assert error is not None
    assert "合法 JSON" in error
    # 指出第几个块、行列位置，供 LLM 定位自纠
    assert "第 2 个 json" in error
    assert "estimated_consumption" in error or "行" in error


def test_think_fragment_reports_error():
    # 残片单独出现也要拦：即使 json 块本身合法
    question = _LEGAL_QUESTION + (
        "</think_never_used_abc123>"
        '<parameter name="options" string="false">["确认生成"]'
    )
    error = _validate_question_payload(question)

    assert error is not None
    assert "退化残片" in error
    assert "重新调用 ask_user" in error


def test_accident_question_reports_error():
    """事故原始样本整体校验：残片检测先命中（优先打回，避免带残片的载荷继续流转）。"""
    error = _validate_question_payload(_ACCIDENT_QUESTION)

    assert error is not None
    assert "退化残片" in error


def test_old_form_fragment_still_cleaned_not_rejected():
    """旧形态（, "parameter name=）由既有清洗静默截断，校验放行，不打回。"""
    cleaned = _strip_degraded_tail(_OLD_FORM_QUESTION)

    assert "parameter name" not in cleaned
    assert _validate_question_payload(cleaned) is None


def test_plain_text_question_passes():
    """无 json 块的普通提问不受影响。"""
    assert _validate_question_payload("是否继续生成第二个片段？") is None
    assert _validate_question_payload("") is None


class _RecordingAgent(AskUserMixin):
    """带 mock task_manager 的最小 agent，断言非法负载不会创建 verification。"""

    agent_id = "expert_article-to-video"

    def __init__(self):
        self.task_manager = _RecordingTaskManager()
        self.task_id = "task-x"
        self._ask_fail_count = 0
        self._conversation_recorder = None
        self._session_id = None


class _RecordingTaskManager:
    def __init__(self):
        self.created = []

    def create_verification(self, **kwargs):
        self.created.append(kwargs)
        raise AssertionError("非法负载不得创建 verification")


def test_handle_ask_user_rejects_illegal_json_without_verification():
    agent = _RecordingAgent()

    result = agent._handle_ask_user(
        {"question": _ACCIDENT_QUESTION, "options": ["确认生成", "修改脚本", "取消"]}
    )

    assert result.get("error")
    assert result.get("user_input") is None
    assert agent.task_manager.created == []
