"""Asset promotion helpers for public marketing publications."""

from __future__ import annotations

import json
import logging
import mimetypes
import os
import shutil
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse

from config.media_file_policy import MediaFilePolicy
from model.media_file_mapping import MediaFileMappingModel
from utils.media_mapping_util import extract_local_path_from_url

logger = logging.getLogger(__name__)


class PublicationAssetError(RuntimeError):
    """Raised when a generated asset cannot be promoted to long-lived storage."""


class MarketingPublicationAssetService:
    """Promote expiring generation files into the public publication asset area."""

    PUBLIC_UPLOAD_PREFIX = "upload/marketing_publications"
    MARKETING_PUBLICATION_ENTITY = 6

    @classmethod
    def promote_assets(
        cls,
        ai_tool: Any,
        publication_id: int,
        root_dir: Optional[Path] = None,
    ) -> Dict[str, Any]:
        root = Path(root_dir) if root_dir is not None else Path(__file__).resolve().parent.parent
        dest_dir = root / cls.PUBLIC_UPLOAD_PREFIX / str(publication_id)
        dest_dir.mkdir(parents=True, exist_ok=True)

        promoted: Dict[str, str] = {}
        result_url = cls._promote_url(
            getattr(ai_tool, "result_url", None),
            dest_dir,
            root,
            publication_id,
            "result",
            getattr(ai_tool, "user_id", None),
        )
        if not result_url:
            raise PublicationAssetError("Generated result file is missing or cannot be promoted")
        promoted[getattr(ai_tool, "result_url", "")] = result_url

        reference_urls: List[str] = []
        for idx, url in enumerate(cls._collect_reference_urls(ai_tool), start=1):
            promoted_ref = cls._promote_url(
                url,
                dest_dir,
                root,
                publication_id,
                f"reference_{idx}",
                getattr(ai_tool, "user_id", None),
            )
            promoted[url] = promoted_ref
            reference_urls.append(promoted_ref)

        audio_urls = cls._promote_multi_path(
            getattr(ai_tool, "audio_path", None),
            dest_dir,
            root,
            publication_id,
            "audio",
            getattr(ai_tool, "user_id", None),
            promoted,
        )
        video_urls = cls._promote_multi_path(
            getattr(ai_tool, "video_path", None),
            dest_dir,
            root,
            publication_id,
            "video",
            getattr(ai_tool, "user_id", None),
            promoted,
        )

        params_snapshot = cls._build_params_snapshot(
            ai_tool,
            result_url=result_url,
            reference_images=reference_urls,
            audio_urls=audio_urls,
            video_urls=video_urls,
        )

        return {
            "result_url": result_url,
            "cover_url": result_url,
            "reference_images": reference_urls,
            "audio_urls": audio_urls,
            "video_urls": video_urls,
            "params_snapshot": params_snapshot,
        }

    @classmethod
    def _collect_reference_urls(cls, ai_tool: Any) -> List[str]:
        urls: List[str] = []
        image_path = getattr(ai_tool, "image_path", None)
        if image_path:
            urls.extend(cls._split_path_list(image_path))

        reference_images = getattr(ai_tool, "reference_images", None)
        if reference_images:
            try:
                parsed = json.loads(reference_images) if isinstance(reference_images, str) else reference_images
                if isinstance(parsed, list):
                    urls.extend(str(item) for item in parsed if item)
            except (TypeError, ValueError):
                urls.extend(cls._split_path_list(str(reference_images)))

        seen = set()
        deduped = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                deduped.append(url)
        return deduped

    @classmethod
    def _promote_multi_path(
        cls,
        value: Optional[str],
        dest_dir: Path,
        root: Path,
        publication_id: int,
        label_prefix: str,
        user_id: Optional[int],
        promoted_map: Dict[str, str],
    ) -> List[str]:
        promoted_urls = []
        for idx, url in enumerate(cls._split_path_list(value), start=1):
            label = f"{label_prefix}_{idx}"
            promoted_url = cls._promote_url(url, dest_dir, root, publication_id, label, user_id)
            promoted_map[url] = promoted_url
            promoted_urls.append(promoted_url)
        return promoted_urls

    @staticmethod
    def _split_path_list(value: Optional[str]) -> List[str]:
        if not value:
            return []
        return [part.strip() for part in str(value).split(",") if part.strip()]

    @classmethod
    def _promote_url(
        cls,
        url: Optional[str],
        dest_dir: Path,
        root: Path,
        publication_id: int,
        label: str,
        user_id: Optional[int],
    ) -> str:
        if not url:
            raise PublicationAssetError(f"Asset '{label}' is missing")

        ext = cls._extension_from_url(url, label)
        dest_path = dest_dir / f"{label}{ext}"

        local_upload_path = extract_local_path_from_url(url)
        if local_upload_path:
            source_path = root / local_upload_path.replace("/", os.sep)
            if not source_path.exists() or not source_path.is_file():
                raise PublicationAssetError(f"Source file not found: {url}")
            shutil.copy2(source_path, dest_path)
        elif cls._is_http_url(url):
            try:
                with urllib.request.urlopen(url, timeout=60) as response, open(dest_path, "wb") as out:
                    shutil.copyfileobj(response, out)
            except Exception as exc:
                raise PublicationAssetError(f"Failed to download asset: {url}") from exc
        else:
            source_path = Path(url)
            if not source_path.is_absolute():
                source_path = root / source_path
            if not source_path.exists() or not source_path.is_file():
                raise PublicationAssetError(f"Source file not found: {url}")
            shutil.copy2(source_path, dest_path)

        public_url = f"/{cls.PUBLIC_UPLOAD_PREFIX}/{publication_id}/{dest_path.name}"
        cls._create_media_mapping(user_id, publication_id, public_url, dest_path, url, label)
        return public_url

    @staticmethod
    def _is_local_upload_url(url: str) -> bool:
        return url.startswith("/upload/")

    @staticmethod
    def _is_http_url(url: str) -> bool:
        parsed = urlparse(url)
        return parsed.scheme in ("http", "https")

    @staticmethod
    def _extension_from_url(url: str, label: str) -> str:
        parsed_path = urlparse(url).path
        ext = Path(parsed_path).suffix
        if ext:
            return ext
        if label.startswith("video"):
            return ".mp4"
        if label.startswith("audio"):
            return ".mp3"
        return ".png"

    @staticmethod
    def _create_media_mapping(
        user_id: Optional[int],
        publication_id: int,
        public_url: str,
        file_path: Path,
        original_url: str,
        label: str,
    ) -> int:
        local_path = public_url.lstrip("/")
        media_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        mapping_id = MediaFileMappingModel.create(
            user_id=user_id,
            local_path=local_path,
            cloud_path=None,
            policy_code=MediaFilePolicy.NEVER_EXPIRE,
            entity_type=MarketingPublicationAssetService.MARKETING_PUBLICATION_ENTITY,
            source_id=publication_id,
            media_type=media_type,
            original_url=original_url,
            file_size=file_path.stat().st_size,
            label=label,
        )
        # 建立映射后异步触发 CDN 上传（仅启用时）；完成后由 cdn_redirect_middleware
        # 将 /upload/... 请求透明 302 到 CDN，前端无需感知 URL 变化。
        if local_path:
            MarketingPublicationAssetService._trigger_cdn_upload(mapping_id, local_path)
        return mapping_id

    @staticmethod
    def _trigger_cdn_upload(mapping_id: int, local_path: str) -> None:
        """异步触发 CDN 上传（fire-and-forget，守护线程执行，不阻塞调用方）。

        仅在 ``server.auto_upload_to_cdn`` 启用时上传。上传完成后由 server.py 的
        ``cdn_redirect_middleware`` 将 ``/upload/...`` 请求透明 302 重定向到 CDN 签名 URL，
        因此发布时仍写入本地路径，前端与中间件配合即可访问 CDN。
        """
        try:
            from config.config_util import get_config

            if not get_config().get("server", {}).get("auto_upload_to_cdn", False):
                return

            import threading
            from utils.cdn_util import CDNUtil

            threading.Thread(
                target=CDNUtil.trigger_cdn_upload,
                args=(mapping_id, local_path),
                daemon=True,
                name=f"mp-cdn-upload-{mapping_id}",
            ).start()
        except Exception as exc:
            logger.warning("触发营销灵感 CDN 上传失败 (mapping_id=%s): %s", mapping_id, exc)

    @classmethod
    def _build_params_snapshot(
        cls,
        ai_tool: Any,
        result_url: str,
        reference_images: List[str],
        audio_urls: List[str],
        video_urls: List[str],
    ) -> Dict[str, Any]:
        extra_config = cls._parse_json_object(getattr(ai_tool, "extra_config", None))
        task_config = cls._get_task_config(getattr(ai_tool, "type", None))
        category = getattr(task_config, "category", None)
        mode, media_type = cls._mode_from_category(category, result_url)
        media = cls._build_input_media(reference_images=reference_images, video_urls=video_urls)

        snapshot = {
            "mode": mode,
            "media_type": media_type,
            "task_id": getattr(ai_tool, "type", None),
            "model_key": getattr(task_config, "key", None),
            "model_name": getattr(task_config, "name", None),
            "ratio": getattr(ai_tool, "ratio", None),
            "resolution": getattr(ai_tool, "image_size", None),
            "duration": getattr(ai_tool, "duration", None),
            "video_mode": extra_config.get("image_mode") or extra_config.get("video_mode"),
            "prompt": getattr(ai_tool, "prompt", None),
            "reference_images": reference_images,
            "audio_urls": audio_urls,
            "video_urls": video_urls,
            "media": media,
            "result_url": result_url,
        }
        return {key: value for key, value in snapshot.items() if value not in (None, "", [], {})}

    @staticmethod
    def _build_input_media(reference_images: List[str], video_urls: List[str]) -> List[Dict[str, str]]:
        media: List[Dict[str, str]] = []
        for url in reference_images:
            media.append({
                "type": "image",
                "serverUrl": url,
                "thumbnailUrl": url,
            })
        for url in video_urls:
            media.append({
                "type": "video",
                "serverUrl": url,
                "thumbnailUrl": url,
            })
        return media

    @staticmethod
    def _parse_json_object(value: Any) -> Dict[str, Any]:
        if isinstance(value, dict):
            return value
        if not value:
            return {}
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, ValueError):
            return {}

    @staticmethod
    def _get_task_config(task_id: Optional[int]) -> Any:
        if task_id is None:
            return None
        try:
            from config.unified_config import UnifiedConfigRegistry
            return UnifiedConfigRegistry.get_by_id(task_id)
        except Exception:
            return None

    @staticmethod
    def _mode_from_category(category: Optional[str], result_url: str) -> Tuple[str, str]:
        if category in ("text_to_video", "image_to_video", "digital_human"):
            return "video", "video"
        if Path(urlparse(result_url).path).suffix.lower() in (".mp4", ".webm", ".mov", ".avi", ".mkv"):
            return "video", "video"
        return "image", "image"
