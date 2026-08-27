"""StoryboardSceneModel.duplicate 排序逻辑单元测试。

验证修复：复制分镜时新分镜应插入到「原分镜」与「原分镜的后继」之间（浮点二分取中点），
而不是简单 sort_order + 1.0（后者会在连续整数序列下与后继分镜碰撞，
经 ORDER BY sort_order, id 的 tie-break 后落到「下一个的下一个」）。
"""
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from model import storyboard_scene as scene_module
from model.storyboard_scene import StoryboardSceneModel


def _patch_no_dialogue(monkeypatch):
    """屏蔽 duplicate 末尾的对话复制，让测试聚焦在 sort_order 计算上。"""
    class _FakeDialogueModel:
        @staticmethod
        def list_by_scene(_scene_id):
            return []

    import model.storyboard_dialogue as dialogue_module
    monkeypatch.setattr(dialogue_module, "StoryboardDialogueModel", _FakeDialogueModel, raising=False)
    # duplicate 内部是局部 import：`from .storyboard_dialogue import StoryboardDialogueModel`
    # 局部 import 经 sys.modules 取回的是同一个模块对象，上面的 monkeypatch 已覆盖，
    # 且测试结束自动恢复；此前这里曾对 sys.modules 条目裸赋值且不恢复，会污染后续测试。
    assert sys.modules["model.storyboard_dialogue"] is dialogue_module


def test_duplicate_middle_scene_uses_midpoint(monkeypatch):
    """连续整数序列 [1,2,3] 中复制 sort_order=2 的中间分镜，新分镜应为 2.5（而非 3）。"""
    _patch_no_dialogue(monkeypatch)

    captured = {}

    def fake_execute_query(sql, params=None, fetch_one=False, fetch_all=False):
        sql_stripped = sql.strip().upper()
        # get_by_id：返回被复制的原分镜（sort_order=2）
        if sql_stripped.startswith("SELECT * FROM STORYBOARD_SCENE WHERE ID"):
            return {
                "id": 2, "storyboard_id": 10, "sort_order": 2.0, "title": "分镜B",
                "duration": 5.0, "prompt_json": None, "video_prompt": None,
                "video_type": "video", "video_config_json": None, "audio_embedded": 0,
                "difficulty": "medium", "act_name": None, "last_modified_user_id": None,
            }
        # _next_sort_after：返回后继分镜 sort_order=3
        if "SORT_ORDER >" in sql_stripped:
            return {"sort_order": 3.0}
        return None

    def fake_execute_insert(sql, params):
        captured["create_params"] = params
        return 999  # 新分镜 id

    monkeypatch.setattr(scene_module, "execute_query", fake_execute_query)
    monkeypatch.setattr(scene_module, "execute_insert", fake_execute_insert)

    new_id = StoryboardSceneModel.duplicate(2)

    assert new_id == 999
    # create 的第 2 个参数是 sort_order，应为中点 2.5，而非碰撞的 3.0
    assert captured["create_params"][1] == 2.5


def test_duplicate_last_scene_appends(monkeypatch):
    """复制末尾分镜（无后继），应退化为末尾追加 cur_sort + 1.0。"""
    _patch_no_dialogue(monkeypatch)

    captured = {}

    def fake_execute_query(sql, params=None, fetch_one=False, fetch_all=False):
        sql_stripped = sql.strip().upper()
        if sql_stripped.startswith("SELECT * FROM STORYBOARD_SCENE WHERE ID"):
            return {
                "id": 3, "storyboard_id": 10, "sort_order": 3.0, "title": "分镜C",
                "duration": 5.0, "prompt_json": None, "video_prompt": None,
                "video_type": "video", "video_config_json": None, "audio_embedded": 0,
                "difficulty": "medium", "act_name": None, "last_modified_user_id": None,
            }
        # _next_sort_after：末尾分镜无后继 → None
        if "SORT_ORDER >" in sql_stripped:
            return None
        return None

    def fake_execute_insert(sql, params):
        captured["create_params"] = params
        return 1000

    monkeypatch.setattr(scene_module, "execute_query", fake_execute_query)
    monkeypatch.setattr(scene_module, "execute_insert", fake_execute_insert)

    new_id = StoryboardSceneModel.duplicate(3)

    assert new_id == 1000
    # 末尾追加：3.0 + 1.0 = 4.0
    assert captured["create_params"][1] == 4.0


def test_duplicate_only_scene(monkeypatch):
    """复制 storyboard 内唯一分镜（无后继），同末尾场景，追加到末尾。"""
    _patch_no_dialogue(monkeypatch)

    captured = {}

    def fake_execute_query(sql, params=None, fetch_one=False, fetch_all=False):
        sql_stripped = sql.strip().upper()
        if sql_stripped.startswith("SELECT * FROM STORYBOARD_SCENE WHERE ID"):
            return {
                "id": 1, "storyboard_id": 20, "sort_order": 0.0, "title": "唯一分镜",
                "duration": 5.0, "prompt_json": None, "video_prompt": None,
                "video_type": "video", "video_config_json": None, "audio_embedded": 0,
                "difficulty": "medium", "act_name": None, "last_modified_user_id": None,
            }
        if "SORT_ORDER >" in sql_stripped:
            return None
        return None

    def fake_execute_insert(sql, params):
        captured["create_params"] = params
        return 777

    monkeypatch.setattr(scene_module, "execute_query", fake_execute_query)
    monkeypatch.setattr(scene_module, "execute_insert", fake_execute_insert)

    new_id = StoryboardSceneModel.duplicate(1)

    assert new_id == 777
    # 唯一分镜 sort_order=0，无后继 → 0.0 + 1.0 = 1.0
    assert captured["create_params"][1] == 1.0


def test_next_sort_after_returns_next_sort_order(monkeypatch):
    """_next_sort_after 直接读后继分镜的 sort_order。"""
    def fake_execute_query(sql, params=None, fetch_one=False, fetch_all=False):
        return {"sort_order": 3.0}

    monkeypatch.setattr(scene_module, "execute_query", fake_execute_query)
    result = StoryboardSceneModel._next_sort_after(10, 2.0)
    assert result == 3.0


def test_next_sort_after_returns_none_when_last(monkeypatch):
    """末尾分镜无后继时 _next_sort_after 返回 None。"""
    def fake_execute_query(sql, params=None, fetch_one=False, fetch_all=False):
        return None

    monkeypatch.setattr(scene_module, "execute_query", fake_execute_query)
    result = StoryboardSceneModel._next_sort_after(10, 3.0)
    assert result is None
