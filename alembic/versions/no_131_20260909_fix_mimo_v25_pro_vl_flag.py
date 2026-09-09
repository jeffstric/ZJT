"""修正 mimo-v2.5-pro 的 supports_vl 错误标记并清理指向它的 VL 偏好

Revision ID: 20260909_fix_mimo_v25_pro_vl_fla
Revises: 20260908_add_video_workflow_cont
Create Date: 2026-09-09

背景：no_127 接入小米 MiMo 时把 mimo-v2.5-pro 误标 supports_vl=1（note 还写着
"全模态输入"）。官方文档（https://mimo.mi.com/models/zh-CN/mimo-v2.5-pro）标明
该模型输入/输出模态均为文本，不支持视觉；mimo-v2.5（非 Pro）官方定位为多模态
理解，保持 supports_vl=1 不变。
误标后果：/style-models 下拉会把 pro 列为可选 VL 模型；若用户保存为 VL 偏好，
_get_vl_model_for_expert 不校验 supports_vl，会把 asset-readiness-checker 等
看图专家路由到纯文本模型，注入图片后 API 直接 400。
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
# ⚠️ revision 长度必须 <= 32 字符 (alembic_version.version_num 为 varchar(32))
revision: str = '20260909_fix_mimo_v25_pro_vl_fla'
down_revision: Union[str, None] = '20260908_add_video_workflow_cont'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """修正 supports_vl 标记 + 误导性 note，并清理失效的 VL 偏好（UPDATE/DELETE 天然幂等）"""
    conn = op.get_bind()

    # 1. 修正 supports_vl 与 note
    conn.execute(text("""
        UPDATE `model`
        SET supports_vl = 0,
            note = '小米 MiMo V2.5 Pro 旗舰（Token Plan），文本模型（不支持视觉），支持思考模式'
        WHERE model_name = 'mimo-v2.5-pro'
    """))
    logger.info("[Migration] Fixed mimo-v2.5-pro supports_vl=0 (text-only model)")

    # 2. 清理已保存的 VL 模型偏好：偏好读取方（_get_vl_model_for_expert）不校验
    #    supports_vl，不清理会继续把看图专家路由到该纯文本模型。
    #    删除后走既有回落链：默认 deepseek-v4-flash-vision-exp > 推荐 > 第一个。
    conn.execute(text("""
        DELETE FROM user_preferences
        WHERE pref_type = 'vl_model'
        AND JSON_UNQUOTE(JSON_EXTRACT(config_value, '$.model')) = 'mimo-v2.5-pro'
    """))
    logger.info("[Migration] Deleted stale vl_model preferences pointing to mimo-v2.5-pro")


def downgrade() -> None:
    """数据修复类迁移：不回滚，避免把错误标记写回"""
    pass
