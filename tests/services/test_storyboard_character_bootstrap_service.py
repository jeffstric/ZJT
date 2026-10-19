"""StoryboardCharacterBootstrapService 单元测试。

不连接真实数据库：mock CharacterModel.create / get_by_name / list_by_world
与 WorldModel.get_by_id。
"""
from unittest.mock import patch

from services.storyboard_character_bootstrap_service import (
    StoryboardCharacterBootstrapService,
)
from config.constant import CharacterConstants


WORLD_ID = 100
USER_ID = 5

_CM = "services.storyboard_character_bootstrap_service.CharacterModel"
_WM = "services.storyboard_character_bootstrap_service.WorldModel"


class _FakeWorld:
    def __init__(self, id, user_id):
        self.id = id
        self.user_id = user_id


# 默认世界属主与任务发起人相同（同用户发起拆分）
_FAKE_WORLD = _FakeWorld(WORLD_ID, USER_ID)


class _FakeCharacter:
    def __init__(self, id, name):
        self.id = id
        self.name = name


def _make_parsed(characters, shots=None):
    return {
        "characters": characters,
        "shot_groups": [{"shots": shots or []}],
    }


class TestBootstrapCreate:
    def test_creates_new_character_and_backfills_db_id(self):
        """库外新角色自动入库：source=script_split，LLM 描述字段映射落库。"""
        created_calls = []

        def fake_create(**kwargs):
            created_calls.append(kwargs)
            return 9001

        parsed = _make_parsed([
            {"id": "char_001", "name": "路人甲", "character_db_id": None,
             "role": "群演", "description": "戴草帽的老人", "gender": "男", "age_range": "老年"},
        ])

        with patch(_CM + ".create", side_effect=fake_create), \
             patch(_WM + ".get_by_id", return_value=_FAKE_WORLD), \
             patch(_CM + ".get_by_name", return_value=None), \
             patch(_CM + ".list_by_world", return_value={"data": [], "total": 0}):
            result = StoryboardCharacterBootstrapService().bootstrap(parsed, WORLD_ID, USER_ID)

        assert result["created_character_count"] == 1
        assert parsed["characters"][0]["character_db_id"] == 9001
        assert len(created_calls) == 1
        call = created_calls[0]
        assert call["source"] == CharacterConstants.SOURCE_SCRIPT_SPLIT
        assert call["appearance"] == "戴草帽的老人"
        assert call["identity"] == "群演"
        assert call["age"] == "男 / 老年"
        assert "自动创建" in call["other_info"]

    def test_existing_db_id_reused_without_create(self):
        """已匹配库内角色（character_db_id 非空）直接复用，不重复入库。"""
        parsed = _make_parsed([
            {"id": "char_001", "name": "奶昔_Milkshake", "character_db_id": 55},
        ])
        with patch(_CM + ".create") as mock_create, \
             patch(_WM + ".get_by_id", return_value=_FAKE_WORLD), \
             patch(_CM + ".list_by_world", return_value={"data": [], "total": 0}):
            result = StoryboardCharacterBootstrapService().bootstrap(parsed, WORLD_ID, USER_ID)

        mock_create.assert_not_called()
        assert result["created_character_count"] == 0
        assert result["reused_character_count"] == 1

    def test_same_name_in_db_reused(self):
        """与库内角色同名：复用既有 id，不创建、不覆盖字段。"""
        parsed = _make_parsed([
            {"id": "char_001", "name": "奶昔_Milkshake", "character_db_id": None},
        ])
        with patch(_CM + ".create") as mock_create, \
             patch(_WM + ".get_by_id", return_value=_FAKE_WORLD), \
             patch(_CM + ".get_by_name",
                   return_value=_FakeCharacter(77, "奶昔_Milkshake")), \
             patch(_CM + ".list_by_world", return_value={"data": [], "total": 0}):
            result = StoryboardCharacterBootstrapService().bootstrap(parsed, WORLD_ID, USER_ID)

        mock_create.assert_not_called()
        assert parsed["characters"][0]["character_db_id"] == 77
        assert result["created_character_count"] == 0
        assert result["reused_character_count"] == 1


