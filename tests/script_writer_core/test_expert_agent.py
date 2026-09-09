"""
ExpertAgent 单元测试

测试 _is_deepseek_model 和 _format_messages_for_api 的纯逻辑。
"""
import os
import sys
import json
import unittest
from unittest.mock import patch, MagicMock

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, project_root)

from script_writer_core.agents.expert_agent import ExpertAgent


class TestExpertAgent(unittest.TestCase):
    """ExpertAgent 测试基类"""

    def _create_agent(self, model="deepseek-chat", **kwargs):
        with patch('script_writer_core.agents.expert_agent.SkillLoader') as MockSkillLoader:
            mock_loader = MagicMock()
            mock_loader.get_skill_prompt.return_value = "test skill"
            MockSkillLoader.return_value = mock_loader

            defaults = {
                "skill_names": ["story-writer"],
                "model": model,
                "allowed_tools": ["tool1"],
                "context_from_pm": "ctx",
                "file_manager": MagicMock(),
                "user_id": "1",
                "world_id": "w1",
                "auth_token": "token",
                "tool_executor": MagicMock(),
            }
            defaults.update(kwargs)
            return ExpertAgent(**defaults)


class TestIsDeepseekModel(TestExpertAgent):
    """测试 _is_deepseek_model"""

    def test_deepseek_lower(self):
        agent = self._create_agent(model="deepseek-chat")
        self.assertTrue(agent._is_deepseek_model())

    def test_deepseek_upper(self):
        agent = self._create_agent(model="DeepSeek-R1")
        self.assertTrue(agent._is_deepseek_model())

    def test_not_deepseek(self):
        agent = self._create_agent(model="gpt-4")
        self.assertFalse(agent._is_deepseek_model())

    def test_empty_model(self):
        agent = self._create_agent(model="")
        self.assertFalse(agent._is_deepseek_model())

    def test_deepseek_in_middle(self):
        agent = self._create_agent(model="my-deepseek-model")
        self.assertTrue(agent._is_deepseek_model())


class TestFormatMessagesForApi(TestExpertAgent):
    """测试 _format_messages_for_api"""

    def test_basic_format(self):
        agent = self._create_agent(model="gpt-4")
        agent.conversation_history = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        messages = agent._format_messages_for_api()
        self.assertEqual(messages[0], {"role": "system", "content": agent.system_prompt})
        self.assertEqual(messages[1], {"role": "user", "content": "hello"})
        self.assertEqual(messages[2], {"role": "assistant", "content": "hi"})

    def test_tool_message(self):
        agent = self._create_agent(model="gpt-4")
        agent.conversation_history = [
            {"role": "tool", "content": {"tool_call_id": "tc1", "name": "tool1", "content": "result"}},
        ]
        messages = agent._format_messages_for_api()
        self.assertEqual(messages[0], {"role": "system", "content": agent.system_prompt})
        self.assertEqual(messages[1], {
            "role": "tool",
            "tool_call_id": "tc1",
            "name": "tool1",
            "content": "result"
        })

    def test_assistant_with_tool_calls(self):
        agent = self._create_agent(model="gpt-4")
        agent.conversation_history = [
            {"role": "assistant", "content": {"tool_calls": [{"id": "tc1", "function": {"name": "f1"}}]}},
        ]
        messages = agent._format_messages_for_api()
        self.assertEqual(messages[1]["role"], "assistant")
        self.assertIsNone(messages[1]["content"])
        self.assertEqual(messages[1]["tool_calls"], [{"id": "tc1", "function": {"name": "f1"}}])

    def test_deepseek_adds_empty_reasoning(self):
        agent = self._create_agent(model="deepseek-chat")
        agent.conversation_history = [
            {"role": "assistant", "content": "hello"},
        ]
        messages = agent._format_messages_for_api()
        assistant_msg = messages[1]
        self.assertEqual(assistant_msg["role"], "assistant")
        self.assertEqual(assistant_msg["content"], "hello")
        self.assertEqual(assistant_msg["reasoning_content"], "")

    def test_deepseek_preserves_existing_reasoning(self):
        agent = self._create_agent(model="deepseek-chat")
        agent.conversation_history = [
            {"role": "assistant", "content": {"text": "hello", "reasoning_content": "think"}},
        ]
        messages = agent._format_messages_for_api()
        assistant_msg = messages[1]
        self.assertEqual(assistant_msg["reasoning_content"], "think")
        self.assertEqual(assistant_msg["content"], "hello")

    def test_non_deepseek_no_reasoning_added(self):
        agent = self._create_agent(model="gpt-4")
        agent.conversation_history = [
            {"role": "assistant", "content": "hello"},
        ]
        messages = agent._format_messages_for_api()
        self.assertNotIn("reasoning_content", messages[1])

    def test_verification_message_skipped(self):
        agent = self._create_agent(model="gpt-4")
        agent.conversation_history = [
            {"role": "user", "content": "q"},
            {"role": "verification", "content": "please confirm"},
            {"role": "assistant", "content": "answer"},
        ]
        messages = agent._format_messages_for_api()
        roles = [m["role"] for m in messages]
        self.assertNotIn("verification", roles)
        self.assertEqual(roles, ["system", "user", "assistant"])

    def test_assistant_dict_without_tool_calls(self):
        agent = self._create_agent(model="gpt-4")
        agent.conversation_history = [
            {"role": "assistant", "content": {"text": "answer", "extra": "data"}},
        ]
        messages = agent._format_messages_for_api()
        self.assertEqual(messages[1]["role"], "assistant")
        self.assertEqual(messages[1]["content"], "{'text': 'answer', 'extra': 'data'}")

    def test_assistant_with_thought_signature(self):
        agent = self._create_agent(model="gpt-4")
        agent.conversation_history = [
            {"role": "assistant", "content": {"tool_calls": [{"id": "tc1"}], "thought_signature": "sig1"}},
        ]
        messages = agent._format_messages_for_api()
        self.assertEqual(messages[1]["thought_signature"], "sig1")

    def test_tool_message_with_string_content(self):
        agent = self._create_agent(model="gpt-4")
        agent.conversation_history = [
            {"role": "tool", "content": {"tool_call_id": "tc1", "name": "tool1", "content": "plain text"}},
        ]
        messages = agent._format_messages_for_api()
        self.assertEqual(messages[1]["content"], "plain text")

    def test_empty_history(self):
        agent = self._create_agent(model="gpt-4")
        agent.conversation_history = []
        messages = agent._format_messages_for_api()
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["role"], "system")

    def test_assistant_none_content(self):
        agent = self._create_agent(model="gpt-4")
        agent.conversation_history = [
            {"role": "assistant", "content": None},
        ]
        messages = agent._format_messages_for_api()
        self.assertEqual(messages[1]["role"], "assistant")
        self.assertEqual(messages[1]["content"], "None")


