"""把场景描述里的「剧情作用」拆到独立字段。

大模型历史上把剧情功能写在 description 的「剧情作用：…」段落。
保存时自动抽出，避免视觉描述和剧情功能混在一起。
"""
import re
from typing import Optional, Tuple

# 段落标题：中文「剧情作用」或英文 Plot Role / Narrative Role
# 一直吃到下一个「标签：」行或文本结束
PLOT_ROLE_SECTION_RE = re.compile(
    r'(?:^|\n)[ \t]*(?:剧情作用|Plot\s*Role|Narrative\s*Role)[：:][ \t]*(.*?)'
    r'(?=(?:\n[ \t]*[^\s\n：:]{1,20}[：:])|\Z)',
    re.S | re.I,
)


def split_plot_role_from_description(
    description: Optional[str],
    plot_role: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """从 description 抽出剧情作用段落。

    - 已显式传入 plot_role 时以其为准，仍从 description 删掉重复段落。
    - 未传入时，用抽到的段落作为 plot_role。
    - 没有该段落则原样返回。
    """
    desc = (description or '').strip() or None
    existing = (plot_role or '').strip() or None
    if not desc:
        return None, existing

    match = PLOT_ROLE_SECTION_RE.search(desc)
    if not match:
        return desc, existing

    extracted = (match.group(1) or '').strip() or None
    new_desc = (desc[:match.start()] + desc[match.end():]).strip()
    new_desc = re.sub(r'\n{3,}', '\n\n', new_desc).strip() or None
    if existing:
        return new_desc, existing
    return new_desc, extracted
