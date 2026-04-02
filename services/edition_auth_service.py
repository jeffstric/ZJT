import logging
import asyncio
from datetime import datetime
from typing import Optional, Dict, Any

import httpx

from config.strategy.edition_strategy import IS_COMMUNITY_EDITION
from model.users import UsersModel
from utils.network_utils import get_local_ip

logger = logging.getLogger(__name__)

AUTH_SERVER_URL = "https://ailive.perseids.cn:11443"
AUTH_VERIFY_ENDPOINT = "/api/v1/auth/verify"
AUTH_REPORT_ENDPOINT = "/api/v1/auth/report"

CHECK_INTERVAL = 3600


class EditionAuthService:

    def __init__(self):
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self):
        try:
            if self._running:
                return

            if IS_COMMUNITY_EDITION:
                return

            self._running = True
            self._task = asyncio.create_task(self._check_loop())
        except Exception as e:
            pass

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _check_loop(self):
        while self._running:
            try:
                await self.check_and_report()
            except Exception as e:
                pass
            
            try:
                await asyncio.sleep(CHECK_INTERVAL)
            except Exception as e:
                break

    async def check_and_report(self):
        try:
            if IS_COMMUNITY_EDITION:
                return

            from config.config_util import get_dynamic_config_value
            zjt_token = get_dynamic_config_value("zjt", "token", default="")

            if not zjt_token:
                await self._report_system_info(token=None, reason="token_empty")
                return

            is_valid, message = await self._verify_token(zjt_token)

            if is_valid:
                pass
            else:
                await self._report_system_info(token=zjt_token, reason=message)
        except Exception as e:
            pass

    async def _verify_token(self, token: str) -> tuple:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{AUTH_SERVER_URL}{AUTH_VERIFY_ENDPOINT}",
                    json={"token": token}
                )

                if response.status_code == 200:
                    data = response.json()
                    if data.get("code") == 0:
                        result = data.get("data", {})
                        if result.get("valid"):
                            return True, "valid"
                        else:
                            return False, result.get("message", "invalid token")
                    else:
                        return False, data.get("message", "verify failed")
                else:
                    return True, f"http error: {response.status_code}"

        except httpx.TimeoutException:
            return True, "auth_server_timeout"

        except Exception as e:
            return True, f"auth_server_error: {e}"

    async def _report_system_info(self, token: Optional[str], reason: str):
        try:
            user_count = UsersModel.get_total_count()
            phone = self._get_first_user_phone()
            ip_address = get_local_ip()

            payload = {
                "user_count": user_count,
                "ip_address": ip_address,
                "phone": phone,
                "token": token or "",
                "reason": reason
            }

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{AUTH_SERVER_URL}{AUTH_REPORT_ENDPOINT}",
                    json=payload
                )

                if response.status_code == 200:
                    data = response.json()
                    if data.get("code") == 0:
                        pass
                    else:
                        pass
                else:
                    pass

        except Exception as e:
            pass

    def _get_first_user_phone(self) -> str:
        try:
            from model.database import execute_query
            result = execute_query(
                "SELECT phone FROM users ORDER BY id ASC LIMIT 1",
                fetch_one=True
            )
            if result and result.get("phone"):
                return result["phone"]
        except Exception as e:
            pass
        return ""


edition_auth_service = EditionAuthService()
