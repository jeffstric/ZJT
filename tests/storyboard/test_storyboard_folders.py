from types import SimpleNamespace

from api import storyboard as storyboard_api
from model.script import ScriptModel
from model.world import WorldModel


def test_build_storyboard_folders_merges_scripts_and_storyboards():
    scripts = [
        {
            "id": 11,
            "world_id": 7,
            "title": "Pilot",
            "episode_number": 1,
            "update_time": "2026-06-20T10:00:00",
        },
        {
            "id": 12,
            "world_id": 7,
            "title": "Second",
            "episode_number": 2,
            "update_time": "2026-06-21T10:00:00",
        },
    ]
    storyboards = [
        {
            "id": 31,
            "world_id": 7,
            "script_id": 11,
            "title": "Pilot Board",
            "episode_number": 1,
            "status": 1,
            "scene_count": 6,
            "update_at": "2026-06-22T10:00:00",
        }
    ]

    folders = storyboard_api.build_storyboard_folders(scripts, storyboards, {7: "Moon City"})

    assert len(folders) == 2
    assert folders[0]["status"] == "created"
    assert folders[0]["world_name"] == "Moon City"
    assert folders[0]["script_id"] == 11
    assert folders[0]["storyboard_id"] == 31
    assert folders[0]["scene_count"] == 6
    assert folders[1]["status"] == "not_created"
    assert folders[1]["script_id"] == 12
    assert folders[1]["storyboard_id"] is None


def test_build_storyboard_folders_keeps_orphan_storyboard():
    folders = storyboard_api.build_storyboard_folders(
        scripts=[],
        storyboards=[
            {
                "id": 99,
                "world_id": 8,
                "script_id": None,
                "title": "Lost Board",
                "episode_number": 3,
                "scene_count": 2,
                "update_at": "2026-06-23T10:00:00",
            }
        ],
        world_names={8: "No Script World"},
    )

    assert folders == [
        {
            "folder_key": "8:3",
            "world_id": 8,
            "world_name": "No Script World",
            "episode_number": 3,
            "script_id": None,
            "script_title": "Lost Board",
            "storyboard_id": 99,
            "storyboard_title": "Lost Board",
            "scene_count": 2,
            "status": "orphan",
            "owner_user_id": None,
            "update_at": "2026-06-23T10:00:00",
        }
    ]


def test_collect_storyboard_folder_data_uses_world_scripts(monkeypatch):
    """入库剧本的 user_id 不是当前用户时，仍按世界+集数视为已创建。"""
    monkeypatch.setattr(
        storyboard_api.WorldModel,
        "get_by_id",
        lambda world_id: SimpleNamespace(id=world_id, name="Moon City"),
    )
    monkeypatch.setattr(
        storyboard_api.ScriptModel,
        "list_by_user",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not list scripts by user")),
    )

    def fake_scripts(world_ids):
        assert list(world_ids) == [7]
        return [
            {
                "id": 21,
                "world_id": 7,
                "user_id": 999,
                "title": "协作者入库",
                "episode_number": 1,
                "update_time": "2026-06-20T10:00:00",
            },
            {
                "id": 11,
                "world_id": 7,
                "user_id": 999,
                "title": "更小 id",
                "episode_number": 1,
                "update_time": "2026-06-19T10:00:00",
            },
        ]

    monkeypatch.setattr(storyboard_api.ScriptModel, "list_for_folders", fake_scripts)
    monkeypatch.setattr(
        storyboard_api.StoryboardModel,
        "list_folders_by_user",
        lambda user_id, world_id=None, **_kwargs: [
            {
                "id": 31,
                "world_id": 7,
                "script_id": None,
                "title": "Board",
                "episode_number": 1,
                "scene_count": 2,
                "update_at": "2026-06-22T10:00:00",
            },
            {
                "id": 32,
                "world_id": 7,
                "script_id": None,
                "title": "No Script Board",
                "episode_number": 4,
                "scene_count": 1,
                "update_at": "2026-06-23T10:00:00",
            },
        ],
    )

    folders = storyboard_api.collect_storyboard_folder_data(1, 7)
    by_episode = {folder["episode_number"]: folder for folder in folders}

    assert by_episode[1]["status"] == "created"
    assert by_episode[1]["script_id"] == 11
    assert by_episode[1]["script_title"] == "更小 id"
    assert by_episode[1]["world_name"] == "Moon City"
    assert by_episode[4]["status"] == "orphan"
    assert by_episode[4]["script_id"] is None


def test_collect_storyboard_folder_data_without_world_id_uses_accessible_worlds(monkeypatch):
    seen = {}

    monkeypatch.setattr(
        storyboard_api.WorldModel,
        "list_names_for_storyboard_folders",
        lambda user_id, include_all_users=False: [{"id": 7, "name": "Moon"}, {"id": 8, "name": "Hidden"}],
    )

    def fake_scripts(world_ids):
        seen["world_ids"] = list(world_ids)
        return [
            {
                "id": 3,
                "world_id": 8,
                "title": "第二集",
                "episode_number": 2,
                "update_time": "2026-06-20T10:00:00",
            }
        ]

    monkeypatch.setattr(storyboard_api.ScriptModel, "list_for_folders", fake_scripts)
    monkeypatch.setattr(
        storyboard_api.StoryboardModel,
        "list_folders_by_user",
        lambda user_id, world_id=None, **_kwargs: [],
    )

    folders = storyboard_api.collect_storyboard_folder_data(5, None)

    assert seen["world_ids"] == [7, 8]
    assert folders == [
        {
            "folder_key": "8:2",
            "world_id": 8,
            "world_name": "Hidden",
            "episode_number": 2,
            "script_id": 3,
            "script_title": "第二集",
            "storyboard_id": None,
            "storyboard_title": None,
            "scene_count": 0,
            "status": "not_created",
            "owner_user_id": None,
            "update_at": "2026-06-20T10:00:00",
        }
    ]


