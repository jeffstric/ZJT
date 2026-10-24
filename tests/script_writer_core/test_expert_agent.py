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
from config.constant import AGENT_LLM_IMAGE_TOKEN_ESTIMATE


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
    """测试 _estimate_input_tokens：文本按 1.5 字符/token、图片按固定 token 上限估算"""

    def test_text_only(self):
        agent = self._create_agent()
        messages = [{"role": "user", "content": "x" * 150}]
        self.assertEqual(agent._estimate_input_tokens(messages), 100)

    def test_image_counted_by_fixed_estimate_not_base64_volume(self):
        # 2026-09-27 官方 API 实测：deepseek-flash 每图 ≈ 1000 token（文档上限 1024），
        # base64 字符量不进入模型上下文，估算按固定 token 计（虚高会过度收缩 max_tokens）
        agent = self._create_agent()
        base = [{"role": "user", "content": [
            {"type": "text", "text": "看图"},
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + "A" * 1300}},
        ]}]
        bigger = [{"role": "user", "content": [
            {"type": "text", "text": "看图"},
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + "A" * 130000}},
        ]}]
        expected = AGENT_LLM_IMAGE_TOKEN_ESTIMATE + 1
        self.assertEqual(agent._estimate_input_tokens(base), expected)
        # base64 体量变化不影响估算
        self.assertEqual(agent._estimate_input_tokens(bigger), expected)

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

    def test_confirmed_video_price_is_not_asked_again_and_does_not_pause(self):
        from script_writer_core.agents.power_budget import PowerBudget
        from script_writer_core.agents.power_confirm import PowerEstimate
        from script_writer_core.agents.task_manager import TaskManager

        with patch('script_writer_core.agents.power_confirm.resolve_user_soft_threshold',
                   return_value=(35, False)):
            agent = self._create_agent(
                power_confirm_enabled=True,
                allowed_tools=["image_to_video"],
            )
        agent.task_manager = TaskManager(power_confirm_approval_loader=lambda session_id: [])
        agent.task_id = "task-1"
        agent._session_id = "session-1"
        agent.power_budget = PowerBudget(limit=200, start_balance=1000)
        same_price = PowerEstimate(cost=303, label="图生视频", duration=5)
        pricier = PowerEstimate(cost=454, label="图生视频", duration=15)

        with patch("script_writer_core.agents.power_confirm.estimate_tool_computing_power", return_value=same_price), \
             patch("script_writer_core.agents.power_confirm.query_user_balance", return_value=1000), \
             patch("script_writer_core.agents.power_confirm.get_effective_thresholds", return_value=(35, 200, False)), \
             patch.object(agent, "_handle_ask_user", return_value={"success": True, "user_input": "确认生成"}) as ask:
            self.assertIsNone(agent._gate_computing_power("image_to_video", {"duration": 5}))
            self.assertEqual(ask.call_count, 1)
            self.assertTrue(agent._budget_authorize_next)
            agent._authorize_generation_spend({"computing_power_required": 303})

            self.assertIsNone(agent._gate_computing_power("image_to_video", {"duration": 5}))
            self.assertEqual(ask.call_count, 1)
            self.assertEqual(agent.task_manager.get_power_confirm_state("session-1")["approved_ceiling"], 303)

        agent.power_budget.observe(697)
        agent.power_budget.check()

        with patch("script_writer_core.agents.power_confirm.estimate_tool_computing_power", return_value=pricier), \
             patch("script_writer_core.agents.power_confirm.query_user_balance", return_value=697), \
             patch("script_writer_core.agents.power_confirm.get_effective_thresholds", return_value=(35, 200, False)), \
             patch.object(agent, "_handle_ask_user", return_value={"success": True, "user_input": "确认生成"}) as ask_again:
            self.assertIsNone(agent._gate_computing_power("image_to_video", {"duration": 15}))
            self.assertEqual(ask_again.call_count, 1)
            self.assertEqual(agent.task_manager.get_power_confirm_state("session-1")["approved_ceiling"], 454)

    def test_approved_price_is_visible_to_another_task_manager(self):
        from script_writer_core.agents.power_confirm import should_confirm
        from script_writer_core.agents.task_manager import TaskManager

        approvals = [{
            "context": {"estimated_cost": 233, "type": "computing_power_confirm"},
            "result": {"action": "confirm", "user_input": "确认生成"},
        }]
        first = TaskManager(power_confirm_approval_loader=lambda session_id: approvals)
        second = TaskManager(power_confirm_approval_loader=lambda session_id: approvals)
        state = second.get_power_confirm_state("27be256f-session")
        self.assertEqual(state["approved_ceiling"], 233)
        self.assertFalse(state["skip"])
        decision = should_confirm(210, False, 35, 200, approved_ceiling=state["approved_ceiling"])
        self.assertFalse(decision.need_confirm)
        self.assertEqual(decision.reason, "within_approved_ceiling")
        self.assertEqual(first.get_power_confirm_state("27be256f-session")["approved_ceiling"], 233)

        cancelled = [{
            "context": {"estimated_cost": 210},
            "result": {"action": "confirm", "user_input": "取消本次生成"},
        }]
        fresh = TaskManager(power_confirm_approval_loader=lambda session_id: cancelled)
        self.assertEqual(fresh.get_power_confirm_state("27be256f-session")["approved_ceiling"], 0)

        def broken(session_id):
            raise RuntimeError("db down")

        failed = TaskManager(power_confirm_approval_loader=broken)
        failed.raise_approved_ceiling("27be256f-session", 233)
        failed.set_power_confirm_skip("27be256f-session", True)
        downgraded = failed.get_power_confirm_state("27be256f-session")
        self.assertEqual(downgraded["approved_ceiling"], 0)
        self.assertFalse(downgraded["skip"])


if __name__ == '__main__':
    unittest.main()
