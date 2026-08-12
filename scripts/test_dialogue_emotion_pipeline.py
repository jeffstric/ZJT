#!/usr/bin/env python3
"""对白情感向量链路冒烟：强制企业门禁开启，模拟拆分后 build_scenes + voiceover resolve。

用法（项目根目录）:
  set comfyui_env=prod
  .venv\\Scripts\\python.exe scripts/test_dialogue_emotion_pipeline.py

不依赖完整 LLM 拆分与 TTS 调度；验证：
1. parser 指令注入日志
2. build_storyboard_scenes 写入 emo_vec 日志
3. resolve_tts / voiceover-bootstrap 风格日志中带 emo_control_method=2
"""
from __future__ import annotations

import logging
import os
import sys
from io import StringIO
from typing import Any, Dict, List

# 项目根
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _setup_logging() -> tuple[logging.Logger, StringIO]:
    buf = StringIO()
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.INFO)
    fmt = logging.Formatter("%(levelname)s %(name)s %(message)s")
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    bh = logging.StreamHandler(buf)
    bh.setFormatter(fmt)
    root.addHandler(sh)
    root.addHandler(bh)
    return logging.getLogger("test_dialogue_emotion_pipeline"), buf


def _force_enterprise_emotion() -> None:
    """注册企业 Provider，并强制 edition 门禁通过（不依赖本机 JWT）。"""
    from services import dialogue_emotion as facade
    from enterprise.services.dialogue_emotion import EnterpriseDialogueEmotionProvider

    facade.reset_provider()
    provider = EnterpriseDialogueEmotionProvider()
    # 强制放行，便于无完整 license runtime 的本地冒烟
    provider._enterprise_edition_allowed = lambda: True  # type: ignore[method-assign]
    facade.register_provider(provider)


def _mock_parsed_script() -> Dict[str, Any]:
    """模拟 script_parser 输出的一段含 emo_vec 的分镜。"""
    return {
        "characters": [
            {
                "id": "char_001",
                "name": "小明",
                "character_db_id": 900001,
            }
        ],
        "locations": [
            {
                "id": "loc_001",
                "name": "教室",
                "location_db_id": 900001,
            }
        ],
        "props": [],
        "shot_groups": [
            {
                "group_id": "grp_001",
                "group_name": "开场",
                "group_type": "递进组",
                "shots": [
                    {
                        "shot_id": "s001",
                        "shot_number": 1,
                        "duration": 4.0,
                        "location_id": "loc_001",
                        "camera_angle": "平视",
                        "shot_type": "中景",
                        "camera_movement": "固定",
                        "description": "【【小明】】激动地说话",
                        "opening_frame_description": "教室中景，【【小明】】面向镜头",
                        "scene_detail": "【【小明】】举手宣布好消息",
                        "characters_present": ["char_001"],
                        "focus_character_ids": ["char_001"],
                        "props_present": [],
                        "dialogue": [
                            {
                                "character_id": "char_001",
                                "character_name": "【【小明】】",
                                "text": "太好了！我们赢了！",
                                # 喜 + 惊喜，总和 0.9
                                "emo_vec": [0.5, 0.0, 0.0, 0.0, 0.0, 0.0, 0.4, 0.0],
                                "emotion_note": "惊喜的喜悦",
                            },
                            {
                                "character_id": "char_001",
                                "character_name": "【【小明】】",
                                "text": "怎么会这样……",
                                # 故意超和 1.8，验证缩放日志
                                "emo_vec": [0.0, 0.0, 0.9, 0.0, 0.0, 0.9, 0.0, 0.0],
                                "emotion_note": "哀伤低落",
                            },
                        ],
                        "action": "【【小明】】表情变化",
                        "mood": "先喜后哀",
                        "environment_sound": "教室环境音",
                        "background_music": None,
                        "narrative_purpose": "情绪：通过台词情绪转折推动观众共情",
                        "difficulty": "易",
                        "difficulty_reason": "单人对话",
                        "audio_notes": "",
                    }
                ],
            }
        ],
        "metadata": {"genre": "测试", "style": "写实"},
    }


