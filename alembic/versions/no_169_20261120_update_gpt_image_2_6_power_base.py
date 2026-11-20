"""update gpt image 2 6 power base

GPT Image 2.6（sunburst / flare）算力改按实现方分流定价（业务决定，2026-11-20）：
- 多米实现方：维持固定 2 点（渠道基准价，不動）；
- 通用站点 site_0~5（走 openlux 网关）：2 → 7（1K PNG 默认品质真实成本基准，
  $0.031 ≈ 5.6 算力 + ~25% 毛利，修饰符见 config/unified_config.py
  GPT_IMAGE_2_6_POWER_MODIFIERS，说明见 docs/image/gpt_image_2_6_integration.md 计费一节）。

任务级 computing_power 置 0，基准随实现方 default_computing_power；
no_167 种子的 implementation_power_config 会覆盖实现方代码默认值，
因此本迁移把仍是种子值 '{"fixed": 2}' 的【站点】行同步为 '{"fixed": 7}'，
多米行保持 2；已被运营手动改过的行不动（WHERE 限定种子值，幂等）。

Revision ID: 20261120_update_gpt_image_2_6_po
Revises: 20261119_add_gpt_image_2_6_power
Create Date: 2026-11-20
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
# ⚠️ revision 长度必须 <= 32 字符 (alembic_version.version_num 为 varchar(32))
revision: str = '20261120_update_gpt_image_2_6_po'
down_revision: Union[str, None] = '20261119_add_gpt_image_2_6_power'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 通用站点实现方（多米不动，维持 '{"fixed": 2}'）
_SITE_IMPLEMENTATIONS = [
    'gpt_image_2_6_common_sunburst_site0_v1',
    'gpt_image_2_6_common_sunburst_site1_v1',
    'gpt_image_2_6_common_sunburst_site2_v1',
    'gpt_image_2_6_common_sunburst_site3_v1',
    'gpt_image_2_6_common_sunburst_site4_v1',
    'gpt_image_2_6_common_sunburst_site5_v1',
    'gpt_image_2_6_common_flare_site0_v1',
    'gpt_image_2_6_common_flare_site1_v1',
    'gpt_image_2_6_common_flare_site2_v1',
    'gpt_image_2_6_common_flare_site3_v1',
    'gpt_image_2_6_common_flare_site4_v1',
    'gpt_image_2_6_common_flare_site5_v1',
]

_IMPL_LIST_SQL = ', '.join(f"'{name}'" for name in _SITE_IMPLEMENTATIONS)

_UPDATE_SQL = (
    "UPDATE implementation_power_config "
    "SET power_config = '{\"fixed\": 7}' "
    f"WHERE implementation_name IN ({_IMPL_LIST_SQL}) "
    "AND power_config = '{\"fixed\": 2}'"
)

_DOWNGRADE_SQL = (
    "UPDATE implementation_power_config "
    "SET power_config = '{\"fixed\": 2}' "
    f"WHERE implementation_name IN ({_IMPL_LIST_SQL}) "
    "AND power_config = '{\"fixed\": 7}'"
)


def upgrade() -> None:
    """站点种子固定算力 2 → 7（仅限仍是种子值的站点行，幂等，不覆盖运营手动配置）"""
    conn = op.get_bind()

    result = conn.execute(text(_UPDATE_SQL))
    logger.info("[Migration] GPT Image 2.6 站点算力基准 2->7, updated %s rows", result.rowcount)


def downgrade() -> None:
    """回滚：站点固定算力 7 → 2（仅限本迁移改过的站点行）"""
    conn = op.get_bind()

    conn.execute(text(_DOWNGRADE_SQL))
    logger.info("[Migration] GPT Image 2.6 站点算力基准 7->2 rollback done")
