"""Pipeline driver for splitting storyboard first-frame grid images."""
from __future__ import annotations

import logging
import os
import uuid
from typing import Any, Dict, List, Optional

from config.config_util import get_config
from config.constant import GridConfig, StoryboardAutoGenerateConstants
from model import AITool, PipelineStep
from model.storyboard_image_batch import StoryboardImageBatchItemModel
from model.storyboard_scene_asset import StoryboardSceneAssetModel
from script_writer_core.image_grid_splitter import ImageGridSplitter
from utils.project_path import get_project_root, resolve_upload_url_to_local_path

from .base_pipeline_driver import BasePipelineDriver

logger = logging.getLogger(__name__)


class StoryboardGridSplitPipelineDriver(BasePipelineDriver):
    """Split one grid result into storyboard first-frame assets."""

    def __init__(self) -> None:
        super().__init__("storyboard_first_frame_grid_split")

    async def execute(self, step: PipelineStep, ai_tool: AITool) -> Dict[str, Any]:
        params = step.get_params_dict()
        source_url = params.get("grid_result_url") or getattr(ai_tool, "result_url", None)
        grid_path = self._resolve_grid_path(params.get("grid_image_path") or source_url)
        if not grid_path:
            return {"success": False, "error": "缺少宫格图片地址"}
        if not os.path.exists(grid_path):
            return {"success": False, "error": f"宫格图片不存在: {grid_path}"}

        try:
            grid_size = int(params.get("grid_size") or GridConfig.SIZE_2X2)
        except (TypeError, ValueError):
            grid_size = GridConfig.SIZE_2X2
        if grid_size not in GridConfig.VALID_SIZES:
            return {"success": False, "error": f"不支持的 grid_size={grid_size}"}

        cells = self._normalize_cells(params.get("cells"), grid_size)
        output_dir = self._resolve_output_dir(params.get("output_dir") or "upload/storyboard/first_frame")
        output_url_path = str(params.get("output_url_path") or "upload/storyboard/first_frame").strip("/")
        os.makedirs(output_dir, exist_ok=True)

        split_paths = ImageGridSplitter().split_grid(
            grid_image_path=grid_path,
            output_dir=output_dir,
            grid_size=grid_size,
            output_names=[str(uuid.uuid4()) for _ in range(grid_size)],
            output_format="png",
        )

        created_assets: List[Dict[str, Any]] = []
        skipped_cells: List[int] = []
        failed_cells: List[Dict[str, Any]] = []
        grid_task_id = self._safe_int(params.get("grid_task_id"))
        ai_tool_id = self._safe_int(getattr(ai_tool, "id", None))

        for cell in cells:
            grid_index = self._safe_int(cell.get("grid_index"))
            if grid_index is None or grid_index < 0 or grid_index >= len(split_paths):
                skipped_cells.append(grid_index if grid_index is not None else -1)
                continue
            scene_id = self._safe_int(cell.get("scene_id"))
            if cell.get("placeholder") or not scene_id:
                skipped_cells.append(grid_index)
                continue

            result_url = self._build_result_url(split_paths[grid_index], output_url_path)
            batch_item = self._resolve_batch_item(cell, grid_task_id, scene_id)
            try:
                asset_id = StoryboardSceneAssetModel.create(
                    scene_id,
                    "first_frame",
                    ai_tool_id=ai_tool_id,
                    result_url=result_url,
                )
                StoryboardSceneAssetModel.set_selected(scene_id, "first_frame", asset_id)

                # 触发首帧单图 CDN 分发（auto_upload_to_cdn 开启时建 mapping + 异步上传）
                _ensure_asset_media_mapping(ai_tool, asset_id, "first_frame", result_url)

                if batch_item:
                    extra = batch_item.get("extra_json") if isinstance(batch_item.get("extra_json"), dict) else {}
                    StoryboardImageBatchItemModel.update(
                        int(batch_item["id"]),
                        status=StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_COMPLETED,
                        ai_tool_id=ai_tool_id,
                        asset_id=asset_id,
                        result_url=result_url,
                        extra_json={
                            **extra,
                            "asset_id": asset_id,
                            "result_url": result_url,
                            "grid_split_step_id": step.id,
                        },
                    )
                else:
                    logger.warning(
                        "Storyboard grid split created asset but no batch item was found: "
                        "grid_task_id=%s scene_id=%s grid_index=%s",
                        grid_task_id,
                        scene_id,
                        grid_index,
                    )

                created_assets.append(
                    {
                        "grid_index": grid_index,
                        "scene_id": scene_id,
                        "asset_id": asset_id,
                        "result_url": result_url,
                    }
                )
            except Exception as exc:
                message = str(exc)[:512]
                logger.error(
                    "Storyboard grid split cell failed: grid_task_id=%s scene_id=%s grid_index=%s error=%s",
                    grid_task_id,
                    scene_id,
                    grid_index,
                    message,
                    exc_info=True,
                )
                failed_cells.append({"grid_index": grid_index, "scene_id": scene_id, "error": message})
                if batch_item:
                    extra = batch_item.get("extra_json") if isinstance(batch_item.get("extra_json"), dict) else {}
                    StoryboardImageBatchItemModel.update(
                        int(batch_item["id"]),
                        status=StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_FAILED,
                        error_code=StoryboardAutoGenerateConstants.ERROR_GRID_FIRST_FRAME_FAILED,
                        error_message=message,
                        extra_json={**extra, "grid_split_step_id": step.id},
                    )

        if failed_cells and not created_assets:
            return {
                "success": False,
                "error": f"分镜首帧宫格切图回写全部失败: {failed_cells[0]['error']}",
                "result_data": {"failed_cells": failed_cells, "skipped_cells": skipped_cells},
            }

        return {
            "success": True,
            "result_data": {
                "source_url": source_url,
                "grid_path": grid_path,
                "created_assets": created_assets,
                "skipped_cells": skipped_cells,
                "failed_cells": failed_cells,
            },
        }

    def _resolve_grid_path(self, value: Any) -> Optional[str]:
        if not value:
            return None
        text = str(value)
        if os.path.exists(text):
            return text
        return resolve_upload_url_to_local_path(text)

    def _resolve_output_dir(self, value: str) -> str:
        if os.path.isabs(value):
            return value
        return os.path.join(get_project_root(), value)

    def _build_result_url(self, path: str, output_url_path: str) -> str:
        host = str(get_config().get("server", {}).get("host") or "").rstrip("/")
        filename = os.path.basename(path)
        suffix = f"{output_url_path}/{filename}".lstrip("/")
        return f"{host}/{suffix}" if host else f"/{suffix}"

    def _normalize_cells(self, raw_cells: Any, grid_size: int) -> List[Dict[str, Any]]:
        cells = raw_cells if isinstance(raw_cells, list) else []
        normalized: List[Dict[str, Any]] = []
        for index in range(grid_size):
            cell = cells[index] if index < len(cells) and isinstance(cells[index], dict) else {}
            grid_index = self._safe_int(cell.get("grid_index"))
            normalized.append({**cell, "grid_index": index if grid_index is None else grid_index})
        return normalized

    def _resolve_batch_item(
        self,
        cell: Dict[str, Any],
        grid_task_id: Optional[int],
        scene_id: int,
    ) -> Optional[Dict[str, Any]]:
        batch_item_id = self._safe_int(cell.get("batch_item_id"))
        if batch_item_id:
            try:
                item = StoryboardImageBatchItemModel.get_by_id(batch_item_id)
                if isinstance(item, dict) and item.get("id"):
                    return item
            except Exception as exc:
                logger.warning("Failed to load storyboard batch item %s: %s", batch_item_id, exc)
            return {"id": batch_item_id, "extra_json": cell.get("extra_json") or {}}
        if grid_task_id:
            item = StoryboardImageBatchItemModel.find_running_by_grid_task(grid_task_id, scene_id)
            if item:
                return item
            return StoryboardImageBatchItemModel.find_by_grid_task(grid_task_id, scene_id)
        return None

    @staticmethod
    def _safe_int(value: Any) -> Optional[int]:
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None


