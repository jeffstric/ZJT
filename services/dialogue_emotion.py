"""
对白情感向量（TTS emo_vec）公共门面。

社区版默认实现恒关闭，不解析、不启用情感向量。
企业版通过 register_provider 注入实现；仅许可证 edition=enterprise 时 is_enabled() 为真。

主仓配音/拆分路径禁止直读 dialogue.emo_vec 写进 ai_audio，必须经本门面：
- normalize_emo_vec
- resolve_tts_emotion_kwargs

设计参考：services/face_mask_provider.py、services/branding.py
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Protocol

logger = logging.getLogger(__name__)


class DialogueEmotionProvider(Protocol):
    """Enterprise 实现需满足的最小协议。"""

    available: bool

    def is_enabled(self) -> bool:
        """当前进程/许可证是否启用对白情感向量 TTS。"""
        ...

    def parser_emotion_enabled(self) -> bool:
        """script_parser 是否注入 emo_vec 指令（通常同 is_enabled）。"""
        ...

    def build_parser_emotion_instructions(self) -> str:
        """返回追加到 script_parser 用户提示的情感指令片段。"""
        ...

    def normalize_emo_vec(self, raw: Any) -> Optional[str]:
        """规范化情感向量；非法/全 0 返回 None。"""
        ...

    def resolve_tts_emotion_kwargs(
        self,
        *,
        dialogue: Any = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """返回可并入 AIAudioModel.create 的情感字段；关闭时返回 {}。"""
        ...


class CommunityDialogueEmotionProvider:
    """社区/未注入时的 fail-closed 默认实现。"""

    available = False

    def is_enabled(self) -> bool:
        return False

    def parser_emotion_enabled(self) -> bool:
        return False

    def build_parser_emotion_instructions(self) -> str:
        return ""

    def normalize_emo_vec(self, raw: Any) -> Optional[str]:
        return None

    def resolve_tts_emotion_kwargs(
        self,
        *,
        dialogue: Any = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return {}


_community_provider = CommunityDialogueEmotionProvider()
_provider: DialogueEmotionProvider = _community_provider


def register_provider(provider: DialogueEmotionProvider) -> None:
    """由已通过版本校验的 Enterprise 模块注册真实实现。"""
    if provider is None or not getattr(provider, "available", False):
        raise ValueError("对白情感向量 Provider 必须声明 available=True")
    global _provider
    _provider = provider
    logger.info("[Enterprise] Dialogue emotion provider registered")


def reset_provider() -> None:
    """恢复社区默认实现（enterprise 加载失败回滚 / 测试隔离）。"""
    global _provider
    _provider = _community_provider


def is_available() -> bool:
    """Provider 是否已注入（不等于许可证已放行）。"""
    return bool(getattr(_provider, "available", False))


def is_enabled() -> bool:
    """功能是否对当前许可证可用（前端 features 探查 / 业务门禁）。"""
    try:
        return bool(_provider.is_enabled())
    except Exception:
        logger.exception("dialogue_emotion.is_enabled failed; fail-closed")
        return False


def parser_emotion_enabled() -> bool:
    try:
        return bool(_provider.parser_emotion_enabled())
    except Exception:
        logger.exception("dialogue_emotion.parser_emotion_enabled failed; fail-closed")
        return False


def build_parser_emotion_instructions() -> str:
    try:
        return str(_provider.build_parser_emotion_instructions() or "")
    except Exception:
        logger.exception("dialogue_emotion.build_parser_emotion_instructions failed")
        return ""


def normalize_emo_vec(raw: Any) -> Optional[str]:
    try:
        return _provider.normalize_emo_vec(raw)
    except Exception:
        logger.exception("dialogue_emotion.normalize_emo_vec failed; drop vector")
        return None


def resolve_tts_emotion_kwargs(
    *,
    dialogue: Any = None,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    try:
        result = _provider.resolve_tts_emotion_kwargs(
            dialogue=dialogue, config=config or {},
        )
        return result if isinstance(result, dict) else {}
    except Exception:
        logger.exception("dialogue_emotion.resolve_tts_emotion_kwargs failed; no emo")
        return {}


__all__ = [
    "DialogueEmotionProvider",
    "CommunityDialogueEmotionProvider",
    "register_provider",
    "reset_provider",
    "is_available",
    "is_enabled",
    "parser_emotion_enabled",
    "build_parser_emotion_instructions",
    "normalize_emo_vec",
    "resolve_tts_emotion_kwargs",
]
