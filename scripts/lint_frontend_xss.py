#!/usr/bin/env python3
"""
Static lint for frontend XSS regression (docs/security/xss_stored_chain_fix_plan.md 阶段 5).

Rules:
  X1  error    web/ 下新增 escapeHtml / sanitizeHtml 函数定义
               （转义统一收敛到 web/js/escape.js，净化统一走 web/js/security.js；
               豁免清单内的文件为收敛过渡期的降级实现，只减不增）
  X2  error    marked.parse( 出现在 web/js/security.js 之外
               （markdown 渲染必须经 secureRenderMarkdown/secureSanitize 净化）
  X3  error    URL 拼接 auth_token 参数（token 进 URL 会经 Referer/浏览器历史/
               服务端访问日志泄漏）
  X4  error    HTML 页面 / js 文件内联事件 onclick= 生成于会流经 renderMarkdown 的
               内容模板中（白名单净化会剥掉 on*，点击行为必须走 data-* + 事件委托）
               —— 该规则以 X4 标注豁免清单方式执行：对已知豁免文件之外的
               `onclick="document.getElementById('imgModal'` 模式报错。
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path


WEB_DIRNAME = "web"

# X1 豁免：收敛过渡期的降级实现（只允许引用 window.escapeHtml，不允许新增脱队实现）
X1_ALLOWED_FILES = {
    "web/js/escape.js",              # 权威实现
    "web/js/utils.js",               # Node/Vitest 导出保留本地定义
    "web/js/script_writer.js",       # 保留 \n -> <br> 历史行为
    "web/js/script_writer_library.js",
    "web/js/agent_message_dedupe.js",
    "web/js/security.js",
}

# X2 豁免：净化入口本身，以及「parse 后立即 secureSanitize」的两个合法渲染点
# （marketing_agent 的 renderMarkdown 有前置 URL 预处理，不能直接用 secureRenderMarkdown）
X2_ALLOWED_FILES = {
    "web/js/security.js",
    "web/js/marketing_agent.js",
    "web/js/script_writer.js",
}

# X4 豁免：静态页面自身的内联事件（不流经 renderMarkdown 净化，属页面自有 UI）
X4_ALLOWED_FILES = {
    "web/index.html",
    "web/video_workflow.html",
    "web/video_workflow_list.html",
    "web/script_writer.html",
    "web/storyboard.html",
    "web/storyboard_list.html",
    "web/admin.html",
    "web/marketing_agent.html",
    "web/marketing_inspiration.html",
    "web/computing_power_logs.html",
    "web/external_recharge.html",
    "web/video-viewer.html",
    "web/image_style_guide.html",
    "web/reference_audio_guide.html",
}

X1_DEFINE_RE = re.compile(
    r"\bfunction\s+(?:escapeHtml|escapeHtmlSafe|escapeHtmlLocal|sanitizeHtml)\s*\("
)
X2_MARKED_PARSE_RE = re.compile(r"\bmarked\s*\.\s*parse\s*\(")
X3_URL_TOKEN_RE = re.compile(r"""[?&]auth_token=\$?\{|[?&]auth_token='""")
X4_IMODAL_ONCLICK_RE = re.compile(r"""onclick=["']document\.getElementById\('imgModal'""")


@dataclass(frozen=True)
class Finding:
    rule: str
    path: Path
    line: int
    message: str


def iter_web_files(web_root: Path):
    for path in web_root.rglob("*"):
        if not path.is_file():
            continue
        if "node_modules" in path.parts or "tests" in path.parts or "vendor" in path.parts:
            continue
        if path.suffix in {".js", ".html"}:
            yield path


def check_file(rel: str, path: Path) -> list[Finding]:
    findings: list[Finding] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return findings
    for lineno, line in enumerate(text.splitlines(), start=1):
        if rel in X1_ALLOWED_FILES or rel.replace("\\", "/") in X1_ALLOWED_FILES:
            pass
        elif X1_DEFINE_RE.search(line):
            findings.append(Finding(
                "X1", path, lineno,
                "新增转义/净化函数定义；统一使用 window.escapeHtml / window.secureSanitize"
                "（web/js/escape.js、web/js/security.js）",
            ))
        if rel not in X2_ALLOWED_FILES and X2_MARKED_PARSE_RE.search(line):
            findings.append(Finding(
                "X2", path, lineno,
                "marked.parse 必须在 web/js/security.js 内经过 DOMPurify 净化后使用",
            ))
        if X3_URL_TOKEN_RE.search(line):
            findings.append(Finding(
                "X3", path, lineno,
                "auth_token 拼进 URL（Referer/历史记录/服务端日志泄漏）；改用 Authorization 头",
            ))
        if rel not in X4_ALLOWED_FILES and X4_IMODAL_ONCLICK_RE.search(line):
            findings.append(Finding(
                "X4", path, lineno,
                "生成内容中的 imgModal 内联 onclick 会被 secureSanitize 白名单剥掉；"
                "改用 data-* 属性 + 事件委托",
            ))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="仓库根目录")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    web_root = root / WEB_DIRNAME
    if not web_root.is_dir():
        print(f"error: {web_root} not found", file=sys.stderr)
        return 2

    findings: list[Finding] = []
    for path in iter_web_files(web_root):
        rel = path.relative_to(root).as_posix()
        findings.extend(check_file(rel, path))

    for f in findings:
        print(f"{f.rule} error  {f.path.relative_to(root)}:{f.line}  {f.message}")

    if findings:
        print(f"\n{len(findings)} finding(s)")
        return 1
    print("frontend xss lint: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
