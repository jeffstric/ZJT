"""Helpers for script-writer database asset library (view / edit / delete)."""
import logging
from typing import Any, Dict, Optional

from model.location import LocationModel
from model.storyboard import StoryboardModel
from model.storyboard_dialogue import StoryboardDialogueModel
from script_writer_core.mcp_tool import get_file_manager

logger = logging.getLogger(__name__)

ASSET_TYPE_CHARACTERS = 'characters'
ASSET_TYPE_LOCATIONS = 'locations'
ASSET_TYPE_PROPS = 'props'
ASSET_TYPE_SCRIPTS = 'scripts'


def owner_user_id_matches(record_user_id: Any, request_user_id: Any) -> bool:
    """Creator-only mutation check. Coerce both sides to int when possible."""
    try:
        return int(record_user_id) == int(request_user_id)
    except (TypeError, ValueError):
        return str(record_user_id) == str(request_user_id)


def delete_staging_asset(
    asset_type: str,
    key: str,
    user_id: str,
    world_id: str,
) -> bool:
    """
    Delete the current user's staging JSON that matches a DB asset.

    key: character/location/prop name, or script episode_number (as string).
    Returns True if a file was removed, False if missing or failed.
    Failures are logged and do not raise — DB delete is the primary result.
    """
    if not key or not user_id or not world_id:
        return False
    uid, wid = str(user_id), str(world_id)
    name = str(key).strip()
    if not name:
        return False
    try:
        fm = get_file_manager()
        if asset_type == ASSET_TYPE_CHARACTERS:
            path = fm.resolve_character_file_path(name, uid, wid)
            if not path:
                return False
            path.unlink()
            logger.info(f"Deleted staging character file: {path}")
            return True
        if asset_type == ASSET_TYPE_LOCATIONS:
            return bool(fm.delete_location(name, uid, wid))
        if asset_type == ASSET_TYPE_PROPS:
            return bool(fm.delete_prop(name, uid, wid))
        if asset_type == ASSET_TYPE_SCRIPTS:
            return bool(fm.delete_script(name, uid, wid))
        logger.warning(f"Unknown staging asset type: {asset_type}")
        return False
    except Exception as e:
        logger.warning(
            f"Failed to delete staging {asset_type} key={name} "
            f"user={uid} world={wid}: {e}"
        )
        return False


def staging_file_exists(
    asset_type: str,
    key: str,
    user_id: str,
    world_id: str,
) -> bool:
    if not key or not user_id or not world_id:
        return False
    uid, wid = str(user_id), str(world_id)
    name = str(key).strip()
    if not name:
        return False
    try:
        fm = get_file_manager()
        if asset_type == ASSET_TYPE_CHARACTERS:
            return fm.resolve_character_file_path(name, uid, wid) is not None
        if asset_type == ASSET_TYPE_LOCATIONS:
            return fm.get_location_json(name, uid, wid) is not None
        if asset_type == ASSET_TYPE_PROPS:
            return fm.get_prop_json(name, uid, wid) is not None
        if asset_type == ASSET_TYPE_SCRIPTS:
            return fm.get_script(name, uid, wid) is not None
        return False
    except Exception as e:
        logger.warning(f"Failed to check staging {asset_type} key={name}: {e}")
        return False


def build_asset_usage(
    asset_type: str,
    record: Dict[str, Any],
    request_user_id: str,
) -> Dict[str, Any]:
    """Sync usage snapshot for GET detail. request_user_id is the current viewer (staging is per-user)."""
    usage: Dict[str, Any] = {
        'storyboard_count': 0,
        'child_location_count': 0,
        'dialogue_count': 0,
        'staging_file_exists': False,
    }
    record_id = record.get('id')
    world_id = record.get('world_id')
    try:
        if asset_type == ASSET_TYPE_SCRIPTS and record_id is not None:
            usage['storyboard_count'] = StoryboardModel.count_by_script_id(int(record_id))
            ep = record.get('episode_number')
            key = str(ep) if ep is not None else (record.get('title') or '')
            usage['staging_file_exists'] = staging_file_exists(
                ASSET_TYPE_SCRIPTS, key, str(request_user_id), str(world_id or '')
            )
        elif asset_type == ASSET_TYPE_LOCATIONS and record_id is not None:
            children = LocationModel.get_children(int(record_id))
            usage['child_location_count'] = len(children or [])
            usage['staging_file_exists'] = staging_file_exists(
                ASSET_TYPE_LOCATIONS,
                record.get('name') or '',
                str(request_user_id),
                str(world_id or ''),
            )
            parent_id = record.get('parent_id')
            if parent_id:
                parent = LocationModel.get_by_id(int(parent_id))
                if parent:
                    record['parent_name'] = parent.name
        elif asset_type == ASSET_TYPE_CHARACTERS and record_id is not None:
            usage['dialogue_count'] = StoryboardDialogueModel.count_by_character_id(int(record_id))
            usage['staging_file_exists'] = staging_file_exists(
                ASSET_TYPE_CHARACTERS,
                record.get('name') or '',
                str(request_user_id),
                str(world_id or ''),
            )
        elif asset_type == ASSET_TYPE_PROPS:
            usage['staging_file_exists'] = staging_file_exists(
                ASSET_TYPE_PROPS,
                record.get('name') or '',
                str(request_user_id),
                str(world_id or ''),
            )
    except Exception as e:
        logger.warning(f"Failed to build usage for {asset_type} id={record_id}: {e}")
    return usage


def attach_usage(
    asset_type: str,
    record: Dict[str, Any],
    request_user_id: str,
) -> Dict[str, Any]:
    out = dict(record)
    out['usage'] = build_asset_usage(asset_type, out, request_user_id)
    return out
