"""
PipelineStepModel 数据库操作单元测试

使用模块直接引用 mock，测试 PipelineStepModel 的 CRUD 方法：
- create: 创建流水线步骤
- get_by_id: 根据 ID 获取步骤
- get_by_ai_tool_and_stage: 获取指定 ai_tool 和阶段的步骤
- update_status: 更新步骤状态
- update_status_with_retry: 更新状态并可选重置重试
- schedule_retry: 安排重试
- has_steps: 检查是否存在步骤
- delete_by_ai_tool_id: 删除指定 ai_tool 的所有步骤
"""
import importlib
import json
import sys
import unittest
from datetime import datetime
from unittest.mock import MagicMock

# 保存原始模块引用，防止污染后续测试
_saved_model_database = sys.modules.get('model.database')

# Mock 数据库依赖（模块级 import 会触发）
mock_db = MagicMock()
sys.modules['model.database'] = mock_db

# 强制重新加载确保使用 mock
if 'model.ai_tool_pipeline_steps' in sys.modules:
    importlib.reload(sys.modules['model.ai_tool_pipeline_steps'])

from model.ai_tool_pipeline_steps import (
    PipelineStepModel,
    PipelineStepStatus,
    PipelineStage,
    PipelineStepType,
    PipelineStep,
)

# 获取模块内实际使用的数据库函数引用
_steps_module = sys.modules['model.ai_tool_pipeline_steps']

# 恢复 model.database，防止污染后续测试
if _saved_model_database is not None:
    sys.modules['model.database'] = _saved_model_database
else:
    sys.modules.pop('model.database', None)


class TestPipelineStepModelCreate(unittest.TestCase):
    """测试 PipelineStepModel.create()"""

    def setUp(self):
        _steps_module.execute_insert.reset_mock()
        _steps_module.execute_insert.return_value = 1

    def test_create_basic(self):
        """基本创建步骤，验证 SQL 参数和返回值"""
        result = PipelineStepModel.create(
            ai_tool_id=100,
            stage='param_prepare',
            step_type='face_mask',
            step_order=0,
        )

        self.assertEqual(result, 1)
        _steps_module.execute_insert.assert_called_once()
        call_args = _steps_module.execute_insert.call_args
        sql = call_args[0][0]
        db_params = call_args[0][1]

        self.assertIn('INSERT INTO ai_tool_pipeline_steps', sql)
        self.assertEqual(db_params[0], 100)       # ai_tool_id
        self.assertEqual(db_params[1], 'param_prepare')  # stage
        self.assertEqual(db_params[2], 'face_mask')       # step_type
        self.assertIsNone(db_params[3])                   # target
        self.assertEqual(db_params[4], 0)                 # step_order
        self.assertEqual(db_params[5], PipelineStepStatus.PENDING)  # status
        self.assertIsNone(db_params[6])                   # params_json

    def test_create_with_params(self):
        """创建时传入 params dict，会被 json.dumps 序列化"""
        params = {"face_region": "all", "threshold": 0.8}
        PipelineStepModel.create(
            ai_tool_id=200,
            stage='param_prepare',
            step_type='face_mask',
            params=params,
        )

        call_args = _steps_module.execute_insert.call_args
        db_params = call_args[0][1]
        self.assertEqual(db_params[6], json.dumps(params))

    def test_create_without_params(self):
        """创建时不传 params，params 为 None"""
        PipelineStepModel.create(
            ai_tool_id=300,
            stage='before_finish',
            step_type='implementation_retry',
        )

        call_args = _steps_module.execute_insert.call_args
        db_params = call_args[0][1]
        self.assertIsNone(db_params[6])

    def test_create_with_target(self):
        """创建时传入 target 字段"""
        PipelineStepModel.create(
            ai_tool_id=400,
            stage='param_prepare',
            step_type='face_mask',
            target='/path/to/video.mp4',
        )

        call_args = _steps_module.execute_insert.call_args
        db_params = call_args[0][1]
        self.assertEqual(db_params[3], '/path/to/video.mp4')


