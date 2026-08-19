from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MARKETING_AGENT_HTML = ROOT / "web" / "marketing_agent.html"
MARKETING_AGENT_JS = ROOT / "web" / "js" / "marketing_agent.js"
MARKETING_AGENT_CSS = ROOT / "web" / "css" / "marketing_agent.css"


def _read_html() -> str:
    return MARKETING_AGENT_HTML.read_text(encoding="utf-8")


def _read_js() -> str:
    return MARKETING_AGENT_JS.read_text(encoding="utf-8")


def _read_css() -> str:
    return MARKETING_AGENT_CSS.read_text(encoding="utf-8")


def test_assets_nav_is_enabled_and_switches_to_assets_view():
    html = _read_html()
    nav_start = html.index("{{ $t('nav_assets') }}")
    nav_block = html[html.rfind("<", 0, nav_start):html.find("</", nav_start)]

    assert "not-allowed" not in nav_block
    assert "@click=\"switchView('assets')\"" in html
    assert "activeView === 'assets'" in html


def test_assets_view_loads_ai_tools_history_and_renders_media_results():
    html = _read_html()
    js = _read_js()

    assert "loadAssets" in js
    assert "/api/ai-tools/history" in js
    assert "has_result_url: 'true'" in js
    assert "assetItems" in html
    assert "isAssetVideo" in html
    assert "asset.result_url" in html
    assert "<video" in html
    assert "assetPreviewStyle" in html
    assert '@loadedmetadata="applyAssetVideoAspect"' in html


def test_asset_video_preview_keeps_portrait_frame():
    css = _read_css()
    js = _read_js()

    assert "max-height: 100%" in css
    assert "width: auto" in css
    assert "${parts.w} / ${parts.h}" in js
    assert "video.videoHeight" in js
