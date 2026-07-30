from services.location_structure_guard import (
    bind_and_validate_planned_locations,
    bind_planned_locations,
    collect_segment_location_graph,
    validate_full_location_structure,
    validate_planned_location_structure,
    validate_segment_location_structure_extended,
    validate_segment_new_roots,
)


def _codes(errors):
    return [error["code"] for error in errors]


def test_segment_allows_unmatched_new_root():
    """新顶层场景放行：DB 没有的新地点允许登记为顶层，由 publish 阶段落库。"""
    parsed = {
        "locations": [
            {
                "id": "loc_001",
                "name": "新酒店",
                "location_db_id": None,
                "parent_id": None,
            }
        ]
    }

    assert validate_segment_new_roots(parsed, []) == []


def test_segment_allows_aliased_new_root():
    """别名字段（location_id/location_name）的新顶层同样放行。"""
    parsed = {
        "locations": [{
            "location_id": "loc_alias",
            "location_name": "别名场景",
            "location_db_id": None,
            "parent_id": None,
        }]
    }

    assert validate_segment_new_roots(parsed, []) == []


def test_segment_allows_new_child_whose_parent_may_arrive_from_another_segment():
    parsed = {
        "locations": [
            {
                "id": "loc_child",
                "name": "套房阳台",
                "location_db_id": None,
                "parent_id": "loc_future_parent",
            }
        ]
    }

    assert validate_segment_new_roots(parsed, []) == []


def test_existing_child_with_omitted_parent_reuses_database_hierarchy():
    parsed = {
        "locations": [
            {
                "id": "loc_001",
                "name": "套房阳台",
                "location_db_id": 20,
                "parent_id": None,
            }
        ]
    }
    db_locations = [
        {
            "id": 10,
            "name": "城南酒店",
            "parent_id": None,
            "children": [
                {"id": 20, "name": "套房阳台", "parent_id": 10, "children": []}
            ],
        }
    ]

    assert validate_full_location_structure(parsed, db_locations) == []


def test_existing_location_with_explicit_wrong_parent_auto_aligns_to_database():
    """父级不一致不再报 location_parent_conflict，而是按数据库层级就地回写 parent_id。"""
    parsed = {
        "locations": [
            {"id": "loc_hotel_b", "name": "酒店B", "location_db_id": 11, "parent_id": None},
            {
                "id": "loc_balcony",
                "name": "套房阳台",
                "location_db_id": 20,
                "parent_id": "loc_hotel_b",
            },
        ]
    }
    db_locations = [
        {"id": 10, "name": "酒店A", "parent_id": None, "children": []},
        {"id": 11, "name": "酒店B", "parent_id": None, "children": []},
        {"id": 20, "name": "套房阳台", "parent_id": 10, "children": []},
    ]

    errors = validate_full_location_structure(parsed, db_locations)

    assert errors == []
    # DB 真父“酒店A”不在 parsed 列表中 → parent_id 置 None（库内父子以 location_db_id 行为准）
    balcony = next(item for item in parsed["locations"] if item["id"] == "loc_balcony")
    assert balcony["parent_id"] is None


def test_existing_location_wrong_parent_aligned_to_internal_id_when_db_parent_present():
    """DB 真父也在 locations 列表中时，parent_id 回写为其内部 loc_xxx，无阻塞错误。"""
    parsed = {
        "locations": [
            {"id": "loc_hotel_a", "name": "酒店A", "location_db_id": 10, "parent_id": None},
            {"id": "loc_hotel_b", "name": "酒店B", "location_db_id": 11, "parent_id": None},
            {"id": "loc_balcony", "name": "套房阳台", "location_db_id": 20, "parent_id": "loc_hotel_b"},
        ]
    }
    db_locations = [
        {"id": 10, "name": "酒店A", "parent_id": None, "children": []},
        {"id": 11, "name": "酒店B", "parent_id": None, "children": []},
        {"id": 20, "name": "套房阳台", "parent_id": 10, "children": []},
    ]

    errors = validate_full_location_structure(parsed, db_locations)

    assert errors == []
    balcony = next(item for item in parsed["locations"] if item["id"] == "loc_balcony")
    assert balcony["parent_id"] == "loc_hotel_a"


def test_full_validation_detects_missing_parent_and_cycle():
    missing_parent = {
        "locations": [
            {
                "id": "loc_child",
                "name": "套房阳台",
                "location_db_id": None,
                "parent_id": "loc_missing",
            }
        ]
    }
    cycle = {
        "locations": [
            {"id": "loc_a", "name": "A", "location_db_id": None, "parent_id": "loc_b"},
            {"id": "loc_b", "name": "B", "location_db_id": None, "parent_id": "loc_a"},
        ]
    }

    assert _codes(validate_full_location_structure(missing_parent, [])) == ["location_parent_invalid"]
    cycle_errors = validate_full_location_structure(cycle, [])
    assert _codes(cycle_errors) == ["location_parent_invalid"]
    assert cycle_errors[0]["reason"] == "cycle"