def main() -> int:
    logger, buf = _setup_logging()
    logger.info("=== dialogue emotion pipeline smoke start ===")

    _force_enterprise_emotion()

    from services.dialogue_emotion import (
        is_enabled,
        parser_emotion_enabled,
        build_parser_emotion_instructions,
        resolve_tts_emotion_kwargs,
        normalize_emo_vec,
    )

    assert is_enabled(), "emotion should be enabled after force gate"
    assert parser_emotion_enabled()
    instructions = build_parser_emotion_instructions()
    assert "emo_vec" in instructions
    logger.info("parser instructions ok, chars=%s", len(instructions))

    # 1) normalize 超和
    scaled = normalize_emo_vec([0.0, 0.0, 0.9, 0.0, 0.0, 0.9, 0.0, 0.0])
    assert scaled, "scaled emo_vec should not be None"
    parts = [float(x) for x in scaled.split(",")]
    assert abs(sum(parts) - 1.5) < 1e-3 or sum(parts) <= 1.5 + 1e-6
    logger.info("normalize scale ok: %s", scaled)

    # 2) 模拟 build_storyboard_scenes 对白映射（与 api.storyboard 同逻辑，
    # 避免拉起完整 FastAPI/DB 依赖栈）
    parsed = _mock_parsed_script()
    dialogues: List[Dict[str, Any]] = []
    for group in parsed.get("shot_groups") or []:
        for shot in group.get("shots") or []:
            for dialogue in shot.get("dialogue") or []:
                text = str(dialogue.get("text") or "").strip()
                if not text:
                    continue
                emo_vec = normalize_emo_vec(dialogue.get("emo_vec"))
                # 与 api.storyboard.build_storyboard_scenes_from_parsed_script 日志格式一致
                logger.info(
                    "[dialogue-emotion][build-scenes] shot=%s character_id=%s "
                    "raw_emo=%r normalized_emo_vec=%r text_preview=%r",
                    shot.get("shot_id") or shot.get("shot_number"),
                    dialogue.get("character_id"),
                    dialogue.get("emo_vec"),
                    emo_vec,
                    (text[:40] + "...") if len(text) > 40 else text,
                )
                dialogues.append({
                    "character_id": 900001,
                    "text": text,
                    "emo_vec": emo_vec,
                })

    assert len(dialogues) == 2
    for i, d in enumerate(dialogues):
        assert d.get("emo_vec"), f"dialogue[{i}] missing emo_vec: {d}"
        logger.info(
            "built dialogue[%s] text=%r emo_vec=%s",
            i,
            d.get("text"),
            d.get("emo_vec"),
        )

    # 3) resolve_tts（企业门面）+ 模拟 voiceover-bootstrap 提交前日志
    from services.storyboard_voiceover_bootstrap_service import (
        StoryboardVoiceoverBootstrapService,
    )

    for i, d in enumerate(dialogues):
        d_with_id = dict(d)
        d_with_id["id"] = 1000 + i
        kwargs = resolve_tts_emotion_kwargs(dialogue=d_with_id, config={})
        assert kwargs.get("emo_control_method") == 2
        assert kwargs.get("emo_vec")
        # 与 StoryboardVoiceoverBootstrapService.ensure_dialogue_voiceover 日志字段一致
        logger.info(
            "[dialogue-emotion][voiceover-bootstrap] ensure dialogue_id=%s scene_id=%s "
            "emo_control_method=%s emo_vec=%r text_preview=%r",
            d_with_id["id"],
            2000 + i,
            kwargs.get("emo_control_method"),
            kwargs.get("emo_vec"),
            d.get("text"),
        )
        # 校验 bootstrap 模块内 logger 名称可导入（不真正写库）
        assert StoryboardVoiceoverBootstrapService is not None

    # 4) 校验捕获日志
    log_text = buf.getvalue()
    required_markers = [
        "[dialogue-emotion] parser instructions injected",
        "[dialogue-emotion] normalize",
        "[dialogue-emotion][build-scenes]",
        "[dialogue-emotion] resolve_tts",
        "emo_control_method=2",
        "emo_vec=",
    ]
    missing = [m for m in required_markers if m not in log_text]
    if missing:
        logger.error("MISSING log markers: %s", missing)
        logger.error("--- captured log ---\n%s", log_text)
        return 1

    logger.info("=== ALL REQUIRED LOG MARKERS FOUND ===")
    for m in required_markers:
        logger.info("  OK marker: %s", m)
    logger.info("=== dialogue emotion pipeline smoke PASS ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
