"""Add api_aggregator.site_0 config keys to system_config

Revision ID: 20260421_site0_aggregator
Revises: 20260421_add_claude_haiku
Create Date: 2026-04-21

"""
import os
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
revision: str = '20260421_site0_aggregator'
down_revision: Union[str, None] = '20260421_add_claude_haiku'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Insert api_aggregator.site_0 config keys"""
    conn = op.get_bind()
    env = os.getenv('comfyui_env', 'dev')

    # api_aggregator.site_0.api_key
    conn.execute(text("""
        INSERT INTO system_config (env, config_key, config_value, value_type, description, editable, is_sensitive)
        VALUES (:env, 'api_aggregator.site_0.api_key', '', 'string', 'YWAPI 官方站点 API Key', 1, 1)
        ON DUPLICATE KEY UPDATE description = VALUES(description), is_sensitive = VALUES(is_sensitive)
    """), {"env": env})
    logger.info("[Migration] Inserted api_aggregator.site_0.api_key for env=%s", env)

    # api_aggregator.site_0.name
    conn.execute(text("""
        INSERT INTO system_config (env, config_key, config_value, value_type, description, editable, is_sensitive)
        VALUES (:env, 'api_aggregator.site_0.name', '', 'string', 'YWAPI 官方站点名称', 1, 0)
        ON DUPLICATE KEY UPDATE description = VALUES(description), is_sensitive = VALUES(is_sensitive)
    """), {"env": env})
    logger.info("[Migration] Inserted api_aggregator.site_0.name for env=%s", env)


def downgrade() -> None:
    """Remove api_aggregator.site_0 config keys"""
    conn = op.get_bind()

    conn.execute(text("""
        DELETE FROM system_config WHERE config_key = 'api_aggregator.site_0.api_key'
    """))
    logger.info("[Migration] Removed api_aggregator.site_0.api_key")

    conn.execute(text("""
        DELETE FROM system_config WHERE config_key = 'api_aggregator.site_0.name'
    """))
    logger.info("[Migration] Removed api_aggregator.site_0.name")
