"""Fix implementation_power_config driver_key to lowercase

Revision ID: 20260416_fix_driver_key_case
Revises: 20260416_veo3_seedance_power
Create Date: 2026-04-16

"""
from typing import Sequence, Union
from alembic import op
from sqlalchemy.sql import text
import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
revision: str = '20260416_fix_driver_key_case'
down_revision: Union[str, None] = '20260416_veo3_seedance_power'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# 大写 -> 小写映射
DRIVER_KEY_MAPPING = {
    'SORA2_IMAGE_TO_VIDEO': 'sora2_image_to_video',
    'KLING_IMAGE_TO_VIDEO': 'kling_image_to_video',
    'GEMINI_IMAGE_EDIT': 'gemini_image_edit',
    'VEO3_IMAGE_TO_VIDEO': 'veo3_image_to_video',
    'LTX2_IMAGE_TO_VIDEO': 'ltx2_image_to_video',
    'WAN22_IMAGE_TO_VIDEO': 'wan22_image_to_video',
    'DIGITAL_HUMAN': 'digital_human',
    'VIDU_IMAGE_TO_VIDEO': 'vidu_image_to_video',
    'VIDU_Q2_IMAGE_TO_VIDEO': 'vidu_q2_image_to_video',
    'SEEDREAM_TEXT_TO_IMAGE': 'seedream_text_to_image',
    'GEMINI_IMAGE_PREVIEW': 'gemini_image_preview',
}


def _build_case_sql(mapping: dict) -> str:
    """构建 CASE WHEN 语句"""
    cases = '\n'.join([f"        WHEN '{k}' THEN '{v}'" for k, v in mapping.items()])
    return cases


def upgrade() -> None:
    """将 driver_key 从大写修正为小写"""
    logger.info("开始修正 implementation_power_config 的 driver_key 大小写...")

    case_sql = _build_case_sql(DRIVER_KEY_MAPPING)
    old_keys = ', '.join([f"'{k}'" for k in DRIVER_KEY_MAPPING.keys()])

    op.execute(text(f"""
        UPDATE implementation_power_config
        SET driver_key = CASE driver_key
{case_sql}
        END
        WHERE driver_key IN ({old_keys})
    """))

    logger.info("driver_key 大小写修正完成")


def downgrade() -> None:
    """回滚：将小写改回大写"""
    logger.info("开始回滚 driver_key 大小写...")

    reverse_mapping = {v: k for k, v in DRIVER_KEY_MAPPING.items()}
    case_sql = _build_case_sql(reverse_mapping)
    new_keys = ', '.join([f"'{k}'" for k in reverse_mapping.keys()])

    op.execute(text(f"""
        UPDATE implementation_power_config
        SET driver_key = CASE driver_key
{case_sql}
        END
        WHERE driver_key IN ({new_keys})
    """))

    logger.info("driver_key 回滚完成")
