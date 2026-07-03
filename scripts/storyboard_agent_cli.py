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

    scene_context = subparsers.add_parser("scene-context", help="Read scene prompts and references.")
    scene_context.add_argument("--scene-id", type=int, required=True)
    scene_context.add_argument("--user-id", type=int)

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

    split_script = subparsers.add_parser("split-from-script", help="Parse linked script into storyboard scenes.")
    split_script.add_argument("--storyboard-id", type=int, required=True)
    split_script.add_argument("--user-id", type=int, required=True)
    split_script.add_argument("--auth-token", default="")
    split_script.add_argument("--model", default="gemini-3-flash-preview")
    split_script.add_argument("--model-id", type=int)
    split_script.add_argument("--vendor-id", type=int)
    split_script.add_argument("--max-group-duration", type=int, default=15)
    split_script.add_argument("--force-medium-shot", action="store_true")
    split_script.add_argument("--no-bg-music", action="store_true")
    split_script.add_argument("--split-multi-dialogue", action="store_true")
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

    bind_projects = subparsers.add_parser("bind-projects", help="Bind existing ai_tools ids to scene assets.")
    bind_projects.add_argument("--scene-id", type=int, required=True)
    bind_projects.add_argument("--user-id", type=int)
    bind_projects.add_argument("--asset-type", choices=["first_frame", "last_frame", "video"], required=True)
    bind_projects.add_argument("--project-ids", required=True, help="Comma separated ai_tools/project ids.")

    return parser


def run_command(args: argparse.Namespace) -> Dict[str, Any]:
    service = StoryboardAgentCliService()

    if args.command == "scene-context":
        return service.scene_context(scene_id=args.scene_id, user_id=args.user_id)

    if args.command == "create-storyboard-from-script":
        return service.create_storyboard_from_script(
            script_id=args.script_id,
            user_id=args.user_id,
            title=args.title,
            workflow_id=args.workflow_id,
            style=args.style,
            style_reference_image=args.style_reference_image,
            workflow_ratio=args.workflow_ratio,
            composition_preference=args.composition_preference,
            version=args.version,
        )

    if args.command == "split-from-script":
        return service.split_from_script(
            storyboard_id=args.storyboard_id,
            user_id=args.user_id,
            auth_token=args.auth_token,
            model=args.model,
            model_id=args.model_id,
            vendor_id=args.vendor_id,
            max_group_duration=args.max_group_duration,
            force_medium_shot=args.force_medium_shot,
            no_bg_music=args.no_bg_music,
            split_multi_dialogue=args.split_multi_dialogue,
            language=args.language,
            dialogue_language=args.dialogue_language,
            prompt_language=args.prompt_language,
        )

    if args.command == "generate-image":
        return service.generate_image(
            scene_id=args.scene_id,
            user_id=args.user_id,
            auth_token=args.auth_token,
            mode=args.mode,
            asset_type=args.asset_type,
            prompt=args.prompt,
            source_image=args.source_image,
            ratio=args.ratio,
            image_size=args.image_size,
            count=args.count,
        )

    if args.command == "generate-video":
        return service.generate_video(
            scene_id=args.scene_id,
            user_id=args.user_id,
            auth_token=args.auth_token,
            mode=args.mode,
            prompt=args.prompt,
            ratio=args.ratio,
            duration_seconds=args.duration_seconds,
            count=args.count,
            image_mode=args.image_mode,
            image_urls=args.image_urls,
            video_urls=args.video_urls,
            audio_urls=args.audio_urls,
        )

    if args.command == "task-status":
        return service.task_status(scene_id=args.scene_id, asset_type=args.asset_type)

    if args.command == "bind-projects":
        project_ids = [int(item.strip()) for item in args.project_ids.split(",") if item.strip()]
        result = service.bind_projects(
            scene_id=args.scene_id,
            user_id=args.user_id,
            asset_type=args.asset_type,
            project_ids=project_ids,
        )
        return {"success": True, "scene_id": args.scene_id, **result}

    raise StoryboardCliError("unknown_command", f"unknown command: {args.command}")


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
