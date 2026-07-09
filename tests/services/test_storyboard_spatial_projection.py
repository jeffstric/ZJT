from enterprise.services.storyboard_spatial import (
    build_spatial_world_index,
    derive_screen_projection,
)


def test_build_spatial_world_index_keeps_multiple_space_units_separate():
    payload = {
        "spatial_world": {
            "space_units": [
                {
                    "space_unit_id": "space_prop_001_cabin",
                    "coordinate_frame": {"frame_id": "frame_cabin", "locked": True},
                    "anchors": [
                        {
                            "anchor_id": "front_driver_seat",
                            "label": "驾驶座",
                            "position_3d": {"x": 0.55, "y": 0.45, "z": 0.25},
                        }
                    ],
                },
                {
                    "space_unit_id": "space_loc_002_syrup",
                    "coordinate_frame": {"frame_id": "frame_syrup", "locked": True},
                    "anchors": [
                        {
                            "anchor_id": "syrup_pool_center",
                            "label": "糖浆池中心",
                            "position_3d": {"x": 0, "y": 0, "z": 0},
                        }
                    ],
                },
            ]
        }
    }

    index = build_spatial_world_index(payload)

    assert set(index["space_units"]) == {"space_prop_001_cabin", "space_loc_002_syrup"}
    assert index["anchors"][("space_prop_001_cabin", "front_driver_seat")]["label"] == "驾驶座"
    assert index["anchors"][("space_loc_002_syrup", "syrup_pool_center")]["label"] == "糖浆池中心"


def test_derive_screen_projection_uses_camera_pose_instead_of_raw_screen_position():
    world_index = build_spatial_world_index({
        "spatial_world": {
            "space_units": [
                {
                    "space_unit_id": "space_prop_001_cabin",
                    "anchors": [
                        {
                            "anchor_id": "front_driver_seat",
                            "position_3d": {"x": 0.55, "y": 0.45, "z": 0.25},
                        },
                        {
                            "anchor_id": "front_passenger_seat",
                            "position_3d": {"x": -0.55, "y": 0.45, "z": 0.25},
                        },
                    ],
                }
            ]
        }
    })
    camera_pose = {
        "space_unit_id": "space_prop_001_cabin",
        "eye": {"x": 0.0, "y": -0.8, "z": 0.6},
        "target": {"x": 0.0, "y": 0.45, "z": 0.25},
        "up": {"x": 0, "y": 0, "z": 1},
    }

    driver = derive_screen_projection(
        {
            "space_unit_id": "space_prop_001_cabin",
            "anchor_id": "front_driver_seat",
            "screen_position": "画面左侧（错误的LLM输出）",
        },
        camera_pose,
        world_index,
    )
    passenger = derive_screen_projection(
        {
            "space_unit_id": "space_prop_001_cabin",
            "anchor_id": "front_passenger_seat",
        },
        camera_pose,
        world_index,
    )

    assert driver["derived_screen_position"] == "画面右侧"
    assert passenger["derived_screen_position"] == "画面左侧"


def test_derive_screen_projection_detects_entity_behind_camera():
    world_index = build_spatial_world_index({
        "spatial_world": {
            "space_units": [
                {
                    "space_unit_id": "space_room",
                    "anchors": [
                        {
                            "anchor_id": "behind",
                            "position_3d": {"x": 0, "y": -1, "z": 0},
                        }
                    ],
                }
            ]
        }
    })

    projection = derive_screen_projection(
        {"space_unit_id": "space_room", "anchor_id": "behind"},
        {
            "space_unit_id": "space_room",
            "eye": {"x": 0, "y": 0, "z": 0},
            "target": {"x": 0, "y": 1, "z": 0},
            "up": {"x": 0, "y": 0, "z": 1},
        },
        world_index,
    )

    assert projection["derived_screen_position"] == "画面外（相机后方）"
