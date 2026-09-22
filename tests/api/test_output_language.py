"""素材输出语言（output_language）单元测试。

覆盖：
- 常量定义：locale 回落表（zh 系/未知不注入）、长度上限、指令块模板标记
- api/script_writer.resolve_material_output_language：显式选择优先、自动档回落、清洗截断
- append_output_language_instruction：空语言原样返回、注入块格式
- TaskCreateRequest.output_language 字段默认值
"""
from api import script_writer
from api.script_writer import TaskCreateRequest


# ==================== 常量定义 ====================

def test_locale_fallback_table_semantics():
    from config.constant import MATERIAL_LANGUAGE_LOCALE_FALLBACK
    # 英文界面回落 English；zh 系/未知 locale 不在表中（get 回落空串 = 不注入）
    assert MATERIAL_LANGUAGE_LOCALE_FALLBACK.get('en') == 'English'
    assert 'zh-CN' not in MATERIAL_LANGUAGE_LOCALE_FALLBACK
    assert 'zh' not in MATERIAL_LANGUAGE_LOCALE_FALLBACK


def test_instruction_template_markers():
    from config.constant import (
        OUTPUT_LANGUAGE_INSTRUCTION_TEMPLATE, MATERIAL_OUTPUT_LANGUAGE_MAX_LENGTH,
    )
    template = OUTPUT_LANGUAGE_INSTRUCTION_TEMPLATE
    assert template.startswith("\n\n[输出语言要求]")
    assert "{language}" in template
    # 关键规则：口播/画面文字/文案语言、专有名词保留、优先级高于英文提示词规则、PM 传导
    for keyword in ("口播旁白", "店招", "不翻译", "提示词用英文", "task_description"):
        assert keyword in template, f"模板缺少关键规则: {keyword}"
    assert MATERIAL_OUTPUT_LANGUAGE_MAX_LENGTH == 50


# ==================== 解析逻辑（真实实现） ====================

def test_explicit_language_wins_over_locale():
    resolve = script_writer.resolve_material_output_language
    assert resolve("English", "zh-CN") == "English"
    assert resolve("中文", "en") == "中文"
    assert resolve("日本語", None) == "日本語"


def test_auto_mode_falls_back_to_ui_locale():
    resolve = script_writer.resolve_material_output_language
    assert resolve(None, "en") == "English"
    assert resolve("", "en") == "English"
    assert resolve("   ", "en") == "English"


def test_auto_mode_zh_and_unknown_locale_no_injection():
    """zh 系/未知界面语言 + 自动档 = 不注入，维持现状默认中文语境。"""
    resolve = script_writer.resolve_material_output_language
    for ui in ("zh-CN", "zh", "", None, "fr", "ja-JP"):
        assert resolve(None, ui) == ''
        assert resolve("", ui) == ''


def test_custom_language_trimmed_and_truncated():
    resolve = script_writer.resolve_material_output_language
    assert resolve("  Español  ", "zh-CN") == "Español"
    long_lang = "很" * 80
    assert len(resolve(long_lang, "en")) == 50


# ==================== 注入拼接（真实实现） ====================

def test_append_instruction_noop_for_empty_language():
    append = script_writer.append_output_language_instruction
    assert append("写个剧本", "") == "写个剧本"
    assert append("写个剧本", None) == "写个剧本"


def test_append_instruction_injects_block():
    append = script_writer.append_output_language_instruction
    result = append("做一张海报", "English")
    assert result.startswith("做一张海报\n\n[输出语言要求]")
    assert "输出语言为：English" in result
    # 语言名出现于多条规则中（format 全量替换）
    assert "{language}" not in result


# ==================== 请求模型 ====================

def test_task_create_request_output_language_optional():
    req = TaskCreateRequest(message="hi")
    assert req.output_language is None
    assert req.language is None