def _ensure_asset_media_mapping(
    ai_tool: Any,
    asset_id: int,
    asset_type: str,
    result_url: str,
) -> Optional[int]:
    """为分镜资产生成的媒体文件建立 CDN 媒体映射（图床分发降带宽）。

    仅当 server.auto_upload_to_cdn 开启且 result_url 指向本服务 /upload/ 路径时生效：
    - 建 media_file_mapping 记录（entity_type=STORYBOARD_SCENE_ASSET, source_id=asset_id）
    - 触发 CDNUtil.trigger_cdn_upload 异步上传到七牛云 qiniu_long_term 桶
    - 回写 storyboard_scene_asset.media_mapping_id

    之后前端访问 /upload/xxx.{媒体扩展名} 时，cdn_redirect_middleware（server.py）
    会查到该映射并 302 重定向到签名 CDN URL，从而降低业务机带宽。

    幂等：按 local_path_hash 查已有 active mapping，命中则复用、不重建、不重传。
    注：storyboard asset 的 result_url 为 uuid 命名的唯一文件，每次拆图生成新 asset_id
    与新 local_path，因此 (entity_type=STORYBOARD_SCENE_ASSET, source_id=asset_id, label)
    三元组在新 mapping 创建时不会与历史记录冲突 uk_entity_label 唯一键。

    任何异常都只记 warning 并返回 None，绝不影响 asset 创建/选中的主流程。

    Args:
        ai_tool: 关联的 AITool 实体（用于读取 user_id）
        asset_id: storyboard_scene_asset.id
        asset_type: 资产类型（first_frame / last_frame / video），用作 mapping label
        result_url: 资产结果 URL（支持 {host}/upload/... 带前缀或 /upload/... 相对路径）

    Returns:
        mapping_id (int)，跳过/失败返回 None
    """
    try:
        from config.config_util import get_config
        if not get_config().get("server", {}).get("auto_upload_to_cdn", False):
            return None

        from utils.media_mapping_util import extract_local_path_from_url
        local_path = extract_local_path_from_url(result_url)
        if not local_path:
            # 非 /upload/ 路径（如外网 URL），无需建 CDN 映射
            return None

        from model.media_file_mapping import (
            MediaFileMappingModel,
            MediaFileEntity,
        )
        from config.media_file_policy import MediaFilePolicy
        from utils.cdn_util import CDNUtil
        from utils.mime_type import get_mime_type_from_extension
        from utils.project_path import get_project_root

        # 幂等：按 local_path_hash 查已有 active mapping
        existing = MediaFileMappingModel.get_by_local_path_hash(
            MediaFileMappingModel._compute_local_path_hash(local_path)
        )
        if existing:
            mapping_id = existing.id
            # 复用已有 mapping，同时确保 asset 表回写指向它（update 幂等，值相同无副作用）
            try:
                StoryboardSceneAssetModel.update_media_mapping_id(asset_id, mapping_id)
            except Exception as sync_err:
                logger.warning(
                    "Storyboard asset CDN mapping 回写失败(非阻塞): asset_id=%s mapping_id=%s err=%s",
                    asset_id, mapping_id, sync_err,
                )
            logger.info(
                "Storyboard asset 复用已有 CDN mapping: asset_id=%s mapping_id=%s local_path=%s",
                asset_id, mapping_id, local_path,
            )
            return mapping_id

        ext = os.path.splitext(result_url)[1].lower()
        media_type = get_mime_type_from_extension(ext)

        file_size = None
        try:
            abs_path = os.path.join(get_project_root(), local_path)
            if os.path.exists(abs_path):
                file_size = os.path.getsize(abs_path)
        except Exception as size_err:
            logger.warning("无法获取文件 %s 大小: %s", local_path, size_err)

        mapping_id = MediaFileMappingModel.create(
            user_id=getattr(ai_tool, "user_id", None),
            local_path=local_path,
            cloud_path=None,
            policy_code=MediaFilePolicy.MEDIA_CACHE,
            entity_type=MediaFileEntity.STORYBOARD_SCENE_ASSET,
            source_id=asset_id,
            media_type=media_type,
            original_url=result_url,
            file_size=file_size,
            label=asset_type,
        )

        # trigger_cdn_upload 内部用 `with ThreadPoolExecutor()`（shutdown(wait=True)），
        # 直接在 async driver 的 for 循环里调用会串行阻塞每张图的上传。
        # 这里用守护线程 fire-and-forget 包裹，让上传在独立线程进行，
        # driver 立即返回，避免阻塞事件循环（参照 marketing_publication_asset_service
        # 的 _trigger_cdn_upload 范式，符合 AGENTS.md 第 1/10 条）。
        import threading
        threading.Thread(
            target=CDNUtil.trigger_cdn_upload,
            args=(mapping_id, local_path),
            daemon=True,
            name=f"sb-cdn-upload-{mapping_id}",
        ).start()

        try:
            StoryboardSceneAssetModel.update_media_mapping_id(asset_id, mapping_id)
        except Exception as sync_err:
            logger.warning(
                "Storyboard asset CDN mapping 回写失败(非阻塞): asset_id=%s mapping_id=%s err=%s",
                asset_id, mapping_id, sync_err,
            )

        logger.info(
            "Storyboard asset 创建 CDN mapping: asset_id=%s mapping_id=%s local_path=%s",
            asset_id, mapping_id, local_path,
        )
        return mapping_id
    except Exception as exc:
        logger.warning(
            "Storyboard asset CDN mapping 失败(非阻塞): asset_id=%s result_url=%s err=%s",
            asset_id, result_url, exc,
        )
        return None
