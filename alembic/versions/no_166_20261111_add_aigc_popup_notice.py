"""add aigc popup notice

Revision ID: 20261111_add_aigc_popup_notice
Revises: 20261111_add_announcements_popup
Create Date: 2026-11-11
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
# ⚠️ revision 长度必须 <= 32 字符 (alembic_version.version_num 为 varchar(32))
revision: str = '20261111_add_aigc_popup_notice'
down_revision: Union[str, None] = '20261111_add_announcements_popup'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 全局弹窗公告（popup=1 + published）：所有用户进页强弹窗，须点"我知道了"（已读）
# 后才不再弹（acceptance 语义由 announcement_popup.js 单按钮交互保证）。
# 首个使用场景：AIGC 内容标识规则变更预告（2026-11-11 图片/视频全量纳入 L1，
# 见 docs/compliance/aigc_labeling_plan.md 3.3 与 docs/backend/aigc_marking.md 八）。
# link_url 站内相对路径 /index.html?aigc_tab=1 直达"设置 → 内容标识"（安全校验允许）。
ANNOUNCEMENT_TITLE = '重要通知：AI 生成内容将默认添加标识'


def upgrade() -> None:
    """植入 AIGC 标识规则变更的全局弹窗公告（数据迁移，幂等：按标题判重）。

    公告发布后由用户侧 /api/announcements 接口下发，announcement_popup.js 在
    index / marketing_agent / video_workflow 三页进页强弹；已读记录复用
    announcement_reads per-user 表（跨设备一致）。
    """
    conn = op.get_bind()
    row = conn.execute(text(
        "SELECT COUNT(*) AS c FROM announcements WHERE title = :title"
    ), {"title": ANNOUNCEMENT_TITLE}).fetchone()
    if row and row.c:
        logger.info("[Migration] AIGC 弹窗公告已存在，跳过")
        return

    content = (
        '根据《互联网信息服务深度合成管理规定》《人工智能生成合成内容标识办法》要求，'
        '自 2026-11-11 起，平台对 AI 生成的图片与视频默认添加"AI生成"显式标识'
        '（画面右下角角标），并在文件元数据中写入隐式标识。\n\n'
        '显式标识不影响内容的正常使用、下载与编辑。如您希望关闭显式标识，可前往'
        '"设置 → 内容标识"申请关闭（按法规要求将留痕记录至少 6 个月）；'
        '隐式标识为法定义务，无法关闭。\n\n'
        '点击下方"前往设置"了解详情并管理您的标识偏好。'
    )
    conn.execute(text("""
        INSERT INTO announcements
            (title, content, link_url, link_text, images,
             level, popup, status, publish_at, expire_at, created_by)
        VALUES
            (:title, :content, :link_url, :link_text, :images,
             :level, :popup, :status, NULL, NULL, :created_by)
    """), {
        "title": ANNOUNCEMENT_TITLE,
        "content": content,
        "link_url": '/index.html?aigc_tab=1',
        "link_text": '前往设置',
        "images": '[]',
        "level": 'warning',
        "popup": 1,
        "status": 'published',
        "created_by": 0,  # 系统植入（无 FK，created_by=0 约定为系统，同 model 默认）
    })
    logger.info("[Migration] seeded AIGC popup announcement")


def downgrade() -> None:
    """回滚：删除本迁移植入的公告（按标题精确定位，不动其他公告及其已读记录）"""
    conn = op.get_bind()
    result = conn.execute(text(
        "DELETE FROM announcements WHERE title = :title"
    ), {"title": ANNOUNCEMENT_TITLE})
    logger.info(f"[Migration] removed AIGC popup announcement (rows={result.rowcount})")
