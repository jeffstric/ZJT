#!/usr/bin/env python3
"""Merge Request 大模型代码审查。

在 GitLab MR Pipeline 中：
1. 用本地 git diff 取本次 MR 的变更（CI_JOB_TOKEN 不能访问 diffs API）
2. 经 jeffS7 会话路由器调用 qwen3.8:27b（默认 http://192.168.10.112:4000，
   按权重分流到 jeffS7:8000 与 jeffS10:8000）
3. 把审查意见发到该 MR 的评论

只依赖 Python 标准库。失败时非 0 退出；CI job 配置 allow_failure，不把流水线打红。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Mapping
from urllib.parse import quote


# 生产 vLLM 集群入口。无 session 键时路由器平滑加权轮询 S7/S10。
# 档案：G:/code/system_config/servers/jeffS7.md
DEFAULT_VLLM_BASE_URL = "http://192.168.10.112:4000"
DEFAULT_VLLM_MODEL = "qwen3.8:27b"

DEFAULT_MAX_DIFF_CHARS = 80_000
DEFAULT_MAX_FILE_CHARS = 20_000
DEFAULT_MAX_FILES = 40
DEFAULT_MAX_TOKENS = 4096
DEFAULT_TEMPERATURE = 0.3
DEFAULT_VLLM_TIMEOUT = 120
DEFAULT_VLLM_PROBE_TIMEOUT = 15
DEFAULT_GITLAB_TIMEOUT = 60
DEFAULT_LLM_ATTEMPTS = 3
# 路由器长时间不回包时，改直连两台 vLLM。非流式接口要等整段生成完才返回状态行，CI 上会读超时。
DIRECT_VLLM_BACKENDS = (
    "http://192.168.10.112:8000",
    "http://192.168.10.243:8000",
)
DEFAULT_GIT_TIMEOUT = 120

COMMENT_MARKER = "<!-- ai-code-review commit:{sha} -->"

SKIP_NAMES = {
    "package-lock.json",
    "uv.lock",
    "yarn.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
}
SKIP_SUFFIXES = (
    ".lock",
    ".min.js",
    ".min.css",
    ".pyc",
    ".pyo",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".mp4",
    ".webm",
    ".mp3",
    ".wav",
    ".zip",
    ".gz",
    ".tgz",
    ".woff",
    ".woff2",
    ".pdf",
    ".exe",
    ".dll",
    ".so",
    ".dylib",
)
SKIP_PATH_PARTS = {
    "node_modules",
    "__pycache__",
    ".git",
    "uv-cache",
}
SKIP_PREFIXES = ("bin/",)


class ReviewError(Exception):
    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


@dataclass
class FileDiff:
    path: str
    status: str
    diff: str
    truncated: bool = False


@dataclass
class HttpResult:
    status: int
    headers: Mapping[str, str]
    body: str


Opener = Callable[[urllib.request.Request, float], Any]


def env_int(env: Mapping[str, str], key: str, default: int) -> int:
    raw = (env.get(key) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ReviewError(f"环境变量 {key} 不是整数: {raw}") from exc


def env_float(env: Mapping[str, str], key: str, default: float) -> float:
    raw = (env.get(key) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ReviewError(f"环境变量 {key} 不是数字: {raw}") from exc


def pick_token(env: Mapping[str, str]) -> tuple[str, str]:
    """优先使用可发评论的项目令牌，否则退回 CI_JOB_TOKEN。"""
    private = (env.get("AI_REVIEW_GITLAB_TOKEN") or "").strip()
    if private:
        return private, "private"
    job = (env.get("CI_JOB_TOKEN") or "").strip()
    if job:
        return job, "job"
    return "", ""


def auth_headers(token: str, token_kind: str) -> dict[str, str]:
    if token_kind == "job":
        return {"JOB-TOKEN": token}
    if token_kind == "private":
        return {"PRIVATE-TOKEN": token}
    raise ReviewError(f"未知令牌类型: {token_kind}")


def redact(text: str, secret: str) -> str:
    if secret and secret in text:
        return text.replace(secret, "***")
    return text


def _header_map(headers: Any) -> dict[str, str]:
    if headers is None:
        return {}
    if hasattr(headers, "items"):
        return {str(k).lower(): str(v) for k, v in headers.items()}
    return {}


def open_http(
    request: urllib.request.Request,
    timeout: float,
    *,
    direct: bool = False,
    opener: Opener | None = None,
) -> HttpResult:
    """发 HTTP 请求。direct=True 时不走 HTTP(S)_PROXY，避免内网 vLLM 被代理送走。"""
    try:
        if opener is not None:
            response = opener(request, timeout)
        elif direct:
            # 必须用关键字 timeout。位置参数会绑到 data，把超时秒数当成请求体。
            response = urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
                request, timeout=timeout
            )
        else:
            response = urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        response = exc
    except urllib.error.URLError as exc:
        raise ReviewError(f"连接失败 {request.full_url}: {exc.reason}", retryable=True) from exc
    except TimeoutError as exc:
        # getresponse() 的读超时不是 URLError，不接住就会变成裸 Traceback，也不会换后端。
        raise ReviewError(f"连接超时 {request.full_url}", retryable=True) from exc
    try:
        raw = response.read()
    except TimeoutError as exc:
        raise ReviewError(f"读取超时 {request.full_url}", retryable=True) from exc
    status = getattr(response, "status", None) or response.getcode()
    body = raw.decode("utf-8", errors="replace")
    closer = getattr(response, "close", None)
    if closer:
        closer()
    return HttpResult(status=int(status), headers=_header_map(getattr(response, "headers", None)), body=body)


def gitlab_request(
    method: str,
    url: str,
    token: str,
    token_kind: str,
    payload: dict | None = None,
    *,
    timeout: float = DEFAULT_GITLAB_TIMEOUT,
    opener: Opener | None = None,
) -> HttpResult:
    """调用 GitLab API。JOB-TOKEN 被拒时，用同一令牌再试 PRIVATE-TOKEN。"""
    header_sets = [auth_headers(token, token_kind)]
    if token_kind == "job":
        header_sets.append({"PRIVATE-TOKEN": token})
    last: HttpResult | None = None
    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    for headers in header_sets:
        req_headers = {"Accept": "application/json", "User-Agent": "zjt-ai-code-review", **headers}
        if data is not None:
            req_headers["Content-Type"] = "application/json; charset=utf-8"
        request = urllib.request.Request(url, data=data, headers=req_headers, method=method)
        result = open_http(request, timeout, opener=opener)
        last = result
        # 未授权端点在 GitLab 上经常是 404 Project Not Found，而不是 401/403。
        # 换一种令牌头再试一次。拒绝时 GET/POST 都不会产生评论。
        if result.status not in (401, 403, 404):
            return result
    assert last is not None
    return last


def project_api(api_base: str, project_id: str) -> str:
    return f"{api_base.rstrip('/')}/projects/{quote(str(project_id), safe='')}"


GitRunner = Callable[[list[str], float], tuple[int, bytes, bytes]]


def _git(args: list[str], timeout: float, runner: GitRunner | None = None) -> tuple[int, bytes, bytes]:
    if runner is not None:
        return runner(args, timeout)
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            timeout=timeout,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
    except FileNotFoundError as exc:
        raise ReviewError("未找到 git，无法在本地生成 diff") from exc
    except subprocess.TimeoutExpired as exc:
        raise ReviewError(f"git 超时: {' '.join(args[:4])}") from exc
    return proc.returncode, proc.stdout or b"", proc.stderr or b""


def _git_ok(args: list[str], timeout: float, runner: GitRunner | None) -> bool:
    code, _, _ = _git(args, timeout, runner)
    return code == 0


def parse_raw_z(blob: bytes) -> list[tuple[str, str, str]]:
    """解析 `git diff --raw -z`。返回 (status, old_path, new_path)。"""
    parts = blob.split(b"\0")
    records: list[tuple[str, str, str]] = []
    index = 0
    while index < len(parts):
        header = parts[index]
        if not header:
            index += 1
            continue
        if not header.startswith(b":"):
            index += 1
            continue
        try:
            status = header.split()[-1].decode("ascii")
        except (IndexError, UnicodeDecodeError):
            index += 1
            continue
        index += 1
        if index >= len(parts) or not parts[index]:
            break
        first_path = parts[index].decode("utf-8", "replace")
        index += 1
        if status[:1] in {"R", "C"}:
            if index >= len(parts):
                break
            second_path = parts[index].decode("utf-8", "replace")
            index += 1
            old_path, new_path = first_path, second_path
        else:
            old_path = new_path = first_path
        records.append((status, old_path, new_path))
    return records


def split_git_diff(text: str) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        if line.startswith("diff --git ") and current:
            chunks.append("\n".join(current))
            current = [line]
        elif line.startswith("diff --git "):
            current = [line]
        elif current:
            current.append(line)
    if current:
        chunks.append("\n".join(current))
    return chunks


def parse_diff_git_header(line: str) -> tuple[str, str]:
    rest = line[len("diff --git "):]

    def take(value: str) -> tuple[str, str]:
        if value.startswith('"'):
            chars: list[str] = []
            index = 1
            while index < len(value):
                if value[index] == "\\" and index + 1 < len(value):
                    chars.append(value[index + 1])
                    index += 2
                    continue
                if value[index] == '"':
                    return "".join(chars), value[index + 1:].lstrip()
                chars.append(value[index])
                index += 1
            return "".join(chars), ""
        token, _, tail = value.partition(" ")
        return token, tail

    old_raw, rest = take(rest)
    new_raw, _ = take(rest)

    def strip_ab(path: str, prefix: str) -> str:
        return path[2:] if path.startswith(prefix) else path

    return strip_ab(old_raw, "a/"), strip_ab(new_raw, "b/")


def diffs_from_git_output(raw_z: bytes, unified: str) -> list[dict]:
    records = parse_raw_z(raw_z)
    chunks = split_git_diff(unified)
    items: list[dict] = []
    if records and len(records) == len(chunks):
        pairs = list(zip(records, chunks))
    else:
        pairs = []
    if pairs:
        for (status, old_path, new_path), chunk in pairs:
            items.append({
                "old_path": old_path,
                "new_path": new_path or old_path,
                "new_file": status.startswith("A"),
                "deleted_file": status.startswith("D"),
                "renamed_file": status[:1] in {"R", "C"},
                "diff": chunk,
            })
        return items
    for chunk in chunks:
        header = chunk.splitlines()[0]
        old_path, new_path = parse_diff_git_header(header)
        preamble = chunk.split("@@", 1)[0]
        items.append({
            "old_path": old_path,
            "new_path": new_path or old_path,
            "new_file": "new file mode " in preamble,
            "deleted_file": "deleted file mode " in preamble,
            "renamed_file": old_path != new_path and "new file mode " not in preamble,
            "diff": chunk,
        })
    return items


def resolve_diff_range(env: Mapping[str, str], runner: GitRunner | None, timeout: float) -> tuple[str, str]:
    head = (env.get("CI_COMMIT_SHA") or "HEAD").strip() or "HEAD"
    base = (env.get("CI_MERGE_REQUEST_DIFF_BASE_SHA") or "").strip()
    target = (env.get("CI_MERGE_REQUEST_TARGET_BRANCH_NAME") or "").strip()
    # 先跟目标分支做 merge-base。CI_MERGE_REQUEST_DIFF_BASE_SHA 有时只是上一次提交，
    # 那样会漏掉本次 MR 里更早的提交。
    if target:
        _git(["git", "fetch", "--depth=500", "origin", target], timeout, runner)
        ref = f"origin/{target}"
        if _git_ok(["git", "cat-file", "-e", f"{ref}^{{commit}}"], timeout, runner):
            code, out, _err = _git(["git", "merge-base", ref, head], timeout, runner)
            merged = out.decode("utf-8", "replace").strip()
            if code == 0 and merged:
                return merged, head
    if base and _git_ok(["git", "cat-file", "-e", f"{base}^{{commit}}"], timeout, runner):
        return base, head
    if base:
        _git(["git", "fetch", "--depth=200", "origin", base], timeout, runner)
        if _git_ok(["git", "cat-file", "-e", f"{base}^{{commit}}"], timeout, runner):
            return base, head
    if _git_ok(["git", "cat-file", "-e", "HEAD~1^{commit}"], timeout, runner):
        print("未找到 MR diff base，退回与 HEAD~1 比较", file=sys.stderr)
        return "HEAD~1", head
    raise ReviewError("无法确定 MR diff 基线")


def load_git_diffs(
    env: Mapping[str, str],
    runner: GitRunner | None = None,
    timeout: float = DEFAULT_GIT_TIMEOUT,
) -> list[dict]:
    base, head = resolve_diff_range(env, runner, timeout)
    code, raw, err = _git(
        ["git", "diff", "--raw", "--find-renames", "-z", base, head],
        timeout,
        runner,
    )
    if code != 0:
        raise ReviewError(f"git diff --raw 失败: {err.decode('utf-8', 'replace')[:300]}")
    code, unified, err = _git(
        ["git", "diff", "--find-renames", "--no-color", "--unified=3", base, head],
        timeout,
        runner,
    )
    if code != 0:
        raise ReviewError(f"git diff 失败: {err.decode('utf-8', 'replace')[:300]}")
    print(f"本地 git diff: {base[:12]}..{str(head)[:12]}")
    return diffs_from_git_output(raw, unified.decode("utf-8", "replace"))


def load_raw_diffs(
    env: Mapping[str, str],
    api_base: str,
    project_id: str,
    iid: str,
    token: str,
    token_kind: str,
    *,
    timeout: float,
    opener: Opener | None = None,
    runner: GitRunner | None = None,
) -> list[dict]:
    """MR Pipeline 优先用本地 git。CI_JOB_TOKEN 访问 /diffs 会得到 404 Project Not Found。"""
    source = (env.get("AI_REVIEW_DIFF_SOURCE") or "").strip().lower()
    base = (env.get("CI_MERGE_REQUEST_DIFF_BASE_SHA") or "").strip()
    if source != "api" and (source == "git" or base):
        try:
            return load_git_diffs(env, runner=runner, timeout=env_int(env, "AI_REVIEW_GIT_TIMEOUT", DEFAULT_GIT_TIMEOUT))
        except ReviewError as exc:
            print(f"本地 git diff 失败，改用 GitLab API: {exc}", file=sys.stderr)
            if source == "git":
                raise
    return fetch_mr_diffs(
        api_base, project_id, iid, token, token_kind, timeout=timeout, opener=opener
    )


def fetch_mr_diffs(
    api_base: str,
    project_id: str,
    iid: str,
    token: str,
    token_kind: str,
    *,
    timeout: float = DEFAULT_GITLAB_TIMEOUT,
    opener: Opener | None = None,
    max_pages: int = 10,
) -> list[dict]:
    diffs: list[dict] = []
    page = 1
    while page <= max_pages:
        url = (
            f"{project_api(api_base, project_id)}/merge_requests/{quote(str(iid), safe='')}"
            f"/diffs?per_page=100&page={page}"
        )
        result = gitlab_request("GET", url, token, token_kind, timeout=timeout, opener=opener)
        if result.status != 200:
            raise ReviewError(
                f"拉取 MR diff 失败 HTTP {result.status}: {redact(result.body[:500], token)}"
            )
        batch = json.loads(result.body)
        if not isinstance(batch, list):
            raise ReviewError("GitLab diffs 响应不是列表")
        diffs.extend(batch)
        if len(batch) < 100:
            break
        next_page = (result.headers.get("x-next-page") or "").strip()
        page = int(next_page) if next_page else page + 1
    return diffs


def fetch_notes(
    api_base: str,
    project_id: str,
    iid: str,
    token: str,
    token_kind: str,
    *,
    timeout: float = DEFAULT_GITLAB_TIMEOUT,
    opener: Opener | None = None,
) -> list[dict] | None:
    """拉取最近评论。失败时返回 None，调用方继续发评论。"""
    url = (
        f"{project_api(api_base, project_id)}/merge_requests/{quote(str(iid), safe='')}"
        "/notes?sort=desc&per_page=50"
    )
    result = gitlab_request("GET", url, token, token_kind, timeout=timeout, opener=opener)
    if result.status != 200:
        return None
    try:
        notes = json.loads(result.body)
    except json.JSONDecodeError:
        return None
    if not isinstance(notes, list):
        return None
    return notes


def already_reviewed(notes: list[dict] | None, sha: str) -> bool:
    if not notes or not sha:
        return False
    marker = COMMENT_MARKER.format(sha=sha)
    return any(marker in (note.get("body") or "") for note in notes)


def skip_reason(path: str) -> str | None:
    norm = path.replace("\\", "/").lstrip("./")
    base = norm.rsplit("/", 1)[-1]
    parts = set(norm.split("/"))
    if norm.startswith(SKIP_PREFIXES) or parts & SKIP_PATH_PARTS:
        return "依赖或缓存目录"
    if base in SKIP_NAMES or norm.endswith(".lock"):
        return "锁文件"
    for suffix in SKIP_SUFFIXES:
        if base.endswith(suffix):
            return "二进制或生成文件"
    return None


def file_status(item: dict) -> str:
    old_path = item.get("old_path") or ""
    new_path = item.get("new_path") or old_path
    if item.get("new_file"):
        return "新增"
    if item.get("deleted_file"):
        return "删除"
    if item.get("renamed_file") and old_path and old_path != new_path:
        return f"重命名 {old_path}"
    return "修改"


def select_diffs(
    raw_files: list[dict],
    *,
    max_files: int = DEFAULT_MAX_FILES,
    max_file_chars: int = DEFAULT_MAX_FILE_CHARS,
    max_total_chars: int = DEFAULT_MAX_DIFF_CHARS,
) -> tuple[list[FileDiff], list[str]]:
    included: list[FileDiff] = []
    omitted: list[str] = []
    used = 0
    for item in raw_files:
        path = (item.get("new_path") or item.get("old_path") or "").replace("\\", "/")
        if not path:
            continue
        reason = skip_reason(path)
        if reason:
            omitted.append(f"{path}（{reason}）")
            continue
        diff = item.get("diff") or ""
        if not diff.strip():
            label = "GitLab 未返回正文" if item.get("too_large") or item.get("collapsed") else "无文本 diff"
            omitted.append(f"{path}（{label}）")
            continue
        if len(included) >= max_files:
            omitted.append(f"{path}（超过文件数上限）")
            continue
        truncated = False
        remaining = max_total_chars - used
        if remaining <= 0:
            omitted.append(f"{path}（超过总长度上限）")
            continue
        limit = min(max_file_chars, remaining)
        if len(diff) > limit:
            diff = diff[:limit]
            truncated = True
        used += len(diff)
        included.append(FileDiff(path=path, status=file_status(item), diff=diff, truncated=truncated))
    return included, omitted


SYSTEM_PROMPT = """你是智剧通（comfyui_server）仓库的代码审查员。只根据用户给出的 Merge Request diff 审查，用中文 Markdown 回答。

