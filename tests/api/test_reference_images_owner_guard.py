"""
reference-images 端点属主校验守卫（审计 BUG-R2-S2-A8-H3 残余修复）

characters/locations 的 4 个参考图端点（add/delete × 2）此前解析 user_id
但从不使用——X-User-Id 一致性中间件（2026-10-20）挡住了匿名/冒充访问，
但任何登录用户仍可对他人资产增删参考图（IDOR）。本守卫用 AST 静态断言
4 个端点必须同时具备：
1. 身份以 token 解析（resolve_authenticated_user_id，不再裸信 X-User-Id）
2. 资源属主比对（resource.user_id != user_id → 403）
3. HTTPException 透传（不被 except Exception 吞成 500）

server.py 导入副作用大（配置/DB/中间件），无法直接 import 测 handler，
故采用与 tests/utils/test_media_upload.py::TestValidateImageSizeChokePoint
一致的 AST 源码守卫模式。
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

_TARGET_ENDPOINTS = (
    "add_character_reference_images",
    "delete_character_reference_image",
    "add_location_reference_images",
    "delete_location_reference_image",
)


def _get_function(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == name:
            return node
    return None


@pytest.fixture(scope="module")
def server_tree():
    return ast.parse((ROOT / "server.py").read_text(encoding="utf-8"))


@pytest.mark.parametrize("func_name", _TARGET_ENDPOINTS)
def test_reference_images_endpoint_owner_guard(server_tree, func_name):
    func = _get_function(server_tree, func_name)
    assert func is not None, f"server.py 中未找到 {func_name}"

    source_names = {
        n.func.id if isinstance(n.func, ast.Name) else getattr(n.func, "attr", "")
        for n in ast.walk(func)
        if isinstance(n, ast.Call)
    }
    # 1. 身份以 token 解析（X-User-Id 仅一致性参考）
    assert "resolve_authenticated_user_id" in source_names, (
        f"{func_name} 必须用 resolve_authenticated_user_id 解析身份（token 为准）"
    )
    assert "get_user_id_from_header" not in source_names, (
        f"{func_name} 不得再裸信 X-User-Id 头"
    )

    # 2. 属主比对：存在 `xxx.user_id != user_id` 形态的比较
    has_owner_compare = any(
        isinstance(n, ast.Compare)
        and any(
            isinstance(c, ast.NotEq)
            and (
                (
                    isinstance(n.left, ast.Attribute) and n.left.attr == "user_id"
                    and isinstance(n.comparators[0], ast.Name) and n.comparators[0].id == "user_id"
                )
                or (
                    isinstance(n.left, ast.Name) and n.left.id == "user_id"
                    and isinstance(n.comparators[0], ast.Attribute) and n.comparators[0].attr == "user_id"
                )
            )
            for c in n.ops
        )
        for n in ast.walk(func)
    )
    assert has_owner_compare, f"{func_name} 必须比对资源属主（user_id != resource.user_id → 403）"

    # 3. HTTPException 透传，防鉴权 401 被 except Exception 吞成 500
    handlers = [
        h.type.id for h in func.handler
        if isinstance(h.type, ast.Name)
    ] if hasattr(func, "handler") else []
    try_nodes = [n for n in ast.walk(func) if isinstance(n, ast.Try)]
    handler_types = {
        h.type.id
        for t in try_nodes
        for h in t.handlers
        if isinstance(h.type, ast.Name)
    }
    assert "HTTPException" in handler_types, (
        f"{func_name} 必须 except HTTPException: raise（透传鉴权异常）"
    )
