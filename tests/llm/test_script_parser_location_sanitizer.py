from llm.script_parser import sanitize_parsed_location_references
from services.location_structure_guard import validate_full_location_structure


def test_explicit_db_id_rewrites_wrong_parent_to_database_hierarchy():
    """已声明 location_db_id 时，错误 parent 必须按 DB 纠正，避免 location_parent_conflict。"""
    parsed = {
        "locations": [
            {
                "id": "loc_001",
                "name": "城南酒店大堂",
                "location_db_id": 565,
                "parent_id": None,
            },
            {
                "id": "loc_004",
                "name": "酒店前台区域",
                "location_db_id": 794,
                # 模型误判为“大堂子场景”，但 DB 中该场景是顶层
                "parent_id": "loc_001",
            },
            {
                "id": "loc_005",
                "name": "经理办公室",
                "location_db_id": 796,
                "parent_id": "loc_001",
            },
        ],
        "shot_groups": [{"shots": [{"location_id": "loc_004"}]}],
    }
    db_locations = [
        {"id": 565, "name": "城南酒店大堂", "parent_id": None, "children": []},
        {"id": 794, "name": "酒店前台区域", "parent_id": None, "children": []},
        {"id": 796, "name": "经理办公室", "parent_id": None, "children": []},
    ]

    result = sanitize_parsed_location_references(parsed, db_locations)

    by_id = {item["id"]: item for item in result["locations"]}
    assert by_id["loc_004"]["location_db_id"] == 794
    assert by_id["loc_004"]["parent_id"] is None
    assert by_id["loc_005"]["location_db_id"] == 796
    assert by_id["loc_005"]["parent_id"] is None
    assert validate_full_location_structure(result, db_locations) == []


def test_explicit_db_id_rewrites_parent_to_internal_id_matching_db_parent():
    """DB 有父级且本段也输出了父场景时，parent_id 应对齐到对应内部 id。"""
    parsed = {
        "locations": [
            {"id": "loc_hotel", "name": "酒店A", "location_db_id": 10, "parent_id": None},
            {
                "id": "loc_balcony",
                "name": "套房阳台",
                "location_db_id": 20,
                "parent_id": None,  # 模型漏写父级
            },
        ],
        "shot_groups": [],
    }
    db_locations = [
        {"id": 10, "name": "酒店A", "parent_id": None, "children": []},
        {"id": 20, "name": "套房阳台", "parent_id": 10, "children": []},
    ]

    result = sanitize_parsed_location_references(parsed, db_locations)
    balcony = next(item for item in result["locations"] if item["id"] == "loc_balcony")
    assert balcony["parent_id"] == "loc_hotel"
    assert validate_full_location_structure(result, db_locations) == []


def test_name_fallback_with_explicit_wrong_parent_binds_database_id_and_aligns_parent():
    """同名异父不再拒绝绑定：降级按数据库同名场景绑定、父级按 DB 对齐，并记录警告。"""
    parsed = {
        "locations": [
            {"id": "loc_hotel_b", "name": "酒店B", "location_db_id": 11, "parent_id": None},
            {
                "id": "loc_balcony",
                "name": "套房阳台",
                "location_db_id": None,
                "parent_id": "loc_hotel_b",
            },
        ],
        "shot_groups": [{"shots": [{"location_id": "loc_balcony"}]}],
    }
    db_locations = [
        {"id": 10, "name": "酒店A", "parent_id": None, "children": []},
        {"id": 11, "name": "酒店B", "parent_id": None, "children": []},
        {"id": 20, "name": "套房阳台", "parent_id": 10, "children": []},
    ]

    result = sanitize_parsed_location_references(parsed, db_locations)

    balcony = next(item for item in result["locations"] if item["id"] == "loc_balcony")
    assert balcony["location_db_id"] == 20
    # DB 真父“酒店A”不在本批 locations 中 → parent_id 置 None
    assert balcony["parent_id"] is None
    assert result["shot_groups"][0]["shots"][0]["location_id"] == "loc_balcony"
    aligned = result["metadata"]["location_parent_auto_aligned"]
    assert len(aligned) == 1
    assert aligned[0]["location_db_id"] == 20
    assert aligned[0]["expected_parent_db_id"] == 10
    assert aligned[0]["actual_parent_db_id"] == 11
    assert validate_full_location_structure(result, db_locations) == []


