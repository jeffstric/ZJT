# -*- coding: utf-8 -*-
"""
Seedance 素材 Action 接口客户端（火山方舟真人库标准协议，供应商无关）

对接《对外接口文档-Seedance素材Action接口.md》：
- POST {base_url}/v1/api/assets/?Action=<Action>&Version=2024-01-01
- 鉴权：Authorization: Bearer <平台 Token>（火山方舟同构网关形态；官方 AK/SK 签名
  形态待真实直连客户出现时再支持）
- 请求体/响应体与火山方舟官方一致（大驼峰字段，响应为 ResponseMetadata + Result）

本客户端为纯协议实现（Bearer 形态），不感知具体供应商；按供应商组解析地址/Token
请用工厂 create_seedance_asset_client(config_group)，配置键约定：
- 地址：<group>.asset_base_url（素材专用，优先）> <group>.base_url（素材与视频同址的网关免配）
- Token：<group>.asset_api_key > <group>.api_key

本客户端为同步实现（requests），供视频驱动在同步任务执行器内调用，
与 BaseVideoDriver._request 同一运行环境，不进入 web 事件循环。
Web 路由如需调用请用 asyncio.to_thread 包装。
"""
import time
import logging
from typing import Any, Dict, List, Optional

import requests

from config.config_util import get_dynamic_config_value
from config.constant import (
    SEEDANCE_ASSET_POLL_INTERVAL_SECONDS,
    SEEDANCE_ASSET_REQUEST_TIMEOUT_SECONDS,
    SEEDANCE_ASSET_WAIT_ACTIVE_TIMEOUT_SECONDS,
)

logger = logging.getLogger(__name__)

# 素材状态（官方 GetAsset/ListAssets 的 Result.Status 取值）
ASSET_STATUS_PROCESSING = "Processing"
ASSET_STATUS_ACTIVE = "Active"
ASSET_STATUS_FAILED = "Failed"


class SeedanceAssetError(Exception):
    """素材 Action 接口错误（平台信封或官方 ResponseMetadata.Error 结构统一封装）"""

    def __init__(self, message: str, code: Optional[str] = None, http_status: Optional[int] = None):
        self.message = message
        self.code = code
        self.http_status = http_status
        super().__init__(message)


def create_seedance_asset_client(config_group: str) -> "SeedanceAssetClient":
    """
    按供应商组构建素材客户端（地址/Token 动态配置解析）

    地址：<group>.asset_base_url > <group>.base_url（素材与视频同址的网关免配），均未配置时报错；
    Token：<group>.asset_api_key > <group>.api_key，均未配置时报错。
    """
    base_url = (
        get_dynamic_config_value(config_group, "asset_base_url", default="")
        or get_dynamic_config_value(config_group, "base_url", default="")
    )
    if not base_url:
        raise SeedanceAssetError(
            f"素材库地址未配置（{config_group}.asset_base_url，"
            f"素材与视频接口同址时可只配 {config_group}.base_url）"
        )
    api_key = (
        get_dynamic_config_value(config_group, "asset_api_key", default="")
        or get_dynamic_config_value(config_group, "api_key", default="")
    )
    if not api_key:
        raise SeedanceAssetError(
            f"素材接口 Token 未配置（{config_group}.asset_api_key / {config_group}.api_key）"
        )
    return SeedanceAssetClient(api_key=api_key, base_url=base_url)


