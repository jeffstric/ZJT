"""
PM Agent 消息队列回归测试

目的：防止 PMAgent 再次直接使用 task.message_queue.put() 发送消息，
      确保所有消息都通过 self.task_manager.push_message() 写入数据库。
"""
import os
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

# 添加项目根目录到路径
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, project_root)

# 在模块级 mock 缺失的第三方模块，避免导入 PMAgent 时失败。
# 注意：*不* mock pymysql，防止污染数据库测试。
_MISSING_MODULES = [
    'openai',
    'google', 'google.genai',
    'aiofiles',
    'litellm',
    'httpx', 'requests',
    'apscheduler', 'apscheduler.schedulers', 'apscheduler.schedulers.background',
    'apscheduler.triggers', 'apscheduler.triggers.cron',
    'redis',
    'PIL', 'PIL.Image',
]
for _mod in _MISSING_MODULES:
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

# aiohttp 需要做成真正的 package mock，否则 litellm 的子模块导入会失败
# 临时 mock aiohttp / pymysql 以完成 PMAgent 导入，导入后立刻恢复，避免污染其他测试
_aiohttp_existed = 'aiohttp' in sys.modules
if not _aiohttp_existed:
    aiohttp_pkg = types.ModuleType('aiohttp')
    aiohttp_pkg.__path__ = []
    sys.modules['aiohttp'] = aiohttp_pkg
    sys.modules['aiohttp.client_exceptions'] = types.ModuleType('aiohttp.client_exceptions')

_pymysql_existed = 'pymysql' in sys.modules
if not _pymysql_existed:
    sys.modules['pymysql'] = MagicMock()
    sys.modules['pymysql.cursors'] = MagicMock()

from script_writer_core.agents.pm_agent import PMAgent
from script_writer_core.agents.task_manager import AgentTask

if not _aiohttp_existed:
    del sys.modules['aiohttp']
    sys.modules.pop('aiohttp.client_exceptions', None)

if not _pymysql_existed:
    del sys.modules['pymysql']
    sys.modules.pop('pymysql.cursors', None)


class TestPMAgentMessageQueueRegression(unittest.TestCase):
    """PMAgent 消息发送机制回归测试"""

    def test_no_message_queue_put_in_pm_agent_source(self):
        """
        静态代码检查：确保 pm_agent.py 中没有直接使用 message_queue.put 发送消息。
        """
        pm_agent_path = os.path.join(
            project_root, 'script_writer_core', 'agents', 'pm_agent.py'
        )
        self.assertTrue(os.path.exists(pm_agent_path),
                        f"pm_agent.py 不存在: {pm_agent_path}")

        with open(pm_agent_path, 'r', encoding='utf-8') as f:
            source = f.read()

        # 禁止直接使用 message_queue.put（包括 task.message_queue.put）
        forbidden_patterns = [
            'message_queue.put',
            '.message_queue.put_nowait',
            '.message_queue.get',
        ]

        for pattern in forbidden_patterns:
            self.assertNotIn(
                pattern,
                source,
                f"pm_agent.py 中不应再使用 '{pattern}'，"
                f"请改用 self.task_manager.push_message()"
            )

    def _create_pm_agent(self, task_manager_mock=None):
        """辅助方法：创建 PMAgent 实例并 mock 外部依赖"""
        file_manager_mock = MagicMock()
        file_manager_mock.get_context_for_ai.return_value = ""

        agents_config = {
            "pm_agent": {"skills": ["script-orchestrator"]},
            "expert_agents": {}
        }

        if task_manager_mock is None:
            task_manager_mock = MagicMock()

        return PMAgent(
            model="test-model",
            allowed_tools=["call_agent", "request_human_verification"],
            task_manager=task_manager_mock,
            file_manager=file_manager_mock,
            tool_executor=MagicMock(),
            agents_config=agents_config,
            user_id="test_user",
            world_id="test_world",
            auth_token="test_token"
        )

    def _create_agent_task(self):
        """辅助方法：创建测试用的 AgentTask"""
        return AgentTask(
            task_id="test-task-001",
            session_id="test-session-001",
            user_message="测试消息",
            user_id="test_user",
            world_id="test_world",
            auth_token="test_token",
            vendor_id=1,
            model_id=1
        )

    def test_push_message_called_when_should_stop(self):
        """
        行为测试：当 should_stop 返回 True 时，PM Agent 应调用
        task_manager.push_message() 而不是 message_queue.put。
        """
        task_manager_mock = MagicMock()
        pm_agent = self._create_pm_agent(task_manager_mock)
        task = self._create_agent_task()

        # mock should_stop 返回 True，直接触发停止分支
        with patch.object(pm_agent, 'should_stop', return_value=(True, "达到停止条件")):
            result = pm_agent._run_pm_loop(task, {})

        self.assertIn("任务执行停止", result)

        # 验证 task_manager.push_message 被调用，而不是 message_queue.put
        task_manager_mock.push_message.assert_called_once()
        call_args = task_manager_mock.push_message.call_args
        self.assertEqual(call_args[0][0], task.task_id)
        self.assertEqual(call_args[0][1], 'message')
        self.assertIn("达到停止条件", call_args[0][2]['content'])

    def test_push_message_called_on_loop_exception(self):
        """
        行为测试：当 PM Loop 中发生异常时，应调用 task_manager.push_message('error', ...)。
        """
        task_manager_mock = MagicMock()
        pm_agent = self._create_pm_agent(task_manager_mock)
        task = self._create_agent_task()

        # 第一次 should_stop 返回 False，让循环进入 LLM 调用阶段
        # 第二次 should_stop 也返回 False（虽然用不上，因为第一次迭代就会异常）
        with patch.object(pm_agent, 'should_stop', side_effect=[(False, ""), (True, "停止")]):
            # mock get_llm_client 抛出异常（patch pm_agent 模块内的局部绑定）
            with patch('script_writer_core.agents.pm_agent.get_llm_client') as mock_get_client:
                mock_client = MagicMock()
                mock_client.call_api.side_effect = RuntimeError("模拟 LLM 异常")
                mock_get_client.return_value = mock_client

                result = pm_agent._run_pm_loop(task, {}, max_iterations=2)

        # 验证 push_message 至少被调用过一次
        self.assertGreaterEqual(task_manager_mock.push_message.call_count, 1)

        # 验证调用列表中存在一次 error 类型的调用
        error_calls = [
            call for call in task_manager_mock.push_message.call_args_list
            if call[0][1] == 'error'
        ]
        self.assertEqual(len(error_calls), 1)
        self.assertIn("模拟 LLM 异常", error_calls[0][0][2]['error'])


if __name__ == '__main__':
    unittest.main()