class TestPruneHistoryImages(TestExpertAgent):
    """测试 _prune_history_images：历史中图片只保留最近 N 张，旧图替换为文本占位"""

    def _multimodal_msg(self, urls):
        content = []
        for url in urls:
            content.append({"type": "text", "text": f"[系统注入] 以下是工具成功获取的图片（URL: {url}）："})
            content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{url}"}})
        return {"role": "user", "content": content}

    def test_below_limit_noop(self):
        agent = self._create_agent()
        agent.conversation_history = [self._multimodal_msg(["a.png", "b.png"])]
        agent._prune_history_images(max_images=6)
        parts = agent.conversation_history[0]["content"]
        self.assertEqual([p["type"] for p in parts], ["text", "image_url", "text", "image_url"])

    def test_prune_oldest_beyond_limit(self):
        agent = self._create_agent()
        # 两条多模态消息共 8 张图（4+4），保留最近 6 张 → 最旧 2 张被替换
        agent.conversation_history = [
            self._multimodal_msg(["1.png", "2.png", "3.png", "4.png"]),
            {"role": "assistant", "content": "ok"},
            self._multimodal_msg(["5.png", "6.png", "7.png", "8.png"]),
        ]
        agent._prune_history_images(max_images=6)

        first = agent.conversation_history[0]["content"]
        self.assertEqual(first[1]["type"], "text")  # 1.png 已移除
        self.assertIn("fetch_image_as_base64", first[1]["text"])
        self.assertEqual(first[3]["type"], "text")  # 2.png 已移除
        self.assertEqual(first[5]["type"], "image_url")  # 3.png 保留
        self.assertEqual(first[7]["type"], "image_url")  # 4.png 保留

        second = agent.conversation_history[2]["content"]
        self.assertTrue(all(p["type"] == ("text" if i % 2 == 0 else "image_url")
                            for i, p in enumerate(second)))

    def test_non_user_and_string_content_untouched(self):
        agent = self._create_agent()
        agent.conversation_history = [
            {"role": "assistant", "content": [{"type": "image_url", "image_url": {"url": "x"}}]},
            {"role": "user", "content": "plain text"},
        ]
        agent._prune_history_images(max_images=0)
        self.assertEqual(agent.conversation_history[0]["content"][0]["type"], "image_url")
        self.assertEqual(agent.conversation_history[1]["content"], "plain text")

    def test_idempotent(self):
        agent = self._create_agent()
        agent.conversation_history = [self._multimodal_msg([f"{i}.png" for i in range(8)])]
        agent._prune_history_images(max_images=6)
        snapshot = [dict(p) for p in agent.conversation_history[0]["content"]]
        agent._prune_history_images(max_images=6)
        self.assertEqual(agent.conversation_history[0]["content"], snapshot)


