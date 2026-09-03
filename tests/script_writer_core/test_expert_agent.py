"""
ExpertAgent 单元测试

测试 _is_deepseek_model 和 _format_messages_for_api 的纯逻辑。
"""
import os
import sys
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
