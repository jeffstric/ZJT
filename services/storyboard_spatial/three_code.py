"""分镜 three.js 场景代码契约（LLM 直出 three.js 代码方案）。

空间表达载体是每个分镜的 ``three_scene_code`` 字符串（three.js 代码）：

- 空间序列首镜（首个分镜，或场景切换后的第一镜）必须以 ``startScene(...)``
  开头完整构建极简空间（场景体块 + 角色站位 + 机位）；
- 空间关系保持的后续镜必须基于上一镜已创建的对象做增量调整（人物运动等），
  禁止重建场景；
- 每镜必须调用 ``setCamera(...)`` 显式确定镜头位置。

本模块只做字符串级校验与分类（确定性、无 IO、无第三方依赖），社区版与企业版
通用；预览端（web/js/storyboard/spatial_3d_preview.js）按相同约定在沙箱内
顺序重放代码链。
"""

from typing import Any, Dict, List, Optional

# 沙箱 API 标记（与前端 replaySequence 注入的 helper 一一对应，两端需同步修改）
SCENE_START_MARKER = "startScene("
CAMERA_MARKERS = (
    "setCamera(",
    "camera.position.set",
    "camera.position.copy",
)
# 序列首镜必须出现的构建类调用（startScene 之外至少一种）
SCENE_BUILD_MARKERS = (
    "makeActor(",
    "makeProp(",
    "makeStage(",
    "addGround(",
)

MAX_THREE_CODE_CHARS = 8000


def normalize_three_scene_code(raw: Any) -> str:
    """LLM 可能把代码包进 markdown 围栏或带语言标注，剥壳后返回纯代码。"""
    if not isinstance(raw, str):
        return ""
    code = raw.strip()
    if code.startswith("```"):
        first_newline = code.find("\n")
        if first_newline != -1:
            code = code[first_newline + 1:]
        if code.rstrip().endswith("```"):
            code = code.rstrip()[: code.rstrip().rfind("```")]
    return code.strip()


def is_sequence_start_code(code: str) -> bool:
    """序列首镜判定：代码显式调用 startScene(...) 即视为新空间序列起点。

    重放端以同一标记切段，保证判定 100% 可靠（不猜语义）。
    """
    return SCENE_START_MARKER in (code or "")


def _has_camera(code: str) -> bool:
    return any(marker in code for marker in CAMERA_MARKERS)


def _has_scene_build(code: str) -> bool:
    return any(marker in code for marker in SCENE_BUILD_MARKERS)


def audit_three_scene_code(
    code: str,
    *,
    is_first_shot: bool = False,
    previous_code: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """校验单镜 three.js 代码，返回诊断列表（error 表示质检必须重拆）。

    is_first_shot: 空间序列首镜（storyboard 第一镜或场景切换后的第一镜），
    必须完整构建场景并设置机位。
    previous_code: 上一镜代码（同序列内）；非首镜存在增量对象引用时更稳，
    这里只用于提示"上一镜为空时应自建序列"。
    """
    diagnostics: List[Dict[str, Any]] = []
    code = code or ""
    if not code:
        diagnostics.append({
            "code": "three_code_missing",
            "severity": "error",
            "message": "分镜缺少 three_scene_code（每镜必须输出 three.js 场景代码）",
        })
        return diagnostics
    if len(code) > MAX_THREE_CODE_CHARS:
        diagnostics.append({
            "code": "three_code_too_long",
            "severity": "warning",
            "message": f"three_scene_code 超过 {MAX_THREE_CODE_CHARS} 字符，将被截断提示",
        })
    if not _has_camera(code):
        diagnostics.append({
            "code": "three_code_camera_missing",
            "severity": "error",
            "message": "three_scene_code 必须调用 setCamera(...) 显式确定镜头位置",
        })
    starts_sequence = is_sequence_start_code(code)
    if is_first_shot and not starts_sequence:
        diagnostics.append({
            "code": "three_code_scene_build_missing",
            "severity": "error",
            "message": "空间序列首镜必须以 startScene(...) 开始并构建场景与角色站位",
        })
    if starts_sequence and not _has_scene_build(code):
        diagnostics.append({
            "code": "three_code_sequence_start_empty",
            "severity": "error",
            "message": "startScene 后必须用 makeActor/makeStage 等构建角色站位与场景",
        })
    if not is_first_shot and not starts_sequence and previous_code is not None and not previous_code.strip():
        diagnostics.append({
            "code": "three_code_no_upstream_scene",
            "severity": "warning",
            "message": "上一镜无 three_scene_code，本镜增量代码没有可继承的空间基座",
        })
    return diagnostics


def audit_three_scene_codes_for_shots(
    shots: List[Dict[str, Any]],
    *,
    first_shot_starts_sequence: bool = True,
) -> List[Dict[str, Any]]:
    """按镜头顺序校验整段 three.js 代码链（序列起点自动识别）。

    first_shot_starts_sequence：段首镜是否必须以 startScene 自建序列
    （独立段/上游无代码时为 True；继承段且上游带代码时为 False）。
    """
    diagnostics: List[Dict[str, Any]] = []
    previous_code = ""
    pending_sequence_start = bool(first_shot_starts_sequence)
    for index, shot in enumerate(shots or []):
        if not isinstance(shot, dict):
            continue
        code = normalize_three_scene_code(shot.get("three_scene_code"))
        shot_ref = str(shot.get("shot_id") or shot.get("id") or f"shot_{index + 1}")
        issues = audit_three_scene_code(
            code,
            is_first_shot=pending_sequence_start,
            previous_code=previous_code or None,
        )
        for issue in issues:
            item = dict(issue)
            item.setdefault("shot_ref", shot_ref)
            item.setdefault("field", "three_scene_code")
            diagnostics.append(item)
        if code:
            previous_code = code
        # 只要本镜有代码（无论 startScene 还是增量），链持续，下一镜走增量；
        # 本镜缺代码即断链，下一镜必须 startScene 自建序列。
        pending_sequence_start = not bool(code)
    return diagnostics


def build_three_code_preview(three_scene_code: Any) -> Optional[Dict[str, Any]]:
    """组装 /spatial-previews 的 three.js 代码载荷；无代码返回 None。"""
    code = normalize_three_scene_code(three_scene_code)
    if not code:
        return None
    diagnostics = audit_three_scene_code(code)
    return {
        "kind": "three_code",
        "code": code,
        "is_sequence_start": is_sequence_start_code(code),
        "diagnostics": diagnostics,
    }


__all__ = [
    "MAX_THREE_CODE_CHARS",
    "SCENE_START_MARKER",
    "audit_three_scene_code",
    "audit_three_scene_codes_for_shots",
    "build_three_code_preview",
    "is_sequence_start_code",
    "normalize_three_scene_code",
]