class TestPipelineStepModelGetById(unittest.TestCase):
    """测试 PipelineStepModel.get_by_id()"""

    def setUp(self):
        _steps_module.execute_query.reset_mock()

    def test_get_existing_record(self):
        """查询存在的记录，返回 PipelineStep 对象"""
        _steps_module.execute_query.return_value = {
            'id': 1,
            'ai_tool_id': 100,
            'stage': 'param_prepare',
            'step_type': 'face_mask',
            'target': '/path/to/video.mp4',
            'step_order': 0,
            'status': PipelineStepStatus.PENDING,
            'params': None,
            'result_data': None,
            'result_url': None,
            'error_message': None,
            'async_task_id': None,
            'retry_count': 0,
            'next_retry_at': None,
            'max_retries': 5,
            'created_at': datetime(2026, 5, 28, 10, 0, 0),
            'updated_at': datetime(2026, 5, 28, 10, 0, 0),
            'completed_at': None,
        }

        result = PipelineStepModel.get_by_id(1)

        self.assertIsNotNone(result)
        self.assertEqual(result.__class__.__name__, PipelineStep.__name__)
        self.assertEqual(result.id, 1)
        self.assertEqual(result.ai_tool_id, 100)
        self.assertEqual(result.stage, 'param_prepare')
        self.assertEqual(result.step_type, 'face_mask')
        call_args = _steps_module.execute_query.call_args
        self.assertIn('WHERE id = %s', call_args[0][0])
        self.assertEqual(call_args[0][1], (1,))

    def test_get_nonexistent_record(self):
        """查询不存在的记录，返回 None"""
        _steps_module.execute_query.return_value = None

        result = PipelineStepModel.get_by_id(999)

        self.assertIsNone(result)


class TestPipelineStepModelGetByAiToolAndStage(unittest.TestCase):
    """测试 PipelineStepModel.get_by_ai_tool_and_stage()"""

    def setUp(self):
        _steps_module.execute_query.reset_mock()

    def test_returns_ordered_steps(self):
        """查询返回按 step_order 排序的步骤列表"""
        _steps_module.execute_query.return_value = [
            {'id': 1, 'ai_tool_id': 100, 'stage': 'param_prepare', 'step_type': 'face_mask',
             'target': None, 'step_order': 0, 'status': 0, 'params': None, 'result_data': None,
             'result_url': None, 'error_message': None, 'async_task_id': None,
             'retry_count': 0, 'next_retry_at': None, 'max_retries': 5,
             'created_at': None, 'updated_at': None, 'completed_at': None},
            {'id': 2, 'ai_tool_id': 100, 'stage': 'param_prepare', 'step_type': 'implementation_retry',
             'target': None, 'step_order': 1, 'status': 0, 'params': None, 'result_data': None,
             'result_url': None, 'error_message': None, 'async_task_id': None,
             'retry_count': 0, 'next_retry_at': None, 'max_retries': 5,
             'created_at': None, 'updated_at': None, 'completed_at': None},
        ]

        result = PipelineStepModel.get_by_ai_tool_and_stage(100, 'param_prepare')

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].__class__.__name__, PipelineStep.__name__)
        self.assertEqual(result[0].id, 1)
        self.assertEqual(result[1].id, 2)
        call_args = _steps_module.execute_query.call_args
        self.assertIn('ORDER BY step_order ASC', call_args[0][0])
        self.assertEqual(call_args[0][1], (100, 'param_prepare'))

    def test_returns_empty_list(self):
        """查询返回空结果时返回空列表"""
        _steps_module.execute_query.return_value = None

        result = PipelineStepModel.get_by_ai_tool_and_stage(999, 'param_prepare')

        self.assertEqual(result, [])


