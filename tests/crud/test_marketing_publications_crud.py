import json
from datetime import datetime


def _seed_config_cache(monkeypatch):
    monkeypatch.setenv("comfyui_env", "unit")
    import config.config_util as config_util

    config_util._config_cache["config_unit.yml"] = {
        "database": {
            "host": "127.0.0.1",
            "port": 3306,
            "user": "unit",
            "password": "unit",
            "database": "unit",
        }
    }


def test_create_pending_inserts_publication_with_pending_status(monkeypatch):
    _seed_config_cache(monkeypatch)
    from model.marketing_publications import MarketingPublicationModel
    from model.marketing_publications import PublicationStatus

    captured = {}

    def fake_insert(sql, params):
        captured["sql"] = sql
        captured["params"] = params
        return 42

    monkeypatch.setattr("model.marketing_publications.execute_insert", fake_insert)

    publication_id = MarketingPublicationModel.create_pending(
        ai_tool_id=9,
        owner_user_id=3,
        media_type="image",
        title="A title",
        description="desc",
        tags=["poster", "summer"],
        result_url="/upload/marketing_publications/42/result.png",
        cover_url="/upload/marketing_publications/42/result.png",
        prompt_snapshot="prompt",
        params_snapshot={"mode": "image"},
    )

    assert publication_id == 42
    assert "INSERT INTO marketing_publications" in captured["sql"]
    assert PublicationStatus.PENDING in captured["params"]
    assert json.dumps(["poster", "summer"], ensure_ascii=False) in captured["params"]
    assert json.dumps({"mode": "image"}, ensure_ascii=False) in captured["params"]


def test_publication_to_dict_decodes_tags_and_params(monkeypatch):
    _seed_config_cache(monkeypatch)
    from model.marketing_publications import MarketingPublication

    publication = MarketingPublication(
        id=1,
        ai_tool_id=9,
        owner_user_id=3,
        media_type="video",
        title="Title",
        description=None,
        tags_json='["tag"]',
        result_url="/result.mp4",
        cover_url="/cover.jpg",
        prompt_snapshot="prompt",
        params_snapshot_json='{"mode":"video"}',
        status="approved",
        submitted_at=datetime(2026, 6, 24, 1, 2, 3),
        reviewed_at=None,
        published_at=None,
        created_at=None,
        updated_at=None,
    )

    data = publication.to_dict()

    assert data["tags"] == ["tag"]
    assert data["params_snapshot"] == {"mode": "video"}
    assert data["submitted_at"] == "2026-06-24T01:02:03"


def test_list_public_filters_only_approved(monkeypatch):
    _seed_config_cache(monkeypatch)
    from model.marketing_publications import MarketingPublicationModel
    from model.marketing_publications import PublicationStatus

    queries = []

    def fake_query(sql, params=(), fetch_one=False, fetch_all=False):
        queries.append((sql, params, fetch_one, fetch_all))
        if fetch_one:
            return {"total": 0}
        return []

    monkeypatch.setattr("model.marketing_publications.execute_query", fake_query)

    result = MarketingPublicationModel.list_public(page=1, page_size=12, media_type="image")

    assert result["total"] == 0
    assert any(PublicationStatus.APPROVED in q[1] for q in queries)
    assert all("status = %s" in q[0] for q in queries)
