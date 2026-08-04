"""日志敏感信息脱敏工具。

该模块只依赖 Python 标准库，可在应用日志初始化的最早阶段加载。
"""

from __future__ import annotations

import logging
import re
from typing import Any


_PHONE_PATTERN = re.compile(
    r"(?<!\d)(?P<prefix>(?:\+?86[\s-]?)?)"
    r"(?P<head>1[3-9]\d)(?P<middle>\d{4})(?P<tail>\d{4})(?!\d)"
)
_EMAIL_PATTERN = re.compile(
    r"(?<![\w.+-])(?P<local>[\w.+-]+)@"
    r"(?P<domain>[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)"
)
_JWT_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]{8,}"
    r"\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"
)
_BEARER_PATTERN = re.compile(
    r"(?i)\b(Bearer)\s+[A-Za-z0-9._~+/-]{8,}=*"
)
_VERIFY_CODE_PATTERN = re.compile(
    r"((?:验证码|驗證碼|verification[_ -]?code|verify[_ -]?code|"
    r"sms[_ -]?code)\s*[:=：]\s*)[A-Za-z0-9]{4,10}",
    re.IGNORECASE,
)
_SENSITIVE_KEY_VALUE_PATTERN = re.compile(
    r"(?P<prefix>[\"']?(?:password|passwd|pwd|api[_-]?token|"
    r"access[_-]?token|refresh[_-]?token|api[_-]?key|secret|"
    r"authorization)[\"']?\s*[:=]\s*)"
    r"(?P<quote>[\"']?)(?P<value>[^,\s}\"']+)(?P=quote)",
    re.IGNORECASE,
)


def mask_phone(value: str | None) -> str:
    """隐藏大陆手机号中间四位，保留国家码、前三位和后四位。"""
    if value is None:
        return ""
    return _PHONE_PATTERN.sub(
        lambda match: (
            f"{match.group('prefix')}{match.group('head')}"
            f"****{match.group('tail')}"
        ),
        str(value),
    )


def mask_email(value: str | None) -> str:
    """隐藏邮箱本地部分，仅保留首尾字符和域名。"""
    if value is None:
        return ""

    def _replace(match: re.Match[str]) -> str:
        local = match.group("local")
        if len(local) == 1:
            masked_local = f"{local}***"
        else:
            masked_local = f"{local[0]}***{local[-1]}"
        return f"{masked_local}@{match.group('domain')}"

    return _EMAIL_PATTERN.sub(_replace, str(value))


def mask_identifier(value: str | None) -> str:
    """对登录标识（手机号、邮箱或用户名）进行适度脱敏。"""
    if value is None:
        return ""
    text = str(value)
    redacted = mask_email(mask_phone(text))
    if redacted != text:
        return redacted
    if len(text) <= 2:
        return "***"
    return f"{text[0]}***{text[-1]}"


def redact_sensitive_text(value: Any) -> str:
    """对任意日志文本执行统一敏感信息脱敏。"""
    text = str(value)
    text = _BEARER_PATTERN.sub(r"\1 <redacted>", text)
    text = _JWT_PATTERN.sub("<redacted-jwt>", text)
    text = _VERIFY_CODE_PATTERN.sub(r"\1<redacted>", text)
    text = _SENSITIVE_KEY_VALUE_PATTERN.sub(
        lambda match: (
            f"{match.group('prefix')}{match.group('quote')}"
            f"<redacted>{match.group('quote')}"
        ),
        text,
    )
    text = mask_email(text)
    return mask_phone(text)


def _redact_log_argument(value: Any) -> Any:
    """保持日志参数结构，只清理其中可能包含敏感信息的字符串。"""
    if isinstance(value, str):
        return redact_sensitive_text(value)
    if isinstance(value, tuple):
        return tuple(_redact_log_argument(item) for item in value)
    if isinstance(value, list):
        return [_redact_log_argument(item) for item in value]
    if isinstance(value, dict):
        return {
            key: _redact_log_argument(item)
            for key, item in value.items()
        }
    return value


class SensitiveDataFilter(logging.Filter):
    """清理日志模板和参数，同时保留第三方 Formatter 所需结构。"""

    def filter(self, record: logging.LogRecord) -> bool:
        # 带参数的 msg 是格式模板。直接对模板执行 key=value 脱敏可能把
        # ``password=%s`` 改成常量文本，导致占位符数量与 args 不一致。
        # 此时保留模板并清理参数，最终格式化文本由 RedactingFormatter
        # 再做一次完整脱敏；无参数消息则可以立即清理。
        if not record.args:
            record.msg = redact_sensitive_text(record.msg)
        record.args = _redact_log_argument(record.args)
        if record.exc_text:
            record.exc_text = redact_sensitive_text(record.exc_text)
        return True


class RedactingFormatter(logging.Formatter):
    """同时清理普通消息与异常堆栈文本。"""

    def formatException(self, exc_info) -> str:
        return redact_sensitive_text(super().formatException(exc_info))

    def format(self, record: logging.LogRecord) -> str:
        return redact_sensitive_text(super().format(record))


_FILTER = SensitiveDataFilter()


def _attach_filter_to_existing_handlers() -> None:
    loggers = [logging.getLogger()]
    loggers.extend(
        logger
        for logger in logging.Logger.manager.loggerDict.values()
        if isinstance(logger, logging.Logger)
    )
    for logger in loggers:
        for handler in logger.handlers:
            if not any(
                isinstance(item, SensitiveDataFilter)
                for item in handler.filters
            ):
                handler.addFilter(_FILTER)


def install_sensitive_log_redaction() -> None:
    """安装进程级日志脱敏，并兼容已经创建的 Handler。"""
    current_factory = logging.getLogRecordFactory()
    if getattr(current_factory, "_zjt_sensitive_redaction", False):
        _attach_filter_to_existing_handlers()
        return

    def redacting_factory(*args, **kwargs) -> logging.LogRecord:
        record = current_factory(*args, **kwargs)
        _FILTER.filter(record)
        return record

    redacting_factory._zjt_sensitive_redaction = True  # type: ignore[attr-defined]
    logging.setLogRecordFactory(redacting_factory)
    _attach_filter_to_existing_handlers()