class TestPipelineStepModelUpdateStatus(unittest.TestCase):
    """测试 PipelineStepModel.update_status()"""

    def setUp(self):
        _steps_module.execute_update.reset_mock()
        _steps_module.execute_update.return_value = 1

    def test_update_to_completed(self):
        """更新为 completed 状态时，SQL 包含 completed_at = NOW()"""
        PipelineStepModel.update_status(1, PipelineStepStatus.COMPLETED)

        call_args = _steps_module.execute_update.call_args
        sql = call_args[0][0]
        self.assertIn('completed_at = NOW()', sql)
        self.assertIn('status = %s', sql)

    def test_update_with_error(self):
        """更新时传入 error_message"""
        PipelineStepModel.update_status(1, PipelineStepStatus.FAILED, error_message="Timeout")

        call_args = _steps_module.execute_update.call_args
        sql = call_args[0][0]
        params = call_args[0][1]
        self.assertIn('error_message = %s', sql)
        self.assertIn("Timeout", params)

    def test_update_with_result_data(self):
        """更新时传入 result_data，会被 json.dumps 序列化"""
        result_data = {"frames": [1, 2, 3]}
        PipelineStepModel.update_status(1, PipelineStepStatus.COMPLETED, result_data=result_data)

        call_args = _steps_module.execute_update.call_args
        sql = call_args[0][0]
        params = call_args[0][1]
        self.assertIn('result_data = %s', sql)
        self.assertIn(json.dumps(result_data), params)

    def test_update_with_result_url(self):
        """更新时传入 result_url"""
        PipelineStepModel.update_status(1, PipelineStepStatus.COMPLETED, result_url='/path/to/output.mp4')

        call_args = _steps_module.execute_update.call_args
        sql = call_args[0][0]
        params = call_args[0][1]
        self.assertIn('result_url = %s', sql)
        self.assertIn('/path/to/output.mp4', params)


class TestPipelineStepModelUpdateStatusWithRetry(unittest.TestCase):
    """测试 PipelineStepModel.update_status_with_retry()"""

    def setUp(self):
        _steps_module.execute_update.reset_mock()
        _steps_module.execute_update.return_value = 1

    def test_reset_retry_true(self):
        """reset_retry=True 时，SQL 包含 retry_count=0 和 next_retry_at=NULL"""
        PipelineStepModel.update_status_with_retry(1, PipelineStepStatus.PENDING, reset_retry=True)

        call_args = _steps_module.execute_update.call_args
        sql = call_args[0][0]
        self.assertIn('retry_count = 0', sql)
        self.assertIn('next_retry_at = NULL', sql)

    def test_reset_retry_false(self):
        """reset_retry=False 时，SQL 不包含 retry 和 next_retry_at 字段"""
        PipelineStepModel.update_status_with_retry(1, PipelineStepStatus.PROCESSING, reset_retry=False)

        call_args = _steps_module.execute_update.call_args
        sql = call_args[0][0]
        self.assertNotIn('retry_count = 0', sql)
        self.assertNotIn('next_retry_at = NULL', sql)

    def test_completed_sets_completed_at(self):
        """状态为 COMPLETED 时，SQL 包含 completed_at = NOW()"""
        PipelineStepModel.update_status_with_retry(1, PipelineStepStatus.COMPLETED, reset_retry=True)

        call_args = _steps_module.execute_update.call_args
        sql = call_args[0][0]
        self.assertIn('completed_at = NOW()', sql)


class TestPipelineStepModelScheduleRetry(unittest.TestCase):
    """测试 PipelineStepModel.schedule_retry()"""

    def setUp(self):
        _steps_module.execute_update.reset_mock()
        _steps_module.execute_update.return_value = 1

    def test_schedule_basic(self):
        """安排重试，验证 retry_count+1 和 next_retry_at 设置"""
        PipelineStepModel.schedule_retry(1, delay_seconds=60)

        call_args = _steps_module.execute_update.call_args
        sql = call_args[0][0]
        params = call_args[0][1]

        self.assertIn('retry_count = retry_count + 1', sql)
        self.assertIn('next_retry_at = %s', sql)
        self.assertEqual(params[1], 1)


