"""reset users terms agreed for aigc labeling

Revision ID: 20261111_reset_users_terms_agree
Revises: 20261108_aigc_explicit_opt_out_l
Create Date: 2026-11-11
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
# ⚠️ revision 长度必须 <= 32 字符 (alembic_version.version_num 为 varchar(32))
revision: str = '20261111_reset_users_terms_agree'
down_revision: Union[str, None] = '20261108_aigc_explicit_opt_out_l'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """重置所有用户的条款同意状态为未同意（terms_agreed=0）。

    背景：《AI工具服务使用条款》已补充"AIGC 生成内容标识"章节并修订 6.1
    （files/AI工具服务使用条款.txt 及英文版，2026-11-11），需全体用户在下次
    登录时对新版条款重新勾选同意：登录链路（perseids_server/services/
    auth_service.py login）在 terms_agreed=0 且未勾选时返回
    "请阅读并同意AI工具服务使用条款"，前端收到该错误自动弹出条款弹窗，
    勾选后重新提交登录并将本字段回写为 1。

    幂等：重复执行无副作用（已是 0 的行不受影响）。
    """
    conn = op.get_bind()
    result = conn.execute(text(
        "UPDATE `users` SET `terms_agreed` = 0 WHERE `terms_agreed` = 1"
    ))
    logger.info(
        "[Migration] 已重置条款同意状态（terms_agreed 1->0），影响行数: %s",
        result.rowcount,
    )


def downgrade() -> None:
    """不可逆数据重置，无回滚。

    原同意名单未留存（用户勾选同意即被覆盖为历史状态），且不应回滚——
    回滚会把已重新同意新条款的用户再次置为未同意。如需撤销本次重置效果，
    只能等待用户在登录时重新勾选（该行为即业务上的恢复路径）。
    """
    logger.warning(
        "[Migration] no_164 为单向数据重置（条款重新同意），downgrade 无操作"
    )