优先指出会在运行时出错或造成数据/安全问题的点：
- 逻辑错误、异常被吞、空值、条件写反
- 不可信文本直接拼进 HTML；auth_token 出现在 URL 查询参数
- 异步接口里调用同步阻塞（如 requests）；Future.result() 没有 timeout；用 with ThreadPoolExecutor() 包装 asyncio.run
- 函数体内 import 了该函数更早已经引用的名字（UnboundLocalError）
- 新增迁移脚本不符合 no_<N>_<YYYYMMDD>_描述.py，或会让 alembic 出现多个 head
- 给 execute_tool 增加关键字参数时没有同步所有实现
- 视频工作流新增节点没有考虑重新加载后复原

输出格式固定为：
## 结论
一句话。没有必须修改的问题时明确写「未发现必须修改的问题」。
## 问题
没有问题就写「无」。有问题时每条包含严重级别（高/中/低）、文件位置、说明、建议。
## 测试建议
一两句。

只讨论 diff 里看得到的代码。不要评价命名、格式、锁文件，不要复述 diff，不要输出思考过程。"""


def build_messages(title: str, source: str, target: str, description: str, files: list[FileDiff], omitted: list[str]) -> list[dict]:
    parts = [
        f"标题: {title or '（无标题）'}",
        f"分支: {source or '?'} -> {target or '?'}",
    ]
    desc = (description or "").strip()
    if desc:
        parts.append("描述:\n" + desc[:2000])
    if omitted:
        parts.append("未纳入审查的文件:\n" + "\n".join(f"- {item}" for item in omitted[:80]))
    parts.append("")
    for item in files:
        note = "（该文件 diff 已截断）" if item.truncated else ""
        parts.append(f"### {item.path}（{item.status}）{note}")
        parts.append("```diff")
        parts.append(item.diff)
        parts.append("```")
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(parts)},
    ]


_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCE_RE = re.compile(r"^```(?:markdown|md)?\s*\n(.*)\n```$", re.DOTALL)


def strip_model_wrapper(text: str) -> str:
    cleaned = _THINK_RE.sub("", text or "").strip()
    fenced = _FENCE_RE.match(cleaned)
    if fenced:
        cleaned = fenced.group(1).strip()
    return cleaned


def parse_sse(body: str) -> tuple[str, dict]:
    """解析 vLLM 流式输出。思考片段不写进评论，只有正文为空时才回退。"""
    content: list[str] = []
    reasoning: list[str] = []
    usage: dict = {}
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if not data or data == "[DONE]":
            continue
        try:
            event = json.loads(data)
        except json.JSONDecodeError:
            continue
        if isinstance(event.get("usage"), dict):
            usage = event["usage"]
        for choice in event.get("choices") or []:
            delta = choice.get("delta") or {}
            if delta.get("content"):
                content.append(delta["content"])
            piece = delta.get("reasoning_content") or delta.get("reasoning") or ""
            if piece:
                reasoning.append(piece)
            message = choice.get("message") or {}
            if message.get("content"):
                content.append(message["content"])
    text = strip_model_wrapper("".join(content))
    if not text:
        text = strip_model_wrapper("".join(reasoning))
    if not text:
        raise ReviewError("vLLM 返回空审查内容", retryable=True)
    return text, usage


def parse_vllm_body(body: str) -> tuple[str, dict]:
    stripped = body.lstrip()
    if stripped.startswith("data:"):
        return parse_sse(body)
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ReviewError(f"vLLM 响应不是 JSON: {body[:300]}") from exc
    return extract_review_text(parsed)


def extract_review_text(payload: dict) -> tuple[str, dict]:
    choices = payload.get("choices") or []
    if not choices:
        raise ReviewError("vLLM 响应没有 choices")
    message = choices[0].get("message") or {}
    content = strip_model_wrapper(message.get("content") or "")
    if not content:
        content = strip_model_wrapper(
            message.get("reasoning_content") or message.get("reasoning") or ""
        )
    if not content:
        raise ReviewError("vLLM 返回空审查内容")
    usage = payload.get("usage") or {}
    return content, usage


def probe_vllm(base_url: str, timeout: float, *, opener: Opener | None = None) -> None:
    """短超时确认路由器可达。生成请求的超时要长得多，连不上时不能干等。"""
    url = f"{base_url.rstrip('/')}/v1/models"
    request = urllib.request.Request(url, headers={"User-Agent": "zjt-ai-code-review"}, method="GET")
    result = open_http(request, timeout, direct=True, opener=opener)
    if result.status != 200:
        raise ReviewError(f"vLLM 探针 HTTP {result.status}: {result.body[:300]}", retryable=True)


def call_vllm_once(
    base_url: str,
    model: str,
    messages: list[dict],
    *,
    timeout: float,
    max_tokens: int,
    temperature: float,
    opener: Opener | None = None,
) -> tuple[str, dict]:
    url = f"{base_url.rstrip('/')}/v1/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Authorization": "Bearer vllm",
            "User-Agent": "zjt-ai-code-review",
        },
        method="POST",
    )
    result = open_http(request, timeout, direct=True, opener=opener)
    if result.status >= 500 or result.status == 429:
        raise ReviewError(f"vLLM HTTP {result.status}: {result.body[:500]}", retryable=True)
    if result.status != 200:
        raise ReviewError(f"vLLM HTTP {result.status}: {result.body[:500]}", retryable=False)
    return parse_vllm_body(result.body)


def vllm_candidates(base_url: str, limit: int) -> list[str]:
    seen: list[str] = []
    for url in (base_url, *DIRECT_VLLM_BACKENDS):
        item = (url or "").strip().rstrip("/")
        if item and item not in seen:
            seen.append(item)
        if len(seen) >= limit:
            break
    return seen


def call_vllm(
    base_url: str,
    model: str,
    messages: list[dict],
    *,
    timeout: float,
    max_tokens: int,
    temperature: float,
    attempts: int = DEFAULT_LLM_ATTEMPTS,
    opener: Opener | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[str, dict]:
    urls = vllm_candidates(base_url, max(1, attempts))
    last: ReviewError | None = None
    for attempt, url in enumerate(urls, start=1):
        print(f"调用 vLLM {url} ({attempt}/{len(urls)})", flush=True)
        try:
            return call_vllm_once(
                url,
                model,
                messages,
                timeout=timeout,
                max_tokens=max_tokens,
                temperature=temperature,
                opener=opener,
            )
        except ReviewError as exc:
            last = exc
            if not exc.retryable or attempt == len(urls):
                raise
            print(f"vLLM 调用失败，换下一个地址 ({attempt}/{len(urls)}): {exc}", file=sys.stderr, flush=True)
            sleep(3)
    assert last is not None
    raise last


def format_note(
    review: str,
    *,
    sha: str,
    model: str,
    base_url: str,
    file_count: int,
    omitted_count: int,
    usage: dict,
) -> str:
    body = review.strip()
    if len(body) > 30_000:
        body = body[:30_000] + "\n\n（审查正文过长，已截断）"
    prompt_tokens = usage.get("prompt_tokens", "?")
    completion_tokens = usage.get("completion_tokens", "?")
    short_sha = (sha or "")[:12]
    footer = (
        f"\n\n---\n"
        f"自动审查，仅供参考，不阻塞合并。"
        f"模型 `{model}`，路由 `{base_url}`（jeffS7 / jeffS10），"
        f"commit `{short_sha}`，审查文件 {file_count} 个，跳过 {omitted_count} 个，"
        f"tokens {prompt_tokens}/{completion_tokens}。"
    )
    return COMMENT_MARKER.format(sha=sha) + "\n\n" + body + footer


def post_note(
    api_base: str,
    project_id: str,
    iid: str,
    token: str,
    token_kind: str,
    body: str,
    *,
    timeout: float = DEFAULT_GITLAB_TIMEOUT,
    opener: Opener | None = None,
) -> None:
    url = f"{project_api(api_base, project_id)}/merge_requests/{quote(str(iid), safe='')}/notes"
    result = gitlab_request(
        "POST",
        url,
        token,
        token_kind,
        {"body": body},
        timeout=timeout,
        opener=opener,
    )
    if result.status not in (200, 201):
        hint = ""
        if result.status in (401, 403, 404) and token_kind == "job":
            hint = (
                " CI_JOB_TOKEN 不能创建 MR 评论（GitLab 对未开放端点返回 404 Project Not Found）。"
                "请在 CI/CD Variables 配置 AI_REVIEW_GITLAB_TOKEN（项目 Access Token，api 范围，Developer）。"
            )
        raise ReviewError(
            f"发表 MR 评论失败 HTTP {result.status}: {redact(result.body[:500], token)}.{hint}"
        )


def run(
    env: Mapping[str, str] | None = None,
    *,
    opener: Opener | None = None,
    sleep: Callable[[float], None] = time.sleep,
    command_runner: GitRunner | None = None,
) -> str:
    env = os.environ if env is None else env
    api_base = (env.get("CI_API_V4_URL") or env.get("GITLAB_API_URL") or "").strip()
    project_id = (env.get("CI_PROJECT_ID") or env.get("GITLAB_PROJECT_ID") or "").strip()
    iid = (env.get("CI_MERGE_REQUEST_IID") or env.get("GITLAB_MR_IID") or "").strip()
    sha = (env.get("CI_COMMIT_SHA") or "").strip()
    if not api_base or not project_id or not iid:
        raise ReviewError(
            "缺少 CI_API_V4_URL / CI_PROJECT_ID / CI_MERGE_REQUEST_IID，仅在 Merge Request Pipeline 中运行"
        )
    token, token_kind = pick_token(env)
    if not token:
        raise ReviewError("缺少 AI_REVIEW_GITLAB_TOKEN 与 CI_JOB_TOKEN，无法读取 diff 或发表评论")

    gitlab_timeout = env_int(env, "AI_REVIEW_GITLAB_TIMEOUT", DEFAULT_GITLAB_TIMEOUT)
    notes = fetch_notes(api_base, project_id, iid, token, token_kind, timeout=gitlab_timeout, opener=opener)
    if already_reviewed(notes, sha):
        print(f"同一 commit {sha[:12]} 已有审查评论，跳过")
        return "skipped"

    raw_diffs = load_raw_diffs(
        env,
        api_base,
        project_id,
        iid,
        token,
        token_kind,
        timeout=gitlab_timeout,
        opener=opener,
        runner=command_runner,
    )
    files, omitted = select_diffs(
        raw_diffs,
        max_files=env_int(env, "AI_REVIEW_MAX_FILES", DEFAULT_MAX_FILES),
        max_file_chars=env_int(env, "AI_REVIEW_MAX_FILE_CHARS", DEFAULT_MAX_FILE_CHARS),
        max_total_chars=env_int(env, "AI_REVIEW_MAX_DIFF_CHARS", DEFAULT_MAX_DIFF_CHARS),
    )
    print(f"diff 文件 {len(raw_diffs)} 个，纳入审查 {len(files)} 个，跳过 {len(omitted)} 个")

    base_url = (env.get("VLLM_BASE_URL") or DEFAULT_VLLM_BASE_URL).strip()
    model = (env.get("VLLM_MODEL") or DEFAULT_VLLM_MODEL).strip()
    if not files:
        note = format_note(
            "本次 MR 没有需要审查的文本 diff。"
            + ("\n\n跳过的文件：\n" + "\n".join(f"- {item}" for item in omitted[:40]) if omitted else ""),
            sha=sha,
            model=model,
            base_url=base_url,
            file_count=0,
            omitted_count=len(omitted),
            usage={},
        )
        post_note(api_base, project_id, iid, token, token_kind, note, timeout=gitlab_timeout, opener=opener)
        print("已发表「无文本 diff」评论")
        return "empty"

    probe_timeout = env_int(env, "AI_REVIEW_PROBE_TIMEOUT", DEFAULT_VLLM_PROBE_TIMEOUT)
    try:
        probe_vllm(base_url, probe_timeout, opener=opener)
    except ReviewError as exc:
        if not exc.retryable:
            raise
        print(f"vLLM 探针失败，准备重试: {exc}", file=sys.stderr)
        sleep(2)
        probe_vllm(base_url, probe_timeout, opener=opener)

    messages = build_messages(
        env.get("CI_MERGE_REQUEST_TITLE") or "",
        env.get("CI_MERGE_REQUEST_SOURCE_BRANCH_NAME") or "",
        env.get("CI_MERGE_REQUEST_TARGET_BRANCH_NAME") or "",
        env.get("CI_MERGE_REQUEST_DESCRIPTION") or "",
        files,
        omitted,
    )
    try:
        review, usage = call_vllm(
            base_url,
            model,
            messages,
            timeout=env_int(env, "AI_REVIEW_VLLM_TIMEOUT", DEFAULT_VLLM_TIMEOUT),
            max_tokens=env_int(env, "AI_REVIEW_MAX_TOKENS", DEFAULT_MAX_TOKENS),
            temperature=env_float(env, "AI_REVIEW_TEMPERATURE", DEFAULT_TEMPERATURE),
            attempts=env_int(env, "AI_REVIEW_LLM_ATTEMPTS", DEFAULT_LLM_ATTEMPTS),
            opener=opener,
            sleep=sleep,
        )
    except ReviewError:
        print("大模型审查失败。已生成的 diff 统计见上方日志。", file=sys.stderr)
        raise
    note = format_note(
        review,
        sha=sha,
        model=model,
        base_url=base_url,
        file_count=len(files),
        omitted_count=len(omitted),
        usage=usage,
    )
    print(note)
    post_note(api_base, project_id, iid, token, token_kind, note, timeout=gitlab_timeout, opener=opener)
    print("已发表 MR 审查评论")
    return "posted"


def main() -> None:
    try:
        run()
    except ReviewError as exc:
        print(f"ai_code_review: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
