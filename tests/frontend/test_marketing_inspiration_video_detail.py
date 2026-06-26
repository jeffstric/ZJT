from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
INSPIRATION_HTML = ROOT / "web" / "marketing_inspiration.html"
INSPIRATION_JS = ROOT / "web" / "js" / "marketing_inspiration.js"


def _read_html() -> str:
    return INSPIRATION_HTML.read_text(encoding="utf-8")


def _read_js() -> str:
    return INSPIRATION_JS.read_text(encoding="utf-8")


def test_lightbox_has_dynamic_media_type_and_prompt_label_targets():
    html = _read_html()

    assert 'id="lightboxMediaType"' in html
    assert 'id="lightboxPromptLabel"' in html


def test_open_lightbox_switches_video_media_and_labels():
    js = _read_js()
    start = js.index("function openLightbox")
    end = js.index("function closeLightbox", start)
    function_body = js[start:end]

    assert "data.mediaType === 'video'" in function_body
    assert "document.createElement('video')" in function_body
    assert "lightboxMediaType" in function_body
    assert "lightboxPromptLabel" in function_body
    assert "video_prompt_label" in function_body
    assert "image_prompt_label" in function_body


def test_publication_mapping_can_infer_video_from_result_url():
    js = _read_js()
    start = js.index("function mapPublicationToCard")
    end = js.index("async function loadPublishedInspirations", start)
    function_body = js[start:end]

    assert "inferMediaTypeFromUrl" in js
    assert "inferMediaTypeFromUrl(item.result_url || item.cover_url)" in function_body


def test_inspiration_feed_does_not_use_hardcoded_sample_images():
    js = _read_js()
    html = _read_html()

    assert "const IMAGE_DATA" not in js
    assert "/files/inspiration/img" not in js
    assert "/files/inspiration/img" not in html
    assert "return publishedInspirationData" in js
    assert "IMAGE_DATA" not in js[js.index("function getFeedData"):js.index("function inferMediaTypeFromUrl")]


def test_prompt_enter_submits_without_newline_and_shift_enter_keeps_newline():
    js = _read_js()

    assert "promptInput.addEventListener('keydown'" in js
    assert "e.key === 'Enter' && !e.shiftKey" in js
    assert "e.preventDefault()" in js
    assert "sendBtn.click()" in js


def test_inspiration_send_opens_new_marketing_agent_session():
    inspiration_js = _read_js()
    agent_html = (ROOT / "web" / "marketing_agent.html").read_text(encoding="utf-8")

    assert "params.set('new_session', '1')" in inspiration_js
    assert "const forceNewSession = getUrlParam('new_session') === '1'" in agent_html
    assert "if (forceNewSession) {" in agent_html
    assert agent_html.index("const forceNewSession = getUrlParam('new_session') === '1'") < agent_html.index("if (backendSessions.length > 0)")
