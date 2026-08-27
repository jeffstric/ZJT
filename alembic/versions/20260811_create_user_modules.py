"""Create user module registry, immutable releases and pinned jobs.

Revision ID: 20260811_user_modules
Revises: 20260810_add_agnes
Create Date: 2026-08-11
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260811_user_modules"
down_revision: Union[str, None] = "20260810_add_agnes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_module",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("module_id", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column("active_release_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(length=32), server_default="disabled", nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("create_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column(
            "update_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("module_id", name="uk_user_module_module_id"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index(
        "idx_user_module_active_release", "user_module", ["active_release_id"], unique=False
    )
    op.create_index(
        "idx_user_module_enabled_status", "user_module", ["enabled", "status"], unique=False
    )

    op.create_table(
        "user_module_release",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("module_id", sa.String(length=128), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("code_digest", sa.String(length=80), nullable=False),
        sa.Column("rpc_protocol", sa.String(length=64), nullable=False),
        sa.Column("driver_protocol", sa.String(length=64), nullable=False),
        sa.Column("sdk_version", sa.String(length=32), nullable=False),
        sa.Column("manifest_json", sa.JSON(), nullable=False),
        sa.Column("release_path", sa.String(length=1024), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="staged", nullable=False),
        sa.Column(
            "compatibility_status", sa.String(length=32), server_default="pending", nullable=False
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("create_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column(
            "update_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["module_id"], ["user_module.module_id"], name="fk_user_module_release_module"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("module_id", "code_digest", name="uk_user_module_release_digest"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index(
        "idx_user_module_release_status",
        "user_module_release",
        ["module_id", "status"],
        unique=False,
    )

    op.create_table(
        "module_job",
        sa.Column("job_id", sa.String(length=64), nullable=False),
        sa.Column("release_id", sa.BigInteger(), nullable=False),
        sa.Column("module_id", sa.String(length=128), nullable=False),
        sa.Column("module_version", sa.String(length=64), nullable=False),
        sa.Column("code_digest", sa.String(length=80), nullable=False),
        sa.Column("protocol_version", sa.String(length=64), nullable=False),
        sa.Column("requester_id", sa.String(length=64), nullable=False),
        sa.Column("operation", sa.String(length=100), nullable=False),
        sa.Column("media_kind", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="queued", nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("completion_modes", sa.JSON(), nullable=False),
        sa.Column("request_json", sa.JSON(), nullable=False),
        sa.Column("external_job_id", sa.String(length=512), nullable=True),
        sa.Column("handle_json", sa.JSON(), nullable=True),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("error_json", sa.JSON(), nullable=True),
        sa.Column("progress", sa.Numeric(precision=6, scale=5), nullable=True),
        sa.Column("next_poll_at", sa.DateTime(), nullable=True),
        sa.Column("timeout_at", sa.DateTime(), nullable=False),
        sa.Column("callback_token_hash", sa.String(length=64), nullable=True),
        sa.Column("create_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column(
            "update_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("complete_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["release_id"], ["user_module_release.id"], name="fk_module_job_release"
        ),
        sa.PrimaryKeyConstraint("job_id"),
        sa.UniqueConstraint(
            "requester_id", "module_id", "idempotency_key", name="uk_module_job_idempotency"
        ),
        sa.UniqueConstraint("callback_token_hash", name="uk_module_job_callback_token"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index("idx_module_job_due", "module_job", ["status", "next_poll_at"], unique=False)
    op.create_index(
        "idx_module_job_release_status", "module_job", ["release_id", "status"], unique=False
    )
    op.create_index(
        "idx_module_job_module_create", "module_job", ["module_id", "create_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index("idx_module_job_module_create", table_name="module_job")
    op.drop_index("idx_module_job_release_status", table_name="module_job")
    op.drop_index("idx_module_job_due", table_name="module_job")
    op.drop_table("module_job")
    op.drop_index("idx_user_module_release_status", table_name="user_module_release")
    op.drop_table("user_module_release")
    op.drop_index("idx_user_module_enabled_status", table_name="user_module")
    op.drop_index("idx_user_module_active_release", table_name="user_module")
    op.drop_table("user_module")
