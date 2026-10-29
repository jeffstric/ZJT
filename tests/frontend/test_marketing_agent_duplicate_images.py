from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
# 轮询/去重函数已由 marketing_agent.html 内联脚本迁至独立 js（降低 token 消耗），
# 扫描源同步切换
MARKETING_AGENT_JS = ROOT / "web" / "js" / "marketing_agent.js"


def _read_js() -> str:
    return MARKETING_AGENT_JS.read_text(encoding="utf-8")


def test_image_polling_checks_for_existing_generated_image_before_persisting():
    js = _read_js()
    start = js.index("function pollAgentImageStatus")
    end = js.index("// Agent", start)
    function_body = js[start:end]

    assert "hasGeneratedImageResult(projectIds, imageUrls)" in function_body
    assert function_body.index("hasGeneratedImageResult(projectIds, imageUrls)") < function_body.index("replacePendingTask(pollSessionId, 'image_task_submitted'")


def test_loaded_history_dedupes_image_results_and_prefers_publishable_card():
    js = _read_js()
    start = js.index("function normalizeLoadedMessages")
    end = js.index("const selectedDuration", start)
    function_body = js[start:end]

    assert "seenImageUrls" in function_body
    assert "publish-result-btn" in function_body
    assert "generated-image-wrapper" in function_body


def test_agent_video_polling_uses_publishable_result_renderer():
    js = _read_js()
    start = js.index("function pollAgentVideoStatus")
    end = js.index("checkStatus().finally", start)
    function_body = js[start:end]

    assert "buildGeneratedTaskContent('video', tasks)" in function_body
    assert function_body.index("buildGeneratedTaskContent('video', tasks)") < function_body.index("replacePendingTask(pollSessionId, 'video_task_submitted'")
