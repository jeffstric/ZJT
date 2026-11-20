from types import SimpleNamespace

from module_runtime import secret_resolver
from module_runtime.protocol import DriverContext
from module_runtime.runner import RunnerRuntime
from module_runtime.supervisor import _build_runner_env, _context_with_secrets


def test_grantable_aliases_generated_from_default_configs():
    """可授权映射由 user_module_grantable 标记自动生成，规范名 = config_key 大写下划线。"""
    aliases = secret_resolver.user_module_grantable_aliases()

    assert aliases["RUNNINGHUB_API_KEY"] == ("runninghub", "api_key")
    assert aliases["HUIMENGI_API_KEY"] == ("huimengi", "api_key")
    assert aliases["DUOMI_TOKEN"] == ("duomi", "token")
    assert aliases["VIDU_TOKEN"] == ("vidu", "token")
    assert aliases["API_AGGREGATOR_SITE_0_API_KEY"] == ("api_aggregator", "site_0", "api_key")
    assert aliases["LLM_GOOGLE_API_KEY"] == ("llm", "google", "api_key")
    # 未标记 user_module_grantable 的敏感配置不得出现在映射中
    assert "ZJT_TOKEN" not in aliases
    assert "PAY_WXPAY_API_KEY" not in aliases
    assert "FILE_STORAGE_QINIU_ACCESS_KEY" not in aliases
    # 每次调用返回独立 dict，篡改不影响缓存
    aliases["RUNNINGHUB_API_KEY"] = ("tampered",)
    assert secret_resolver.user_module_grantable_aliases()["RUNNINGHUB_API_KEY"] == (
        "runninghub",
        "api_key",
    )


def test_grantable_catalog_includes_config_descriptions():
    """目录接口透传 DEFAULT_CONFIGS 的 description，供生成任务区分同族编号槽位。"""
    catalog = secret_resolver.user_module_grantable_catalog()

    path, desc = catalog["API_AGGREGATOR_SITE_3_API_KEY"]
    assert path == ("api_aggregator", "site_3", "api_key")
    assert desc == "API 聚合站站点3 API Key"
    assert catalog["RUNNINGHUB_API_KEY"][0] == ("runninghub", "api_key")
    # aliases 接口行为保持不变：只含规范名 → 配置路径
    assert "API_AGGREGATOR_SITE_3_API_KEY" in secret_resolver.user_module_grantable_aliases()


def test_dynamic_secret_read_bypasses_process_cache(monkeypatch):
    """后台更新后，Supervisor 不应继续使用另一个进程里的旧缓存。"""
    from config import config_util
    from model.system_config import SystemConfig, SystemConfigModel

    env = config_util.get_current_env()
    cache_key = f"{env}:huimengi.api_key"
    monkeypatch.setitem(
        config_util._dynamic_config_cache,
        cache_key,
        {"value": "old-cached-secret", "expire_at": float("inf")},
    )
    monkeypatch.setattr(
        SystemConfigModel,
        "get_by_key",
        lambda actual_env, key: SystemConfig(
            env=actual_env,
            config_key=key,
            config_value="fresh-database-secret",
        ),
    )

    result = secret_resolver.resolve_declared_secrets(["HUIMENGI_API_KEY"], {})

    assert result == {"HUIMENGI_API_KEY": "fresh-database-secret"}
    assert config_util._dynamic_config_cache[cache_key]["value"] == "old-cached-secret"


def test_same_name_environment_variable_has_priority(monkeypatch):
    def fail_if_dynamic_config_is_read(_config_path):
        raise AssertionError("环境变量已配置时不应读取动态配置")

    monkeypatch.setattr(secret_resolver, "read_dynamic_secret", fail_if_dynamic_config_is_read)

    result = secret_resolver.resolve_declared_secrets(
        ["RUNNINGHUB_API_KEY"],
        {"RUNNINGHUB_API_KEY": "from-environment"},
    )

    assert result == {"RUNNINGHUB_API_KEY": "from-environment"}


