"""
GridImageTasksModel.create 的 None 兜底单元测试

回归点：grid_size / grid_layout 是 NOT NULL 列，显式 INSERT NULL 会绕过 DB DEFAULT
触发 "Column 'grid_size' cannot be null"。本测试验证 create() 在收到 None（或上游漏传）
时，于构造 SQL 前归一化为合法默认值（GridConfig.SIZE_2X2=4 / '2x2'），并在显式传值时
保留原值。

对应根因修复：
- model/grid_image_tasks.py: create() 增加 None 兜底
- 上游 create_image_task / generate_text_to_image / edit_image 普通单图路径
"""
import importlib
import sys
import unittest
from unittest.mock import MagicMock

# 保存原始模块引用，防止污染后续测试
_saved_model_database = sys.modules.get('model.database')

# Mock 数据库依赖（模块级 from .database import execute_insert 会触发）
mock_db = MagicMock()
sys.modules['model.database'] = mock_db

# 强制重新加载确保使用 mock
if 'model.grid_image_tasks' in sys.modules:
    importlib.reload(sys.modules['model.grid_image_tasks'])

from model.grid_image_tasks import GridImageTasksModel, GridImageTaskStatus
from config.constant import GridConfig

# 获取模块内实际使用的数据库函数引用（create 内部调用 execute_insert）
_model_module = sys.modules['model.grid_image_tasks']

# 恢复 model.database，防止污染后续测试
if _saved_model_database is not None:
    sys.modules['model.database'] = _saved_model_database
else:
    sys.modules.pop('model.database', None)


def _base_kwargs(**overrides):
    """构造 create() 的最小合法入参（不含 grid_size/grid_layout，交由 overrides 控制）。"""
    kwargs = dict(
        task_key="test_key",
        project_id="pid_1",
        item_type=1,
        item_name="角色A",
        user_id="u1",
        world_id="w1",
        comfyui_base_url="http://inner",
        auth_token="token",
    )
    kwargs.update(overrides)
    return kwargs


class TestGridImageTasksNoneFallback(unittest.TestCase):
    """验证 grid_size / grid_layout 的 None 兜底逻辑。"""

    def setUp(self):
        _model_module.execute_insert.reset_mock()
        _model_module.execute_insert.return_value = 1

    def _grid_size_in_params(self):
        """从 execute_insert 调用中提取 params 元组里的 grid_size / grid_layout。"""
        call_args = _model_module.execute_insert.call_args
        db_params = call_args[0][1]
        # SQL params 顺序：...image_size(13), is_grid(14), max_retries(15), grid_size(16), grid_layout(17), ...
        return db_params[16], db_params[17]

    def test_grid_size_none_falls_back_to_default(self):
        """显式传 grid_size=None 时应兜底为 SIZE_2X2(4)，而非穿透 NULL。"""
        GridImageTasksModel.create(**_base_kwargs(grid_size=None, grid_layout=None))
        grid_size, grid_layout = self._grid_size_in_params()
        self.assertEqual(grid_size, GridConfig.SIZE_2X2)
        self.assertEqual(grid_layout, '2x2')

    def test_grid_size_omitted_falls_back_to_default(self):
        """不传 grid_size（普通单图/通用任务历史写法）应写入默认 4。"""
        GridImageTasksModel.create(**_base_kwargs())
        grid_size, grid_layout = self._grid_size_in_params()
        self.assertEqual(grid_size, GridConfig.SIZE_2X2)
        self.assertEqual(grid_layout, '2x2')

    def test_grid_size_explicit_value_preserved(self):
        """宫格任务显式传 9/'3x3' 时应原样保留，不被兜底覆盖。"""
        GridImageTasksModel.create(**_base_kwargs(grid_size=GridConfig.SIZE_3X3, grid_layout='3x3'))
        grid_size, grid_layout = self._grid_size_in_params()
        self.assertEqual(grid_size, 9)
        self.assertEqual(grid_layout, '3x3')

    def test_sql_explicitly_writes_grid_columns(self):
        """INSERT 语句应显式包含 grid_size / grid_layout 列名（确保列存在）。"""
        GridImageTasksModel.create(**_base_kwargs())
        sql = _model_module.execute_insert.call_args[0][0]
        self.assertIn('grid_size', sql)
        self.assertIn('grid_layout', sql)


if __name__ == '__main__':
    unittest.main()
