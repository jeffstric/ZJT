import importlib.util
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "ai_code_review.py"


def load_review_module():
    spec = importlib.util.spec_from_file_location("ai_code_review", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


review = load_review_module()


class FakeResponse:
    def __init__(self, status, body, headers=None):
        self.status = status
        self._body = body.encode("utf-8") if isinstance(body, str) else body
        self.headers = headers or {}

    def read(self):
        return self._body

    def close(self):
        return None


def test_pick_token_prefers_project_token():
    token, kind = review.pick_token({"AI_REVIEW_GITLAB_TOKEN": "secret", "CI_JOB_TOKEN": "job"})
    assert token == "secret"
    assert kind == "private"
    assert review.auth_headers(token, kind) == {"PRIVATE-TOKEN": "secret"}


def test_pick_token_falls_back_to_job_token():
    token, kind = review.pick_token({"CI_JOB_TOKEN": "job"})
    assert (token, kind) == ("job", "job")
    assert review.auth_headers(token, kind) == {"JOB-TOKEN": "job"}


def test_skip_reason_filters_vendor_and_lockfiles():
    assert review.skip_reason("uv.lock") == "锁文件"
    assert review.skip_reason("web/js/app.min.js") == "二进制或生成文件"
    assert review.skip_reason("pkg/__pycache__/a.pyc") == "依赖或缓存目录"
    assert review.skip_reason("bin/ffmpeg/ffmpeg.exe") == "依赖或缓存目录"
    assert review.skip_reason("api/storyboard.py") is None


def test_select_diffs_skips_and_truncates():
    raw = [
        {"new_path": "package-lock.json", "diff": "+lock"},
        {"new_path": "api/a.py", "diff": "+" + ("x" * 50)},
        {"new_path": "api/b.py", "diff": "+" + ("y" * 50)},
        {"new_path": "api/empty.py", "diff": ""},
    ]
    included, omitted = review.select_diffs(raw, max_files=1, max_file_chars=10, max_total_chars=12)
    assert [item.path for item in included] == ["api/a.py"]
    assert included[0].truncated
    assert len(included[0].diff) == 10
    assert any("package-lock.json" in item for item in omitted)
    assert any("超过文件数上限" in item and "api/b.py" in item for item in omitted)
    assert any("api/empty.py" in item for item in omitted)


def test_strip_model_wrapper_removes_think_and_fence():
    text = review.strip_model_wrapper("<think>内部</think>\n```markdown\n## 结论\n无\n```")
    assert text == "## 结论\n无"


def test_extract_review_text_falls_back_to_reasoning():
    text, usage = review.extract_review_text(
        {
            "choices": [{"message": {"content": "", "reasoning_content": "有空指针"}}],
            "usage": {"prompt_tokens": 4, "completion_tokens": 2},
        }
    )
    assert text == "有空指针"
    assert usage["prompt_tokens"] == 4


def test_format_note_marks_commit():
    note = review.format_note(
        "未发现必须修改的问题。",
        sha="abcdef1234567890",
        model="qwen3.8:27b",
        base_url="http://192.168.10.112:4000",
        file_count=1,
        omitted_count=2,
        usage={"prompt_tokens": 9, "completion_tokens": 3},
    )
    assert "<!-- ai-code-review commit:abcdef1234567890 -->" in note
    assert "不阻塞合并" in note
    assert "192.168.10.112:4000" in note


def test_call_vllm_retries_then_reads_content():
    calls = {"n": 0}
    sleeps = []

    def opener(request, timeout):
        calls["n"] += 1
        payload = json.loads(request.data.decode("utf-8"))
        assert payload["chat_template_kwargs"]["enable_thinking"] is False
        assert payload["stream"] is True
        assert payload["model"] == "qwen3.8:27b"
        assert timeout == 12
        if calls["n"] == 1:
            return FakeResponse(500, "overloaded")
        return FakeResponse(
            200,
            json.dumps(
                {"choices": [{"message": {"content": "OK"}}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}},
                ensure_ascii=False,
            ),
        )

    text, usage = review.call_vllm(
        "http://192.168.10.112:4000",
        "qwen3.8:27b",
        [{"role": "user", "content": "hi"}],
        timeout=12,
        max_tokens=32,
        temperature=0.3,
        attempts=2,
        opener=opener,
        sleep=lambda seconds: sleeps.append(seconds),
    )
    assert text == "OK"
    assert usage["completion_tokens"] == 1
    assert sleeps == [3]
    assert calls["n"] == 2


def test_run_posts_review_and_skips_duplicate_commit():
    posted = []
    vllm_calls = {"n": 0}

    def opener(request, timeout):
        url = request.full_url
        method = request.method if hasattr(request, "method") else request.get_method()
        if method == "GET" and "/notes?" in url:
            return FakeResponse(200, "[]")
        if method == "GET" and "/diffs?" in url:
            return FakeResponse(
                200,
                json.dumps(
                    [
                        {"new_path": "api/foo.py", "diff": "@@ -1 +1 @@\n-old\n+new\n"},
                        {"new_path": "uv.lock", "diff": "+lock"},
                    ]
                ),
            )
        if method == "GET" and url.rstrip("/").endswith("/v1/models"):
            return FakeResponse(200, json.dumps({"data": [{"id": "qwen3.8:27b"}]}))
        if url.endswith("/v1/chat/completions"):
            vllm_calls["n"] += 1
            payload = json.loads(request.data.decode("utf-8"))
            assert "api/foo.py" in payload["messages"][1]["content"]
            assert "uv.lock" not in payload["messages"][1]["content"].split("```diff")[-1]
            return FakeResponse(
                200,
                json.dumps(
                    {
                        "choices": [{"message": {"content": "## 结论\n未发现必须修改的问题。\n## 问题\n无"}}],
                        "usage": {"prompt_tokens": 20, "completion_tokens": 12},
                    },
                    ensure_ascii=False,
                ),
            )
        if method == "POST" and url.endswith("/notes"):
            posted.append(json.loads(request.data.decode("utf-8"))["body"])
            return FakeResponse(201, "{}")
        raise AssertionError(f"unexpected {method} {url}")

    env = {
        "CI_API_V4_URL": "https://gitlab.example/api/v4",
        "CI_PROJECT_ID": "7",
        "CI_MERGE_REQUEST_IID": "15",
        "CI_COMMIT_SHA": "abc123def456",
        "CI_JOB_TOKEN": "job-token",
        "CI_MERGE_REQUEST_TITLE": "修复空指针",
        "CI_MERGE_REQUEST_SOURCE_BRANCH_NAME": "fix",
        "CI_MERGE_REQUEST_TARGET_BRANCH_NAME": "develop",
        "AI_REVIEW_DIFF_SOURCE": "api",
        "VLLM_BASE_URL": "http://192.168.10.112:4000",
        "VLLM_MODEL": "qwen3.8:27b",
    }
    assert review.run(env, opener=opener, sleep=lambda _seconds: None) == "posted"
    assert vllm_calls["n"] == 1
    assert len(posted) == 1
    assert "<!-- ai-code-review commit:abc123def456 -->" in posted[0]
    assert "未发现必须修改的问题" in posted[0]

    def opener_duplicate(request, timeout):
        if request.get_method() == "GET" and "/notes?" in request.full_url:
            return FakeResponse(200, json.dumps([{"body": posted[0]}]))
        raise AssertionError("duplicate run should not call the model or post again")

    assert review.run(env, opener=opener_duplicate, sleep=lambda _seconds: None) == "skipped"


def test_run_empty_diff_does_not_call_model():
    posted = []

    def opener(request, timeout):
        method = request.get_method()
        url = request.full_url
        if method == "GET" and "/notes?" in url:
            return FakeResponse(200, "[]")
        if method == "GET" and "/diffs?" in url:
            return FakeResponse(200, json.dumps([{"new_path": "uv.lock", "diff": "+x"}]))
        if url.endswith("/v1/chat/completions"):
            raise AssertionError("empty diff must not call vLLM")
        if method == "POST" and url.endswith("/notes"):
            posted.append(json.loads(request.data.decode("utf-8"))["body"])
            return FakeResponse(201, "{}")
        raise AssertionError(url)

    env = {
        "CI_API_V4_URL": "https://gitlab.example/api/v4",
        "CI_PROJECT_ID": "7",
        "CI_MERGE_REQUEST_IID": "16",
        "CI_COMMIT_SHA": "fff",
        "AI_REVIEW_GITLAB_TOKEN": "private",
        "AI_REVIEW_DIFF_SOURCE": "api",
    }
    assert review.run(env, opener=opener, sleep=lambda _seconds: None) == "empty"
    assert "没有需要审查的文本 diff" in posted[0]


def test_run_comment_failure_degrades_instead_of_failing_job():
    """审查成功但评论 401 时，应返回 post_failed 而不是抛 ReviewError（否则 CI job 打红）。"""
    posted_status = []

    def opener(request, timeout):
        url = request.full_url
        method = request.get_method()
        if method == "GET" and "/notes?" in url:
            return FakeResponse(200, "[]")
        if method == "GET" and "/diffs?" in url:
            return FakeResponse(
                200,
                json.dumps([{"new_path": "api/foo.py", "diff": "@@ -1 +1 @@\n-old\n+new\n"}]),
            )
        if method == "GET" and url.rstrip("/").endswith("/v1/models"):
            return FakeResponse(200, json.dumps({"data": [{"id": "qwen3.8:27b"}]}))
        if url.endswith("/v1/chat/completions"):
            return FakeResponse(
                200,
                json.dumps(
                    {"choices": [{"message": {"content": "## 结论\n未发现必须修改的问题。"}}], "usage": {}},
                    ensure_ascii=False,
                ),
            )
        if method == "POST" and url.endswith("/notes"):
            posted_status.append(401)
            return FakeResponse(401, '{"message":"401 Unauthorized"}')
        raise AssertionError(f"unexpected {method} {url}")

    env = {
        "CI_API_V4_URL": "https://gitlab.example/api/v4",
        "CI_PROJECT_ID": "7",
        "CI_MERGE_REQUEST_IID": "15",
        "CI_COMMIT_SHA": "abc123def456",
        "CI_JOB_TOKEN": "job-token",
        "CI_MERGE_REQUEST_TITLE": "修复空指针",
        "CI_MERGE_REQUEST_SOURCE_BRANCH_NAME": "fix",
        "CI_MERGE_REQUEST_TARGET_BRANCH_NAME": "develop",
        "AI_REVIEW_DIFF_SOURCE": "api",
        "VLLM_BASE_URL": "http://192.168.10.112:4000",
        "VLLM_MODEL": "qwen3.8:27b",
    }
    assert review.run(env, opener=opener, sleep=lambda _seconds: None) == "post_failed"
    # JOB-TOKEN 401 后会用同一令牌换 PRIVATE-TOKEN 再试一次，仍 401 才降级
    assert posted_status == [401, 401]


def test_job_token_header_falls_back_after_401():
    seen = []

    def opener(request, timeout):
        job = request.get_header("Job-token")
        private = request.get_header("Private-token")
        seen.append(job)
        seen.append(private)
        if job:
            return FakeResponse(401, "unauthorized")
        return FakeResponse(200, "[]")

    result = review.gitlab_request(
        "GET",
        "https://gitlab.example/api/v4/projects/1/merge_requests/1/notes?sort=desc&per_page=50",
        "job",
        "job",
        opener=opener,
    )
    assert result.status == 200
    assert any(item == "job" for item in seen)


def test_parse_git_diff_pairs_raw_status_with_patch():
    raw = (
        b":100644 100644 aaa bbb M\0api/foo.py\0"
        b":100644 100644 ccc ddd A\0scripts/ai_code_review.py\0"
    )
    unified = """diff --git a/api/foo.py b/api/foo.py
index aaa..bbb 100644
--- a/api/foo.py
+++ b/api/foo.py
@@ -1 +1 @@
-old
+new
diff --git a/scripts/ai_code_review.py b/scripts/ai_code_review.py
new file mode 100644
--- /dev/null
+++ b/scripts/ai_code_review.py
@@ -0,0 +1 @@
+print('x')
"""
    items = review.diffs_from_git_output(raw, unified)
    assert [item["new_path"] for item in items] == ["api/foo.py", "scripts/ai_code_review.py"]
    assert items[0]["new_file"] is False
    assert items[1]["new_file"] is True
    assert "+new" in items[0]["diff"]


def test_run_uses_local_git_diff_instead_of_diffs_api():
    posted = []
    base = "abc123def4567890"
    raw = b":100644 100644 aaa bbb M\0api/foo.py\0"
    unified = """diff --git a/api/foo.py b/api/foo.py
--- a/api/foo.py
+++ b/api/foo.py
@@ -1 +1 @@
-old
+new
"""

    def command_runner(args, timeout):
        if args[1:3] == ["cat-file", "-e"] and base in args[3]:
            return 0, b"", b""
        if args[1:3] == ["diff", "--raw"]:
            return 0, raw, b""
        if args[1] == "diff":
            return 0, unified.encode("utf-8"), b""
        raise AssertionError(args)

    def opener(request, timeout):
        url = request.full_url
        method = request.get_method()
        if "/diffs?" in url:
            raise AssertionError("job token cannot call diffs API")
        if method == "GET" and "/notes?" in url:
            return FakeResponse(200, "[]")
        if method == "GET" and url.rstrip("/").endswith("/v1/models"):
            return FakeResponse(200, json.dumps({"data": [{"id": "qwen3.8:27b"}]}))
        if url.endswith("/v1/chat/completions"):
            payload = json.loads(request.data.decode("utf-8"))
            assert "api/foo.py" in payload["messages"][1]["content"]
            return FakeResponse(
                200,
                json.dumps(
                    {"choices": [{"message": {"content": "## 结论\n未发现必须修改的问题。"}}], "usage": {}},
                    ensure_ascii=False,
                ),
            )
        if method == "POST" and url.endswith("/notes"):
            posted.append(json.loads(request.data.decode("utf-8"))["body"])
            return FakeResponse(201, "{}")
        raise AssertionError(f"{method} {url}")

    env = {
        "CI_API_V4_URL": "https://gitlab.example/api/v4",
        "CI_PROJECT_ID": "60",
        "CI_MERGE_REQUEST_IID": "781",
        "CI_COMMIT_SHA": "43c856b1abcd",
        "CI_MERGE_REQUEST_DIFF_BASE_SHA": base,
        "CI_JOB_TOKEN": "job-token",
        "VLLM_BASE_URL": "http://192.168.10.112:4000",
        "VLLM_MODEL": "qwen3.8:27b",
    }
    assert review.run(env, opener=opener, sleep=lambda _seconds: None, command_runner=command_runner) == "posted"
    assert "未发现必须修改的问题" in posted[0]


def test_parse_sse_keeps_content_and_skips_reasoning():
    body = """data: {"choices":[{"delta":{"reasoning_content":"先想"}}]}
data: {"choices":[{"delta":{"content":"未发现必须修改的问题"}}]}
data: {"usage":{"prompt_tokens":4,"completion_tokens":2}}
data: [DONE]
"""
    text, usage = review.parse_sse(body)
    assert text == "未发现必须修改的问题"
    assert usage["prompt_tokens"] == 4


def test_call_vllm_treats_read_timeout_as_retryable():
    calls = {"n": 0}

    def opener(request, timeout):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TimeoutError("timed out")
        return FakeResponse(
            200,
            json.dumps({"choices": [{"message": {"content": "OK"}}], "usage": {}}, ensure_ascii=False),
        )

    text, _usage = review.call_vllm(
        "http://192.168.10.112:4000",
        "qwen3.8:27b",
        [{"role": "user", "content": "hi"}],
        timeout=5,
        max_tokens=16,
        temperature=0.3,
        attempts=2,
        opener=opener,
        sleep=lambda _seconds: None,
    )
    assert text == "OK"
    assert calls["n"] == 2


def test_resolve_diff_range_prefers_target_merge_base():
    def runner(args, timeout):
        if args[1] == "fetch":
            return 0, b"", b""
        if args[1:3] == ["cat-file", "-e"] and args[3].startswith("origin/develop"):
            return 0, b"", b""
        if args[1] == "merge-base":
            return 0, b"226f4406aaaa\n", b""
        raise AssertionError(args)

    base, head = review.resolve_diff_range(
        {
            "CI_COMMIT_SHA": "3088da12bbbb",
            "CI_MERGE_REQUEST_DIFF_BASE_SHA": "43c856b1cccc",
            "CI_MERGE_REQUEST_TARGET_BRANCH_NAME": "develop",
        },
        runner,
        5,
    )
    assert base == "226f4406aaaa"
    assert head == "3088da12bbbb"


def test_run_backfills_base_sha_from_mr_detail_when_missing():
    """新 MR 首条 pipeline 没有 CI_MERGE_REQUEST_DIFF_BASE_SHA 时，应从 MR 详情补全并走本地 git。"""
    posted = []
    base = "226f4406aaaabbbb"
    raw = b":100644 100644 aaa bbb M\0api/foo.py\0"
    unified = """diff --git a/api/foo.py b/api/foo.py
--- a/api/foo.py
+++ b/api/foo.py
@@ -1 +1 @@
-old
+new
"""

    def command_runner(args, timeout):
        if args[1:3] == ["cat-file", "-e"] and base in args[3]:
            return 0, b"", b""
        if args[1:3] == ["diff", "--raw"]:
            assert args[-2] == base
            return 0, raw, b""
        if args[1] == "diff":
            return 0, unified.encode("utf-8"), b""
        raise AssertionError(args)

    def opener(request, timeout):
        url = request.full_url
        method = request.get_method()
        if method == "GET" and url.endswith("/merge_requests/781"):
            return FakeResponse(200, json.dumps({"diff_refs": {"base_sha": base}}))
        if "/diffs?" in url:
            raise AssertionError("must use local git instead of diffs API")
        if method == "GET" and "/notes?" in url:
            return FakeResponse(200, "[]")
        if method == "GET" and url.rstrip("/").endswith("/v1/models"):
            return FakeResponse(200, json.dumps({"data": [{"id": "qwen3.8:27b"}]}))
        if url.endswith("/v1/chat/completions"):
            return FakeResponse(
                200,
                json.dumps(
                    {"choices": [{"message": {"content": "## 结论\n未发现必须修改的问题。"}}], "usage": {}},
                    ensure_ascii=False,
                ),
            )
        if method == "POST" and url.endswith("/notes"):
            posted.append(json.loads(request.data.decode("utf-8"))["body"])
            return FakeResponse(201, "{}")
        raise AssertionError(f"unexpected {method} {url}")

    env = {
        "CI_API_V4_URL": "https://gitlab.example/api/v4",
        "CI_PROJECT_ID": "60",
        "CI_MERGE_REQUEST_IID": "781",
        "CI_COMMIT_SHA": "43c856b1abcd",
        "CI_JOB_TOKEN": "job-token",
        "VLLM_BASE_URL": "http://192.168.10.112:4000",
        "VLLM_MODEL": "qwen3.8:27b",
    }
    assert review.run(env, opener=opener, sleep=lambda _seconds: None, command_runner=command_runner) == "posted"
    assert "未发现必须修改的问题" in posted[0]


def test_run_survives_missing_base_and_failed_fetch():
    """MR 详情与 git fetch 都失败时，退到 HEAD~1 也要完成审查，而不是落到 /diffs API 404。"""
    posted = []
    head = "43c856b1abcd"
    raw = b":100644 100644 aaa bbb M\0api/foo.py\0"
    unified = """diff --git a/api/foo.py b/api/foo.py
--- a/api/foo.py
+++ b/api/foo.py
@@ -1 +1 @@
-old
+new
"""

    def command_runner(args, timeout):
        if args[1] == "fetch":
            return 128, b"", b"fatal: Authentication failed for 'https://gitlab.example/group/repo.git/'"
        if args[1:3] == ["cat-file", "-e"]:
            return (0, b"", b"") if args[3] == "HEAD~1^{commit}" else (128, b"", b"error")
        if args[1:3] == ["diff", "--raw"]:
            assert args[-2:] == ["HEAD~1", head]
            return 0, raw, b""
        if args[1] == "diff":
            return 0, unified.encode("utf-8"), b""
        raise AssertionError(args)

    def opener(request, timeout):
        url = request.full_url
        method = request.get_method()
        if method == "GET" and url.endswith("/merge_requests/782"):
            return FakeResponse(404, '{"message":"404 Project Not Found"}')
        if "/diffs?" in url:
            raise AssertionError("must fall back to HEAD~1 instead of diffs API")
        if method == "GET" and "/notes?" in url:
            return FakeResponse(200, "[]")
        if method == "GET" and url.rstrip("/").endswith("/v1/models"):
            return FakeResponse(200, json.dumps({"data": [{"id": "qwen3.8:27b"}]}))
        if url.endswith("/v1/chat/completions"):
            return FakeResponse(
                200,
                json.dumps(
                    {"choices": [{"message": {"content": "## 结论\n未发现必须修改的问题。"}}], "usage": {}},
                    ensure_ascii=False,
                ),
            )
        if method == "POST" and url.endswith("/notes"):
            posted.append(json.loads(request.data.decode("utf-8"))["body"])
            return FakeResponse(201, "{}")
        raise AssertionError(f"unexpected {method} {url}")

    env = {
        "CI_API_V4_URL": "https://gitlab.example/api/v4",
        "CI_PROJECT_ID": "60",
        "CI_MERGE_REQUEST_IID": "782",
        "CI_COMMIT_SHA": head,
        "CI_MERGE_REQUEST_TARGET_BRANCH_NAME": "develop",
        "CI_JOB_TOKEN": "job-token",
        "VLLM_BASE_URL": "http://192.168.10.112:4000",
        "VLLM_MODEL": "qwen3.8:27b",
    }
    assert review.run(env, opener=opener, sleep=lambda _seconds: None, command_runner=command_runner) == "posted"
    assert "未发现必须修改的问题" in posted[0]


def test_probe_falls_through_to_direct_backend_when_router_down():
    """路由器探针失败时轮询直连候选：不得在探针阶段终止（换后端兜底可用）。"""
    vllm_calls = []

    def opener(request, timeout):
        url = request.full_url
        method = request.get_method()
        if method == "GET" and "/notes?" in url:
            return FakeResponse(200, "[]")
        if method == "GET" and "/diffs?" in url:
            return FakeResponse(
                200,
                json.dumps([{"new_path": "api/foo.py", "diff": "@@ -1 +1 @@\n-old\n+new\n"}]),
            )
        if method == "GET" and url.rstrip("/").endswith("/v1/models"):
            if ":4000" in url:
                # 会话路由器整体宕机：5xx（retryable）
                return FakeResponse(502, "bad gateway")
            # 直连后端健康
            return FakeResponse(200, json.dumps({"data": [{"id": "qwen3.8:27b"}]}))
        if url.endswith("/v1/chat/completions"):
            if ":4000" in url:
                # 路由器整体宕机：生成请求同样失败，触发 call_vllm 换后端
                return FakeResponse(502, "bad gateway")
            vllm_calls.append(url)
            return FakeResponse(
                200,
                json.dumps(
                    {
                        "choices": [{"message": {"content": "## 结论\n无\n## 问题\n无"}}],
                        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                    }
                ),
            )
        if method == "POST" and url.endswith("/notes"):
            return FakeResponse(201, "{}")
        raise AssertionError(f"unexpected {method} {url}")

    env = {
        "CI_API_V4_URL": "https://gitlab.example/api/v4",
        "CI_PROJECT_ID": "7",
        "CI_MERGE_REQUEST_IID": "15",
        "CI_COMMIT_SHA": "abc123def456",
        "CI_JOB_TOKEN": "job-token",
        "CI_MERGE_REQUEST_TITLE": "修复探针",
        "CI_MERGE_REQUEST_SOURCE_BRANCH_NAME": "fix",
        "CI_MERGE_REQUEST_TARGET_BRANCH_NAME": "develop",
        "AI_REVIEW_DIFF_SOURCE": "api",
        "VLLM_BASE_URL": "http://192.168.10.112:4000",
        "VLLM_MODEL": "qwen3.8:27b",
    }
    assert review.run(env, opener=opener, sleep=lambda _seconds: None) == "posted"
    # 探针与生成均已落到直连后端
    assert vllm_calls and ":4000" not in vllm_calls[0]


def test_probe_raises_when_all_backends_down():
    """全部候选后端不可达时探针才失败（此时确实无法审查）。"""
    from pytest import raises

    def opener(request, timeout):
        url = request.full_url
        method = request.get_method()
        if method == "GET" and "/notes?" in url:
            return FakeResponse(200, "[]")
        if method == "GET" and "/diffs?" in url:
            return FakeResponse(
                200,
                json.dumps([{"new_path": "api/foo.py", "diff": "@@ -1 +1 @@\n-old\n+new\n"}]),
            )
        if method == "GET" and url.rstrip("/").endswith("/v1/models"):
            return FakeResponse(502, "bad gateway")
        raise AssertionError(f"unexpected {method} {url}")

    env = {
        "CI_API_V4_URL": "https://gitlab.example/api/v4",
        "CI_PROJECT_ID": "7",
        "CI_MERGE_REQUEST_IID": "15",
        "CI_COMMIT_SHA": "abc123def456",
        "CI_JOB_TOKEN": "job-token",
        "CI_MERGE_REQUEST_TITLE": "全挂",
        "CI_MERGE_REQUEST_SOURCE_BRANCH_NAME": "fix",
        "CI_MERGE_REQUEST_TARGET_BRANCH_NAME": "develop",
        "AI_REVIEW_DIFF_SOURCE": "api",
        "VLLM_BASE_URL": "http://192.168.10.112:4000",
        "VLLM_MODEL": "qwen3.8:27b",
    }
    with raises(Exception) as excinfo:
        review.run(env, opener=opener, sleep=lambda _seconds: None)
    assert "502" in str(excinfo.value) or "探针" in str(excinfo.value)


# ==================== 上下文增强（定义骨架 + 符号定位） ====================

def test_python_skeleton_lists_definitions_with_line_numbers():
    content = (
        "import json\n"
        "\n"
        "\n"
        "class A:\n"
        "    def m(self):\n"
        "        local_var = 1\n"
        "\n"
        "TOP = 1\n"
        "# TOP2 = 2\n"
        "def f():\n"
        "    pass\n"
    )
    lines = review.python_skeleton(content)
    joined = "\n".join(lines)
    assert "1: import json" in joined
    assert "4: class A:" in joined
    assert "8: TOP = 1" in joined
    assert "10: def f():" in joined
    # 局部赋值与注释行不进骨架
    assert "local_var" not in joined
    assert "TOP2" not in joined


def test_python_skeleton_truncates_at_budget():
    content = "\n".join(f"def func_{i}():\n    pass\n" for i in range(200))
    lines = review.python_skeleton(content, max_chars=300)
    assert lines[-1] == "…（骨架已截断）"
    assert sum(len(s) + 1 for s in lines[:-1]) <= 300 + len("…（骨架已截断）")


def test_collect_added_identifiers_excludes_diff_resolved_and_stoplist():
    files = [
        review.FileDiff(
            path="api/user.py",
            status="修改",
            diff=(
                "@@ -1,2 +1,5 @@\n"
                " ctx\n"
                "-old\n"
                "+current_locks.pop(task_key, None)\n"
                "+enabled_by_task = {}\n"
                "+logger.info(f\"json {value}\")\n"
            ),
        ),
    ]
    ids = review.collect_added_identifiers(files)
    # diff 内已有定义的 enabled_by_task、停用词 logger/json/value、上下文变量 task_key 不送
    assert "enabled_by_task" not in ids
    assert "logger" not in ids and "json" not in ids and "value" not in ids
    assert "task_key" in ids  # 新增行引用且 diff 内无定义，交给全仓定位核实
    # current_locks 是真实事故案例：diff 内无定义，必须送定位
    assert "current_locks" in ids


def test_locate_symbols_greps_head_and_caps_output():
    captured = {}

    def runner(args, timeout):
        captured["args"] = args
        payload = "\n".join(
            [f"api/user.py:{no}:    current_locks = await asyncio.to_thread(x)" for no in range(1, 100)]
        )
        return 0, payload.encode("utf-8"), b""

    lines = review.locate_symbols(["current_locks"], timeout=5, runner=runner, max_chars=400)

    pattern = captured["args"][captured["args"].index("-E") + 1]
    assert "current_locks" in pattern
    assert captured["args"][-3:] == ["HEAD", "--", "*.py"]
    assert "-E" in captured["args"] and "-nI" in captured["args"]
    joined = "\n".join(lines)
    assert lines[-1] == "…（符号定位已截断）"
    assert len(joined) <= 400 + len("…（符号定位已截断）")


def test_locate_symbols_no_match_returns_empty():
    def runner(args, timeout):
        return 1, b"", b""  # git grep 无匹配退出码 1

    assert review.locate_symbols(["ghost_name"], timeout=5, runner=runner) == []


def test_build_messages_includes_skeleton_and_symbol_sections():
    files = [review.FileDiff(path="api/user.py", status="修改", diff="+x = 1")]
    messages = review.build_messages(
        "t", "s", "target", "",
        files,
        [],
        skeletons={"api/user.py": ["95:     current_locks = await asyncio.to_thread(f)"]},
        symbol_lines=["model/users.py:714:        preferences = parse_implementation_preferences(...)"],
    )
    user_content = messages[1]["content"]
    assert "符号定位（HEAD 全仓" in user_content
    assert "model/users.py:714" in user_content
    assert "定义骨架（行号: 定义行" in user_content
    assert "95:     current_locks" in user_content


def test_build_messages_without_enrichment_still_works():
    files = [review.FileDiff(path="a.py", status="新增", diff="+x = 1")]
    messages = review.build_messages("t", "s", "target", "", files, ["b.lock（锁文件）"])
    user_content = messages[1]["content"]
    assert "符号定位" not in user_content
    assert "定义骨架" not in user_content
    assert "b.lock（锁文件）" in user_content


def test_load_git_diffs_sends_configurable_context_lines():
    base = "226f4406aaaa"
    head = "3088da12bbbb"
    raw = b":100644 100644 aaa bbb M\0api/foo.py\0"
    captured = {}

    def runner(args, timeout):
        if args[1] == "fetch":
            return 0, b"", b""
        if args[1:3] == ["cat-file", "-e"]:
            return 0, b"", b""
        if args[1] == "merge-base":
            return 0, base.encode() + b"\n", b""
        if args[1:3] == ["diff", "--raw"]:
            return 0, raw, b""
        if args[1] == "diff":
            captured["unified"] = [a for a in args if a.startswith("--unified")]
            return 0, b"", b""
        raise AssertionError(args)

    env = {
        "CI_COMMIT_SHA": head,
        "CI_MERGE_REQUEST_TARGET_BRANCH_NAME": "develop",
        "AI_REVIEW_CONTEXT_LINES": "12",
    }
    review.load_git_diffs(env, runner=runner, timeout=5)
    assert captured["unified"] == ["--unified=12"]


def test_run_enrichment_failure_degrades_to_plain_review():
    """增强 git 调用失败（如 fake runner 未覆盖）不阻断审查主流程。"""
    posted = []
    base = "abc123def4567890"
    raw = b":100644 100644 aaa bbb M\0api/foo.py\0"
    unified = "diff --git a/api/foo.py b/api/foo.py\n--- a/api/foo.py\n+++ b/api/foo.py\n@@ -1 +1 @@\n-old\n+new\n"

    def command_runner(args, timeout):
        if args[1] == "fetch":
            return 0, b"", b""
        if args[1:3] == ["cat-file", "-e"]:
            return 0, b"", b""
        if args[1] == "merge-base":
            return 0, base.encode() + b"\n", b""
        if args[1:3] == ["diff", "--raw"]:
            return 0, raw, b""
        if args[1] == "diff":
            return 0, unified.encode("utf-8"), b""
        # git show / git grep 未模拟：抛错走降级路径
        raise AssertionError(args)

    def opener(request, timeout):
        url = request.full_url
        method = request.get_method()
        if method == "GET" and "/notes?" in url:
            return FakeResponse(200, "[]")
        if url.endswith("/v1/models"):
            return FakeResponse(200, json.dumps({"data": [{"id": "qwen3.8:27b"}]}))
        if url.endswith("/v1/chat/completions"):
            payload = json.loads(request.data.decode("utf-8"))
            content = payload["messages"][1]["content"]
            assert "符号定位" not in content  # 降级后无增强段
            assert "api/foo.py" in content
            return FakeResponse(
                200,
                json.dumps({"choices": [{"message": {"content": "## 结论\n未发现必须修改的问题。"}}], "usage": {}}, ensure_ascii=False),
            )
        if method == "POST" and url.endswith("/notes"):
            posted.append(json.loads(request.data.decode("utf-8"))["body"])
            return FakeResponse(201, "{}")
        raise AssertionError(f"{method} {url}")

    env = {
        "CI_API_V4_URL": "https://gitlab.example/api/v4",
        "CI_PROJECT_ID": "60",
        "CI_MERGE_REQUEST_IID": "782",
        "CI_COMMIT_SHA": "43c856b1abcd",
        "CI_MERGE_REQUEST_DIFF_BASE_SHA": base,
        "CI_JOB_TOKEN": "job-token",
        "VLLM_BASE_URL": "http://192.168.10.112:4000",
        "VLLM_MODEL": "qwen3.8:27b",
    }
    assert review.run(env, opener=opener, sleep=lambda _s: None, command_runner=command_runner) == "posted"
    assert "未发现必须修改的问题" in posted[0]
