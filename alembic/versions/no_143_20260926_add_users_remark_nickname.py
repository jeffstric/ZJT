"""add users remark nickname

Revision ID: 20260926_users_remark_nick
Revises: 20260922_add_mimo_v26_models
Create Date: 2026-09-26
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

from config.constant import generate_default_nickname

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
# ⚠️ revision 长度必须 <= 32 字符 (alembic_version.version_num 为 varchar(32))
revision: str = '20260926_users_remark_nick'
down_revision: Union[str, None] = '20260922_add_mimo_v26_models'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """users 表新增 nickname（用户自定义昵称）与 remark（管理员备注），
    并为存量用户回填随机趣味默认昵称。"""
    conn = op.get_bind()

    nickname_exists = conn.execute(text("""
        SELECT COUNT(*) FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'users'
          AND COLUMN_NAME = 'nickname'
    """)).scalar()
    if not nickname_exists:
        conn.execute(text("""
            ALTER TABLE users
            ADD COLUMN nickname VARCHAR(50) DEFAULT NULL
            COMMENT '用户昵称（用户自定义；NULL=使用系统默认昵称）'
            AFTER email
        """))
        logger.info("[Migration] added users.nickname")

    remark_exists = conn.execute(text("""
        SELECT COUNT(*) FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'users'
          AND COLUMN_NAME = 'remark'
    """)).scalar()
    if not remark_exists:
        conn.execute(text("""
            ALTER TABLE users
            ADD COLUMN remark VARCHAR(500) DEFAULT NULL
            COMMENT '管理员备注（仅后台可见）'
            AFTER nickname
        """))
        logger.info("[Migration] added users.remark")

    # 存量用户回填随机趣味昵称（幂等：只处理仍为 NULL 的行）
    used = set()
    for (name,) in conn.execute(text(
        "SELECT nickname FROM users WHERE nickname IS NOT NULL"
    )):
        if name:
            used.add(name)
    rows = conn.execute(text("SELECT id FROM users WHERE nickname IS NULL")).fetchall()
    for (user_id,) in rows:
        name = generate_default_nickname(used_names=used)
        used.add(name)
        conn.execute(
            text("UPDATE users SET nickname = :name, updated_at = NOW() WHERE id = :id"),
            {"name": name, "id": user_id},
        )
    logger.info("[Migration] backfilled random nicknames for %d users", len(rows))


def downgrade() -> None:
    conn = op.get_bind()
    remark_exists = conn.execute(text("""
        SELECT COUNT(*) FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'users'
          AND COLUMN_NAME = 'remark'
    """)).scalar()
    if remark_exists:
        conn.execute(text("ALTER TABLE users DROP COLUMN remark"))
        logger.info("[Migration] dropped users.remark")

    nickname_exists = conn.execute(text("""
        SELECT COUNT(*) FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'users'
          AND COLUMN_NAME = 'nickname'
    """)).scalar()
    if nickname_exists:
        conn.execute(text("ALTER TABLE users DROP COLUMN nickname"))
        logger.info("[Migration] dropped users.nickname")
