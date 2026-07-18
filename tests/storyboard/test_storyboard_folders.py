from api import storyboard as storyboard_api


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
            "update_at": "2026-06-23T10:00:00",
        }
    ]
