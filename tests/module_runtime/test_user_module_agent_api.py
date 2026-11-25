import asyncio
from types import SimpleNamespace

import httpx
from fastapi import FastAPI

import api.user_module_admin as module_admin_api
from module_runtime.client import SupervisorClientError
from module_runtime.generation import UserModuleReviewBusyError
from model.model import ModelModel
from model.vendor_model import VendorModelModel
from services.user_module_agent_service import (
    UserModuleAgentAnswerError,
    UserModuleAgentBusyError,
    UserModuleAgentTaskNotFoundError,
)


class FakeAgentService:
    def __init__(self, *, busy=False):
        self.busy = busy
        self.created = []
        self.answers = []
        self.answer_error = None

    async def create_task(self, **kwargs):
        if self.busy:
            raise UserModuleAgentBusyError("busy")
        self.created.append(kwargs)
        return {
            "task_id": "22222222-2222-2222-2222-222222222222",
            "generation_id": "11111111-1111-1111-1111-111111111111",
            "status": "queued",
        }

    async def get_task(self, task_id, *, requester_id, after_id=0):
        return {
            "task_id": task_id,
            "created_by": requester_id,
            "status": "running",
            "messages": [{"id": after_id + 1, "type": "running", "content": "working"}],
        }

    async def submit_answer(self, task_id, *, requester_id, question_id, selected=None, free_text=None):
        if self.answer_error is not None:
            raise self.answer_error
        payload = {
            "task_id": task_id,
            "requester_id": requester_id,
            "question_id": question_id,
            "selected": selected,
            "free_text": free_text,
            "answered_at": "2026-08-21T00:00:00+00:00",
        }
        self.answers.append(payload)
        return payload


class FakeGenerationService:
    def __init__(self):
        self.created = []

    async def create(self, **kwargs):
        self.created.append(kwargs)
        return {
            "generation_id": "11111111-1111-1111-1111-111111111111",
            "status": "draft",
            **kwargs,
        }


def _patch_admin(monkeypatch):
    async def authenticated(_authorization):
        return SimpleNamespace(id=7, role="admin"), None

    monkeypatch.setattr(module_admin_api, "_require_admin_user", authenticated)


def _app():
    app = FastAPI()
    app.include_router(module_admin_api.router)
    return app


def test_create_agent_task_validates_model_vendor_pair_and_forwards_memory_token(monkeypatch):
    async def scenario():
        _patch_admin(monkeypatch)
        service = FakeAgentService()
        monkeypatch.setattr(module_admin_api, "get_user_module_agent_service", lambda: service)
        monkeypatch.setattr(
            ModelModel,
            "get_by_id",
            lambda model_id: SimpleNamespace(
                id=model_id,
                enabled=1,
                supports_tools=1,
                model_name="tool-model",
            ),
        )
        monkeypatch.setattr(
            VendorModelModel,
            "get_by_vendor_model",
            lambda vendor_id, model_id: SimpleNamespace(vendor_id=vendor_id, model_id=model_id),
        )

        transport = httpx.ASGITransport(app=_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/admin/user-modules/agent/tasks",
                headers={"Authorization": "Bearer transient-admin-token"},
                json={
                    "module_id": "vendor.demo",
                    "requirement": "实现一个异步图片生成接口",
                    "model_id": 12,
                    "vendor_id": 3,
                },
            )

        assert response.status_code == 202
        assert service.created[0]["auth_token"] == "transient-admin-token"
        assert service.created[0]["vendor_id"] == 3
        assert service.created[0]["model"] == "tool-model"

    asyncio.run(scenario())