class TestPipelineStepModelHasSteps(unittest.TestCase):
    """测试 PipelineStepModel.has_steps()"""

    def setUp(self):
        _steps_module.execute_query.reset_mock()

    def test_has_steps_true(self):
        """存在步骤时返回 True"""
        _steps_module.execute_query.return_value = {'cnt': 3}

        result = PipelineStepModel.has_steps(100, 'param_prepare')

        self.assertTrue(result)
        call_args = _steps_module.execute_query.call_args
        self.assertIn('COUNT(*)', call_args[0][0])
        self.assertEqual(call_args[0][1], (100, 'param_prepare'))

    def test_has_steps_false(self):
        """不存在步骤时返回 False"""
        _steps_module.execute_query.return_value = {'cnt': 0}

        result = PipelineStepModel.has_steps(999, 'param_prepare')

        self.assertFalse(result)


class TestPipelineStepModelDeleteByAiToolId(unittest.TestCase):
    """测试 PipelineStepModel.delete_by_ai_tool_id()"""

    def setUp(self):
        _steps_module.execute_update.reset_mock()
        _steps_module.execute_update.return_value = 5

    def test_delete_returns_count(self):
        """删除返回影响的行数"""
        result = PipelineStepModel.delete_by_ai_tool_id(100)

        self.assertEqual(result, 5)
        call_args = _steps_module.execute_update.call_args
        sql = call_args[0][0]
        params = call_args[0][1]
        self.assertIn('DELETE FROM ai_tool_pipeline_steps', sql)
        self.assertIn('WHERE ai_tool_id = %s', sql)
        self.assertEqual(params, (100,))


class TestFailPendingGridSplitStep(unittest.TestCase):
    """测试 PipelineStepModel.fail_pending_grid_split_step()"""

    def setUp(self):
        _steps_module.execute_update.reset_mock()
        _steps_module.execute_update.return_value = 1

    def test_fails_pending_step(self):
        """把 PENDING 的 grid split step 标记为 FAILED，返回影响行数"""
        result = PipelineStepModel.fail_pending_grid_split_step(1075, "宫格生图失败")

        self.assertEqual(result, 1)
        call_args = _steps_module.execute_update.call_args
        sql = call_args[0][0]
        params = call_args[0][1]

        # SQL 应只更新 PENDING 的行
        self.assertIn('UPDATE ai_tool_pipeline_steps', sql)
        self.assertIn('SET status = %s, error_message = %s', sql)
        self.assertIn('WHERE ai_tool_id = %s', sql)
        self.assertIn(f'step_type = %s', sql)
        self.assertIn(f'status = %s', sql)
        # 参数顺序：新status, error_msg, ai_tool_id, stage, step_type, 旧status
        self.assertEqual(params[0], PipelineStepStatus.FAILED)
        self.assertEqual(params[1], "宫格生图失败")
        self.assertEqual(params[2], 1075)
        self.assertEqual(params[3], PipelineStage.BEFORE_FINISH)
        self.assertEqual(params[4], PipelineStepType.STORYBOARD_FIRST_FRAME_GRID_SPLIT)
        self.assertEqual(params[5], PipelineStepStatus.PENDING)

    def test_truncates_long_error_message(self):
        """超长 error_message 截断到 512 字符"""
        long_msg = "x" * 600
        PipelineStepModel.fail_pending_grid_split_step(1, long_msg)

        params = _steps_module.execute_update.call_args[0][1]
        self.assertEqual(len(params[1]), 512)

    def test_no_pending_step_returns_zero(self):
        """没有匹配的 PENDING step 时返回 0（不影响已终结的行）"""
        _steps_module.execute_update.return_value = 0
        result = PipelineStepModel.fail_pending_grid_split_step(999, "err")

        self.assertEqual(result, 0)


