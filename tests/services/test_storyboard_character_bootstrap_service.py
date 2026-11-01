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


class TestBootstrapMatchedDbIdNormalize:
    """方案A：已回填 character_db_id 的角色，name 简称/变体按库内完整名归一化。"""

    def test_db_id_with_short_name_normalized(self):
        """db_id 正确但 name 是简称：归一化 name + shot 标记，不重复入库。"""
        parsed = _make_parsed([
            {"id": "char_001", "name": "哈利", "character_db_id": 81397},
        ], shots=[{
            "opening_frame_description": "【【哈利】】举起魔杖",
            "scene_detail": "走廊昏暗",
            "description": "【【哈利】】直视前方",
            "action": "【【哈利】】后撤",
            "dialogue": [{"text": "【【哈利】】说：快跑"}],
        }])
        world_rows = [
            {"id": 81397, "name": "哈利波特"},
            {"id": 81401, "name": "德拉科莉亚马尔福"},
        ]

        with patch(_CM + ".create") as mock_create, \
             patch(_WM + ".get_by_id", return_value=_FAKE_WORLD), \
             patch(_CM + ".get_by_name") as mock_get_by_name, \
             patch(_CM + ".list_by_world",
                   return_value={"data": world_rows, "total": len(world_rows)}):
            result = StoryboardCharacterBootstrapService().bootstrap(parsed, WORLD_ID, USER_ID)

        mock_create.assert_not_called()
        mock_get_by_name.assert_not_called()
        assert parsed["characters"][0]["name"] == "哈利波特"
        assert parsed["characters"][0]["character_db_id"] == 81397
        assert result["reused_character_count"] == 1
        assert result["renamed"] == {"哈利": "哈利波特"}
        shot = parsed["shot_groups"][0]["shots"][0]
        assert shot["opening_frame_description"] == "【【哈利波特】】举起魔杖"
        assert shot["description"] == "【【哈利波特】】直视前方"
        assert shot["dialogue"][0]["text"] == "【【哈利波特】】说：快跑"
        assert any("归一化" in w for w in result["warnings"])

    def test_db_id_with_separator_variant_normalized(self):
        """分隔符变体（德拉科莉亚·马尔福）归一化为库内无点全名。"""
        parsed = _make_parsed([
            {"id": "char_001", "name": "德拉科莉亚·马尔福", "character_db_id": 81401},
        ], shots=[{"action": "【【德拉科莉亚·马尔福】】冷笑"}])
        world_rows = [{"id": 81401, "name": "德拉科莉亚马尔福"}]

        with patch(_CM + ".create") as mock_create, \
             patch(_WM + ".get_by_id", return_value=_FAKE_WORLD), \
             patch(_CM + ".get_by_name"), \
             patch(_CM + ".list_by_world",
                   return_value={"data": world_rows, "total": len(world_rows)}):
            result = StoryboardCharacterBootstrapService().bootstrap(parsed, WORLD_ID, USER_ID)

        mock_create.assert_not_called()
        assert parsed["characters"][0]["name"] == "德拉科莉亚马尔福"
        assert result["renamed"] == {"德拉科莉亚·马尔福": "德拉科莉亚马尔福"}
        assert parsed["shot_groups"][0]["shots"][0]["action"] == "【【德拉科莉亚马尔福】】冷笑"

    def test_db_id_with_name_of_another_character_not_renamed(self):
        """name 恰为库内另一角色完整名：不改写，避免标记误替换。"""
        parsed = _make_parsed([
            {"id": "char_001", "name": "哈利波特", "character_db_id": 2},
        ], shots=[{"action": "【【哈利波特】】挥手"}])
        world_rows = [
            {"id": 1, "name": "哈利波特"},
            {"id": 2, "name": "哈利"},
        ]

        with patch(_CM + ".create") as mock_create, \
             patch(_WM + ".get_by_id", return_value=_FAKE_WORLD), \
             patch(_CM + ".list_by_world",
                   return_value={"data": world_rows, "total": len(world_rows)}):
            result = StoryboardCharacterBootstrapService().bootstrap(parsed, WORLD_ID, USER_ID)

        mock_create.assert_not_called()
        assert parsed["characters"][0]["name"] == "哈利波特"
        assert result["renamed"] == {}
        assert parsed["shot_groups"][0]["shots"][0]["action"] == "【【哈利波特】】挥手"
        assert any("同名" in w for w in result["warnings"])

    def test_db_id_deleted_from_world_kept_as_is(self):
        """db_id 已不在世界角色库（角色被删）：保持复用原 db_id，仅记 warning。"""
        parsed = _make_parsed([
            {"id": "char_001", "name": "哈利", "character_db_id": 404},
        ])

        with patch(_CM + ".create") as mock_create, \
             patch(_WM + ".get_by_id", return_value=_FAKE_WORLD), \
             patch(_CM + ".list_by_world", return_value={"data": [], "total": 0}):
            result = StoryboardCharacterBootstrapService().bootstrap(parsed, WORLD_ID, USER_ID)

        mock_create.assert_not_called()
        assert parsed["characters"][0]["character_db_id"] == 404
        assert parsed["characters"][0]["name"] == "哈利"
        assert result["reused_character_count"] == 1
        assert result["renamed"] == {}
        assert any("不存在" in w for w in result["warnings"])


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
