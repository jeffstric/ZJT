import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ADMIN_HTML = ROOT / "web" / "admin.html"
ADMIN_JS = ROOT / "web" / "js" / "admin.js"
ADMIN_CSS = ROOT / "web" / "css" / "admin.css"
ZH = ROOT / "web" / "i18n" / "locales" / "zh-CN" / "admin.json"
EN = ROOT / "web" / "i18n" / "locales" / "en" / "admin.json"


REQUIRED_I18N = [
    "queue_backlog_title",
    "queue_name_download_queue",
    "queue_name_generate_video",
    "queue_name_generate_audio",
    "queue_name_async_tasks",
    "queue_name_grid_image",
    "queue_name_script_split",
    "queue_name_pipeline_steps",
    "queue_name_runninghub_slots",
    "queue_name_agent_tasks",
    "queue_level_ok",
    "queue_level_warn",
    "queue_level_danger",
    "queue_hint_stale",
    "queue_hint_zero_progress",
]


def test_admin_dashboard_has_queue_backlog_panel():
    html = ADMIN_HTML.read_text(encoding="utf-8")
    js = ADMIN_JS.read_text(encoding="utf-8")
    css = ADMIN_CSS.read_text(encoding="utf-8")

    assert 'class="queue-backlog-section"' in html
    assert "/api/admin/dashboard/queues" in js
    assert "loadQueueBacklog" in js
    assert "startQueueBacklogPoll" in js
    assert "stopQueueBacklogPoll" in js
    assert "setInterval(() => {" in js
    assert ".queue-backlog-grid" in css
    assert ".queue-card.danger" in css


def test_queue_backlog_i18n_keys():
    zh = json.loads(ZH.read_text(encoding="utf-8"))
    en = json.loads(EN.read_text(encoding="utf-8"))
    for key in REQUIRED_I18N:
        assert key in zh, key
        assert key in en, key
        assert zh[key].strip()
        assert en[key].strip()
