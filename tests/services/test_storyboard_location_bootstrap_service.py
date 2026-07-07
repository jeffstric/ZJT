"""
StoryboardLocationBootstrapService 单元测试。

不连接真实数据库：用 monkeypatch 替换 LocationModel.create_or_update / get_by_name。
"""
from unittest.mock import patch, MagicMock

import pytest

from services.storyboard_location_bootstrap_service import (
    StoryboardLocationBootstrapService,
)
from llm.script_parser import sanitize_parsed_location_references


WORLD_ID = 100
USER_ID = 5


def _make_db_location(loc_id, name, parent_id=None):
    """构造一个模拟的 Location 对象（带 parent_id 属性）。"""
    class _FakeLoc:
        def __init__(self, id, name, parent_id):
            self.id = id
            self.name = name
            self.parent_id = parent_id
    return _FakeLoc(loc_id, name, parent_id)


# ---------------------------------------------------------------------------
# Phase 1: sanitize_parsed_location_references 保留新子场景
# ---------------------------------------------------------------------------

class TestSanitizeKeepsUnpersistedSubscenes:
    def test_keeps_subscene_with_null_location_db_id(self):
        parsed = {
            "locations": [
                {"id": "loc_001", "name": "主场景", "location_db_id": 10, "level": 0},
                {
                    "id": "loc_002", "name": "子场景A", "parent_id": "loc_001",
                    "location_db_id": None, "level": 1,
                    "description": "子场景描述", "atmosphere": "昏暗",
                },
            ],
            "shot_groups": [
                {"shots": [{"location_id": "loc_002"}]},
            ],
        }
        db_locations = [{"id": 10, "name": "主场景", "children": []}]

        result = sanitize_parsed_location_references(parsed, db_locations)

        loc_ids = [loc["id"] for loc in result["locations"]]
        assert loc_ids == ["loc_001", "loc_002"]
        sub = next(loc for loc in result["locations"] if loc["id"] == "loc_002")
        assert sub["location_db_id"] is None
        assert sub["atmosphere"] == "昏暗"
        # shot.location_id 指向保留的新子场景，不应被置空
        assert result["shot_groups"][0]["shots"][0]["location_id"] == "loc_002"
        # metadata 调试字段
        assert result["metadata"]["has_unpersisted_locations"] is True
        assert result["metadata"]["unpersisted_location_count"] == 1

    def test_drops_fabricated_db_id(self):
        """编造的非 null 假 id 且 DB 不存在 → 丢弃。"""
        parsed = {
            "locations": [
                {"id": "loc_001", "name": "假场景", "location_db_id": 99999},
            ],
            "shot_groups": [{"shots": [{"location_id": "loc_001"}]}],
        }
        result = sanitize_parsed_location_references(parsed, db_locations=[])
        assert result["locations"] == []
        assert result["shot_groups"][0]["shots"][0]["location_id"] is None
        assert result["metadata"]["has_unpersisted_locations"] is False

    def test_all_matched_no_unpersisted(self):
        parsed = {
            "locations": [{"id": "loc_001", "name": "主场景", "location_db_id": 10}],
            "shot_groups": [],
        }
        result = sanitize_parsed_location_references(parsed, [{"id": 10, "name": "主场景"}])
        assert result["metadata"]["has_unpersisted_locations"] is False
        assert result["metadata"]["unpersisted_location_count"] == 0


# ---------------------------------------------------------------------------
# Phase 2: StoryboardLocationBootstrapService
# ---------------------------------------------------------------------------

# bootstrap 现在用 LocationModel.create（纯 INSERT，不触发 ON DUPLICATE KEY 覆盖）+
# get_by_name（查同名复用）。测试统一 mock 这两个方法。
_LM = "services.storyboard_location_bootstrap_service.LocationModel"


