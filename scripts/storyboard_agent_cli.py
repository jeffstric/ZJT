import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.storyboard_agent_cli_service import (  # noqa: E402
    StoryboardAgentCliService,
    StoryboardCliError,
)
from services.storyboard_agent_command_service import StoryboardAgentCommandService  # noqa: E402


def _print_json(payload: Dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def _int_or_none(value: Optional[str]) -> Optional[int]:
    if value in (None, ""):
        return None
    return int(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="storyboard-agent-cli",
        description="Storyboard automation CLI for agents.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_worlds = subparsers.add_parser("list-worlds", help="List worlds visible to a user.")
    list_worlds.add_argument("--user-id", type=int, required=True)
    list_worlds.add_argument("--page", type=int, default=1)
    list_worlds.add_argument("--page-size", type=int, default=20)
    list_worlds.add_argument("--keyword")
    list_worlds.add_argument("--include-full-story-outline", action="store_true")

    list_world_scripts = subparsers.add_parser("list-world-scripts", help="List scripts under a world.")
    list_world_scripts.add_argument("--world-id", type=int, required=True)
    list_world_scripts.add_argument("--user-id", type=int, required=True)
    list_world_scripts.add_argument("--page", type=int, default=1)
    list_world_scripts.add_argument("--page-size", type=int, default=20)
    list_world_scripts.add_argument("--include-content", action="store_true")
    list_world_scripts.add_argument("--include-full-story-outline", action="store_true")

    get_script = subparsers.add_parser("get-script", help="Read one script with full content.")
    get_script.add_argument("--script-id", type=int, required=True)
    get_script.add_argument("--user-id", type=int, required=True)

    list_world_characters = subparsers.add_parser("list-world-characters", help="List characters under a world.")
    list_world_characters.add_argument("--world-id", type=int, required=True)
    list_world_characters.add_argument("--user-id", type=int, required=True)
    list_world_characters.add_argument("--page", type=int, default=1)
    list_world_characters.add_argument("--page-size", type=int, default=20)
    list_world_characters.add_argument("--keyword")
    list_world_characters.add_argument("--include-full-story-outline", action="store_true")

    list_world_locations = subparsers.add_parser("list-world-locations", help="List locations under a world.")
    list_world_locations.add_argument("--world-id", type=int, required=True)
    list_world_locations.add_argument("--user-id", type=int, required=True)
    list_world_locations.add_argument("--page", type=int, default=1)
    list_world_locations.add_argument("--page-size", type=int, default=20)
    list_world_locations.add_argument("--keyword")
    list_world_locations.add_argument("--include-full-story-outline", action="store_true")

    list_world_props = subparsers.add_parser("list-world-props", help="List props under a world.")
    list_world_props.add_argument("--world-id", type=int, required=True)
    list_world_props.add_argument("--user-id", type=int, required=True)
    list_world_props.add_argument("--page", type=int, default=1)
    list_world_props.add_argument("--page-size", type=int, default=20)
    list_world_props.add_argument("--keyword")
    list_world_props.add_argument("--include-full-story-outline", action="store_true")

    world_context = subparsers.add_parser("world-context", help="Read scripts, characters, locations, and props for a world.")
    world_context.add_argument("--world-id", type=int, required=True)
    world_context.add_argument("--user-id", type=int, required=True)
    world_context.add_argument("--page-size", type=int, default=100)
    world_context.add_argument("--include-script-content", action="store_true")
    world_context.add_argument("--include-full-story-outline", action="store_true")

    scene_context = subparsers.add_parser("scene-context", help="Read scene prompts and references.")
    scene_context.add_argument("--scene-id", type=int, required=True)
    scene_context.add_argument("--user-id", type=int)

    list_scenes = subparsers.add_parser("list-scenes", help="List storyboard scenes with asset summaries.")
    list_scenes.add_argument("--storyboard-id", type=int, required=True)
    list_scenes.add_argument("--user-id", type=int)

    insert_scene = subparsers.add_parser("insert-scene", help="Insert a storyboard scene after or before another scene.")
    insert_scene.add_argument("--storyboard-id", type=int, required=True)
    insert_scene.add_argument("--user-id", type=int, required=True)
    insert_scene.add_argument("--after-scene-id", type=int)
    insert_scene.add_argument("--before-scene-id", type=int)
    insert_scene.add_argument("--prev-id", type=int)
    insert_scene.add_argument("--next-id", type=int)
    insert_scene.add_argument("--title", default="")
    insert_scene.add_argument("--duration", type=float, default=5.0)
    insert_scene.add_argument("--prompt-json")
    insert_scene.add_argument("--video-prompt")
    insert_scene.add_argument("--video-type", default="video")
    insert_scene.add_argument("--video-config-json")
    insert_scene.add_argument("--difficulty", choices=["易", "中", "难"], default="中",
                              help="分镜难易程度（易/中/难），默认 中")
    insert_scene.add_argument("--act-name", help="所属幕/分镜组名称")

    create_storyboard = subparsers.add_parser(
        "create-storyboard-from-script",
        help="Create or reuse a blank storyboard linked to a script.",
    )
    create_storyboard.add_argument("--script-id", type=int, required=True)
    create_storyboard.add_argument("--user-id", type=int, required=True)
    create_storyboard.add_argument("--title")
    create_storyboard.add_argument("--workflow-id", type=int)
    create_storyboard.add_argument("--style")
    create_storyboard.add_argument("--style-reference-image")
    create_storyboard.add_argument("--workflow-ratio")
    create_storyboard.add_argument("--composition-preference")
    create_storyboard.add_argument("--version", type=int, default=1)
    create_storyboard.add_argument("--model")
    create_storyboard.add_argument("--model-id", type=int)
    create_storyboard.add_argument("--vendor-id", type=int)

    split_script = subparsers.add_parser(
        "split-from-script",
        help="Parse linked script into storyboard scenes (async: returns task_id, poll GET /api/script-split/tasks/{task_id}).",
    )
    split_script.add_argument("--storyboard-id", type=int, required=True)
    split_script.add_argument("--user-id", type=int, required=True)
    split_script.add_argument("--auth-token", default="")
    split_script.add_argument("--model")
    split_script.add_argument("--model-id", type=int)
    split_script.add_argument("--vendor-id", type=int)
    split_script.add_argument("--max-group-duration", type=int, default=15)
    split_script.add_argument("--force-medium-shot", action="store_true")
    split_script.add_argument("--no-bg-music", action="store_true")
    split_script.add_argument("--split-multi-dialogue", action="store_true")
    split_script.add_argument("--force-overwrite-subscene-grids", action="store_true")
    split_script.add_argument("--language", default="")
    split_script.add_argument("--dialogue-language", default="")
    split_script.add_argument("--prompt-language", default="")

    generate_image = subparsers.add_parser("generate-image", help="Generate a storyboard frame.")
    generate_image.add_argument("--scene-id", type=int, required=True)
    generate_image.add_argument("--user-id", type=int, required=True)
    generate_image.add_argument("--auth-token", default="")
    generate_image.add_argument("--mode", choices=["auto", "text_to_image", "image_edit"], default="auto")
    generate_image.add_argument("--asset-type", choices=["first_frame", "last_frame"], default="first_frame")
    generate_image.add_argument("--prompt")
    generate_image.add_argument("--source-image")
    generate_image.add_argument("--ratio")
    generate_image.add_argument("--image-size")
    generate_image.add_argument("--count", type=int, default=1)

    auto_generate = subparsers.add_parser(
        "auto-generate-missing-images",
        help="Generate missing storyboard frame images in a bounded batch.",
    )
    auto_generate.add_argument("--storyboard-id", type=int, required=True)
    auto_generate.add_argument("--user-id", type=int, required=True)
    auto_generate.add_argument("--auth-token", default="")
    auto_generate.add_argument("--asset-type", choices=["first_frame", "last_frame"], default="first_frame")
    auto_generate.add_argument("--mode", choices=["auto", "text_to_image", "image_edit"], default="auto")
    auto_generate.add_argument("--prompt")
    auto_generate.add_argument("--source-image")
    auto_generate.add_argument("--ratio")
    auto_generate.add_argument("--image-size")
    auto_generate.add_argument("--count", type=int, default=1)
    auto_generate.add_argument("--limit", type=int)
    auto_generate.add_argument("--task-type", type=int)
    auto_generate.add_argument(
        "--sequence-mode",
        choices=["speed", "balanced", "quality"],
        default="balanced",
        help="speed=no references, balanced=parallel by parsed group, quality=enterprise grid first-frame generation.",
    )
    auto_generate.add_argument("--continue-on-error", action="store_true")

    generate_video = subparsers.add_parser("generate-video", help="Generate storyboard video.")
    generate_video.add_argument("--scene-id", type=int, required=True)
    generate_video.add_argument("--user-id", type=int, required=True)
    generate_video.add_argument("--auth-token", default="")
    generate_video.add_argument("--mode", choices=["text_to_video", "image_to_video"], default="image_to_video")
    generate_video.add_argument(
        "--image-mode",
        choices=["first_last_frame", "multi_reference", "first_last_with_ref"],
        default="first_last_frame",
    )
    generate_video.add_argument("--prompt")
    generate_video.add_argument("--ratio")
    generate_video.add_argument("--duration-seconds", type=int)
    generate_video.add_argument("--count", type=int, default=1)
    generate_video.add_argument("--image-urls")
    generate_video.add_argument("--video-urls")
    generate_video.add_argument("--audio-urls")

    task_status = subparsers.add_parser("task-status", help="Read selected task status for a scene.")
    task_status.add_argument("--scene-id", type=int, required=True)
    task_status.add_argument("--asset-type", choices=["first_frame", "last_frame", "video"])

    storyboard_task_status = subparsers.add_parser(
        "storyboard-task-status",
        help="Read selected task status for all scenes in a storyboard.",
    )
    storyboard_task_status.add_argument("--storyboard-id", type=int, required=True)
    storyboard_task_status.add_argument("--user-id", type=int)
    storyboard_task_status.add_argument("--asset-type", choices=["first_frame", "last_frame", "video"], default="first_frame")

    image_batch_status = subparsers.add_parser(
        "storyboard-image-batch-status",
        help="Read a storyboard image batch orchestration status.",
    )
    image_batch_status.add_argument("--batch-id", type=int, required=True)
    image_batch_status.add_argument("--user-id", type=int)

    bind_projects = subparsers.add_parser("bind-projects", help="Bind existing ai_tools ids to scene assets.")
    bind_projects.add_argument("--scene-id", type=int, required=True)
    bind_projects.add_argument("--user-id", type=int)
    bind_projects.add_argument("--asset-type", choices=["first_frame", "last_frame", "video"], required=True)
    bind_projects.add_argument("--project-ids", required=True, help="Comma separated ai_tools/project ids.")

    update_scene = subparsers.add_parser("update-scene", help="Update editable fields of an existing storyboard scene.")
    update_scene.add_argument("--scene-id", type=int, required=True)
    update_scene.add_argument("--user-id", type=int)
    update_scene.add_argument("--duration", type=float)
    update_scene.add_argument("--title")
    update_scene.add_argument("--prompt-json")
    update_scene.add_argument("--video-prompt")
    update_scene.add_argument("--video-type")
    update_scene.add_argument("--video-config-json")
    update_scene.add_argument("--difficulty", choices=["易", "中", "难"],
                              help="分镜难易程度（易/中/难）")
    update_scene.add_argument("--act-name", help="所属幕/分镜组名称")

    return parser


def run_command(args: argparse.Namespace) -> Dict[str, Any]:
    params = {key: value for key, value in vars(args).items() if key != "command"}
    return StoryboardAgentCommandService(
        service=StoryboardAgentCliService()
    ).execute(args.command, params)


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        payload = run_command(args)
        _print_json(payload)
        return 0 if payload.get("success", True) is not False else 1
    except StoryboardCliError as exc:
        _print_json(exc.to_dict())
        return 1
    except Exception as exc:
        _print_json({"success": False, "error_code": "unexpected_error", "error": str(exc)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