class TestGetOrphanGridSplitSteps(unittest.TestCase):
    """测试 PipelineStepModel.get_orphan_grid_split_steps()"""

    def setUp(self):
        # 彻底重置（含 return_value/side_effect），避免跨测试/跨文件 mock 残留污染
        _steps_module.execute_query.reset_mock(return_value=True, side_effect=True)

    def tearDown(self):
        # 清掉 return_value，避免以 list 形态残留给后续文件的 fetch_one 调用（如 AIToolsModel.get_by_id）
        _steps_module.execute_query.reset_mock(return_value=True, side_effect=True)

    def test_returns_orphan_steps(self):
        """JOIN 命中后返回 PipelineStep 列表"""
        _steps_module.execute_query.return_value = [
            {'id': 72, 'ai_tool_id': 1075, 'stage': 'before_finish',
             'step_type': 'storyboard_first_frame_grid_split', 'status': 0},
            {'id': 91, 'ai_tool_id': 1076, 'stage': 'before_finish',
             'step_type': 'storyboard_first_frame_grid_split', 'status': 0},
        ]

        result = PipelineStepModel.get_orphan_grid_split_steps(
            limit=50, grid_terminal_statuses=(-1, -2, -4),
        )

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].id, 72)
        # SQL 应含按 grid_task_id 的 JOIN 与终态状态 IN
        sql = _steps_module.execute_query.call_args[0][0]
        self.assertIn('INNER JOIN grid_image_tasks', sql)
        # JOIN 按 params.grid_task_id 主键关联（不再按 project_id == ai_tool_id）
        self.assertIn("g.id = CAST(JSON_UNQUOTE(JSON_EXTRACT(s.params", sql)
        self.assertIn("grid_task_id", sql)
        self.assertNotIn('g.project_id = CAST(s.ai_tool_id AS CHAR)', sql)
        self.assertIn('IN (%s,%s,%s)', sql)

    def test_empty_statuses_returns_empty(self):
        """终态状态元组为空时直接返回空列表（不发 SQL）"""
        result = PipelineStepModel.get_orphan_grid_split_steps(limit=50, grid_terminal_statuses=())

        self.assertEqual(result, [])
        _steps_module.execute_query.assert_not_called()

    def test_no_results_returns_empty(self):
        """查询无结果返回空列表"""
        _steps_module.execute_query.return_value = None
        result = PipelineStepModel.get_orphan_grid_split_steps(limit=50, grid_terminal_statuses=(-1,))

        self.assertEqual(result, [])


class TestFailStepsByIds(unittest.TestCase):
    """测试 PipelineStepModel.fail_steps_by_ids()"""

    def setUp(self):
        _steps_module.execute_update.reset_mock(return_value=True, side_effect=True)
        _steps_module.execute_update.return_value = 2

    def tearDown(self):
        _steps_module.execute_update.reset_mock(return_value=True, side_effect=True)

    def test_fails_steps_by_ids(self):
        """按 ID 批量标记 FAILED，只更新 PENDING 的"""
        result = PipelineStepModel.fail_steps_by_ids([72, 91], "孤儿清理")

        self.assertEqual(result, 2)
        call_args = _steps_module.execute_update.call_args
        sql = call_args[0][0]
        params = call_args[0][1]

        self.assertIn('UPDATE ai_tool_pipeline_steps', sql)
        self.assertIn('WHERE id IN (%s,%s)', sql)
        self.assertIn('AND status = %s', sql)
        self.assertEqual(params[0], PipelineStepStatus.FAILED)
        self.assertEqual(params[1], "孤儿清理")
        self.assertEqual(params[2], 72)
        self.assertEqual(params[3], 91)
        self.assertEqual(params[4], PipelineStepStatus.PENDING)

    def test_empty_ids_returns_zero(self):
        """空 ID 列表不发 SQL"""
        result = PipelineStepModel.fail_steps_by_ids([], "err")

        self.assertEqual(result, 0)
        _steps_module.execute_update.assert_not_called()


if __name__ == '__main__':
    unittest.main()
