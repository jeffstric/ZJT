"""deepseek-v4-flash 开启图片理解（supports_vl=1）

Revision ID: 20261029_enable_ds_v4_flash_vl
Revises: 20261027_add_asset_group_create
Create Date: 2026-10-29

背景：deepseek-v4-flash 与 deepseek-v4-flash-vision-exp 已统一映射到
DeepSeek-V4.1-Flash（model ID: deepseek-flash，见 llm/openai_deepseek.py
_MODEL_NAME_MAP 与 docs/backend/deepseek_model_name_mapping.md），VL 能力
已并入该模型；方舟侧映射 deepseek-v4-flash-ga-260731（GA 版，实测支持
图片输入）。官方视觉接口每张图片 token 有 1024 上限（服务端自动缩放），
不存在 token 爆炸。model 表 deepseek-v4-flash 行 supports_vl 仍为 0，
导致 VL 场景（画风识别下拉、资产检查专家、H3 提示词优化多模态改造）
无法选到该模型。

线上案例（2026-10-29 会话 5d72a44f）：H3 Ref2VA 提示词优化只能走纯文本
模型，凭"蓝色乌灵胶囊"字面臆测出 "round blue-and-white creature" 角色
外观，文字压过参考图，成片角色形象与资产库参考图完全不符。

幂等：UPDATE 天然幂等；行不存在时影响 0 行，无害。
方向说明：与 no_132（vl=1 误标回退 0）相反，本迁移基于 API 实测能力
开启标记，无需清理 vl_model 偏好（0→1 方向旧偏好只会更合法）。
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
# ⚠️ revision 长度必须 <= 32 字符 (alembic_version.version_num 为 varchar(32))
revision: str = '20261029_enable_ds_v4_flash_vl'
down_revision: Union[str, None] = '20261027_add_asset_group_create'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """开启 deepseek-v4-flash 图片理解标记（UPDATE 天然幂等）"""
    conn = op.get_bind()
    conn.execute(text("""
        UPDATE `model`
        SET supports_vl = 1
        WHERE model_name = 'deepseek-v4-flash'
    """))
    logger.info("[Migration] Enabled deepseek-v4-flash supports_vl=1 (maps to deepseek-flash, VL capable)")


def downgrade() -> None:
    """数据修复类迁移：不回滚，避免把可用 VL 能力改回不可用"""
    pass
