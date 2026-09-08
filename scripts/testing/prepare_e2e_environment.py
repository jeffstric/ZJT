#!/usr/bin/env python3
"""为一次性 E2E 数据库执行迁移并幂等创建测试账号。"""

import os
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from model.computing_power import ComputingPowerModel
from model.database import execute_update
from model.users import UsersModel
from perseids_server.utils.token import hash_password
from scripts.enable_test_mode import write_configs


def required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"缺少必要环境变量: {name}")
    return value


def run_migrations() -> None:
    """baseline.sql 带基线版本号，此处只应用之后的增量迁移。"""
    alembic_config = Config(str(PROJECT_ROOT / "alembic.ini"))
    command.upgrade(alembic_config, "head")
    print("[prepare_e2e] Alembic 迁移完成")


def upsert_user(
    phone: str,
    password: str,
    invite_code: str,
    role: str,
    computing_power: int,
) -> int:
    password_hash = hash_password(password)
    user = UsersModel.get_by_phone(phone)
    if user:
        UsersModel.update_password(user.id, password_hash)
        execute_update(
            """
            UPDATE users
            SET status = 1, role = %s, terms_agreed = 1, invite_code = %s
            WHERE id = %s
            """,
            (role, invite_code, user.id),
        )
        user_id = user.id
    else:
        user_id = UsersModel.create(
            phone=phone,
            password_hash=password_hash,
            role=role,
            terms_agreed=1,
            invite_code=invite_code,
        )

    ComputingPowerModel.create_or_update(user_id, computing_power)
    return user_id


def main() -> None:
    run_migrations()
    computing_power = int(required_env("E2E_TEST_POWER"))

    primary_user_id = upsert_user(
        phone=required_env("E2E_TEST_PHONE"),
        password=required_env("E2E_TEST_PASSWORD"),
        invite_code=required_env("E2E_TEST_INVITE_CODE"),
        role="admin",
        computing_power=computing_power,
    )
    secondary_user_id = upsert_user(
        phone=required_env("E2E_SECONDARY_PHONE"),
        password=required_env("E2E_SECONDARY_PASSWORD"),
        invite_code=required_env("E2E_SECONDARY_INVITE_CODE"),
        role="user",
        computing_power=computing_power,
    )

    write_configs()
    print(
        "[prepare_e2e] 测试账号准备完成 "
        f"primary_user_id={primary_user_id} secondary_user_id={secondary_user_id}"
    )


if __name__ == "__main__":
    main()
