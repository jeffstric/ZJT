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
    }
    assert review.run(env, opener=opener, sleep=lambda _seconds: None) == "empty"
    assert "没有需要审查的文本 diff" in posted[0]


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
