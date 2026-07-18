"""
故事板媒体导出服务。

方式1：素材包 zip（分镜N.mp4/图 + 分镜N_M.wav）→ 上传 CDN
方式2：按时间轴预览规则合成完整 MP4 → 上传 CDN

同步函数为主；API 层用 asyncio.to_thread / 后台线程调用，禁止在事件循环内直接跑 ffmpeg。
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
import zipfile
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse
from urllib.request import urlopen, Request

from config.config_util import get_config, get_config_value, resolve_bin_path
from config.constant import StoryboardExportConstants, StoryboardTimeouts
from model.ai_tools import AIToolsModel
from model.storyboard import StoryboardModel
from model.storyboard_scene import StoryboardSceneModel
from model.storyboard_scene_asset import StoryboardSceneAssetModel
from model.storyboard_dialogue import StoryboardDialogueModel
from utils.project_path import get_project_root, get_upload_dir, resolve_upload_url_to_local_path

logger = logging.getLogger(__name__)

# 模块级长寿 executor：仅用于整片后台任务，禁止 with ThreadPoolExecutor 包 result
_export_job_lock = threading.Lock()
_export_jobs: Dict[str, Dict[str, Any]] = {}


@dataclass
class AudioItem:
    index: int
    dialogue_id: int
    url: str
    file: str = ""
    duration: Optional[float] = None
    text: str = ""


@dataclass
class SceneExportItem:
    index: int
    scene_id: int
    title: str
    duration: float
    visual_type: str  # video | image | none
    visual_url: str
    visual_file: str = ""
    audios: List[AudioItem] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)
    # 声音同出：选中视频已内嵌对话声音（如数字人 LTX2.3 产物）。
    # 导出完整视频时保留视频原音轨、跳过 TTS 混音。
    audio_embedded: bool = False


@dataclass
class ExportPlan:
    storyboard_id: int
    title: str
    episode_number: int
    workflow_ratio: str
    scenes: List[SceneExportItem] = field(default_factory=list)

    def to_manifest(self) -> dict:
        return {
            "storyboard_id": self.storyboard_id,
            "title": self.title,
            "episode_number": self.episode_number,
            "workflow_ratio": self.workflow_ratio,
            "scenes": [
                {
                    "index": s.index,
                    "scene_id": s.scene_id,
                    "title": s.title,
                    "duration": s.duration,
                    "visual": {
                        "type": s.visual_type,
                        "file": s.visual_file,
                        "url": s.visual_url,
                    } if s.visual_type != "none" else None,
                    "audios": [
                        {
                            "index": a.index,
                            "file": a.file,
                            "dialogue_id": a.dialogue_id,
                            "url": a.url,
                            "duration": a.duration,
                            "text": a.text,
                        }
                        for a in s.audios
                    ],
                    "missing": s.missing,
                }
                for s in self.scenes
            ],
        }


def _safe_filename_part(text: str, max_len: int = 40) -> str:
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(text or "").strip())
    s = re.sub(r"\s+", "_", s).strip("._") or "storyboard"
    return s[:max_len]


def _ffmpeg_path() -> str:
    raw = get_config_value("bin", "ffmpeg", default="ffmpeg")
    return resolve_bin_path(raw, get_project_root())


def _ffprobe_path() -> str:
    raw = get_config_value("bin", "ffprobe", default="ffprobe")
    return resolve_bin_path(raw, get_project_root())


def _run_cmd(cmd: List[str], timeout: float) -> None:
    logger.debug("run: %s", " ".join(cmd))
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"命令超时({timeout}s): {cmd[0]}") from e
    except FileNotFoundError as e:
        raise RuntimeError(f"找不到可执行文件: {cmd[0]}") from e
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "")[-800:]
        raise RuntimeError(f"命令失败 returncode={proc.returncode}: {err}")


def _probe_duration(path: str) -> Optional[float]:
    if not path or not os.path.isfile(path):
        return None
    cmd = [
        _ffprobe_path(),
        "-v", "quiet",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path,
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=StoryboardTimeouts.EXPORT_FFMPEG_TIMEOUT_SECONDS,
            encoding="utf-8", errors="replace",
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return float(proc.stdout.strip())
    except Exception as e:
        logger.warning("ffprobe duration failed %s: %s", path, e)
    return None


def _has_audio_stream(path: str) -> bool:
    """探测媒体文件是否含音频流（用于 audio_embedded 兜底：视频文件可能无音轨）。"""
    if not path or not os.path.isfile(path):
        return False
    cmd = [
        _ffprobe_path(),
        "-v", "quiet",
        "-select_streams", "a",
        "-show_entries", "stream=codec_type",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path,
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=StoryboardTimeouts.EXPORT_FFMPEG_TIMEOUT_SECONDS,
            encoding="utf-8", errors="replace",
        )
        return proc.returncode == 0 and bool(proc.stdout.strip())
    except Exception as e:
        logger.warning("ffprobe audio stream failed %s: %s", path, e)
        return False


def _ext_from_url_or_path(url: str, default: str) -> str:
    path = urlparse(url).path if "://" in (url or "") else (url or "")
    ext = os.path.splitext(path)[1].lower()
    if ext and len(ext) <= 5 and re.match(r"^\.[a-z0-9]+$", ext):
        return ext
    return default


def resolve_media_to_local(url: str, dest_path: str) -> bool:
    """将 URL/相对路径落到 dest_path。优先本地 upload 映射，否则 HTTP 下载。"""
    if not url or not str(url).strip():
        return False
    url = str(url).strip()
    try:
        local = resolve_upload_url_to_local_path(url)
        if local and os.path.isfile(local):
            os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
            shutil.copy2(local, dest_path)
            return True
    except Exception as e:
        logger.debug("local resolve fail %s: %s", url, e)

    # HTTP(S)
    if not (url.startswith("http://") or url.startswith("https://")):
        # 尝试作为相对 upload 路径再查一次
        try:
            local2 = resolve_upload_url_to_local_path(url if url.startswith("/") else f"/upload/{url}")
            if local2 and os.path.isfile(local2):
                os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
                shutil.copy2(local2, dest_path)
                return True
        except Exception:
            pass
        return False

    try:
        os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
        req = Request(url, headers={"User-Agent": "storyboard-export/1.0"})
        timeout = StoryboardTimeouts.EXPORT_MEDIA_DOWNLOAD_TIMEOUT_SECONDS
        with urlopen(req, timeout=timeout) as resp, open(dest_path, "wb") as f:
            shutil.copyfileobj(resp, f)
        return os.path.isfile(dest_path) and os.path.getsize(dest_path) > 0
    except Exception as e:
        logger.warning("download fail %s: %s", url, e)
        if os.path.isfile(dest_path):
            try:
                os.remove(dest_path)
            except OSError:
                pass
        return False


def _resolve_asset_result_url(asset_id: Optional[int]) -> str:
    """asset.result_url 优先，空则用关联 ai_tools.result_url 兜底（对齐 API _asset_task_info）。"""
    if not asset_id:
        return ""
    try:
        asset = StoryboardSceneAssetModel.get_by_id(int(asset_id))
    except Exception as e:
        logger.warning("export resolve asset %s failed: %s", asset_id, e)
        return ""
    if not asset:
        return ""
    url = (getattr(asset, "result_url", None) or "").strip()
    if url:
        return url
    tool_id = getattr(asset, "ai_tool_id", None)
    if not tool_id:
        return ""
    try:
        tool = AIToolsModel.get_by_id(int(tool_id))
    except Exception as e:
        logger.warning("export resolve ai_tool %s for asset %s failed: %s", tool_id, asset_id, e)
        return ""
    if not tool:
        return ""
    return (getattr(tool, "result_url", None) or "").strip()


def _resolve_scene_visual(sc: Dict[str, Any], index: int) -> Tuple[str, str, str, List[str]]:
    """
    决定分镜画面：有 selected_video_id / 非空 video_url 时只用视频，绝不回退首帧图。

    Returns:
        (visual_type, visual_url, visual_file, missing_extra)
        visual_type: video | image | none
    """
    missing: List[str] = []
    video_url = (sc.get("video_url") or "").strip()
    selected_video_id = sc.get("selected_video_id")
    has_video_selection = bool(video_url) or bool(selected_video_id)

    if has_video_selection:
        if not video_url and selected_video_id:
            try:
                video_url = _resolve_asset_result_url(int(selected_video_id))
            except (TypeError, ValueError) as e:
                logger.warning("export invalid selected_video_id scene=%s: %s", sc.get("id"), e)
                video_url = ""
        if video_url:
            return "video", video_url, f"分镜{index}.mp4", missing
        # 已选中视频但拿不到 URL：黑场/缺失，禁止用分镜图顶替
        missing.append("video_missing")
        return "none", "", "", missing

    image_url = (sc.get("first_frame_url") or "").strip()
    selected_ff_id = sc.get("selected_first_frame_id")
    if not image_url and selected_ff_id:
        try:
            image_url = _resolve_asset_result_url(int(selected_ff_id))
        except (TypeError, ValueError) as e:
            logger.warning("export invalid selected_first_frame_id scene=%s: %s", sc.get("id"), e)
            image_url = ""
    if image_url:
        ext = _ext_from_url_or_path(image_url, ".png")
        if ext not in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"):
            ext = ".png"
        return "image", image_url, f"分镜{index}{ext}", missing

    return "none", "", "", missing


def collect_export_plan(storyboard_id: int) -> ExportPlan:
    sb = StoryboardModel.get_by_id(storyboard_id)
    if not sb:
        raise FileNotFoundError(f"故事板不存在: {storyboard_id}")

    scenes_raw = StoryboardSceneModel.list_by_storyboard(storyboard_id) or []
    title = (getattr(sb, "title", None) or "").strip() or f"第{getattr(sb, 'episode_number', 1) or 1}集故事板"
    ratio = (getattr(sb, "workflow_ratio", None) or "9:16").strip() or "9:16"
    ep = int(getattr(sb, "episode_number", None) or 1)

    plan = ExportPlan(
        storyboard_id=storyboard_id,
        title=title,
        episode_number=ep,
        workflow_ratio=ratio,
    )

    for i, sc in enumerate(scenes_raw, start=1):
        span = float(sc.get("duration") or 0) or StoryboardExportConstants.DEFAULT_FALLBACK_SPAN_SECONDS
        if span <= 0:
            span = StoryboardExportConstants.DEFAULT_FALLBACK_SPAN_SECONDS

        vtype, vurl, vfile, visual_missing = _resolve_scene_visual(sc, i)

        item = SceneExportItem(
            index=i,
            scene_id=int(sc["id"]),
            title=sc.get("title") or f"分镜{i}",
            duration=span,
            visual_type=vtype,
            visual_url=vurl,
            visual_file=vfile,
            missing=list(visual_missing),
            audio_embedded=bool(sc.get("audio_embedded")),
        )

        dialogues = StoryboardDialogueModel.list_by_scene(sc["id"]) or []
        aj = 0
        for d in dialogues:
            audio_url = (d.get("audio_url") or "").strip()
            if not audio_url:
                continue
            aj += 1
            try:
                adur = float(d["duration"]) if d.get("duration") is not None else None
            except (TypeError, ValueError):
                adur = None
            item.audios.append(AudioItem(
                index=aj,
                dialogue_id=int(d["id"]),
                url=audio_url,
                file=f"分镜{i}_{aj}.wav",
                duration=adur,
                text=str(d.get("text") or "").strip(),
            ))

        if vtype == "none" and not item.audios and "video_missing" not in item.missing:
            item.missing.append("no_media")
        plan.scenes.append(item)

    return plan


def _ensure_video_mp4(src: str, dest_mp4: str) -> None:
    ext = os.path.splitext(src)[1].lower()
    if ext == ".mp4":
        shutil.copy2(src, dest_mp4)
        return
    timeout = StoryboardTimeouts.EXPORT_FFMPEG_TIMEOUT_SECONDS
    _run_cmd([
        _ffmpeg_path(), "-y", "-i", src,
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-movflags", "+faststart",
        dest_mp4,
    ], timeout=timeout)


def _ensure_wav(src: str, dest_wav: str) -> None:
    ext = os.path.splitext(src)[1].lower()
    if ext == ".wav":
        shutil.copy2(src, dest_wav)
        return
    timeout = StoryboardTimeouts.EXPORT_FFMPEG_TIMEOUT_SECONDS
    _run_cmd([
        _ffmpeg_path(), "-y", "-i", src,
        "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "2",
        dest_wav,
    ], timeout=timeout)


def materialize_package_files(plan: ExportPlan, out_dir: str) -> ExportPlan:
    """下载/转换媒体到 out_dir，更新 plan 中的 file 字段与 missing。"""
    os.makedirs(out_dir, exist_ok=True)
    for sc in plan.scenes:
        if sc.visual_type != "none" and sc.visual_url:
            raw = os.path.join(out_dir, f"_raw_v_{sc.index}{ _ext_from_url_or_path(sc.visual_url, '.bin') }")
            dest = os.path.join(out_dir, sc.visual_file)
            ok = resolve_media_to_local(sc.visual_url, raw)
            if not ok:
                sc.missing.append("visual")
                sc.visual_type = "none"
                sc.visual_file = ""
            else:
                try:
                    if sc.visual_type == "video":
                        _ensure_video_mp4(raw, dest)
                    else:
                        shutil.copy2(raw, dest)
                except Exception as e:
                    logger.warning("visual convert fail scene=%s: %s", sc.index, e)
                    sc.missing.append("visual_convert")
                    sc.visual_type = "none"
                    sc.visual_file = ""
                finally:
                    if os.path.isfile(raw) and os.path.abspath(raw) != os.path.abspath(dest):
                        try:
                            os.remove(raw)
                        except OSError:
                            pass

        kept_audios: List[AudioItem] = []
        for a in sc.audios:
            raw = os.path.join(out_dir, f"_raw_a_{sc.index}_{a.index}{ _ext_from_url_or_path(a.url, '.bin') }")
            dest = os.path.join(out_dir, a.file)
            ok = resolve_media_to_local(a.url, raw)
            if not ok:
                sc.missing.append(f"audio_{a.index}")
                continue
            try:
                _ensure_wav(raw, dest)
                # 补全字幕用时长
                if a.duration is None or a.duration <= 0:
                    a.duration = _probe_duration(dest)
                kept_audios.append(a)
            except Exception as e:
                logger.warning("audio convert fail scene=%s a=%s: %s", sc.index, a.index, e)
                sc.missing.append(f"audio_convert_{a.index}")
            finally:
                if os.path.isfile(raw) and os.path.abspath(raw) != os.path.abspath(dest):
                    try:
                        os.remove(raw)
                    except OSError:
                        pass
        sc.audios = kept_audios
    return plan


def build_package_zip(plan: ExportPlan, work_dir: str) -> str:
    """materialize + zip，返回 zip 本地路径。"""
    pack_dir = os.path.join(work_dir, "package")
    if os.path.isdir(pack_dir):
        shutil.rmtree(pack_dir, ignore_errors=True)
    os.makedirs(pack_dir, exist_ok=True)

    materialize_package_files(plan, pack_dir)

    manifest_path = os.path.join(pack_dir, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(plan.to_manifest(), f, ensure_ascii=False, indent=2)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_name = f"{_safe_filename_part(plan.title)}_素材_{stamp}.zip"
    zip_path = os.path.join(work_dir, zip_name)

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(pack_dir):
            for name in files:
                if name.startswith("_raw_"):
                    continue
                full = os.path.join(root, name)
                arc = os.path.relpath(full, pack_dir)
                zf.write(full, arcname=arc)
    return zip_path


def _ratio_size(ratio: str) -> Tuple[int, int]:
    r = (ratio or "9:16").replace("：", ":")
    try:
        w_s, h_s = r.split(":")
        wr, hr = float(w_s), float(h_s)
        if wr <= 0 or hr <= 0:
            raise ValueError
        # 固定长边 1920
        if hr >= wr:
            h = StoryboardExportConstants.DEFAULT_VIDEO_HEIGHT
            w = max(2, int(round(h * wr / hr)) // 2 * 2)
        else:
            w = 1920
            h = max(2, int(round(w * hr / wr)) // 2 * 2)
        return w, h
    except Exception:
        return (
            StoryboardExportConstants.DEFAULT_VIDEO_WIDTH,
            StoryboardExportConstants.DEFAULT_VIDEO_HEIGHT,
        )


def _build_scene_audio(sc: SceneExportItem, pack_dir: str, work_dir: str, span: float) -> Optional[str]:
    """拼接本镜配音并 trim/pad 到 span，返回 wav 路径；无音频返回 None。"""
    paths = []
    for a in sc.audios:
        p = os.path.join(pack_dir, a.file)
        if os.path.isfile(p):
            paths.append(p)
    if not paths:
        return None

    timeout = StoryboardTimeouts.EXPORT_FFMPEG_TIMEOUT_SECONDS
    out = os.path.join(work_dir, f"scene_{sc.index}_audio.wav")
    if len(paths) == 1:
        src = paths[0]
    else:
        list_file = os.path.join(work_dir, f"scene_{sc.index}_alist.txt")
        with open(list_file, "w", encoding="utf-8") as f:
            for p in paths:
                # concat demuxer 需要转义单引号
                ap = p.replace("\\", "/").replace("'", "'\\''")
                f.write(f"file '{ap}'\n")
        concat_out = os.path.join(work_dir, f"scene_{sc.index}_aconcat.wav")
        # 统一重编码为 wav，避免多源编码不一致时 copy 失败
        _run_cmd([
            _ffmpeg_path(), "-y", "-f", "concat", "-safe", "0",
            "-i", list_file,
            "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "2",
            concat_out,
        ], timeout=timeout)
        src = concat_out

    # atrim + apad 到 span
    _run_cmd([
        _ffmpeg_path(), "-y", "-i", src,
        "-af", f"atrim=0:{span:.3f},apad=whole_dur={span:.3f}",
        "-t", f"{span:.3f}",
        "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "2",
        out,
    ], timeout=timeout)
    return out if os.path.isfile(out) else None


def _build_scene_visual(
    sc: SceneExportItem,
    pack_dir: str,
    work_dir: str,
    span: float,
    width: int,
    height: int,
    *,
    keep_audio: bool = False,
) -> str:
    """生成本镜视频 silent.mp4，时长 span。

    keep_audio=True 时保留视频原音轨（用于 audio_embedded 分镜：视频已内嵌对话声音，
    如数字人 LTX2.3 产物），音轨截断/静音补齐到 span。其余情况丢弃音轨（-an），
    由 _mux_segment 另行混入 TTS 或静音。
    """
    timeout = StoryboardTimeouts.EXPORT_FFMPEG_TIMEOUT_SECONDS
    out = os.path.join(work_dir, f"scene_{sc.index}_silent.mp4")
    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=25"
    )

    if sc.visual_type == "image" and sc.visual_file:
        img = os.path.join(pack_dir, sc.visual_file)
        if os.path.isfile(img):
            _run_cmd([
                _ffmpeg_path(), "-y", "-loop", "1", "-i", img,
                "-t", f"{span:.3f}",
                "-vf", vf,
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an",
                out,
            ], timeout=timeout)
            return out

    if sc.visual_type == "video" and sc.visual_file:
        vid = os.path.join(pack_dir, sc.visual_file)
        if os.path.isfile(vid):
            vdur = _probe_duration(vid) or span
            # 截断到 span；若视频更短则 tpad 定格补满
            pad = max(0.0, span - vdur)
            vf_full = vf
            if pad > 0.05:
                vf_full = vf + f",tpad=stop_mode=clone:stop_duration={pad:.3f}"
            # keep_audio 由调用方（build_merged_video）探测视频音轨后决定；
            # 此处信任传入值。无音轨时调用方不会传 keep_audio=True。
            if keep_audio:
                # 保留视频原音轨：视频截断到 span，音轨 atrim+apad 对齐到 span。
                af = f"atrim=0:{span:.3f},apad=whole_dur={span:.3f}"
                try:
                    _run_cmd([
                        _ffmpeg_path(), "-y", "-i", vid,
                        "-t", f"{span:.3f}",
                        "-vf", vf_full,
                        "-af", af,
                        "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-b:a", "192k",
                        out,
                    ], timeout=timeout)
                except RuntimeError as e:
                    # 视频实际无音轨（-af 滤镜失败）：降级丢弃音轨，由 _mux_segment 补静音
                    logger.warning("keep_audio failed (no audio stream?) scene=%s: %s", sc.index, e)
                    _run_cmd([
                        _ffmpeg_path(), "-y", "-i", vid,
                        "-t", f"{span:.3f}",
                        "-vf", vf_full,
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an",
                        out,
                    ], timeout=timeout)
            else:
                _run_cmd([
                    _ffmpeg_path(), "-y", "-i", vid,
                    "-t", f"{span:.3f}",
                    "-vf", vf_full,
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an",
                    out,
                ], timeout=timeout)
            return out

    # 黑场
    _run_cmd([
        _ffmpeg_path(), "-y",
        "-f", "lavfi", "-i", f"color=c=black:s={width}x{height}:d={span:.3f}:r=25",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an",
        out,
    ], timeout=timeout)
    return out


def _mux_segment(
    silent_video: str,
    audio_wav: Optional[str],
    out_mp4: str,
    span: float,
    *,
    keep_audio: bool = False,
) -> None:
    """混流单镜视频与音频。

    keep_audio=True 表示 silent_video 已含原音轨（audio_embedded 分镜），此时不再
    另行混入 TTS 或补静音，直接 copy 音视频并截断到 span。
    """
    timeout = StoryboardTimeouts.EXPORT_FFMPEG_TIMEOUT_SECONDS
    if audio_wav and os.path.isfile(audio_wav):
        _run_cmd([
            _ffmpeg_path(), "-y",
            "-i", silent_video, "-i", audio_wav,
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-t", f"{span:.3f}", "-shortest",
            "-movflags", "+faststart",
            out_mp4,
        ], timeout=timeout)
    elif keep_audio and _has_audio_stream(silent_video):
        # 视频已自带音轨（audio_embedded），直接 copy，按 span 截断
        _run_cmd([
            _ffmpeg_path(), "-y",
            "-i", silent_video,
            "-c:v", "copy", "-c:a", "copy",
            "-t", f"{span:.3f}",
            "-movflags", "+faststart",
            out_mp4,
        ], timeout=timeout)
    else:
        # 无音轨：补静音
        _run_cmd([
            _ffmpeg_path(), "-y",
            "-i", silent_video,
            "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
            "-t", f"{span:.3f}", "-shortest",
            "-movflags", "+faststart",
            out_mp4,
        ], timeout=timeout)


def build_merged_video(
    plan: ExportPlan,
    work_dir: str,
    *,
    burn_subtitles: bool = True,
) -> str:
    """合成完整 MP4，返回本地路径。依赖 pack 目录已 materialize。

    burn_subtitles=True 时，在整片 concat 后硬烧 ASS 字幕（见 storyboard_subtitle）。
    """
    pack_dir = os.path.join(work_dir, "package")
    if not os.path.isdir(pack_dir):
        materialize_package_files(plan, pack_dir)

    width, height = _ratio_size(plan.workflow_ratio)
    segments: List[str] = []
    timeout = StoryboardTimeouts.EXPORT_FFMPEG_TIMEOUT_SECONDS

    for sc in plan.scenes:
        span = max(float(sc.duration or 0), StoryboardExportConstants.DEFAULT_FALLBACK_SPAN_SECONDS)
        # 声音同出：视频已内嵌对话声音（如数字人 LTX2.3 产物），保留原音轨、跳过 TTS 混音。
        # 仅当选中视频确实含音轨时才 keep_audio；无音轨（异常/损坏）降级走 TTS 混音，
        # 保证数字人镜不会因视频异常而无声。
        keep_audio = False
        if sc.audio_embedded and sc.visual_type == "video" and sc.visual_file:
            vid_path = os.path.join(pack_dir, sc.visual_file)
            keep_audio = os.path.isfile(vid_path) and _has_audio_stream(vid_path)
        silent = _build_scene_visual(sc, pack_dir, work_dir, span, width, height, keep_audio=keep_audio)
        audio = None if keep_audio else _build_scene_audio(sc, pack_dir, work_dir, span)
        seg = os.path.join(work_dir, f"segment_{sc.index:04d}.mp4")
        _mux_segment(silent, audio, seg, span, keep_audio=keep_audio)
        segments.append(seg)

    if not segments:
        raise RuntimeError("没有可合成的分镜")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_name = f"{_safe_filename_part(plan.title)}_完整_{stamp}.mp4"
    raw_path = os.path.join(work_dir, f"_full_raw_{stamp}.mp4")
    out_path = os.path.join(work_dir, out_name)

    if len(segments) == 1:
        shutil.copy2(segments[0], raw_path)
    else:
        list_file = os.path.join(work_dir, "concat_list.txt")
        with open(list_file, "w", encoding="utf-8") as f:
            for p in segments:
                ap = p.replace("\\", "/").replace("'", "'\\''")
                f.write(f"file '{ap}'\n")
        _run_cmd([
            _ffmpeg_path(), "-y", "-f", "concat", "-safe", "0",
            "-i", list_file, "-c", "copy",
            "-movflags", "+faststart",
            raw_path,
        ], timeout=timeout)

    if burn_subtitles:
        try:
            from config.constant import StoryboardSubtitleConstants
            from services.storyboard_subtitle import (
                build_subtitle_cues,
                write_ass_file,
                ffmpeg_subtitles_filter_arg,
                resolve_builtin_font,
            )
            cues = build_subtitle_cues(plan, width=width, height=height)
            if cues:
                ass_name = "subtitles.ass"
                ass_path = os.path.join(work_dir, ass_name)
                write_ass_file(cues, ass_path, width, height)

                # 拷贝内置 CJK 字体到 work_dir/fonts/，让 libass 经 fontsdir= 加载，
                # 规避宿主机 fontconfig 在 Windows 下解析失败导致字幕渲染为豆腐块（蚂蚁文）
                fonts_subdir: Optional[str] = None
                _, builtin_font_abspath = resolve_builtin_font()
                if builtin_font_abspath:
                    fonts_subdir = StoryboardSubtitleConstants.WORK_FONT_SUBDIR
                    work_fonts_dir = os.path.join(work_dir, fonts_subdir)
                    os.makedirs(work_fonts_dir, exist_ok=True)
                    shutil.copy2(
                        builtin_font_abspath,
                        os.path.join(
                            work_fonts_dir,
                            StoryboardSubtitleConstants.BUILTIN_FONT_FILENAME,
                        ),
                    )

                vf = ffmpeg_subtitles_filter_arg(ass_name, fonts_subdir=fonts_subdir)
                # cwd=work_dir，滤镜用相对路径，避免 Windows 盘符破坏 subtitles=
                _run_cmd_cwd(
                    work_dir,
                    [
                        _ffmpeg_path(), "-y",
                        "-i", os.path.basename(raw_path),
                        "-vf", vf,
                        "-c:a", "copy",
                        "-movflags", "+faststart",
                        os.path.basename(out_path),
                    ],
                    timeout=timeout,
                )
                if os.path.isfile(out_path):
                    return out_path
                logger.warning("subtitle burn produced no output, fallback to raw")
        except Exception as e:
            logger.exception("burn subtitles failed, fallback to raw: %s", e)

    shutil.copy2(raw_path, out_path)
    return out_path


def _run_cmd_cwd(cwd: str, cmd: List[str], timeout: float) -> None:
    logger.debug("run(cwd=%s): %s", cwd, " ".join(cmd))
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
            cwd=cwd,
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"命令超时({timeout}s): {cmd[0]}") from e
    except FileNotFoundError as e:
        raise RuntimeError(f"找不到可执行文件: {cmd[0]}") from e
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "")[-800:]
        raise RuntimeError(f"命令失败 returncode={proc.returncode}: {err}")


def make_work_dir(storyboard_id: int) -> str:
    base = os.path.join(
        get_upload_dir(),
        StoryboardExportConstants.WORK_SUBDIR,
        str(storyboard_id),
        uuid.uuid4().hex[:12],
    )
    os.makedirs(base, exist_ok=True)
    return base


def cleanup_dir(path: str) -> None:
    if path and os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)
    elif path and os.path.isfile(path):
        try:
            os.remove(path)
        except OSError:
            pass


def _job_path(job_id: str) -> str:
    d = os.path.join(get_upload_dir(), StoryboardExportConstants.JOBS_SUBDIR)
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, f"{job_id}.json")


def save_job(job: dict) -> None:
    job_id = job["job_id"]
    with _export_job_lock:
        _export_jobs[job_id] = job
    try:
        with open(_job_path(job_id), "w", encoding="utf-8") as f:
            json.dump(job, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning("save job file fail: %s", e)


def get_job(job_id: str) -> Optional[dict]:
    with _export_job_lock:
        if job_id in _export_jobs:
            return dict(_export_jobs[job_id])
    path = _job_path(job_id)
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    return None


def create_job(storyboard_id: int, export_type: str, user_id: int) -> dict:
    job = {
        "job_id": uuid.uuid4().hex,
        "storyboard_id": storyboard_id,
        "export_type": export_type,  # package | full_video
        "user_id": user_id,
        "status": "pending",  # pending|running|completed|failed
        "progress": 0,
        "download_url": None,
        "filename": None,
        "error": None,
        "create_at": datetime.now().isoformat(),
        "update_at": datetime.now().isoformat(),
    }
    save_job(job)
    return job


def update_job(job_id: str, **kwargs) -> Optional[dict]:
    job = get_job(job_id)
    if not job:
        return None
    job.update(kwargs)
    job["update_at"] = datetime.now().isoformat()
    save_job(job)
    return job


def run_package_export_sync(storyboard_id: int) -> Tuple[str, str]:
    """
    同步：打包 zip。返回 (local_zip_path, filename)。
    调用方负责 CDN 上传与清理。
    """
    work = make_work_dir(storyboard_id)
    try:
        plan = collect_export_plan(storyboard_id)
        if not plan.scenes:
            raise RuntimeError("故事板没有分镜，无法导出")
        zip_path = build_package_zip(plan, work)
        return zip_path, os.path.basename(zip_path)
    except Exception:
        cleanup_dir(work)
        raise


def run_full_video_export_job(job_id: str, storyboard_id: int) -> None:
    """后台线程入口：合成 + 由 API 层负责 CDN 前先写本地路径到 job，或在此完成上传？
    上传需 async storage，故此处只做合成，API 线程里 to_thread 整段更简单。

    实际由 export_full_video_pipeline 在 to_thread 中：合成 → 返回 path，
    外层 async 上传。本函数供线程池整条同步流水线（含阻塞上传）使用可选。
    """
    update_job(job_id, status="running", progress=5)
    work = make_work_dir(storyboard_id)
    try:
        plan = collect_export_plan(storyboard_id)
        update_job(job_id, progress=15)
        materialize_package_files(plan, os.path.join(work, "package"))
        update_job(job_id, progress=40)
        out_path = build_merged_video(plan, work)
        update_job(job_id, progress=80, filename=os.path.basename(out_path))
        # 把路径暂存，供 async 上传；上传成功后清理
        update_job(job_id, status="uploading", progress=85, **{"_local_path": out_path, "_work_dir": work})
    except Exception as e:
        logger.exception("full video export failed job=%s", job_id)
        update_job(job_id, status="failed", error=str(e), progress=100)
        cleanup_dir(work)


async def upload_local_file_to_cdn(
    local_path: str,
    content_type: str,
) -> Tuple[str, str]:
    """上传本地文件到图床，返回 (download_url, filename)。"""
    from utils.file_storage.factory import get_file_storage

    if not local_path or not os.path.isfile(local_path):
        raise RuntimeError("待上传文件不存在")
    filename = os.path.basename(local_path)
    storage = get_file_storage(get_config())
    storage_key = storage.generate_key_with_datetime(filename)
    upload_result = await storage.upload_file(storage_key, local_path, content_type=content_type)
    if not upload_result.success:
        raise RuntimeError(upload_result.error or "上传导出文件失败")
    download_url = storage.get_download_url(upload_result.key)
    return download_url, filename