class SeedanceAssetClient:
    """
    Seedance 素材 Action 接口客户端（纯协议实现，地址/Token 由调用方显式注入）
    """

    def __init__(self, api_key: str, base_url: str, timeout: Optional[float] = None):
        if not api_key or not base_url:
            raise SeedanceAssetError("素材客户端构造需显式提供 api_key 与 base_url")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout or SEEDANCE_ASSET_REQUEST_TIMEOUT_SECONDS

    # ---------- 基础调用 ----------

    def _call_action(self, action: str, body: Dict[str, Any]) -> Dict[str, Any]:
        """
        调用单个 Action 并返回官方响应结构（ResponseMetadata + Result）。

        Raises:
            SeedanceAssetError: HTTP 非 2xx（平台信封 {code, message} 或官方
                ResponseMetadata.Error 结构）、响应非 JSON、或网络异常。
        """
        url = f"{self.base_url}/v1/api/assets/"
        try:
            response = requests.post(
                url,
                params={"Action": action, "Version": "2024-01-01"},
                json=body or {},
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=self.timeout,
            )
        except requests.exceptions.RequestException as e:
            raise SeedanceAssetError(f"素材接口网络异常: {e}") from e

        try:
            payload = response.json()
        except ValueError:
            raise SeedanceAssetError(
                f"素材接口响应非 JSON: HTTP {response.status_code}",
                http_status=response.status_code,
            ) from None

        if response.status_code >= 400:
            raise self._build_error(response.status_code, payload)

        # 2xx 但官方错误结构（如 404 NotFound 已在 >=400 分支；此处兜底防御）
        metadata = payload.get("ResponseMetadata") if isinstance(payload, dict) else None
        if isinstance(metadata, dict) and "Error" in metadata:
            error = metadata["Error"] or {}
            raise SeedanceAssetError(
                f"素材接口错误 [{error.get('Code', 'Unknown')}]: {error.get('Message', '未知错误')}",
                code=error.get("Code"),
                http_status=response.status_code,
            )

        return payload

    @staticmethod
    def _build_error(http_status: int, payload: Any) -> SeedanceAssetError:
        """将平台信封 / 官方错误结构统一转为 SeedanceAssetError"""
        if isinstance(payload, dict):
            # 官方结构：ResponseMetadata.Error（NotFound.asset_id / NotFound.group_id 等）
            metadata = payload.get("ResponseMetadata")
            if isinstance(metadata, dict) and "Error" in metadata:
                error = metadata["Error"] or {}
                request_id = metadata.get("RequestId", "")
                message = error.get("Message", "未知错误")
                if request_id:
                    message = f"{message} (RequestId: {request_id})"
                return SeedanceAssetError(
                    f"素材接口错误 [{error.get('Code', 'Unknown')}]: {message}",
                    code=error.get("Code"),
                    http_status=http_status,
                )
            # 平台信封：{code, message}
            if "message" in payload:
                return SeedanceAssetError(
                    str(payload["message"]),
                    code=str(payload.get("code", "")) or None,
                    http_status=http_status,
                )
        return SeedanceAssetError(
            f"素材接口请求失败: HTTP {http_status}", http_status=http_status
        )

    @staticmethod
    def _extract_result(payload: Dict[str, Any]) -> Dict[str, Any]:
        """提取官方响应的 Result 部分（各 Action 的数据字段均在 Result 内）"""
        result = payload.get("Result")
        return result if isinstance(result, dict) else {}

    # ---------- 素材 CRUD ----------

    def create_asset(
        self,
        url: str,
        asset_type: str,
        name: Optional[str] = None,
        group_id: Optional[str] = None,
        moderation: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        上传素材（按公网 URL）。素材创建后为 Processing，需等待 Active 才可用于视频生成。

        Args:
            url: 素材公网可访问地址（内网/保留网段会被拒绝）
            asset_type: Image / Video / Audio
            name: 素材名称（可选）
            group_id: 目标素材组 id（可选，不传落默认组）
            moderation: 审核参数（可选，按官方定义透传）

        Returns:
            Result dict，含 Id / Status
        """
        body: Dict[str, Any] = {"URL": url, "AssetType": asset_type}
        if name:
            body["Name"] = name
        if group_id:
            body["GroupId"] = group_id
        if moderation:
            body["Moderation"] = moderation
        return self._extract_result(self._call_action("CreateAsset", body))

    def get_asset(self, asset_id: str) -> Dict[str, Any]:
        """查询单个素材（Result.Status: Processing / Active / Failed）"""
        return self._extract_result(self._call_action("GetAsset", {"Id": asset_id}))

    def list_assets(
        self,
        group_ids: Optional[List[str]] = None,
        page: Optional[int] = None,
        page_size: Optional[int] = None,
    ) -> Dict[str, Any]:
        """查询素材列表（Result: TotalCount / PageNumber / PageSize / Items）"""
        body: Dict[str, Any] = {}
        if group_ids:
            body["GroupIds"] = group_ids
        if page is not None:
            body["Page"] = page
        if page_size is not None:
            body["PageSize"] = page_size
        return self._extract_result(self._call_action("ListAssets", body))

    def update_asset(self, asset_id: str, name: Optional[str] = None) -> Dict[str, Any]:
        """修改素材名称"""
        body: Dict[str, Any] = {"Id": asset_id}
        if name is not None:
            body["Name"] = name
        return self._extract_result(self._call_action("UpdateAsset", body))

    def delete_asset(self, asset_id: str) -> Dict[str, Any]:
        """删除素材（删除后不再出现在 ListAssets 结果中）"""
        return self._extract_result(self._call_action("DeleteAsset", {"Id": asset_id}))

    # ---------- 素材组 CRUD ----------

    def create_asset_group(
        self,
        name: str,
        description: Optional[str] = None,
        group_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """创建素材组（Result: Id / Name / GroupType）"""
        body: Dict[str, Any] = {"Name": name}
        if description:
            body["Description"] = description
        if group_type:
            body["GroupType"] = group_type
        return self._extract_result(self._call_action("CreateAssetGroup", body))

    def get_asset_group(self, group_id: str) -> Dict[str, Any]:
        """查询单个素材组"""
        return self._extract_result(self._call_action("GetAssetGroup", {"Id": group_id}))

    def update_asset_group(
        self,
        group_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Dict[str, Any]:
        """修改素材组（名称/描述）"""
        body: Dict[str, Any] = {"Id": group_id}
        if name is not None:
            body["Name"] = name
        if description is not None:
            body["Description"] = description
        return self._extract_result(self._call_action("UpdateAssetGroup", body))

    def delete_asset_group(self, group_id: str) -> Dict[str, Any]:
        """删除素材组（组下素材将不可用，谨慎调用）"""
        return self._extract_result(self._call_action("DeleteAssetGroup", {"Id": group_id}))

    def list_asset_groups(
        self,
        page: Optional[int] = None,
        page_size: Optional[int] = None,
    ) -> Dict[str, Any]:
        """查询素材组列表（Result: TotalCount / PageNumber / PageSize / Items）"""
        body: Dict[str, Any] = {}
        if page is not None:
            body["Page"] = page
        if page_size is not None:
            body["PageSize"] = page_size
        return self._extract_result(self._call_action("ListAssetGroups", body))

    # ---------- 真人活体认证（需账号开通「私域真人」能力） ----------

    def create_visual_validate_session(self, callback_url: Optional[str] = None) -> Dict[str, Any]:
        """
        创建真人活体认证会话（H5 认证流程入口，暂未接入前端路由）

        Args:
            callback_url: 认证结果回调地址（公网可访问，可选）
        """
        body: Dict[str, Any] = {}
        if callback_url:
            body["CallbackURL"] = callback_url
        return self._extract_result(self._call_action("CreateVisualValidateSession", body))

    def get_visual_validate_result(self, byted_token: str) -> Dict[str, Any]:
        """
        获取真人活体认证结果（BytedToken 换认证状态与真人素材组 GroupId）
        """
        return self._extract_result(
            self._call_action("GetVisualValidateResult", {"BytedToken": byted_token})
        )

    # ---------- 轮询等待 ----------

    def wait_asset_active(
        self,
        asset_id: str,
        timeout: Optional[float] = None,
        poll_interval: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        轮询等待素材变为 Active（官方建议间隔 1 秒以上）

        Returns:
            Active 状态的素材 Result dict

        Raises:
            SeedanceAssetError: 素材 Failed 或等待超时
        """
        deadline = time.time() + (timeout or SEEDANCE_ASSET_WAIT_ACTIVE_TIMEOUT_SECONDS)
        interval = poll_interval or SEEDANCE_ASSET_POLL_INTERVAL_SECONDS
        while True:
            asset = self.get_asset(asset_id)
            status = asset.get("Status")
            if status == ASSET_STATUS_ACTIVE:
                return asset
            if status == ASSET_STATUS_FAILED:
                raise SeedanceAssetError(
                    f"素材处理失败: {asset_id}", code="AssetFailed"
                )
            if time.time() >= deadline:
                raise SeedanceAssetError(
                    f"等待素材 Active 超时: {asset_id}", code="AssetWaitTimeout"
                )
            time.sleep(interval)