class TestBootstrap:
    def test_creates_subscene_with_correct_parent_id(self):
        """子场景入库时 parent_id 填父场景真实 DB id。"""
        created = {}
        seq = iter([1001, 1002])  # 父先建 → 1001，子 → 1002

        def fake_create(world_id, name, user_id, parent_id=None, **kw):
            new_id = next(seq)
            created[name] = {"id": new_id, "parent_id": parent_id}
            return new_id

        parsed = {
            "locations": [
                {"id": "loc_001", "name": "主场景", "location_db_id": None, "level": 0},
                {"id": "loc_002", "name": "子场景", "parent_id": "loc_001",
                 "location_db_id": None, "level": 1, "description": "子"},
            ],
            "shot_groups": [],
        }

        with patch(_LM + ".create", side_effect=fake_create), \
             patch(_LM + ".get_by_name", return_value=None):
            svc = StoryboardLocationBootstrapService()
            result = svc.bootstrap(parsed, WORLD_ID, USER_ID)

        assert result["created_location_count"] == 2
        # 子场景 parent_id 必须是父场景真实 DB id
        assert created["子场景"]["parent_id"] == 1001
        # 回填到 location dict
        sub = next(loc for loc in parsed["locations"] if loc["id"] == "loc_002")
        assert sub["location_db_id"] == 1002

    def test_backfills_shot_db_location_id(self):
        """shot.db_location_id 被回填为真实 DB id。"""
        seq = iter([2001])

        def fake_create(world_id, name, user_id, parent_id=None, **kw):
            return next(seq)

        parsed = {
            "locations": [
                {"id": "loc_001", "name": "新场景", "location_db_id": None, "level": 0},
            ],
            "shot_groups": [
                {"shots": [{"location_id": "loc_001", "scene_desc": "x"}]},
            ],
        }

        with patch(_LM + ".create", side_effect=fake_create), \
             patch(_LM + ".get_by_name", return_value=None):
            svc = StoryboardLocationBootstrapService()
            svc.bootstrap(parsed, WORLD_ID, USER_ID)

        assert parsed["shot_groups"][0]["shots"][0]["db_location_id"] == 2001

    def test_reuses_existing_top_level_db_id(self):
        """顶层已匹配场景直接复用 DB id，不调 create。"""
        parsed = {
            "locations": [
                {"id": "loc_001", "name": "主场景", "location_db_id": 30, "level": 0},
            ],
            "shot_groups": [],
        }
        with patch(_LM + ".create") as mock_create, \
             patch(_LM + ".get_by_name", return_value=None):
            svc = StoryboardLocationBootstrapService()
            result = svc.bootstrap(parsed, WORLD_ID, USER_ID)

        mock_create.assert_not_called()
        assert result["reused_location_count"] == 1
        assert result["created_location_count"] == 0
        assert parsed["locations"][0]["location_db_id"] == 30

    def test_same_name_same_parent_reuses_without_clearing_reference_image(self):
        """
        【P1 数据丢失防护】同名同父 → 直接复用 existing.id，绝不走 upsert，
        避免把已有的 reference_image / reference_images 抹成 NULL。

        这是 create → create_or_update 重构的核心目的：bootstrap 不应破坏
        已有参考图等字段，只在新场景时插入。
        """
        # DB 已有 "客厅"，parent_id=6000，且有参考图
        existing = _make_db_location(5000, "客厅", parent_id=6000)
        existing.reference_image = "http://h/existing.png"

        parsed = {
            "locations": [
                {"id": "loc_001", "name": "父场景", "location_db_id": 6000, "level": 0},
                {"id": "loc_002", "name": "客厅", "parent_id": "loc_001",
                 "location_db_id": None, "level": 1},
            ],
            "shot_groups": [],
        }

        with patch(_LM + ".create") as mock_create, \
             patch(_LM + ".get_by_name", return_value=existing):
            svc = StoryboardLocationBootstrapService()
            result = svc.bootstrap(parsed, WORLD_ID, USER_ID)

        # 关键：create 不应被调用（复用 existing，不插入新行）
        mock_create.assert_not_called()
        sub = next(loc for loc in parsed["locations"] if loc["id"] == "loc_002")
        assert sub["location_db_id"] == 5000  # 复用既有 id
        assert sub["name"] == "客厅"  # 不改名
        assert result["created_location_count"] == 0
        # existing.reference_image 未被触碰（mock 对象仍保留原值）
        assert existing.reference_image == "http://h/existing.png"

    def test_name_collision_different_parent_gets_renamed(self):
        """同名但 parent_id 不一致 → 加 (子场景) 后缀后新建，不覆盖既有行。"""
        # DB 已有同名行 "客厅"，parent_id=50（与当前子场景的 parent 不同）
        existing_conflict = _make_db_location(5000, "客厅", parent_id=50)
        # 父场景 + 改名后的子场景各需一个 id
        seq = iter([5001, 5002])

        def fake_create(world_id, name, user_id, parent_id=None, **kw):
            return next(seq)

        def fake_get_by_name(world_id, name):
            # 只有 "客厅" 在 DB 已存在且 parent 冲突；改名后的 "客厅 (子场景)" 无冲突
            if name == "客厅":
                return existing_conflict
            return None

        parsed = {
            "locations": [
                {"id": "loc_001", "name": "父场景", "location_db_id": None, "level": 0},
                {"id": "loc_002", "name": "客厅", "parent_id": "loc_001",
                 "location_db_id": None, "level": 1},
            ],
            "shot_groups": [],
        }

        with patch(_LM + ".create", side_effect=fake_create), \
             patch(_LM + ".get_by_name", side_effect=fake_get_by_name):
            svc = StoryboardLocationBootstrapService()
            result = svc.bootstrap(parsed, WORLD_ID, USER_ID)

        sub = next(loc for loc in parsed["locations"] if loc["id"] == "loc_002")
        assert sub["name"] == "客厅 (子场景)"
        assert sub["location_db_id"] == 5002
        assert any("冲突" in w for w in result["warnings"])

    def test_orphan_subscene_degrades_to_top_level(self):
        """父场景缺失的孤儿子场景降级为顶层创建，记 warning。"""
        seq = iter([7001])

        def fake_create(world_id, name, user_id, parent_id=None, **kw):
            assert parent_id is None, "孤儿场景应作为顶层创建"
            return next(seq)

        parsed = {
            "locations": [
                # 子场景的 parent_id 指向不存在的 loc_999
                {"id": "loc_002", "name": "孤儿子场景", "parent_id": "loc_999",
                 "location_db_id": None, "level": 1},
            ],
            "shot_groups": [],
        }

        with patch(_LM + ".create", side_effect=fake_create), \
             patch(_LM + ".get_by_name", return_value=None):
            svc = StoryboardLocationBootstrapService()
            result = svc.bootstrap(parsed, WORLD_ID, USER_ID)

        assert result["created_location_count"] == 1
        assert any("降级" in w or "孤儿" in w or "父场景" in w for w in result["warnings"])

    def test_topological_order_parents_before_children(self):
        """验证 level 排序：乱序输入时父先于子入库。"""
        creation_order = []

        def fake_create(world_id, name, user_id, parent_id=None, **kw):
            creation_order.append((name, parent_id))
            # 用名字 hash 模拟 id
            return abs(hash(name)) % 100000 + 8000

        parsed = {
            "locations": [
                # 故意把子场景放在父场景前面
                {"id": "loc_002", "name": "子", "parent_id": "loc_001",
                 "location_db_id": None, "level": 1},
                {"id": "loc_001", "name": "父", "location_db_id": None, "level": 0},
            ],
            "shot_groups": [],
        }

        with patch(_LM + ".create", side_effect=fake_create), \
             patch(_LM + ".get_by_name", return_value=None):
            svc = StoryboardLocationBootstrapService()
            svc.bootstrap(parsed, WORLD_ID, USER_ID)

        # 父必须先于子
        names = [n for n, _ in creation_order]
        assert names.index("父") < names.index("子")
        # 子的 parent_id 应是父的 DB id
        sub_entry = next(item for item in creation_order if item[0] == "子")
        assert sub_entry[1] is not None


