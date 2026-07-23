"""Agent auth API."""
import asyncio
from typing import Optional

from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from model.user_tokens import UserTokensModel
from services.agent_auth_service import AgentAuthError, AgentAuthService

router = APIRouter(prefix="/api/agent-auth", tags=["agent-auth"])


class AgentTokenExchangeRequest(BaseModel):
    token: Optional[str] = None
    device_uuid: Optional[str] = None


def _auth_header_token(token: Optional[str]) -> str:
    token = (token or "").strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    return token


@router.post("/exchange")
async def exchange_agent_token(request: AgentTokenExchangeRequest):
    raw_token = (request.token or "").strip()
    if not raw_token:
        return JSONResponse(
            status_code=401,
            content={"success": False, "error_code": "missing_agent_token", "error": "agent token is required"},
        )

    try:
        result = await asyncio.to_thread(
            AgentAuthService.exchange_token,
            raw_token,
            request.device_uuid,
        )
    except AgentAuthError as exc:
        return JSONResponse(status_code=exc.status_code, content=exc.to_dict())

    return JSONResponse(result)


@router.post("/storyboard-connection")
async def create_storyboard_agent_connection(
    auth_token: Optional[str] = Header(None, alias="Authorization"),
):
    token = _auth_header_token(auth_token)
    if not token:
        return JSONResponse(
            status_code=401,
            content={"success": False, "error_code": "missing_auth_token", "error": "Authorization is required"},
        )

    user_id = await asyncio.to_thread(UserTokensModel.get_user_id_by_token, token)
    if not user_id:
        return JSONResponse(
            status_code=401,
            content={"success": False, "error_code": "invalid_auth_token", "error": "Authorization is invalid or expired"},
        )

    try:
        result = await asyncio.to_thread(
            AgentAuthService.create_storyboard_agent_token,
            int(user_id),
        )
    except AgentAuthError as exc:
        return JSONResponse(status_code=exc.status_code, content=exc.to_dict())

    result["user_id"] = int(user_id)
    return JSONResponse(result)
