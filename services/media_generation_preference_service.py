"""媒体生成模型偏好、模式判定和不可变快照服务。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional

from config.constant import (
    MediaGenerationErrorCode,
    MediaGenerationMode,
    MediaGenerationPreferenceConstants,
    MediaGenerationSurface,
    MediaGenerationType,
)
from config.unified_config import ImageMode, TaskCategory, UnifiedConfigRegistry
from model.user_preferences import (
    PREF_TYPE_IMAGE_TO_VIDEO_MODEL,
    PREF_TYPE_TEXT_TO_IMAGE_MODEL,
    PREF_TYPE_TEXT_TO_VIDEO_MODEL,
    UserPreferencesModel,
)


@dataclass
class MediaGenerationPreferenceError(ValueError):
    code: str
    message: str
    details: Optional[Dict[str, Any]] = None

    def __str__(self) -> str:
        return self.message

    def to_dict(self) -> Dict[str, Any]:
        result = {"code": self.code, "message": self.message}
        if self.details:
            result["details"] = self.details
        return result


class MediaGenerationPreferenceService:
    """统一管理 3 个入口 × 5 种模式的用户偏好。"""

    PROFILE_FIELDS = {
        "task_id",
        "ratio",
        "resolution",
        "duration_seconds",
        "image_mode",
        "enable_face_mask",
    }
    STORYBOARD_CONFIG_FIELDS = {
        (MediaGenerationType.IMAGE, MediaGenerationMode.TEXT_TO_IMAGE): "selectedTextToImageTaskId",
        (MediaGenerationType.IMAGE, MediaGenerationMode.IMAGE_EDIT): "selectedImageEditTaskId",
        (MediaGenerationType.VIDEO, MediaGenerationMode.TEXT_TO_VIDEO): "selectedTextToVideoTaskId",
        (MediaGenerationType.VIDEO, MediaGenerationMode.IMAGE_TO_VIDEO): "selectedImageToVideoTaskId",
        (MediaGenerationType.VIDEO, MediaGenerationMode.REFERENCE_TO_VIDEO): "selectedReferenceToVideoTaskId",
    }

    @classmethod
    def storyboard_config_field(cls, media_type: str, mode: str) -> str:
        cls.validate_scope(MediaGenerationSurface.STORYBOARD_UI, media_type, mode)
        return cls.STORYBOARD_CONFIG_FIELDS[(media_type, mode)]

    @classmethod
    def preference_type(cls, surface: str, media_type: str, mode: str) -> str:
        cls.validate_scope(surface, media_type, mode)
        value = (
            f"{MediaGenerationPreferenceConstants.PREF_TYPE_PREFIX}."
            f"{surface}.{media_type}.{mode}"
        )
        if len(value) > 64:
            raise ValueError(f"pref_type exceeds varchar(64): {value}")
        return value

    @staticmethod
    def slot_key(media_type: str, mode: str) -> str:
        MediaGenerationPreferenceService.validate_scope(
            MediaGenerationSurface.MARKETING_UI, media_type, mode
        )
        return f"{media_type}.{mode}"

    @staticmethod
    def validate_scope(surface: str, media_type: str, mode: str) -> None:
        if surface not in MediaGenerationSurface.ALL:
            raise ValueError(f"invalid media preference surface: {surface}")
        if media_type not in MediaGenerationType.ALL:
            raise ValueError(f"invalid media type: {media_type}")
        allowed = (
            MediaGenerationMode.IMAGE_MODES
            if media_type == MediaGenerationType.IMAGE
            else MediaGenerationMode.VIDEO_MODES
        )
        if mode not in allowed:
            raise ValueError(f"mode {mode} does not belong to media type {media_type}")

    @staticmethod
    def determine_mode(
        media_type: str,
        *,
        image_urls: Optional[Iterable[Any]] = None,
        reference_image_urls: Optional[Iterable[Any]] = None,
        video_urls: Optional[Iterable[Any]] = None,
        audio_urls: Optional[Iterable[Any]] = None,
        image_mode: Optional[str] = None,
    ) -> str:
        images = MediaGenerationPreferenceService._material_count(image_urls)
        reference_images = MediaGenerationPreferenceService._material_count(reference_image_urls)
        videos = MediaGenerationPreferenceService._material_count(video_urls)
        audios = MediaGenerationPreferenceService._material_count(audio_urls)
        normalized_image_mode = str(image_mode or "").strip().lower()

        if media_type == MediaGenerationType.IMAGE:
            return (
                MediaGenerationMode.IMAGE_EDIT
                if images or reference_images
                else MediaGenerationMode.TEXT_TO_IMAGE
            )
        if media_type != MediaGenerationType.VIDEO:
            raise ValueError(f"invalid media type: {media_type}")
        if (
            videos
            or audios
            or reference_images
            or images > 2
            or normalized_image_mode
            in {
                ImageMode.MULTI_REFERENCE,
                MediaGenerationPreferenceConstants.FIRST_LAST_WITH_REF,
            }
        ):
            return MediaGenerationMode.REFERENCE_TO_VIDEO
        if images:
            return MediaGenerationMode.IMAGE_TO_VIDEO
        return MediaGenerationMode.TEXT_TO_VIDEO

    @staticmethod
    def _material_count(value: Optional[Iterable[Any]]) -> int:
        if value is None:
            return 0
        if isinstance(value, str):
            return len([part for part in value.split(",") if part.strip()])
        try:
            return len([item for item in value if item not in (None, "")])
        except TypeError:
            return 1

    @classmethod
    def validate_model(
        cls,
        task_id: Any,
        media_type: str,
        mode: str,
        *,
        image_mode: Optional[str] = None,
        has_reference_audio_video: bool = False,
        allow_hidden: bool = False,
        expected_model_key: Optional[str] = None,
    ):
        cls.validate_scope(MediaGenerationSurface.MARKETING_UI, media_type, mode)
        try:
            normalized_task_id = int(task_id)
        except (TypeError, ValueError):
            raise MediaGenerationPreferenceError(
                MediaGenerationErrorCode.MODEL_NOT_FOUND,
                f"无效的媒体模型 task_id: {task_id}",
            )
        config = UnifiedConfigRegistry.get_by_id(normalized_task_id)
        if config is None:
            raise MediaGenerationPreferenceError(
                MediaGenerationErrorCode.MODEL_NOT_FOUND,
                f"媒体模型 task_id={normalized_task_id} 不存在",
            )
        if not config.enabled:
            raise MediaGenerationPreferenceError(
                MediaGenerationErrorCode.MODEL_DISABLED,
                f"媒体模型 {config.name} 已禁用",
            )
        if config.hidden and not allow_hidden:
            raise MediaGenerationPreferenceError(
                MediaGenerationErrorCode.MODEL_HIDDEN,
                f"媒体模型 {config.name} 不允许用于新任务",
            )
        if expected_model_key and config.key != expected_model_key:
            raise MediaGenerationPreferenceError(
                MediaGenerationErrorCode.SNAPSHOT_MISMATCH,
                "任务快照中的 task_id 与 model_key 映射已发生变化",
                {
                    "task_id": normalized_task_id,
                    "snapshot_model_key": expected_model_key,
                    "current_model_key": config.key,
                },
            )

        categories = {config.category, *(config.categories or [])}
        required_category = {
            MediaGenerationMode.TEXT_TO_IMAGE: TaskCategory.TEXT_TO_IMAGE,
            MediaGenerationMode.IMAGE_EDIT: TaskCategory.IMAGE_EDIT,
            MediaGenerationMode.TEXT_TO_VIDEO: TaskCategory.TEXT_TO_VIDEO,
            MediaGenerationMode.IMAGE_TO_VIDEO: TaskCategory.IMAGE_TO_VIDEO,
            MediaGenerationMode.REFERENCE_TO_VIDEO: TaskCategory.IMAGE_TO_VIDEO,
        }[mode]
        if required_category not in categories:
            raise MediaGenerationPreferenceError(
                MediaGenerationErrorCode.MODEL_MODE_UNSUPPORTED,
                f"模型 {config.name} 不支持 {mode}",
            )

        supported_modes = set(config.supported_image_modes or [])
        normalized_image_mode = str(image_mode or "").strip().lower()
        if mode == MediaGenerationMode.IMAGE_TO_VIDEO:
            if ImageMode.FIRST_LAST_FRAME not in supported_modes:
                raise MediaGenerationPreferenceError(
                    MediaGenerationErrorCode.MODEL_INPUT_UNSUPPORTED,
                    f"模型 {config.name} 不支持首帧/首尾帧输入",
                )
        elif mode == MediaGenerationMode.REFERENCE_TO_VIDEO:
            if normalized_image_mode == MediaGenerationPreferenceConstants.FIRST_LAST_WITH_REF:
                required_modes = {ImageMode.FIRST_LAST_FRAME, ImageMode.MULTI_REFERENCE}
                if not required_modes.issubset(supported_modes):
                    raise MediaGenerationPreferenceError(
                        MediaGenerationErrorCode.MODEL_INPUT_UNSUPPORTED,
                        f"模型 {config.name} 不支持首尾帧加参考图输入",
                    )
            elif not has_reference_audio_video and ImageMode.MULTI_REFERENCE not in supported_modes:
                raise MediaGenerationPreferenceError(
                    MediaGenerationErrorCode.MODEL_INPUT_UNSUPPORTED,
                    f"模型 {config.name} 不支持多参考图输入",
                )
            if has_reference_audio_video and not config.supports_ref_audio_video:
                raise MediaGenerationPreferenceError(
                    MediaGenerationErrorCode.MODEL_INPUT_UNSUPPORTED,
                    f"模型 {config.name} 不支持参考视频或参考音频",
                )
        return config

    @classmethod
    def save_profile(
        cls,
        user_id: Any,
        world_id: Any,
        surface: str,
        media_type: str,
        mode: str,
        profile: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not isinstance(profile, dict) or profile.get("task_id") in (None, ""):
            raise MediaGenerationPreferenceError(
                MediaGenerationErrorCode.MODEL_REQUIRED,
                "必须选择媒体生成模型",
            )
        config = cls.validate_model(
            profile.get("task_id"),
            media_type,
            mode,
            image_mode=profile.get("image_mode"),
        )
        normalized = {
            key: value
            for key, value in profile.items()
            if key in cls.PROFILE_FIELDS and value is not None
        }
        normalized.update(
            {
                "schema_version": MediaGenerationPreferenceConstants.SCHEMA_VERSION,
                "task_id": int(config.id),
                "model_key": config.key,
                "model_name": config.name,
            }
        )
        UserPreferencesModel.upsert(
            str(user_id),
            str(world_id),
            cls.preference_type(surface, media_type, mode),
            normalized,
        )
        return normalized

    @classmethod
    def get_profile(
        cls,
        user_id: Any,
        world_id: Any,
        surface: str,
        media_type: str,
        mode: str,
        *,
        initialize: bool = True,
    ) -> Optional[Dict[str, Any]]:
        pref = UserPreferencesModel.get(
            str(user_id),
            str(world_id),
            cls.preference_type(surface, media_type, mode),
        )
        if pref and isinstance(pref.get_value(), dict):
            stored = dict(pref.get_value())
            try:
                config = cls.validate_model(
                    stored.get("task_id"),
                    media_type,
                    mode,
                    image_mode=stored.get("image_mode"),
                    expected_model_key=stored.get("model_key"),
                )
                stored.update(
                    {
                        "schema_version": MediaGenerationPreferenceConstants.SCHEMA_VERSION,
                        "task_id": int(config.id),
                        "model_key": config.key,
                        "model_name": config.name,
                    }
                )
                return stored
            except MediaGenerationPreferenceError:
                if not initialize:
                    raise

        if not initialize:
            return None
        legacy_task_id = cls._legacy_task_id(user_id, world_id, surface, media_type, mode)
        if legacy_task_id is not None:
            try:
                return cls.save_profile(
                    user_id,
                    world_id,
                    surface,
                    media_type,
                    mode,
                    {"task_id": legacy_task_id},
                )
            except MediaGenerationPreferenceError:
                pass
        config = cls.default_model(media_type, mode)
        if config is None:
            raise MediaGenerationPreferenceError(
                MediaGenerationErrorCode.MODEL_REQUIRED,
                f"没有可用于 {mode} 的媒体模型",
            )
        return cls.save_profile(
            user_id,
            world_id,
            surface,
            media_type,
            mode,
            {"task_id": config.id},
        )

    @classmethod
    def default_model(cls, media_type: str, mode: str):
        category = {
            MediaGenerationMode.TEXT_TO_IMAGE: TaskCategory.TEXT_TO_IMAGE,
            MediaGenerationMode.IMAGE_EDIT: TaskCategory.IMAGE_EDIT,
            MediaGenerationMode.TEXT_TO_VIDEO: TaskCategory.TEXT_TO_VIDEO,
            MediaGenerationMode.IMAGE_TO_VIDEO: TaskCategory.IMAGE_TO_VIDEO,
            MediaGenerationMode.REFERENCE_TO_VIDEO: TaskCategory.IMAGE_TO_VIDEO,
        }[mode]
        candidates = sorted(
            UnifiedConfigRegistry.get_by_category(category),
            key=lambda config: (config.sort_order, config.id),
        )
        for config in candidates:
            if not config.enabled or config.hidden:
                continue
            try:
                cls.validate_model(
                    config.id,
                    media_type,
                    mode,
                    image_mode=(
                        ImageMode.MULTI_REFERENCE
                        if mode == MediaGenerationMode.REFERENCE_TO_VIDEO
                        else None
                    ),
                )
                return config
            except MediaGenerationPreferenceError:
                continue
        return None

    @classmethod
    def build_snapshot(
        cls,
        profile: Dict[str, Any],
        surface: str,
        media_type: str,
        mode: str,
        *,
        model_source: str,
        has_reference_audio_video: bool = False,
    ) -> Dict[str, Any]:
        config = cls.validate_model(
            profile.get("task_id"),
            media_type,
            mode,
            image_mode=profile.get("image_mode"),
            has_reference_audio_video=has_reference_audio_video,
            expected_model_key=profile.get("model_key"),
        )
        snapshot = dict(profile)
        snapshot.update(
            {
                "schema_version": MediaGenerationPreferenceConstants.SCHEMA_VERSION,
                "surface": surface,
                "media_type": media_type,
                "mode": mode,
                "model_source": model_source,
                "task_id": int(config.id),
                "model_key": config.key,
                "model_name": config.name,
            }
        )
        return snapshot

    @staticmethod
    def _legacy_task_id(
        user_id: Any,
        world_id: Any,
        surface: str,
        media_type: str,
        mode: str,
    ) -> Optional[int]:
        if surface != MediaGenerationSurface.MARKETING_UI:
            return None
        legacy_type = {
            (MediaGenerationType.IMAGE, MediaGenerationMode.TEXT_TO_IMAGE): PREF_TYPE_TEXT_TO_IMAGE_MODEL,
            (MediaGenerationType.IMAGE, MediaGenerationMode.IMAGE_EDIT): PREF_TYPE_TEXT_TO_IMAGE_MODEL,
            (MediaGenerationType.VIDEO, MediaGenerationMode.TEXT_TO_VIDEO): PREF_TYPE_TEXT_TO_VIDEO_MODEL,
            (MediaGenerationType.VIDEO, MediaGenerationMode.IMAGE_TO_VIDEO): PREF_TYPE_IMAGE_TO_VIDEO_MODEL,
            (MediaGenerationType.VIDEO, MediaGenerationMode.REFERENCE_TO_VIDEO): PREF_TYPE_IMAGE_TO_VIDEO_MODEL,
        }.get((media_type, mode))
        if not legacy_type:
            return None
        pref = UserPreferencesModel.get(str(user_id), str(world_id), legacy_type)
        if not pref:
            return None
        value = pref.get_value()
        try:
            return int(value)
        except (TypeError, ValueError):
            return None


__all__ = [
    "MediaGenerationPreferenceError",
    "MediaGenerationPreferenceService",
]
