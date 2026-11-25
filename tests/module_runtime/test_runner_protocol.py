"""协议类双模块键防御测试。

真实事故：Runner 以裸名 ``module_runtime.*`` 启动、内部曾用
``module_runtime.*`` 导入，同一 protocol.py 在 Runner 进程内被两个
模块键各加载一份；用户模块按合同用裸名拿到 Accepted 实例，Runner 的 union
校验对实例做类身份判定，三分支全部拒绝，最终只报笼统的 MODULE_CALL_FAILED。

防线：Runner 校验一律先 ``model_dump`` 按结构校验（见 runner._validate_result），
多份类共存不再触发身份拒绝；同时 runner 在 Runner 进程内统一走裸名导入。
"""

import importlib.util
import sys
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from module_runtime.runner import SUBMIT_RESULT_ADAPTER, _validate_result

_PROTOCOL_FILE = (
    Path(__file__).resolve().parents[2] / "module_runtime" / "protocol.py"
)


def _load_bare_protocol():
    """以裸名键直接从文件加载一份 protocol（不经 sys.path，避免 enterprise/
    目录劫持主仓同名命名空间包），模拟 Runner 子进程中的"裸名份"。"""
    spec = importlib.util.spec_from_file_location("module_runtime.protocol", _PROTOCOL_FILE)
    module = importlib.util.module_from_spec(spec)
    sys.modules["module_runtime.protocol"] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop("module_runtime.protocol", None)
        raise
    return module


@pytest.fixture()
def bare_protocol():
    # 主仓版（develop_f1214 起 runner 只走裸名导入）：先用常规键加载一份
    # "常规份"，再以文件加载覆盖裸名键得到"外来份"，两者类身份必然不同，
    # 保留双模块键防御语义（与原 enterprise 前缀键 vs 裸名键同构）。
    import module_runtime.protocol as regular_protocol

    module = _load_bare_protocol()
    yield module, regular_protocol
    sys.modules.pop("module_runtime.protocol", None)


def test_runner_validation_immune_to_duplicate_protocol_classes(bare_protocol):
    """Runner 现行校验（结构 dump 后校验）对"外来份"实例一视同仁。"""
    bare, regular_protocol = bare_protocol

    assert bare.Accepted is not regular_protocol.Accepted
    foreign_accepted = bare.Accepted(
        handle=bare.TaskHandle(external_job_id="job-1"),
        next_poll_after_seconds=10.0,
    )
    validated = _validate_result(SUBMIT_RESULT_ADAPTER, foreign_accepted)
    assert validated.result_type == "accepted"
    assert validated.handle.external_job_id == "job-1"


def test_legacy_instance_validation_rejects_foreign_class_instance(bare_protocol):
    """回归锚点：旧的实例直校验在双份类下必然失败（说明防御是必要的）。"""
    bare, regular_protocol = bare_protocol

    foreign_accepted = bare.Accepted(
        handle=bare.TaskHandle(external_job_id="job-1"),
        next_poll_after_seconds=1.0,
    )
    legacy_adapter = TypeAdapter(regular_protocol.SubmitResult)
    with pytest.raises(ValidationError):
        legacy_adapter.validate_python(foreign_accepted)


def test_validate_result_accepts_plain_dict(bare_protocol):
    """结构化 dict（跨 RPC 的实际载荷形态）始终是合法输入。"""
    bare, _regular = bare_protocol
    payload = bare.Accepted(
        handle=bare.TaskHandle(external_job_id="job-2"),
        next_poll_after_seconds=3.0,
    ).model_dump(mode="json")
    validated = _validate_result(SUBMIT_RESULT_ADAPTER, payload)
    assert validated.result_type == "accepted"
    assert validated.handle.external_job_id == "job-2"
