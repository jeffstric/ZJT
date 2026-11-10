"""Agent 上传接口 session_id 目录穿越校验（issue 2869，2026-11-10 修复）。

session_id 由表单字段直接拼入 upload/marketing/{pic,video,audio}/{session_id}/
存储路径，未校验时 ``../../evil`` 可穿越出 upload 树（Windows 带盘符值经
os.path.join 直接落绝对路径），构成任意目录写盘。三接口入口统一走
``_validate_session_id``——仅接受标准 36 位 UUID（会话创建即
``str(uuid.uuid4())``），非法 400 且不触碰文件/配置/落盘逻辑。
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.responses import JSONResponse

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api import script_writer


VALID = "3f2a8a5e-1c9b-4f7d-9a2e-6b8d0c1e2f3a"


@pytest.mark.parametrize("bad", [
    "",
    "../../evil",
    "..\\..\\evil",
    "C:/windows/temp",
    "/abs/path",
    "a" * 36,                                  # 长度对但非 UUID
    "3f2a8a5e1c9b4f7d9a2e6b8d0c1e2f3a",       # 32 位 hex 无连字符（UUID()可解析但非本系统格式）
    f"{VALID}/../../evil",
    f" {VALID}",
    f"{VALID} ",
    "%2e%2e%2f",
    None,
    123,
])
def test_validate_rejects_non_uuid(bad):
    assert script_writer._validate_session_id(bad) is False


def test_validate_accepts_standard_uuid():
    assert script_writer._validate_session_id(VALID) is True


def _make_file():
    f = MagicMock()
    f.filename = "clip.mp4"
    return f


_ENDPOINTS = [
    ("upload_agent_image", ".jpg"),
    ("upload_agent_video", ".mp4"),
    ("upload_agent_audio", ".mp3"),
]


@pytest.mark.parametrize("fn_name,ext", _ENDPOINTS)
def test_endpoints_reject_traversal_session_before_any_io(fn_name, ext):
    """非法 session_id 必须在扩展名校验/文件读取/落盘之前 400 短路"""
    endpoint = getattr(script_writer, fn_name).__wrapped__
    upload = _make_file()
    upload.filename = f"x{ext}"
    result = asyncio.run(endpoint(MagicMock(), upload, "../../evil"))
    assert isinstance(result, JSONResponse)
    assert result.status_code == 400
    upload.read.assert_not_called()


@pytest.mark.parametrize("fn_name,ext", _ENDPOINTS)
def test_endpoints_pass_valid_session_to_next_gate(fn_name, ext):
    """合法 UUID 放行进入后续校验（这里用非法扩展名挡住，证明未在 session 处拦截）"""
    endpoint = getattr(script_writer, fn_name).__wrapped__
    upload = _make_file()
    upload.filename = "x.exe"
    result = asyncio.run(endpoint(MagicMock(), upload, VALID))
    assert isinstance(result, JSONResponse)
    assert result.status_code == 400
    # 走到的是扩展名白名单（错误文案包含"不支持的文件类型"），而非"无效的会话ID"
    assert "不支持的文件类型" in result.body.decode("utf-8")
