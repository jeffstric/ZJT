# -*- coding: utf-8 -*-
"""
Seedance 真人素材处理三模式 mixin（供应商无关，按中转站组配置分派）

「用户勾选处理人脸」后按实现方所属供应商组的 human_asset_mode 三选一：
- face_mask（默认）：本地人脸遮盖预处理，由 server/storyboard 侧 pipeline 完成，
  驱动不做任何处理（遮盖互斥：本 mixin 不介入）
- asset_library：原图上传官方真人库（素材 Action 接口）→ asset:// 引用
- param_pass：原图直传，payload 注入 human_review=true（如 huimengi 网关）

决策输入只有「extra_config.enable_face_mask（用户勾选）+ 组模式」，human_review
不再是跨实现方流转的语义载体：失败重试切换实现方后按新实现方的模式现场重算，
不会残留旧实现方的处理方式（此前 extra_config.human_review 固化导致的错配根源）。

接入方式：驱动类混入本 mixin 并声明 `_human_asset_config_group = "<配置组名>"`
（None = 不接入，恒为 face_mask 模式），后台配置组内三键：
- <group>.human_asset_mode：face_mask / asset_library / param_pass
- <group>.asset_base_url：素材库地址（asset_base_url > base_url 回落，同址网关免配）
- <group>.asset_api_key：素材 Token（缺省回落 <group>.api_key）
"""
import logging
from typing import Any, Dict, List, Optional

from config.config_util import get_dynamic_config_value
from config.constant import (
    SEEDANCE_ASSET_URL_SCHEME,
    SEEDANCE_HUMAN_ASSET_MODES,
    SEEDANCE_HUMAN_ASSET_MODE_ASSET_LIBRARY,
    SEEDANCE_HUMAN_ASSET_MODE_DEFAULT,
    SEEDANCE_HUMAN_ASSET_MODE_FACE_MASK,
    SEEDANCE_HUMAN_ASSET_MODE_PARAM_PASS,
)
from utils.seedance_asset_client import (
    SeedanceAssetClient,
    SeedanceAssetError,
    create_seedance_asset_client,
)
from .face_mask_prompt import strip_face_mask_hint

logger = logging.getLogger(__name__)

# content 条目 type → 素材库 AssetType（真人素材上传素材库时的类型映射）
_ASSET_TYPE_BY_CONTENT_TYPE = {
    "image_url": "Image",
    "video_url": "Video",
    "audio_url": "Audio",
}


def read_human_asset_mode(config_group: Optional[str]) -> str:
    """
    读供应商组的真人素材模式；无组 / 未配置 / 非法值一律回落 face_mask。

    server/storyboard 闸门与驱动 mixin 共用本函数，保证两侧对同一实现方
    解析出一致的模式（跳遮盖与驱动分派不会各说各话）。
    """
    if not config_group:
        return SEEDANCE_HUMAN_ASSET_MODE_FACE_MASK
    mode = get_dynamic_config_value(
        config_group, "human_asset_mode", default=SEEDANCE_HUMAN_ASSET_MODE_DEFAULT
    )
    if mode not in SEEDANCE_HUMAN_ASSET_MODES:
        logger.warning(
            "真人素材模式配置非法: %s.human_asset_mode=%r，回落 %s",
            config_group, mode, SEEDANCE_HUMAN_ASSET_MODE_DEFAULT,
        )
        return SEEDANCE_HUMAN_ASSET_MODE_DEFAULT
    return mode