def test_create_agent_task_requires_comfyui_address_and_workflow(monkeypatch):
    async def scenario():
        _patch_admin(monkeypatch)
        service = FakeAgentService()
        monkeypatch.setattr(module_admin_api, "get_user_module_agent_service", lambda: service)
        monkeypatch.setattr(
            ModelModel,
            "get_by_id",
            lambda model_id: SimpleNamespace(
                id=model_id,
                enabled=1,
                supports_tools=1,
                model_name="tool-model",
            ),
        )
        monkeypatch.setattr(
            VendorModelModel,
            "get_by_vendor_model",
            lambda vendor_id, model_id: SimpleNamespace(vendor_id=vendor_id, model_id=model_id),
        )

        transport = httpx.ASGITransport(app=_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            missing = await client.post(
                "/api/admin/user-modules/agent/tasks",
                headers={"Authorization": "Bearer token"},
                json={
                    "module_id": "local.qwen-edit",
                    "requirement": "",
                    "model_id": 12,
                    "connector": "local_comfyui",
                },
            )
            ok = await client.post(
                "/api/admin/user-modules/agent/tasks",
                headers={"Authorization": "Bearer token"},
                json={
                    "module_id": "local.qwen-edit",
                    "model_id": 12,
                    "vendor_id": 3,
                    "connector": "local_comfyui",
                    "comfyui_base_url": "http://192.168.10.187:8188/",
                    "workflow_json": '{"78": {"class_type": "LoadImage", "inputs": {"image": "a.png"}}}',
                },
            )

        assert missing.status_code == 422
        assert ok.status_code == 202
        assert len(service.created) == 1
        assert service.created[0]["connector"] == "local_comfyui"
        assert service.created[0]["comfyui_base_url"] == "http://192.168.10.187:8188/"

    asyncio.run(scenario())


def test_create_agent_task_rejects_model_without_tool_calling(monkeypatch):
    async def scenario():
        _patch_admin(monkeypatch)
        service = FakeAgentService()
        monkeypatch.setattr(module_admin_api, "get_user_module_agent_service", lambda: service)
        monkeypatch.setattr(
            ModelModel,
            "get_by_id",
            lambda model_id: SimpleNamespace(
                id=model_id,
                enabled=1,
                supports_tools=0,
                model_name="text-only-model",
            ),
        )

        transport = httpx.ASGITransport(app=_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/admin/user-modules/agent/tasks",
                headers={"Authorization": "Bearer token"},
                json={
                    "module_id": "vendor.demo",
                    "requirement": "实现一个异步图片生成接口",
                    "model_id": 12,
                },
            )

        assert response.status_code == 400
        assert not service.created

    asyncio.run(scenario())


def test_create_agent_task_rejects_unrelated_vendor(monkeypatch):
    async def scenario():
        _patch_admin(monkeypatch)
        service = FakeAgentService()
        monkeypatch.setattr(module_admin_api, "get_user_module_agent_service", lambda: service)
        monkeypatch.setattr(
            ModelModel,
            "get_by_id",
            lambda model_id: SimpleNamespace(
                id=model_id,
                enabled=1,
                supports_tools=1,
                model_name="tool-model",
            ),
        )
        monkeypatch.setattr(VendorModelModel, "get_by_vendor_model", lambda *_args: None)

        transport = httpx.ASGITransport(app=_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/admin/user-modules/agent/tasks",
                headers={"Authorization": "Bearer token"},
                json={
                    "module_id": "vendor.demo",
                    "requirement": "实现一个异步图片生成接口",
                    "model_id": 12,
                    "vendor_id": 99,
                },
            )

        assert response.status_code == 400
        assert not service.created

    asyncio.run(scenario())


def test_create_agent_task_returns_429_when_service_is_busy(monkeypatch):
    async def scenario():
        _patch_admin(monkeypatch)
        service = FakeAgentService(busy=True)
        monkeypatch.setattr(module_admin_api, "get_user_module_agent_service", lambda: service)
        monkeypatch.setattr(
            ModelModel,
            "get_by_id",
            lambda model_id: SimpleNamespace(
                id=model_id,
                enabled=1,
                supports_tools=1,
                model_name="tool-model",
            ),
        )
        monkeypatch.setattr(VendorModelModel, "get_vendor_id_by_model_id", lambda _model_id: 3)

        transport = httpx.ASGITransport(app=_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/admin/user-modules/agent/tasks",
                headers={"Authorization": "Bearer token"},
                json={
                    "module_id": "vendor.demo",
                    "requirement": "实现一个异步图片生成接口",
                    "model_id": 12,
                },
            )

        assert response.status_code == 429
        assert response.json()["error_code"] == "agent_task_busy"

    asyncio.run(scenario())


def test_get_agent_task_forwards_incremental_message_cursor(monkeypatch):
    async def scenario():
        _patch_admin(monkeypatch)
        service = FakeAgentService()
        monkeypatch.setattr(module_admin_api, "get_user_module_agent_service", lambda: service)
        transport = httpx.ASGITransport(app=_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                "/api/admin/user-modules/agent/tasks/22222222-2222-2222-2222-222222222222",
                params={"after_id": 7},
                headers={"Authorization": "Bearer token"},
            )
        assert response.status_code == 200
        assert response.json()["data"]["messages"][0]["id"] == 8

    asyncio.run(scenario())


def test_submit_agent_task_answer_forwards_payload(monkeypatch):
    async def scenario():
        _patch_admin(monkeypatch)
        service = FakeAgentService()
        monkeypatch.setattr(module_admin_api, "get_user_module_agent_service", lambda: service)
        transport = httpx.ASGITransport(app=_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/admin/user-modules/agent/tasks/22222222-2222-2222-2222-222222222222/answers",
                headers={"Authorization": "Bearer token"},
                json={"question_id": "q_abc123", "selected": "是", "free_text": "见文档"},
            )
        assert response.status_code == 200
        assert service.answers[0]["question_id"] == "q_abc123"
        assert service.answers[0]["selected"] == "是"
        assert service.answers[0]["free_text"] == "见文档"
        assert service.answers[0]["requester_id"] == "7"

    asyncio.run(scenario())


def test_submit_agent_task_answer_requires_payload(monkeypatch):
    async def scenario():
        _patch_admin(monkeypatch)
        service = FakeAgentService()
        monkeypatch.setattr(module_admin_api, "get_user_module_agent_service", lambda: service)
        transport = httpx.ASGITransport(app=_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/admin/user-modules/agent/tasks/22222222-2222-2222-2222-222222222222/answers",
                headers={"Authorization": "Bearer token"},
                json={"question_id": "q_abc123"},
            )
        assert response.status_code == 422
        assert service.answers == []

    asyncio.run(scenario())


def test_submit_agent_task_answer_maps_service_errors(monkeypatch):
    async def scenario():
        _patch_admin(monkeypatch)
        service = FakeAgentService()
        monkeypatch.setattr(module_admin_api, "get_user_module_agent_service", lambda: service)
        transport = httpx.ASGITransport(app=_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            service.answer_error = UserModuleAgentTaskNotFoundError("模块生成任务不存在")
            missing = await client.post(
                "/api/admin/user-modules/agent/tasks/22222222-2222-2222-2222-222222222222/answers",
                headers={"Authorization": "Bearer token"},
                json={"question_id": "q_abc123", "selected": "是"},
            )
            assert missing.status_code == 404

            service.answer_error = UserModuleAgentAnswerError(
                "任务已中断，请重新发起",
                code="agent_task_interrupted",
                status_code=409,
            )
            interrupted = await client.post(
                "/api/admin/user-modules/agent/tasks/22222222-2222-2222-2222-222222222222/answers",
                headers={"Authorization": "Bearer token"},
                json={"question_id": "q_abc123", "selected": "是"},
            )
            assert interrupted.status_code == 409
            assert interrupted.json()["error_code"] == "agent_task_interrupted"

            service.answer_error = UserModuleAgentAnswerError(
                "该问题已回答",
                code="question_already_answered",
                status_code=409,
            )
            duplicate = await client.post(
                "/api/admin/user-modules/agent/tasks/22222222-2222-2222-2222-222222222222/answers",
                headers={"Authorization": "Bearer token"},
                json={"question_id": "q_abc123", "selected": "是"},
            )
            assert duplicate.status_code == 409
            assert duplicate.json()["error_code"] == "question_already_answered"

            service.answer_error = UserModuleAgentAnswerError(
                "selected 不在可选列表中",
                code="invalid_selected_option",
                status_code=400,
            )
            invalid = await client.post(
                "/api/admin/user-modules/agent/tasks/22222222-2222-2222-2222-222222222222/answers",
                headers={"Authorization": "Bearer token"},
                json={"question_id": "q_abc123", "selected": "其他"},
            )
            assert invalid.status_code == 400
            assert invalid.json()["error_code"] == "invalid_selected_option"

    asyncio.run(scenario())


def test_direct_generation_create_resolves_and_persists_review_target(monkeypatch):
    async def scenario():
        _patch_admin(monkeypatch)
        service = FakeGenerationService()
        monkeypatch.setattr(module_admin_api, "generation_service", service)
        monkeypatch.setattr(module_admin_api, "USER_MODULE_REVIEW_ENABLED", True)
        monkeypatch.setattr(module_admin_api, "USER_MODULE_REVIEW_REQUIRED", True)
        monkeypatch.setattr(module_admin_api, "USER_MODULE_REVIEW_MODEL", "")
        monkeypatch.setattr(
            ModelModel,
            "get_by_id",
            lambda model_id: SimpleNamespace(
                id=model_id,
                enabled=1,
                model_name="review-fallback-model",
            ),
        )
        monkeypatch.setattr(
            VendorModelModel,
            "get_by_vendor_model",
            lambda vendor_id, model_id: SimpleNamespace(vendor_id=vendor_id, model_id=model_id),
        )

        transport = httpx.ASGITransport(app=_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/admin/user-modules/generations",
                headers={"Authorization": "Bearer token"},
                json={
                    "module_id": "vendor.demo",
                    "requirement": "实现一个异步图片生成接口",
                    "model_id": 12,
                    "vendor_id": 3,
                },
            )

        assert response.status_code == 201
        assert service.created == [{
            "module_id": "vendor.demo",
            "requirement": "实现一个异步图片生成接口",
            "created_by": "7",
            "review_model": "review-fallback-model",
            "review_model_id": 12,
            "review_vendor_id": 3,
        }]

    asyncio.run(scenario())


def test_direct_generation_create_requires_review_model_route_for_fallback(monkeypatch):
    async def scenario():
        _patch_admin(monkeypatch)
        service = FakeGenerationService()
        monkeypatch.setattr(module_admin_api, "generation_service", service)
        monkeypatch.setattr(module_admin_api, "USER_MODULE_REVIEW_ENABLED", True)
        monkeypatch.setattr(module_admin_api, "USER_MODULE_REVIEW_REQUIRED", True)
        monkeypatch.setattr(module_admin_api, "USER_MODULE_REVIEW_MODEL", "")

        transport = httpx.ASGITransport(app=_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/admin/user-modules/generations",
                headers={"Authorization": "Bearer token"},
                json={
                    "module_id": "vendor.demo",
                    "requirement": "实现一个异步图片生成接口",
                },
            )

        assert response.status_code == 400
        assert "model_id" in response.json()["error"]
        assert service.created == []

    asyncio.run(scenario())


def test_direct_generation_create_rejects_unrelated_review_vendor(monkeypatch):
    async def scenario():
        _patch_admin(monkeypatch)
        service = FakeGenerationService()
        monkeypatch.setattr(module_admin_api, "generation_service", service)
        monkeypatch.setattr(module_admin_api, "USER_MODULE_REVIEW_ENABLED", True)
        monkeypatch.setattr(module_admin_api, "USER_MODULE_REVIEW_REQUIRED", True)
        monkeypatch.setattr(module_admin_api, "USER_MODULE_REVIEW_MODEL", "")
        monkeypatch.setattr(
            ModelModel,
            "get_by_id",
            lambda model_id: SimpleNamespace(
                id=model_id,
                enabled=1,
                model_name="review-fallback-model",
            ),
        )
        monkeypatch.setattr(VendorModelModel, "get_by_vendor_model", lambda *_args: None)

        transport = httpx.ASGITransport(app=_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/admin/user-modules/generations",
                headers={"Authorization": "Bearer token"},
                json={
                    "module_id": "vendor.demo",
                    "requirement": "实现一个异步图片生成接口",
                    "model_id": 12,
                    "vendor_id": 99,
                },
            )

        assert response.status_code == 400
        assert service.created == []

    asyncio.run(scenario())


def test_direct_generation_create_rejects_disabled_review_model(monkeypatch):
    async def scenario():
        _patch_admin(monkeypatch)
        service = FakeGenerationService()
        monkeypatch.setattr(module_admin_api, "generation_service", service)
        monkeypatch.setattr(module_admin_api, "USER_MODULE_REVIEW_ENABLED", True)
        monkeypatch.setattr(module_admin_api, "USER_MODULE_REVIEW_REQUIRED", True)
        monkeypatch.setattr(module_admin_api, "USER_MODULE_REVIEW_MODEL", "")
        monkeypatch.setattr(
            ModelModel,
            "get_by_id",
            lambda model_id: SimpleNamespace(
                id=model_id,
                enabled=0,
                model_name="disabled-model",
            ),
        )

        transport = httpx.ASGITransport(app=_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/admin/user-modules/generations",
                headers={"Authorization": "Bearer token"},
                json={
                    "module_id": "vendor.demo",
                    "requirement": "实现一个异步图片生成接口",
                    "model_id": 12,
                    "vendor_id": 3,
                },
            )

        assert response.status_code == 400
        assert "未启用" in response.json()["error"]
        assert service.created == []

    asyncio.run(scenario())


def test_validate_generation_returns_conflict_when_review_is_running(monkeypatch):
    class BusyGenerationService:
        async def assert_owner(self, _generation_id, _requester_id):
            return None

        async def validate(self, _generation_id, *, auth_token):
            assert auth_token == "token"
            raise UserModuleReviewBusyError("该草稿正在执行 AI 安全审核")

    async def scenario():
        _patch_admin(monkeypatch)
        monkeypatch.setattr(module_admin_api, "generation_service", BusyGenerationService())

        transport = httpx.ASGITransport(app=_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/admin/user-modules/generations/generation-1/validate",
                headers={"Authorization": "Bearer token"},
            )

        assert response.status_code == 409
        assert response.json()["error_code"] == "review_in_progress"

    asyncio.run(scenario())


def test_approve_generation_redacts_supervisor_validation_message(monkeypatch):
    leaked_secret = "hm-api-leaked-health-value"

    class LeakyGenerationService:
        async def assert_owner(self, _generation_id, _requester_id):
            return None

        async def approve(self, _generation_id, _approved_by):
            raise SupervisorClientError(
                "RELEASE_HEALTH_UNHEALTHY",
                leaked_secret,
                status_code=422,
                safe_details={
                    "missing_secrets": ["EXAMPLE_API_KEY"],
                    "debug": leaked_secret,
                },
            )

    async def scenario():
        _patch_admin(monkeypatch)
        monkeypatch.setattr(module_admin_api, "generation_service", LeakyGenerationService())

        transport = httpx.ASGITransport(app=_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/admin/user-modules/generations/generation-1/approve",
                headers={"Authorization": "Bearer token"},
            )

        assert response.status_code == 422
        assert response.json() == {
            "success": False,
            "error_code": "RELEASE_HEALTH_UNHEALTHY",
            "error": "候选 Release 的 Driver health 返回不健康",
            "details": {"missing_secrets": ["EXAMPLE_API_KEY"]},
        }
        assert leaked_secret not in response.text

    asyncio.run(scenario())


def test_secret_catalog_returns_metadata_without_values(monkeypatch):
    """密钥目录只返回名称/描述/是否已配置，绝不包含密钥值；未标记配置不出现在目录。"""
    import module_runtime.secret_resolver as secret_resolver

    async def scenario():
        _patch_admin(monkeypatch)
        monkeypatch.setattr(
            secret_resolver,
            "read_dynamic_secret",
            lambda config_path: "real-secret-value" if config_path == ("runninghub", "api_key") else "",
        )
        transport = httpx.ASGITransport(app=_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                "/api/admin/user-modules/secret-catalog",
                headers={"Authorization": "Bearer test"},
            )
        assert response.status_code == 200
        catalog = response.json()["data"]["catalog"]
        runninghub = next(
            item for item in catalog if item["secret_name"] == "RUNNINGHUB_API_KEY"
        )
        assert runninghub["config_key"] == "runninghub.api_key"
        assert runninghub["configured"] is True
        assert runninghub["description"]
        names = {item["secret_name"] for item in catalog}
        assert "VIDU_TOKEN" in names
        assert "ZJT_TOKEN" not in names
        assert "PAY_WXPAY_API_KEY" not in names
        assert "real-secret-value" not in response.text

    asyncio.run(scenario())


def test_list_agent_tasks_returns_current_admin_tasks(monkeypatch):
    async def scenario():
        _patch_admin(monkeypatch)

        class FakeService:
            async def list_tasks(self, *, limit, requester_id):
                captured.update(limit=limit, requester_id=requester_id)
                return [{"task_id": "t-1", "module_id": "demo.echo", "status": "completed"}]

        captured = {}
        monkeypatch.setattr(module_admin_api, "get_user_module_agent_service", lambda: FakeService())
        transport = httpx.ASGITransport(app=_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                "/api/admin/user-modules/agent/tasks?limit=5",
                headers={"Authorization": "Bearer test"},
            )
        assert response.status_code == 200
        assert response.json()["data"]["tasks"][0]["task_id"] == "t-1"
        assert captured == {"limit": 5, "requester_id": "7"}

    asyncio.run(scenario())


def test_delete_module_soft_deletes_disabled_module(monkeypatch):
    async def scenario():
        _patch_admin(monkeypatch)
        import model.user_modules as user_modules_model

        monkeypatch.setattr(
            user_modules_model.UserModulesModel,
            "get_module",
            staticmethod(lambda _module_id: SimpleNamespace(enabled=False, status="disabled")),
        )
        monkeypatch.setattr(
            user_modules_model.UserModulesModel,
            "delete_module",
            staticmethod(lambda _module_id: 1),
        )

        class FakeSupervisorClient:
            def __init__(self):
                pass

            async def reload(self):
                return {"ok": True}

        monkeypatch.setattr(module_admin_api, "SupervisorClient", FakeSupervisorClient)
        reloaded = []

        async def fake_reload_registrations():
            reloaded.append(True)

        monkeypatch.setattr(
            module_admin_api,
            "_reload_binding_registrations",
            fake_reload_registrations,
        )
        transport = httpx.ASGITransport(app=_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.delete(
                "/api/admin/user-modules/demo.echo",
                headers={"Authorization": "Bearer test"},
            )
        assert response.status_code == 200
        assert response.json()["data"] == {"module_id": "demo.echo", "deleted": True}
        assert reloaded == [True]

    asyncio.run(scenario())


def test_delete_module_rejects_enabled_module(monkeypatch):
    async def scenario():
        _patch_admin(monkeypatch)
        import model.user_modules as user_modules_model

        monkeypatch.setattr(
            user_modules_model.UserModulesModel,
            "get_module",
            staticmethod(lambda _module_id: SimpleNamespace(enabled=True, status="active")),
        )
        transport = httpx.ASGITransport(app=_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.delete(
                "/api/admin/user-modules/demo.echo",
                headers={"Authorization": "Bearer test"},
            )
        assert response.status_code == 400
        assert "禁用" in response.json()["error"]

    asyncio.run(scenario())


def test_release_file_content_read_and_escape_rejected(tmp_path, monkeypatch):
    async def scenario():
        _patch_admin(monkeypatch)
        import model.user_modules as user_modules_model
        import module_runtime.paths as paths

        release_dir = tmp_path / "modules" / "demo.echo" / "releases" / "1.0.0-a"
        (release_dir / "src").mkdir(parents=True)
        (release_dir / "src" / "driver.py").write_text("# demo driver", encoding="utf-8")
        (tmp_path / "secret.txt").write_text("nope", encoding="utf-8")

        monkeypatch.setattr(
            user_modules_model.UserModulesModel,
            "get_release",
            staticmethod(
                lambda _release_id: SimpleNamespace(
                    module_id="demo.echo", release_path="modules/demo.echo/releases/1.0.0-a"
                )
            ),
        )
        monkeypatch.setattr(paths, "get_user_module_root", lambda: tmp_path)

        transport = httpx.ASGITransport(app=_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = {"Authorization": "Bearer test"}
            ok = await client.get(
                "/api/admin/user-modules/demo.echo/releases/3/files",
                headers=headers,
            )
            assert ok.status_code == 200
            file_paths = [item["path"] for item in ok.json()["data"]["files"]]
            assert file_paths == ["src/driver.py"]

            content = await client.get(
                "/api/admin/user-modules/demo.echo/releases/3/files/content",
                params={"path": "src/driver.py"},
                headers=headers,
            )
            assert content.status_code == 200
            assert content.json()["data"]["content"] == "# demo driver"

            escape = await client.get(
                "/api/admin/user-modules/demo.echo/releases/3/files/content",
                params={"path": "../../secret.txt"},
                headers=headers,
            )
            assert escape.status_code == 400

    asyncio.run(scenario())


def test_release_file_content_rejects_foreign_release(tmp_path, monkeypatch):
    async def scenario():
        _patch_admin(monkeypatch)
        import model.user_modules as user_modules_model

        monkeypatch.setattr(
            user_modules_model.UserModulesModel,
            "get_release",
            staticmethod(
                lambda _release_id: SimpleNamespace(
                    module_id="other.module", release_path="modules/other/releases/1.0.0"
                )
            ),
        )
        transport = httpx.ASGITransport(app=_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                "/api/admin/user-modules/demo.echo/releases/3/files",
                headers={"Authorization": "Bearer test"},
            )
        assert response.status_code == 400
        assert "不属于" in response.json()["error"]

    asyncio.run(scenario())