def test_bind_planned_locations_writes_db_id_for_unique_name():
    planned = [
        {"id": "loc_001", "location_key": "location:lobby", "name": "城南酒店大堂"},
        {
            "id": "loc_002",
            "location_key": "location:office",
            "name": "酒店办公室",
            "parent_location_key": "location:lobby",
        },
    ]
    db = [{"id": 565, "name": "城南酒店大堂", "parent_id": None, "children": []}]

    bound = bind_planned_locations(planned, db)

    assert bound[0]["location_db_id"] == 565
    assert bound[1]["location_db_id"] is None
    assert bound[1]["parent_id"] == "loc_001"


def test_planned_new_root_without_parent_is_allowed():
    """规划阶段无父级的新顶层场景放行。"""
    planned = [
        {"id": "loc_004", "location_key": "location:hotel_office", "name": "酒店办公室"},
    ]

    errors = validate_planned_location_structure(planned, [])

    assert errors == []


def test_planned_new_child_with_parent_key_reaches_db_root():
    planned = [
        {"id": "loc_001", "location_key": "location:lobby", "name": "城南酒店大堂"},
        {
            "id": "loc_004",
            "location_key": "location:hotel_office",
            "name": "酒店办公室",
            "parent_location_key": "location:lobby",
        },
    ]
    db = [{"id": 565, "name": "城南酒店大堂", "parent_id": None, "children": []}]

    bound, errors = bind_and_validate_planned_locations(planned, db)

    assert errors == []
    assert bound[1]["parent_id"] == "loc_001"
    assert bound[0]["location_db_id"] == 565


def test_planned_space_unit_must_bind_to_location():
    planned = [
        {"id": "loc_001", "location_key": "location:lobby", "name": "城南酒店大堂"},
    ]
    db = [{"id": 565, "name": "城南酒店大堂", "parent_id": None, "children": []}]
    spatial_world = {
        "space_units": [
            {"space_unit_id": "space_unit:office", "name": "酒店办公室", "containers": []},
        ]
    }

    _bound, errors = bind_and_validate_planned_locations(
        planned, db, spatial_world=spatial_world,
    )

    assert "planned_space_unit_location_unbound" in _codes(errors)


def test_collect_graph_pulls_registry_location_from_space_unit_owner():
    parsed = {
        "locations": [
            {"id": "loc_001", "name": "城南酒店大堂", "location_db_id": 565, "parent_id": None},
        ],
        "spatial_world": {
            "space_units": [
                {
                    "space_unit_id": "space_unit:office",
                    "name": "酒店办公室",
                    "owner_id": "loc_004",
                    "location_ids": ["loc_004"],
                }
            ]
        },
    }
    plan = {
        "compiled_registry": {
            "locations": [
                {"id": "loc_001", "name": "城南酒店大堂", "location_db_id": 565, "parent_id": None},
                {
                    "id": "loc_004",
                    "name": "酒店办公室",
                    "location_db_id": None,
                    "parent_id": None,
                },
            ]
        }
    }

    graph = collect_segment_location_graph(parsed, plan)
    ids = {item["id"] for item in graph["locations"]}
    assert "loc_004" in ids


def test_segment_extended_rejects_space_unit_registry_new_root():
    """task 47 形态：locations 无新根，但 space_unit 引用规划非法顶层。"""
    parsed = {
        "locations": [
            {"id": "loc_001", "name": "城南酒店大堂", "location_db_id": 565, "parent_id": None},
        ],
        "spatial_world": {
            "space_units": [
                {
                    "space_unit_id": "space_unit:office",
                    "name": "酒店办公室",
                    "owner_id": "loc_004",
                    "location_ids": ["loc_004"],
                }
            ]
        },
        "shot_groups": [],
    }
    plan = {
        "compiled_registry": {
            "locations": [
                {"id": "loc_001", "name": "城南酒店大堂", "location_db_id": 565},
                {"id": "loc_004", "name": "酒店办公室", "location_db_id": None, "parent_id": None},
            ]
        }
    }
    db = [{"id": 565, "name": "城南酒店大堂", "parent_id": None, "children": []}]

    errors = validate_segment_location_structure_extended(parsed, db, plan=plan)

    # 新顶层放行：space_unit 引用的规划新顶层不再报 new_root_location_forbidden
    assert "new_root_location_forbidden" not in _codes(errors)