def test_build_storyboard_folders_separates_owners():
    folders = storyboard_api.build_storyboard_folders(
        scripts=[
            {"id": 1, "world_id": 7, "user_id": 14, "title": "A", "episode_number": 1},
            {"id": 2, "world_id": 7, "user_id": 33, "title": "B", "episode_number": 1},
        ],
        storyboards=[
            {
                "id": 9,
                "world_id": 7,
                "user_id": 33,
                "title": "B board",
                "episode_number": 1,
                "scene_count": 3,
            }
        ],
        world_names={7: "Moon"},
        separate_owners=True,
    )
    by_owner = {folder["owner_user_id"]: folder for folder in folders}
    assert set(by_owner) == {14, 33}
    assert by_owner[14]["status"] == "not_created"
    assert by_owner[14]["storyboard_id"] is None
    assert by_owner[33]["status"] == "created"
    assert by_owner[33]["storyboard_id"] == 9
    assert by_owner[33]["script_id"] == 2


def test_apply_folder_owner_nicknames_falls_back():
    folders = [{"owner_user_id": 14}, {"owner_user_id": 33}, {"owner_user_id": None}]
    storyboard_api.apply_folder_owner_nicknames(folders, {14: "远方"})
    assert folders[0]["owner_nickname"] == "远方"
    assert folders[1]["owner_nickname"] == "用户33"
    assert folders[2]["owner_nickname"] == ""


def test_list_for_folders_queries_by_world_without_content_or_user(monkeypatch):
    captured = {}

    def fake_execute_query(sql, params=None, fetch_one=False, fetch_all=False):
        captured["sql"] = sql
        captured["params"] = params
        return [{
            "id": 1,
            "world_id": 7,
            "title": "A",
            "episode_number": 1,
            "update_time": None,
            "create_time": None,
        }]

    monkeypatch.setattr("model.script.execute_query", fake_execute_query)

    assert ScriptModel.list_for_folders([]) == []
    assert "sql" not in captured

    rows = ScriptModel.list_for_folders([7, 7, "8", None])
    assert rows[0]["id"] == 1
    assert captured["params"] == (7, 8)
    sql = " ".join(captured["sql"].split()).lower()
    assert "from script" in sql
    assert "world_id in" in sql
    assert "select id, world_id, user_id, title" in sql
    assert "user_id =" not in sql
    assert "user_id in" not in sql
    assert "content" not in sql
    assert "limit" not in sql


def test_list_names_for_storyboard_folders_keeps_soft_deleted_worlds(monkeypatch):
    captured = {}

    def fake_execute_query(sql, params=None, fetch_one=False, fetch_all=False):
        captured["sql"] = sql
        captured["params"] = params
        return [{"id": 1, "name": "W"}]

    monkeypatch.setattr("model.world.execute_query", fake_execute_query)
    monkeypatch.setattr("model.world.Edition.is_space_isolated", lambda: True)

    assert WorldModel.list_names_for_storyboard_folders(9) == [{"id": 1, "name": "W"}]
    sql = " ".join(captured["sql"].split()).lower()
    assert captured["params"] == (9,)
    assert "is_deleted" not in sql
    assert "limit" not in sql
    assert "user_id = %s" in sql

    monkeypatch.setattr("model.world.Edition.is_space_isolated", lambda: False)
    WorldModel.list_names_for_storyboard_folders(9)
    shared_sql = " ".join(captured["sql"].split()).lower()
    assert captured["params"] == tuple()
    assert "user_id" not in shared_sql
    assert "limit" not in shared_sql


def test_build_storyboard_folders_cross_owner_storyboard_is_not_orphan():
    """scope=all 按创建者拆开时，故事板属主与剧本属主不同不算「剧本缺失」。

    剧本 359 属主 17、故事板 201 属主 23 的场景：拆开后两者 key 不同合并不了，
    但同一世界同一集存在剧本，故事板卡片应显示已创建并带回剧本信息。
    """
    scripts = [
        {
            "id": 359,
            "world_id": 93,
            "user_id": 17,
            "title": "包裹里的远方",
            "episode_number": 1,
            "update_time": "2026-10-19T20:03:15",
        },
    ]
    storyboards = [
        {
            "id": 201,
            "world_id": 93,
            "user_id": 23,
            "script_id": 359,
            "title": "包裹里的远方",
            "episode_number": 1,
            "scene_count": 5,
            "update_at": "2026-10-20T10:00:00",
        },
        {
            "id": 202,
            "world_id": 93,
            "user_id": 23,
            "script_id": None,
            "title": "无剧本集",
            "episode_number": 2,
            "scene_count": 1,
            "update_at": "2026-10-20T11:00:00",
        },
    ]

    folders = storyboard_api.build_storyboard_folders(
        scripts, storyboards, {93: "包裹里的远方（A组)"}, separate_owners=True
    )
    by_key = {folder["folder_key"]: folder for folder in folders}

    board_folder = by_key["93:1:23"]
    assert board_folder["status"] == "created"
    assert board_folder["script_id"] == 359
    assert board_folder["script_title"] == "包裹里的远方"
    assert board_folder["storyboard_id"] == 201

    # 同一世界同集确实没有剧本时，仍保持 orphan（剧本缺失）
    orphan_folder = by_key["93:2:23"]
    assert orphan_folder["status"] == "orphan"
    assert orphan_folder["script_id"] is None