# ---------------------------------------------------------------------------
# 修复验证：target_entity_ids 贯穿、短 key、入库失败、门禁重跑、按 id 回写
# ---------------------------------------------------------------------------

class TestSubsceneGridFixes:
    """验证 P1-P4 修复：target_entity_ids 真正写入 DB 并贯穿到回写。"""

    def test_submit_grid_image_task_passes_target_ids_to_create(self, monkeypatch):
        """generate_9grid_location_images 的 target_entity_ids 应贯穿到 GridImageTasksModel.create。"""
        import script_writer_core.mcp_tool as mcp

        captured = {}

        def fake_create(**kwargs):
            captured.update(kwargs)
            return 1

        monkeypatch.setattr(mcp, 'httpx', MagicMock())
        monkeypatch.setattr(mcp.httpx, 'post', MagicMock())
        mcp.httpx.post.return_value.raise_for_status.return_value = None
        mcp.httpx.post.return_value.json.return_value = {'project_ids': ['pid123']}
        monkeypatch.setattr(mcp, '_resolve_image_edit_task_id', lambda *a: 7)
        monkeypatch.setattr(mcp, '_get_model_name_by_task_id', lambda *a: 'edit')
        monkeypatch.setattr(mcp, '_to_public_http_url', lambda *a: 'http://h/p.png')
        monkeypatch.setattr(mcp, 'get_config', lambda: {'server': {'comfyui_base_url_inner': 'http://h'}})

        from model.grid_image_tasks import GridImageTasksModel
        monkeypatch.setattr(GridImageTasksModel, 'get_by_task_key', lambda *a: None)
        monkeypatch.setattr(GridImageTasksModel, 'delete_by_task_key', lambda *a: None)
        monkeypatch.setattr(GridImageTasksModel, 'create', fake_create)

        result = mcp.generate_9grid_location_images(
            user_id='u', world_id='w', auth_token='t',
            sub_location_names=['子1', '子2', 'placeholder'] + ['placeholder'] * 6,
            prompts=['p'] * 9,
            parent_reference_image='http://h/p.png',
            target_entity_ids=[100, 101, None] + [None] * 6,
        )

        assert result.get('success') is True, result
        # create 收到过滤 None 后的纯 id 列表
        assert captured['target_entity_ids'] == [100, 101]
        # item_name 是短 key（含 loc#，不含全名）
        assert 'loc#' in captured['item_name'] and '#' in captured['item_name']
        # item_names_json 含完整名
        assert captured['item_names'] == ['子1', '子2', 'placeholder'] + ['placeholder'] * 6

    def test_i2i_create_failure_returns_failure(self, monkeypatch):
        """i2i 入库失败必须返回 success=False（否则上层误认为已提交）。"""
        import script_writer_core.mcp_tool as mcp

        monkeypatch.setattr(mcp, 'httpx', MagicMock())
        mcp.httpx.post.return_value.raise_for_status.return_value = None
        mcp.httpx.post.return_value.json.return_value = {'project_ids': ['pid']}
        monkeypatch.setattr(mcp, '_resolve_image_edit_task_id', lambda *a: 7)
        monkeypatch.setattr(mcp, '_get_model_name_by_task_id', lambda *a: 'edit')
        monkeypatch.setattr(mcp, '_to_public_http_url', lambda *a: 'http://h/p.png')
        monkeypatch.setattr(mcp, 'get_config', lambda: {'server': {'comfyui_base_url_inner': 'http://h'}})

        from model.grid_image_tasks import GridImageTasksModel
        monkeypatch.setattr(GridImageTasksModel, 'get_by_task_key', lambda *a: None)
        monkeypatch.setattr(GridImageTasksModel, 'create', MagicMock(side_effect=Exception('DB 冲突')))

        result = mcp.generate_9grid_location_images(
            user_id='u', world_id='w', auth_token='t',
            sub_location_names=['s'] * 9, prompts=['p'] * 9,
            parent_reference_image='http://h/p.png',
            target_entity_ids=list(range(100, 109)),
        )
        assert result.get('success') is False
        assert '后台任务记录创建失败' in result['error']

    def test_submit_subscene_grids_skips_already_has_image_and_running(self, monkeypatch):
        """门禁重跑：已有图 / 运行中任务的子场景被跳过，只提交缺图且无任务的。"""
        svc = StoryboardLocationBootstrapService()

        parsed = {
            'locations': [
                {'id': 'loc_p', 'name': '主厅', 'location_db_id': 100, 'reference_image': 'http://h/p.png'},
                {'id': 'c1', 'name': '角落1', 'parent_id': 'loc_p', 'location_db_id': 201},  # 已有图
                {'id': 'c2', 'name': '角落2', 'parent_id': 'loc_p', 'location_db_id': 202},  # 运行中
                {'id': 'c3', 'name': '角落3', 'parent_id': 'loc_p', 'location_db_id': 203},  # 需生成
            ],
        }
        br = {'id_map': {'loc_p': 100, 'c1': 201, 'c2': 202, 'c3': 203}, 'warnings': [], 'created_location_count': 0}

        monkeypatch.setattr(svc, '_subscene_has_reference_image', lambda db_id, loc: db_id == 201)
        monkeypatch.setattr(svc, '_subscene_has_running_grid', lambda db_id: db_id == 202)

        captured_target_ids = []

        def fake_gen(**kw):
            captured_target_ids.append(kw.get('target_entity_ids'))
            return {'success': True, 'project_ids': ['pid']}

        monkeypatch.setattr(
            'script_writer_core.mcp_tool.generate_9grid_location_images', MagicMock(side_effect=fake_gen)
        )

        result = svc.submit_subscene_grids(parsed, br, world_id=1, user_id=1, auth_token='t')

        # 只有 c3 进了批次
        assert len(captured_target_ids) == 1
        # c3 的 id(203) 在首位，其余为 None（placeholder 补位）
        assert captured_target_ids[0] == [203] + [None] * 8
        assert result['submitted_subscene_count'] == 1

    def test_location_grid_writeback_aligns_by_id(self, monkeypatch):
        """item_type=5 回写：target_entity_ids 过滤 None 后，与非 placeholder 名称按序对齐回写。"""
        import task.grid_image_task as git

        task = MagicMock()
        task.task_key = 'grid:u:w:pid'
        task.item_type = 5
        task.item_name = 'loc#100,101,#,#,#,#,#,#,#'  # 短 key
        task.grid_size = 9
        task.user_id = 'u'
        task.world_id = 'w'
        task.auth_token = 't'
        task.comfyui_base_url = 'http://h'
        task.get_item_names_list.return_value = ['角落1', '角落2'] + ['placeholder'] * 7
        task.get_target_entity_ids_list.return_value = [100, 101]

        loc_updates = []

        def fake_loc_update(db_id, **kw):
            loc_updates.append((db_id, kw.get('reference_image')))
            return 1

        splitter = MagicMock()
        splitter.split_grid.return_value = [f'upload/location/pic/s{i}.png' for i in range(9)]

        fake_mcp = MagicMock()
        fake_mcp.update_location_json.return_value = {'success': True}

        monkeypatch.setattr(git, 'get_config', lambda: {
            'image': {'enable_download': False}, 'server': {'host': 'http://h'}
        })
        monkeypatch.setattr(git, '_download_and_store_image',
                            lambda *a: ('http://h/upload/mock/grid.png', 'grid.png'))
        monkeypatch.setattr(git, 'ImageGridSplitter', MagicMock(return_value=splitter))
        monkeypatch.setattr(git, 'GridImageTasksModel', MagicMock())
        monkeypatch.setattr('model.location.LocationModel.update', fake_loc_update)
        monkeypatch.setattr('importlib.import_module', lambda name: fake_mcp)

        git._handle_task_success(task, {'results': [{'file_url': '/upload/mock/grid.png'}]})

        # 按真实 DB id 回写 2 次（角落1→100, 角落2→101），placeholder 跳过
        assert len(loc_updates) == 2
        assert loc_updates[0][0] == 100
        assert loc_updates[1][0] == 101
        # 按名更新 JSON 也 2 次
        assert fake_mcp.update_location_json.call_count == 2