class TestBootstrapAliasNormalize:
    def test_short_alias_normalized_to_full_name(self):
        """短名唯一命中受控别名：归一化复用 + shot 文本标记同步改写。"""
        parsed = _make_parsed([
            {"id": "char_001", "name": "奶昔", "character_db_id": None},
        ], shots=[{
            "opening_frame_description": "【【奶昔】】坐在沙发上",
            "scene_detail": "【【奶昔】】微笑",
            "description": "【【奶昔】】看向窗外",
            "action": "【【奶昔】】挥手",
            "dialogue": [{"text": "【【奶昔】】说：你好"}],
        }])
        world_names = ["奶昔_Milkshake"]

        with patch(_CM + ".create") as mock_create, \
             patch(_WM + ".get_by_id", return_value=_FAKE_WORLD), \
             patch(_CM + ".get_by_name",
                   return_value=_FakeCharacter(66, "奶昔_Milkshake")), \
             patch(_CM + ".list_by_world",
                   return_value={"data": [{"name": n} for n in world_names], "total": len(world_names)}):
            result = StoryboardCharacterBootstrapService().bootstrap(parsed, WORLD_ID, USER_ID)

        mock_create.assert_not_called()
        assert parsed["characters"][0]["name"] == "奶昔_Milkshake"
        assert parsed["characters"][0]["character_db_id"] == 66
        assert result["renamed"] == {"奶昔": "奶昔_Milkshake"}
        shot = parsed["shot_groups"][0]["shots"][0]
        assert shot["opening_frame_description"] == "【【奶昔_Milkshake】】坐在沙发上"
        assert shot["action"] == "【【奶昔_Milkshake】】挥手"
        assert shot["dialogue"][0]["text"] == "【【奶昔_Milkshake】】说：你好"

    def test_ambiguous_alias_not_created(self):
        """多义短名无法确定目标：不自动入库，保持幽灵并记 warning。"""
        parsed = _make_parsed([
            {"id": "char_001", "name": "小明", "character_db_id": None},
        ])
        world_names = ["小明_Tom", "小明_Jerry"]

        with patch(_CM + ".create") as mock_create, \
             patch(_WM + ".get_by_id", return_value=_FAKE_WORLD), \
             patch(_CM + ".get_by_name", return_value=None), \
             patch(_CM + ".list_by_world",
                   return_value={"data": [{"name": n} for n in world_names], "total": len(world_names)}):
            result = StoryboardCharacterBootstrapService().bootstrap(parsed, WORLD_ID, USER_ID)

        mock_create.assert_not_called()
        assert parsed["characters"][0]["character_db_id"] is None
        assert any("多个库内角色" in w for w in result["warnings"])


class TestBootstrapResilience:
    def test_single_character_failure_does_not_block(self):
        """单角色入库异常仅 warning，其余角色正常处理。"""
        calls = []

        def fake_get_by_name(world_id, name):
            if name == "坏角色":
                raise RuntimeError("db down")
            return None

        def fake_create(**kwargs):
            calls.append(kwargs["name"])
            return 42

        parsed = _make_parsed([
            {"id": "char_001", "name": "坏角色", "character_db_id": None},
            {"id": "char_002", "name": "好角色", "character_db_id": None},
        ])
        with patch(_CM + ".create", side_effect=fake_create), \
             patch(_WM + ".get_by_id", return_value=_FAKE_WORLD), \
             patch(_CM + ".get_by_name", side_effect=fake_get_by_name), \
             patch(_CM + ".list_by_world", return_value={"data": [], "total": 0}):
            result = StoryboardCharacterBootstrapService().bootstrap(parsed, WORLD_ID, USER_ID)

        assert calls == ["好角色"]
        assert parsed["characters"][0]["character_db_id"] is None
        assert parsed["characters"][1]["character_db_id"] == 42
        assert any("坏角色" in w for w in result["warnings"])

    def test_empty_or_invalid_characters(self):
        """characters 缺失/非列表：返回空结果不报错。"""
        with patch(_CM + ".list_by_world"), \
             patch(_WM + ".get_by_id", return_value=_FAKE_WORLD):
            result = StoryboardCharacterBootstrapService().bootstrap({}, WORLD_ID, USER_ID)
        assert result["created_character_count"] == 0
        assert result["warnings"] == []


class TestBootstrapOwner:
    def test_create_uses_world_owner_not_task_initiator(self):
        """admin 代跑场景：入库属主取世界属主，而非拆分任务发起人。

        若按任务发起人落库，世界主人在按属主校验的角色接口
        （voice-desc / reference-audio）会被误拦 403。
        """
        created_calls = []

        def fake_create(**kwargs):
            created_calls.append(kwargs)
            return 9001

        parsed = _make_parsed([
            {"id": "char_001", "name": "快递员群像", "character_db_id": None},
        ])
        # 世界属主 55，拆分任务发起人 2（admin 代跑）
        with patch(_CM + ".create", side_effect=fake_create), \
             patch(_WM + ".get_by_id", return_value=_FakeWorld(WORLD_ID, 55)), \
             patch(_CM + ".get_by_name", return_value=None), \
             patch(_CM + ".list_by_world", return_value={"data": [], "total": 0}):
            StoryboardCharacterBootstrapService().bootstrap(parsed, WORLD_ID, 2)

        assert len(created_calls) == 1
        assert created_calls[0]["user_id"] == 55

    def test_world_row_missing_falls_back_to_task_initiator(self):
        """世界行缺失（异常数据）时回退任务发起人作属主，不阻塞入库。"""
        created_calls = []

        def fake_create(**kwargs):
            created_calls.append(kwargs)
            return 9002

        parsed = _make_parsed([
            {"id": "char_001", "name": "路人甲", "character_db_id": None},
        ])
        with patch(_CM + ".create", side_effect=fake_create), \
             patch(_WM + ".get_by_id", return_value=None), \
             patch(_CM + ".get_by_name", return_value=None), \
             patch(_CM + ".list_by_world", return_value={"data": [], "total": 0}):
            result = StoryboardCharacterBootstrapService().bootstrap(parsed, WORLD_ID, USER_ID)

        assert result["created_character_count"] == 1
        assert created_calls[0]["user_id"] == USER_ID
