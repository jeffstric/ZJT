from types import SimpleNamespace
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


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


def _client(monkeypatch):
    _seed_config_cache(monkeypatch)
    from api.marketing_publications import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_create_publication_rejects_unfinished_ai_tool(monkeypatch):
    client = _client(monkeypatch)

    monkeypatch.setattr(
        "api.marketing_publications.AIToolsModel.get_by_id",
        lambda record_id: SimpleNamespace(id=record_id, user_id=7, status=1, result_url=None),
    )

    response = client.post(
        "/api/marketing-publications",
        json={"ai_tool_id": 12, "title": "Draft"},
        headers={"X-User-Id": "7"},
    )

    assert response.status_code == 400
    assert "not completed" in response.json()["detail"]


def test_create_publication_promotes_assets_and_returns_pending(monkeypatch):
    client = _client(monkeypatch)

    ai_tool = SimpleNamespace(
        id=12,
        user_id=7,
        status=2,
        result_url="/upload/cache/result.png",
        prompt="A bright poster",
    )
    calls = []

    monkeypatch.setattr("api.marketing_publications.AIToolsModel.get_by_id", lambda record_id: ai_tool)
    monkeypatch.setattr("api.marketing_publications.MarketingPublicationModel.get_active_by_ai_tool_id", lambda ai_tool_id: None)
    monkeypatch.setattr(
        "api.marketing_publications.MarketingPublicationModel.create_pending",
        lambda **kwargs: calls.append(("create", kwargs)) or 99,
    )
    monkeypatch.setattr(
        "api.marketing_publications.MarketingPublicationAssetService.promote_assets",
        lambda tool, publication_id: {
            "result_url": "/upload/marketing_publications/99/result.png",
            "cover_url": "/upload/marketing_publications/99/result.png",
            "params_snapshot": {"prompt": tool.prompt, "mode": "image"},
        },
    )
    monkeypatch.setattr(
        "api.marketing_publications.MarketingPublicationModel.update_assets",
        lambda publication_id, result_url, cover_url, params_snapshot: calls.append(
            ("update_assets", publication_id, result_url, cover_url, params_snapshot)
        ) or 1,
    )
    monkeypatch.setattr(
        "api.marketing_publications.MarketingPublicationModel.get_by_id",
        lambda publication_id: SimpleNamespace(to_dict=lambda: {"id": publication_id, "status": "pending"}),
    )

    response = client.post(
        "/api/marketing-publications",
        json={"ai_tool_id": 12, "title": "Public title", "tags": ["poster"]},
        headers={"X-User-Id": "7"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "pending"
    assert calls[0][0] == "create"
    assert calls[1][0] == "update_assets"
    assert calls[1][2] == "/upload/marketing_publications/99/result.png"


def test_public_inspirations_uses_public_publication_list(monkeypatch):
    client = _client(monkeypatch)

    def fake_list_public(page, page_size, media_type=None):
        assert media_type == "image"
        return {"total": 1, "page": page, "page_size": page_size, "data": [{"id": 1, "status": "approved"}]}

    monkeypatch.setattr(
        "api.marketing_publications.MarketingPublicationModel.list_public",
        fake_list_public,
    )

    response = client.get("/api/marketing-inspirations?media_type=image")

    assert response.status_code == 200
    assert response.json()["data"]["data"][0]["status"] == "approved"


def test_template_media_uses_reference_images_not_result_media(monkeypatch):
    client = _client(monkeypatch)

    params_snapshot = {
        "prompt": "make a puppy portrait",
        "mode": "image",
        "media_type": "image",
        "result_url": "/upload/marketing_publications/9/result.png",
        "reference_images": ["/upload/marketing_publications/9/reference_1.png"],
        "media": [
            {
                "type": "image",
                "serverUrl": "/upload/marketing_publications/9/result.png",
                "thumbnailUrl": "/upload/marketing_publications/9/result.png",
            }
        ],
    }

    publication = SimpleNamespace(
        id=9,
        status="approved",
        prompt_snapshot="make a puppy portrait",
        result_url="/upload/marketing_publications/9/result.png",
        to_dict=lambda: {"params_snapshot": params_snapshot},
    )

    monkeypatch.setattr(
        "api.marketing_publications.MarketingPublicationModel.get_by_id",
        lambda publication_id: publication,
    )

    response = client.get("/api/marketing-inspirations/9/template")

    assert response.status_code == 200
    media = response.json()["data"]["media"]
    assert media == [
        {
            "type": "image",
            "serverUrl": "/upload/marketing_publications/9/reference_1.png",
            "thumbnailUrl": "/upload/marketing_publications/9/reference_1.png",
        }
    ]
