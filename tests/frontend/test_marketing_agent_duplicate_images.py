from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MARKETING_AGENT_HTML = ROOT / "web" / "marketing_agent.html"


def _read_html() -> str:
    return MARKETING_AGENT_HTML.read_text(encoding="utf-8")


def test_image_polling_checks_for_existing_generated_image_before_persisting():
    html = _read_html()
    start = html.index("function pollAgentImageStatus")
    end = html.index("// Agent", start)
    function_body = html[start:end]

    assert "hasGeneratedImageResult(projectIds, imageUrls)" in function_body
    assert function_body.index("hasGeneratedImageResult(projectIds, imageUrls)") < function_body.index("replacePendingTask(pollSessionId, 'image_task_submitted'")


def test_loaded_history_dedupes_image_results_and_prefers_publishable_card():
    html = _read_html()
    start = html.index("function normalizeLoadedMessages")
    end = html.index("const selectedDuration", start)
    function_body = html[start:end]

    assert "seenImageUrls" in function_body
    assert "publish-result-btn" in function_body
    assert "generated-image-wrapper" in function_body


def test_agent_video_polling_uses_publishable_result_renderer():
    html = _read_html()
    start = html.index("function pollAgentVideoStatus")
    end = html.index("checkStatus().finally", start)
    function_body = html[start:end]

    assert "buildGeneratedTaskContent('video', tasks)" in function_body
    assert function_body.index("buildGeneratedTaskContent('video', tasks)") < function_body.index("replacePendingTask(pollSessionId, 'video_task_submitted'")