class TestFetchImageResultStripped(TestExpertAgent):
    """fetch_image_as_base64 的 base64 不落 tool 历史，仅通过多模态 user 消息注入"""

    def test_base64_stripped_from_tool_history(self):
        agent = self._create_agent(allowed_tools=["fetch_image_as_base64"])
        agent.tool_executor.execute_tool = MagicMock(return_value={
            "success": True,
            "base64_data_url": "data:image/jpeg;base64," + "A" * 5000,
            "size_kb": 4,
            "message": "图片已成功加载",
        })

        tool_call = MagicMock()
        tool_call.id = "tc1"
        tool_call.function.name = "fetch_image_as_base64"
        tool_call.function.arguments = json.dumps({"image_url": "/upload/x.png"})
        message = MagicMock()
        message.tool_calls = [tool_call]
        message.reasoning_content = None

        agent._handle_tool_calls(message)

        tool_msgs = [m for m in agent.conversation_history if m["role"] == "tool"]
        self.assertEqual(len(tool_msgs), 1)
        self.assertNotIn("base64_data_url", tool_msgs[0]["content"]["content"])
        self.assertNotIn("AAAA", tool_msgs[0]["content"]["content"])
        self.assertIn('"success": true', tool_msgs[0]["content"]["content"])

        # 图片仍通过多模态 user 消息注入
        multimodal = [m for m in agent.conversation_history
                      if m["role"] == "user" and isinstance(m["content"], list)]
        self.assertEqual(len(multimodal), 1)
        types = [p["type"] for p in multimodal[0]["content"]]
        self.assertEqual(types, ["text", "image_url"])

    def test_failed_fetch_no_multimodal(self):
        agent = self._create_agent(allowed_tools=["fetch_image_as_base64"])
        agent.tool_executor.execute_tool = MagicMock(return_value={
            "success": False, "error": "本地文件不存在"
        })

        tool_call = MagicMock()
        tool_call.id = "tc1"
        tool_call.function.name = "fetch_image_as_base64"
        tool_call.function.arguments = json.dumps({"image_url": "/upload/x.png"})
        message = MagicMock()
        message.tool_calls = [tool_call]
        message.reasoning_content = None

        agent._handle_tool_calls(message)

        multimodal = [m for m in agent.conversation_history
                      if m["role"] == "user" and isinstance(m["content"], list)]
        self.assertEqual(len(multimodal), 0)


class TestEstimateInputTokens(TestExpertAgent):
    """测试 _estimate_input_tokens：文本按 1.5 字符/token、图片按 base64 体量估算"""

    def test_text_only(self):
        agent = self._create_agent()
        messages = [{"role": "user", "content": "x" * 150}]
        self.assertEqual(agent._estimate_input_tokens(messages), 100)

    def test_image_counted_by_base64_volume(self):
        agent = self._create_agent()
        messages = [{"role": "user", "content": [
            {"type": "text", "text": "看图"},
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + "A" * 1300}},
        ]}]
        # 图片 1300 字符 / 1.3 = 1000 tokens，文本 2 字符约 1 token
        estimate = agent._estimate_input_tokens(messages)
        self.assertGreaterEqual(estimate, 1000)
        self.assertLess(estimate, 1100)

    def test_floor_is_last_api_input_tokens(self):
        agent = self._create_agent()
        agent.last_api_input_tokens = 500000
        messages = [{"role": "user", "content": "hi"}]
        self.assertEqual(agent._estimate_input_tokens(messages), 500000)


class TestPowerConfirmSwitch(TestExpertAgent):
    """算力确认门开关：script_writer 链路关闭（不拦截/不注入提示），marketing 链路默认开启"""

    def test_disabled_gate_passes_through(self):
        agent = self._create_agent(power_confirm_enabled=False)
        # 门关闭：计费生成工具直接放行（返回 None），不估算、不弹验证
        self.assertIsNone(
            agent._gate_computing_power("generate_text_to_image", {"prompt": "x"})
        )

    def test_disabled_gate_no_prompt_note(self):
        agent = self._create_agent(power_confirm_enabled=False)
        self.assertNotIn("算力确认上限", agent.system_prompt)
        self.assertNotIn("把确认交给系统", agent.system_prompt)

    def test_enabled_gate_prompt_note_present(self):
        with patch('script_writer_core.agents.power_confirm.resolve_user_soft_threshold',
                   return_value=(35, False)):
            agent = self._create_agent()
        self.assertIn("算力确认上限", agent.system_prompt)


if __name__ == '__main__':
    unittest.main()