def test_name_fallback_conflict_rewrites_parent_to_db_true_parent():
    """“校长办公室”形态：同名 DB 子场景 + LLM 乱写父级 + DB 真父在列表中 → 回写真父内部 id。"""
    parsed = {
        "locations": [
            {"id": "loc_teaching_building", "name": "教学楼", "location_db_id": 1, "parent_id": None},
            {"id": "loc_playground", "name": "操场", "location_db_id": None, "parent_id": None},
            {
                "id": "loc_principal_office",
                "name": "校长办公室",
                "location_db_id": None,
                "parent_id": "loc_playground",  # LLM 乱挂到操场下
            },
        ],
        "shot_groups": [{"shots": [{"location_id": "loc_principal_office"}]}],
    }
    db_locations = [
        {
            "id": 1, "name": "教学楼", "parent_id": None,
            "children": [{"id": 2, "name": "校长办公室", "parent_id": 1, "children": []}],
        },
    ]

    result = sanitize_parsed_location_references(parsed, db_locations)

    office = next(item for item in result["locations"] if item["id"] == "loc_principal_office")
    assert office["location_db_id"] == 2
    assert office["parent_id"] == "loc_teaching_building"
    aligned = result["metadata"]["location_parent_auto_aligned"]
    assert len(aligned) == 1
    assert aligned[0]["location_id"] == "loc_principal_office"
    assert validate_full_location_structure(result, db_locations) == []


def test_name_fallback_without_explicit_parent_reuses_existing_child():
    parsed = {
        "locations": [
            {
                "id": "loc_balcony",
                "name": "套房阳台",
                "location_db_id": None,
                "parent_id": None,
            }
        ],
        "shot_groups": [],
    }
    db_locations = [
        {
            "id": 10,
            "name": "酒店A",
            "parent_id": None,
            "children": [
                {"id": 20, "name": "套房阳台", "parent_id": 10, "children": []}
            ],
        }
    ]

    result = sanitize_parsed_location_references(parsed, db_locations)

    assert result["locations"][0]["location_db_id"] == 20
    assert result["locations"][0]["parent_id"] is None


def test_fuzzy_name_match_with_different_parent_stays_new_scene():
    """“阳台”（酒店B下）撞上 DB“酒店A阳台”：模糊匹配且父级不同，拒绝绑定保留为新场景。"""
    parsed = {
        "locations": [
            {"id": "loc_hotel_b", "name": "酒店B", "location_db_id": 11, "parent_id": None},
            {
                "id": "loc_balcony",
                "name": "阳台",
                "location_db_id": None,
                "parent_id": "loc_hotel_b",
            },
        ],
        "shot_groups": [{"shots": [{"location_id": "loc_balcony"}]}],
    }
    db_locations = [
        {
            "id": 10, "name": "酒店A", "parent_id": None,
            "children": [{"id": 20, "name": "酒店A阳台", "parent_id": 10, "children": []}],
        },
        {"id": 11, "name": "酒店B", "parent_id": None, "children": []},
    ]

    result = sanitize_parsed_location_references(parsed, db_locations)

    balcony = next(item for item in result["locations"] if item["id"] == "loc_balcony")
    assert balcony["location_db_id"] is None  # 不绑定“酒店A阳台”
    assert balcony["parent_id"] == "loc_hotel_b"  # 保留规划父级，等待 bootstrap 入库
    assert result["shot_groups"][0]["shots"][0]["location_id"] == "loc_balcony"
    assert "location_parent_auto_aligned" not in result["metadata"]
    assert result["metadata"]["has_unpersisted_locations"] is True
    assert validate_full_location_structure(result, db_locations) == []