class SeedanceHumanAssetMixin:
    """
    Seedance 真人素材三模式处理 mixin（模板方法模式，无 MRO 依赖）。

    宿主驱动在 build_create_request 的 return 前调用 `_apply_human_asset_pipeline`
    （按模式分派，face_mask/未勾选原样返回），在 check_status 的终态分支调用
    `_cleanup_assets_if_terminal`（回收素材）。asset_library 的 content 媒体替换
    默认按火山方舟 content[] 结构实现，payload 结构不同的网关可覆盖
    `_convert_content_to_asset_refs` / `_inject_human_review_param` 钩子。
    """

    # 供应商配置组名（None = 未接入，恒为 face_mask）。子类按需声明。
    _human_asset_config_group: Optional[str] = None

    # 写死的真人素材模式（None = 按组配置 human_asset_mode 分派）。供应商模式唯一、
    # 无需用户选择时声明（如 TopenRouter 恒为 asset_library），声明后忽略组配置，
    # 提交闸门（driver_factory.resolve_human_asset_mode）与驱动分派共用本约定。
    _human_asset_mode_fixed: Optional[str] = None

    def _resolve_human_asset_mode(self) -> str:
        if self._human_asset_mode_fixed:
            return self._human_asset_mode_fixed
        return read_human_asset_mode(self._human_asset_config_group)

    @staticmethod
    def _should_handle_human(extra_config: Dict[str, Any]) -> bool:
        """用户是否勾选「处理人脸」（enable_face_mask 为用户原始意图，随任务流转）"""
        return bool(extra_config.get('enable_face_mask'))

    # ---------- asset_library：素材上传与 asset:// 引用 ----------

    def _get_asset_client(self) -> SeedanceAssetClient:
        """懒建素材客户端（实例缓存）。配置缺失抛 SeedanceAssetError，由提交分派转为错误。"""
        client = getattr(self, '_asset_client_instance', None)
        if client is None:
            client = create_seedance_asset_client(self._human_asset_config_group)
            self._asset_client_instance = client
        return client

    def _convert_content_to_asset_refs(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        将 content 中的图片/视频/音频公网 URL 上传真人库并替换为 asset:// 引用。

        素材需等待 Active 才可用于视频生成；上传/等待失败直接抛错由调用方转为
        SYSTEM 错误（不静默降级直传 URL：真人素材直传会触发上游敏感风控）。
        同时清理 text 条目中残留的人脸遮盖还原句（跨实现方重试时遮盖 pipeline
        可能已写入，与素材库加白语义冲突）。
        """
        client = self._get_asset_client()
        content = payload.get("content")
        if not isinstance(content, list):
            return payload
        for item in content:
            item_type = item.get("type")
            if item_type == "text":
                text = item.get("text")
                if isinstance(text, str):
                    item["text"] = strip_face_mask_hint(text)
                continue
            asset_type = _ASSET_TYPE_BY_CONTENT_TYPE.get(item_type)
            media = item.get(item_type)
            url = media.get("url") if isinstance(media, dict) else None
            if not asset_type or not url or url.startswith(SEEDANCE_ASSET_URL_SCHEME):
                continue
            asset = client.create_asset(url=url, asset_type=asset_type)
            asset_id = asset.get("Id")
            if not asset_id:
                raise SeedanceAssetError(f"素材接口未返回 Id: {url}")
            client.wait_asset_active(asset_id)
            self._record_created_asset(asset_id)
            media["url"] = f"{SEEDANCE_ASSET_URL_SCHEME}{asset_id}"
            self.logger.info(
                f"[{self.driver_name}] 真人素材已上传素材库: {url} -> {media['url']}"
            )
        return payload

    # ---------- param_pass：human_review 参数注入 ----------

    def _inject_human_review_param(self, request_params: Dict[str, Any]) -> None:
        """
        param_pass 模式注入 human_review 参数（就地修改）。

        默认按火山方舟同构网关形状注入顶层 json.human_review；
        payload 结构不同的网关（如 huimengi 的 params 嵌套）覆盖本钩子。
        """
        payload = request_params.get("json")
        if isinstance(payload, dict):
            payload["human_review"] = True

    # ---------- 素材生命周期：任务终态回收 ----------

    def _record_created_asset(self, asset_id: str) -> None:
        """记录本次任务创建的素材 id，供终态清理（驱动实例为单任务实例化）"""
        created = getattr(self, '_created_asset_ids', None)
        if created is None:
            created = []
            self._created_asset_ids = created
        created.append(asset_id)

    def _cleanup_created_assets(self) -> None:
        """删除本次任务创建的素材（视频生成时已被服务端消费，终态后无保留价值）"""
        asset_ids: List[str] = getattr(self, '_created_asset_ids', None) or []
        if not asset_ids:
            return
        self._created_asset_ids = []
        try:
            client = self._get_asset_client()
        except SeedanceAssetError as e:
            self.logger.warning(f"[{self.driver_name}] 素材清理跳过（客户端不可用）: {e.message}")
            return
        for asset_id in asset_ids:
            try:
                client.delete_asset(asset_id)
            except SeedanceAssetError as e:
                # 清理失败不影响任务结果，仅记录
                self.logger.warning(
                    f"[{self.driver_name}] 素材清理失败: {asset_id} ({e.message})"
                )

    # ---------- 提交/查询分派（模板方法：由宿主 build_create_request return 处调用） ----------

    def _apply_human_asset_pipeline(self, request_params: Dict[str, Any], ai_tool) -> Dict[str, Any]:
        """
        真人素材统一入口：按实现方模式分派，face_mask / 未勾选时原样返回。

        宿主驱动的 build_create_request 在 return 前调用本方法（模板方法模式，
        不依赖 MRO 包装——宿主自己定义了 build_create_request，mixin 覆盖会被遮蔽）。
        """
        if not isinstance(request_params, dict) or request_params.get("success") is False:
            return request_params

        mode = self._resolve_human_asset_mode()
        if mode == SEEDANCE_HUMAN_ASSET_MODE_FACE_MASK:
            return request_params

        parser = getattr(self, '_parse_extra_config', None)
        extra_config = parser(ai_tool) if callable(parser) else {}
        if not self._should_handle_human(extra_config):
            return request_params

        if mode == SEEDANCE_HUMAN_ASSET_MODE_ASSET_LIBRARY:
            try:
                request_params["json"] = self._convert_content_to_asset_refs(
                    request_params.get("json") or {}
                )
            except SeedanceAssetError as e:
                # 素材上传/等待失败：系统级错误，可重试；不降级直传（真人风控）
                self.logger.error(f"[{self.driver_name}] 真人素材上传素材库失败: {e.message}")
                self._send_alert(
                    alert_type="ASSET_UPLOAD_FAILED",
                    message=f"真人素材库上传失败: {e.message}",
                    context={"task_id": getattr(ai_tool, 'id', None), "code": e.code, "http_status": e.http_status}
                )
                return {
                    "success": False,
                    "error": "真人素材上传失败，请稍后重试",
                    "error_type": "SYSTEM",
                    "error_detail": e.message,
                    "retry": True
                }
        elif mode == SEEDANCE_HUMAN_ASSET_MODE_PARAM_PASS:
            self._inject_human_review_param(request_params)
        return request_params

    def _cleanup_assets_if_terminal(self, status: Any) -> None:
        """
        任务到达终态时回收素材（宿主 check_status 的状态映射处调用）。

        兼容两种传参：volcengine 系映射后的小写状态（succeeded/failed，cancelled/
        expired 已被 _map_task_status 归并为 failed）与 huimengi 的原始大写状态
        （COMPLETED/FAILED）。
        """
        if status in ("succeeded", "failed", "SUCCESS", "FAILED", "COMPLETED"):
            self._cleanup_created_assets()
