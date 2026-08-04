from __future__ import annotations

import io
import logging

from utils.log_sanitizer import (
    RedactingFormatter,
    SensitiveDataFilter,
    install_sensitive_log_redaction,
    mask_email,
    mask_identifier,
    mask_phone,
    redact_sensitive_text,
)


def test_mask_phone_and_email() -> None:
    assert mask_phone("13800138000") == "138****8000"
    assert mask_phone("+86 13800138000") == "+86 138****8000"
    assert mask_email("tester@example.com") == "t***r@example.com"
    assert mask_identifier("13800138000") == "138****8000"
    assert mask_identifier("tester@example.com") == "t***r@example.com"


def test_redact_sensitive_text_covers_credentials() -> None:
    jwt = "eyJhbGciOiJFZERTQSJ9.eyJzdWIiOiIxMjM0NTYifQ.abcdefghijklmnop"
    message = (
        "手机号=13800138000 email=tester@example.com 验证码：123456 "
        "password=secret-value api_token=abcdef0123456789 "
        f"Authorization: Bearer token-value-123456 {jwt}"
    )

    redacted = redact_sensitive_text(message)

    assert "13800138000" not in redacted
    assert "tester@example.com" not in redacted
    assert "123456" not in redacted
    assert "secret-value" not in redacted
    assert "abcdef0123456789" not in redacted
    assert "token-value-123456" not in redacted
    assert jwt not in redacted
    assert "138****8000" in redacted
    assert "t***r@example.com" in redacted


def test_filter_redacts_percent_style_log_arguments() -> None:
    record = logging.LogRecord(
        "test",
        logging.INFO,
        __file__,
        1,
        "用户登录成功: %s",
        ("13800138000",),
        None,
    )

    assert SensitiveDataFilter().filter(record) is True
    assert record.getMessage() == "用户登录成功: 138****8000"
    assert record.args == ("138****8000",)


def test_filter_preserves_uvicorn_access_log_argument_shape() -> None:
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        (
            "127.0.0.1:50000",
            "GET",
            "/api/test?phone=13800138000",
            "1.1",
            200,
        ),
        None,
    )

    assert SensitiveDataFilter().filter(record) is True
    assert isinstance(record.args, tuple)
    assert len(record.args) == 5
    assert record.args[2] == "/api/test?phone=138****8000"


def test_global_factory_and_formatter_redact_messages() -> None:
    install_sensitive_log_redaction()
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(RedactingFormatter("%(message)s"))
    logger = logging.getLogger("test.log-sanitizer")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)

    logger.info(
        "登录标识=%s password=%s",
        "13800138000",
        "unsafe-password",
    )

    output = stream.getvalue()
    assert "13800138000" not in output
    assert "unsafe-password" not in output
    assert "138****8000" in output


def test_formatter_redacts_exception_text() -> None:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(RedactingFormatter("%(message)s"))
    logger = logging.getLogger("test.log-sanitizer.exception")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.ERROR)

    try:
        raise ValueError(
            "手机号=13800138000 password=unsafe-exception-password"
        )
    except ValueError:
        logger.exception("认证异常")

    output = stream.getvalue()
    assert "13800138000" not in output
    assert "unsafe-exception-password" not in output
    assert "138****8000" in output