def test_grantable_names_map_to_dynamic_config(monkeypatch):
    calls = []

    def read_dynamic_config(config_path):
        calls.append(config_path)
        return "from-dynamic-config"

    monkeypatch.setattr(secret_resolver, "read_dynamic_secret", read_dynamic_config)

    result = secret_resolver.resolve_declared_secrets(
        ["RUNNINGHUB_API_KEY", "HUIMENGI_API_KEY"],
        {},
    )

    assert result == {
        "RUNNINGHUB_API_KEY": "from-dynamic-config",
        "HUIMENGI_API_KEY": "from-dynamic-config",
    }
    assert calls == [("runninghub", "api_key"), ("huimengi", "api_key")]


def test_removed_legacy_alias_and_untagged_names_do_not_resolve(monkeypatch):
    """旧手写别名 HUIMENG_API_KEY 已删除；未标记配置的规范名也不可解析。"""
    monkeypatch.setattr(
        secret_resolver,
        "read_dynamic_secret",
        lambda _config_path: "must-not-be-used",
    )

    result = secret_resolver.resolve_declared_secrets(
        ["HUIMENG_API_KEY", "ZJT_TOKEN", "PAY_WXPAY_API_KEY"],
        {},
    )

    assert result == {}


def test_unknown_names_only_use_same_name_environment(monkeypatch):
    monkeypatch.setattr(
        secret_resolver,
        "read_dynamic_secret",
        lambda _config_path: "must-not-be-used",
    )

    result = secret_resolver.resolve_declared_secrets(
        ["CUSTOM_PROVIDER_TOKEN", "UNCONFIGURED_TOKEN"],
        {"CUSTOM_PROVIDER_TOKEN": "custom-secret"},
    )

    assert result == {"CUSTOM_PROVIDER_TOKEN": "custom-secret"}


def test_empty_or_invalid_values_are_not_injected(monkeypatch):
    monkeypatch.setattr(secret_resolver, "read_dynamic_secret", lambda _config_path: "  ")

    result = secret_resolver.resolve_declared_secrets(
        ["HUIMENGI_API_KEY", "invalid-name", "", 42],
        {"HUIMENGI_API_KEY": ""},
    )

    assert result == {}


def test_resolver_emits_no_secret_output(monkeypatch, capsys, caplog):
    secret_value = "never-print-this-secret"
    monkeypatch.setattr(secret_resolver, "read_dynamic_secret", lambda _config_path: secret_value)

    result = secret_resolver.resolve_declared_secrets(["RUNNINGHUB_API_KEY"], {})

    assert result["RUNNINGHUB_API_KEY"] == secret_value
    captured = capsys.readouterr()
    assert secret_value not in captured.out
    assert secret_value not in captured.err
    assert secret_value not in caplog.text


def test_runner_env_excludes_business_secrets(monkeypatch):
    monkeypatch.setenv("HUIMENGI_API_KEY", "must-not-leak")
    env = _build_runner_env("token-value")
    assert env["ZJT_MODULE_RUNNER_TOKEN"] == "token-value"
    assert "HUIMENGI_API_KEY" not in env
    assert "must-not-leak" not in env.values()


def test_context_with_secrets_overwrites_caller_payload():
    params = _context_with_secrets(
        {"context": {"job_id": "j", "secrets": {"EXAMPLE_API_KEY": "stale"}}},
        {"EXAMPLE_API_KEY": "fresh"},
    )
    assert params["context"]["secrets"] == {"EXAMPLE_API_KEY": "fresh"}
    assert params["context"]["job_id"] == "j"


def test_runner_with_secrets_keeps_declared_names_only():
    runtime = object.__new__(RunnerRuntime)
    runtime.manifest = SimpleNamespace(
        permissions=SimpleNamespace(secret_names=["HUIMENGI_API_KEY"])
    )
    ctx = DriverContext(
        request_id="r",
        job_id="j",
        module_id="demo.echo",
        module_version="1.0.0",
        code_digest="sha256:" + "a" * 64,
        deadline_unix_ms=1,
        secrets={
            "HUIMENGI_API_KEY": "fresh",
            "OTHER": "nope",
            "RUNNINGHUB_API_KEY": "also-no",
        },
    )
    out = RunnerRuntime._with_secrets(runtime, ctx)
    assert out.secrets == {"HUIMENGI_API_KEY": "fresh"}

    blank = ctx.model_copy(update={"secrets": {"HUIMENGI_API_KEY": "  "}})
    assert RunnerRuntime._with_secrets(runtime, blank).secrets == {}
