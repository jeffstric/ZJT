from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ADMIN_HTML = ROOT / "web" / "admin.html"
ADMIN_JS = ROOT / "web" / "js" / "admin.js"
ADMIN_CSS = ROOT / "web" / "css" / "admin.css"


def test_admin_marketing_review_video_keeps_portrait_frame():
    html = ADMIN_HTML.read_text(encoding="utf-8")
    js = ADMIN_JS.read_text(encoding="utf-8")
    css = ADMIN_CSS.read_text(encoding="utf-8")

    assert 'class="marketing-review-thumb-wrap"' in html
    assert '@loadedmetadata="applyMarketingReviewVideoAspect"' in html
    assert "applyMarketingReviewVideoAspect" in js
    assert "video.videoHeight" in js
    assert "max-height: 100%" in css
    assert ".marketing-review-thumb-wrap video" in css
    assert "object-fit: contain" in css
