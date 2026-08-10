"""
人脸遮罩叠加工具
将 YOLO 识别的人脸遮罩视频叠加到原始视频上，用于遮盖人脸后传给对人脸敏感的模型
"""
import os
import shutil
import subprocess
import threading
import logging
from typing import Optional, Tuple

from config.constant import MediaConstants

logger = logging.getLogger(__name__)


def _log_ffmpeg_error(proc, stderr_chunks):
    """读取 ffmpeg stderr 并记录错误日志"""
    try:
        proc.stdin.close()
    except Exception:
        pass
    proc.wait(timeout=5)
    stderr = b"".join(stderr_chunks).decode("utf-8", errors="replace")
    logger.error(f"ffmpeg 进程异常退出, returncode={proc.returncode}, stderr: {stderr[:1000]}")


def _normalize_video_to_cfr(
    ffmpeg_path: str,
    input_video: str,
    output_video: str,
    fps: int,
    max_short_side: Optional[int] = None,
) -> bool:
    """
    用 ffmpeg 将视频重采样为固定帧率的 CFR 视频。

    帧率元数据（cv2/ffprobe 探测值）对 VFR webm/mkv 完全不可信（可能误报 1000fps
    或看似合理但与时长矛盾的 60fps），因此一律不信任元数据，改由 ffmpeg 按每帧
    PTS 时间戳抽帧/补帧：输出严格为 fps 指定的 CFR，且时长与原视频保持一致。

    max_short_side 不为 None 时，短边超过该值的视频按比例缩小（长边等比、取偶数），
    用于上传 RunningHub 前降低其解码/加载的显存占用。
    """
    try:
        vf = f"fps={fps}"
        if max_short_side:
            vf += (
                f",scale='if(gt(iw,ih),-2,min(iw,{max_short_side}))'"
                f":'if(gt(iw,ih),min(ih,{max_short_side}),-2)'"
            )
        cmd = [
            ffmpeg_path, "-y",
            "-i", input_video,
            "-vf", vf,
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-an",
            output_video,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0 or not os.path.exists(output_video):
            logger.error(f"视频 CFR 归一化失败: {input_video}, stderr: {result.stderr[:500]}")
            return False
        return True
    except Exception as e:
        logger.error(f"视频 CFR 归一化异常: {input_video}, {e}")
        return False


def _map_mask_frame_index(frame_idx: int, orig_total: int, mask_total: int) -> int:
    """
    计算原视频第 frame_idx 帧对应的遮罩帧号。

    两路视频虽已归一化为同一 CFR，但 RunningHub 工作流对 VFR 源视频的解码假设
    与我们不同，产出的遮罩帧数可能与原视频不一致（如原视频 269 帧 vs 遮罩 285 帧），
    其遮罩时间轴相当于被整体拉伸。按帧数比例映射可在两种情况下都正确对齐：
    帧数一致时退化为 1:1，不一致时按全长比例对齐。
    """
    if orig_total > 0 and mask_total > 0:
        return int(round(frame_idx * mask_total / orig_total))
    return frame_idx


def _split_mask_video(cap_mask) -> list:
    """
    读取遮罩视频全部帧，返回逐帧灰度图列表。

    新版 RunningHub 工作流每帧输出「该帧全部检测框 mask + 一个全白分隔帧」
    （因为 ImpactSEGSToMaskBatch 对每个检测框各产出一个 mask，直接累积会导致
    遮罩流比视频帧数多且错位）；此处按全白分隔帧切分并对组内求并集，
    还原为与源视频严格 1:1 的逐帧遮罩。
    旧版工作流（无分隔帧）原样逐帧返回，保持兼容。
    """
    import cv2
    import numpy as np

    raw = []
    while True:
        ret, frame = cap_mask.read()
        if not ret:
            break
        raw.append(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
    if not raw:
        return []

    # 全白分隔帧：整帧接近纯白（h264 压缩后仍远高于检测框占比）
    is_sep = [np.count_nonzero(g > 250) > g.size * 0.99 for g in raw]
    if not any(is_sep):
        return raw

    frames = []
    current = None
    for gray, sep in zip(raw, is_sep):
        if sep:
            frames.append(current if current is not None else np.zeros_like(gray))
            current = None
        else:
            current = gray if current is None else np.maximum(current, gray)
    if current is not None:
        # 容错：最后一组缺分隔帧时仍保留
        frames.append(current)
    logger.info(f"遮罩视频按全白分隔帧解析: {len(raw)} 帧 -> {len(frames)} 帧逐帧遮罩")
    return frames


def _save_debug_artifacts(
    debug_dir: str,
    original_video: str,
    mask_video: str,
    temp_orig: str,
    temp_mask: str,
) -> None:
    """
    保留人脸遮罩叠加的各阶段产物，用于排查遮罩对齐问题。

    - source_input<ext>: 上传的原始视频（浏览器压缩产物，未经任何处理）
    - mask_source.mp4:   RunningHub 返回的遮罩视频
    - original_cfr.mp4:  原视频 PTS 重采样后的 CFR 中间产物（等同于上传给 RH 的内容）
    - mask_cfr.mp4:      遮罩视频 CFR 中间产物
    """
    try:
        os.makedirs(debug_dir, exist_ok=True)
        src_ext = os.path.splitext(original_video)[1] or ".mp4"
        shutil.copy2(original_video, os.path.join(debug_dir, f"source_input{src_ext}"))
        shutil.copy2(mask_video, os.path.join(debug_dir, "mask_source.mp4"))
        for src, name in ((temp_orig, "original_cfr.mp4"), (temp_mask, "mask_cfr.mp4")):
            if os.path.exists(src):
                shutil.move(src, os.path.join(debug_dir, name))
        logger.info(f"人脸遮罩调试产物已保留: {debug_dir}")
    except Exception as e:
        logger.warning(f"保留人脸遮罩调试产物失败: {e}")


def overlay_face_mask(
    original_video: str,
    mask_video: str,
    output_video: str,
    mask_color: Tuple[int, int, int] = (0, 0, 0),
    mask_alpha: float = 1.0,
    threshold: int = 128,
    ffmpeg_path: Optional[str] = None,
    ffprobe_path: Optional[str] = None,
    debug_dir: Optional[str] = None,
) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    将人脸遮罩视频叠加到原始视频上

    帧率处理策略：不信任任何帧率元数据（VFR webm 会误报 1000fps/60fps），
    先用 ffmpeg 按帧 PTS 把原视频和遮罩视频统一重采样为固定 CFR
    （MediaConstants.FACE_MASK_CFR_FPS），时长保持不变。

    遮罩对齐策略：RunningHub 工作流逐帧输出「该帧全部检测框 mask + 全白分隔帧」
    （ImpactSEGSToMaskBatch 对每个检测框各产出一个 mask），按分隔帧切分求并集后
    与原视频严格 1:1；旧版工作流无分隔帧时按帧数比例映射兜底。
    输出同为该固定帧率，保证与原视频时长、音频同步。

    Args:
        original_video: 原始视频路径（带有人脸的视频）
        mask_video: 遮罩视频路径（YOLO 识别的人脸方框，白色区域为遮罩）
        output_video: 输出视频路径
        mask_color: 遮罩颜色 (B, G, R)，默认黑色 (0, 0, 0)
        mask_alpha: 遮罩透明度 (0.0-1.0)，值越大遮罩越不透明，默认 1.0
        threshold: 遮罩阈值 (0-255)，高于此值的像素被视为遮罩区域，默认 128
        ffmpeg_path: ffmpeg 可执行文件路径，为 None 时从配置读取
        ffprobe_path: ffprobe 可执行文件路径，为 None 时从配置读取
        debug_dir: 调试产物保留目录，为 None 时删除中间产物

    Returns:
        Tuple[bool, Optional[str], Optional[str]]:
            - 是否成功
            - 输出文件路径（成功时）
            - 错误信息（失败时）
    """
    import cv2
    import numpy as np

    if ffmpeg_path is None or ffprobe_path is None:
        from config.config_util import get_config_value, resolve_bin_path
        from utils.project_path import get_project_root
        app_dir = get_project_root()
        if ffmpeg_path is None:
            ffmpeg_path = resolve_bin_path(
                get_config_value("bin", "ffmpeg", default="ffmpeg"), app_dir
            )
        if ffprobe_path is None:
            ffprobe_path = resolve_bin_path(
                get_config_value("bin", "ffprobe", default="ffprobe"), app_dir
            )

    if not os.path.exists(original_video):
        return False, None, f"原始视频不存在: {original_video}"
    if not os.path.exists(mask_video):
        return False, None, f"遮罩视频不存在: {mask_video}"

    os.makedirs(os.path.dirname(os.path.abspath(output_video)), exist_ok=True)

    fps = MediaConstants.FACE_MASK_CFR_FPS
    temp_audio = output_video + ".audio.aac"
    temp_orig = output_video + ".orig_cfr.mp4"
    temp_mask = output_video + ".mask_cfr.mp4"
    temp_files = (temp_audio, temp_orig, temp_mask)
    cap_orig = None
    cap_mask = None
    ffmpeg_proc = None

    try:
        # 诊断日志：原视频元数据（VFR webm 上不可信，仅供排查，不参与任何决策）
        try:
            probe_cap = cv2.VideoCapture(original_video)
            logger.info(
                f"原视频元数据(仅供参考): fps={probe_cap.get(cv2.CAP_PROP_FPS)}, "
                f"frames={int(probe_cap.get(cv2.CAP_PROP_FRAME_COUNT))}"
            )
            probe_cap.release()
        except Exception:
            pass

        has_audio = _extract_audio(ffmpeg_path, ffprobe_path, original_video, temp_audio)

        # 两路视频统一重采样为固定 CFR：元数据帧率不可信，PTS 时间戳可信
        if not _normalize_video_to_cfr(ffmpeg_path, original_video, temp_orig, fps):
            return False, None, f"原视频 CFR 归一化失败: {original_video}"
        if not _normalize_video_to_cfr(ffmpeg_path, mask_video, temp_mask, fps):
            return False, None, f"遮罩视频 CFR 归一化失败: {mask_video}"

        cap_orig = cv2.VideoCapture(temp_orig)
        cap_mask = cv2.VideoCapture(temp_mask)

        if not cap_orig.isOpened():
            return False, None, f"无法打开原始视频: {original_video}"
        if not cap_mask.isOpened():
            return False, None, f"无法打开遮罩视频: {mask_video}"

        width = int(cap_orig.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap_orig.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total_frames = int(cap_orig.get(cv2.CAP_PROP_FRAME_COUNT))

        mask_w = int(cap_mask.get(cv2.CAP_PROP_FRAME_WIDTH))
        mask_h = int(cap_mask.get(cv2.CAP_PROP_FRAME_HEIGHT))
        mask_raw_total = int(cap_mask.get(cv2.CAP_PROP_FRAME_COUNT))
        # 解析遮罩视频为逐帧遮罩列表（新工作流含全白分隔帧，按组求并集还原 1:1）
        mask_frames = _split_mask_video(cap_mask)
        mask_total = len(mask_frames)
        logger.info(
            f"原始视频: {width}x{height}, {fps}fps(CFR), {total_frames} 帧 | "
            f"遮罩视频: {mask_w}x{mask_h}, {fps}fps(CFR), 原始 {mask_raw_total} 帧 -> 逐帧 {mask_total} 帧"
        )

        # 通过 ffmpeg stdin pipe 直接写入原始帧，避免 OpenCV VideoWriter 编码兼容问题
        ffmpeg_cmd = [
            ffmpeg_path, "-y",
            "-f", "rawvideo",
            "-pix_fmt", "rgb24",
            "-s", f"{width}x{height}",
            "-r", str(fps),
            "-i", "pipe:0",
        ]
        if has_audio:
            ffmpeg_cmd += ["-i", temp_audio, "-c:a", "aac", "-b:a", "128k", "-shortest"]
        else:
            ffmpeg_cmd += ["-an"]
        ffmpeg_cmd += [
            "-c:v", "libx264", "-preset", "medium", "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            output_video,
        ]

        stderr_chunks = []

        def _drain_stderr():
            while True:
                chunk = ffmpeg_proc.stderr.read(4096)
                if not chunk:
                    break
                stderr_chunks.append(chunk)

        ffmpeg_proc = subprocess.Popen(
            ffmpeg_cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
        drain_thread = threading.Thread(target=_drain_stderr, daemon=True)
        drain_thread.start()

        frame_idx = 0
        masked_count = 0
        empty_count = 0

        while True:
            ret_orig, frame = cap_orig.read()
            if not ret_orig:
                break

            # ffmpeg 可能因 -shortest 提前结束（音频比视频短），检查进程状态
            if ffmpeg_proc.poll() is not None:
                logger.info(f"ffmpeg 已提前结束 (returncode={ffmpeg_proc.returncode})，停止写帧")
                break

            # 两路均已归一化为同一 CFR，且新工作流遮罩已还原为逐帧 1:1；
            # 帧数比例映射兜底零星出入，越界冻结最后一帧，不回绕。
            mask_frame = None
            if mask_frames:
                target_mask_idx = _map_mask_frame_index(frame_idx, total_frames, mask_total)
                mask_frame = mask_frames[min(target_mask_idx, mask_total - 1)]
            if mask_frame is None:
                # 遮罩视频无任何可读帧，原样输出
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                try:
                    ffmpeg_proc.stdin.write(rgb.tobytes())
                except BrokenPipeError:
                    break
                frame_idx += 1
                empty_count += 1
                continue

            if mask_frame.shape[:2] != frame.shape[:2]:
                mask_frame = cv2.resize(mask_frame, (width, height))

            mask_binary = mask_frame > threshold
            pixel_count = int(np.sum(mask_binary))

            result = frame.copy()
            result[mask_binary] = (
                frame[mask_binary] * (1.0 - mask_alpha)
                + np.array(mask_color, dtype=np.float32) * mask_alpha
            ).astype(np.uint8)
            rgb = cv2.cvtColor(result, cv2.COLOR_BGR2RGB)
            try:
                ffmpeg_proc.stdin.write(rgb.tobytes())
            except BrokenPipeError:
                break

            if pixel_count > 0:
                masked_count += 1
            else:
                empty_count += 1

            frame_idx += 1
            if frame_idx % 100 == 0:
                logger.info(f"已处理 {frame_idx}/{total_frames} 帧")

        cap_orig.release()
        cap_mask.release()
        cap_orig = None
        cap_mask = None

        ffmpeg_proc.stdin.close()
        try:
            ffmpeg_proc.wait(timeout=300)
        except subprocess.TimeoutExpired:
            logger.warning("ffmpeg 编码超时（300秒），强制终止")
            ffmpeg_proc.kill()
            ffmpeg_proc.wait()
        drain_thread.join(timeout=5)

        logger.info(f"帧处理完成，共 {frame_idx} 帧，有遮罩: {masked_count}，无遮罩: {empty_count}")

        if ffmpeg_proc.returncode != 0:
            stderr = b"".join(stderr_chunks).decode("utf-8", errors="replace")
            logger.error(f"ffmpeg 编码失败: {stderr[:500]}")
            return False, None, "ffmpeg 编码失败"

        logger.info(f"人脸遮罩叠加完成: {output_video}")
        if debug_dir:
            _save_debug_artifacts(debug_dir, original_video, mask_video, temp_orig, temp_mask)
        return True, output_video, None

    except Exception as e:
        logger.error(f"人脸遮罩叠加异常: {e}", exc_info=True)
        return False, None, f"人脸遮罩叠加异常: {e}"
    finally:
        if cap_orig is not None:
            cap_orig.release()
        if cap_mask is not None:
            cap_mask.release()
        if ffmpeg_proc is not None:
            try:
                if ffmpeg_proc.stdin:
                    ffmpeg_proc.stdin.close()
                ffmpeg_proc.kill()
                ffmpeg_proc.wait()
            except Exception:
                pass
        for temp_file in temp_files:
            try:
                if os.path.exists(temp_file):
                    os.remove(temp_file)
            except Exception:
                pass


def _extract_audio(
    ffmpeg_path: str,
    ffprobe_path: str,
    video_path: str,
    audio_path: str,
) -> bool:
    """从视频中提取音频，返回是否包含音频"""
    try:
        probe_cmd = [
            ffprobe_path, "-v", "quiet",
            "-select_streams", "a",
            "-show_entries", "stream=codec_type",
            "-of", "csv=p=0",
            video_path,
        ]
        probe_result = subprocess.run(
            probe_cmd, capture_output=True, text=True, timeout=30
        )
        has_audio = "audio" in probe_result.stdout

        if not has_audio:
            logger.info("原始视频无音频，跳过音频提取")
            return False

        cmd = [
            ffmpeg_path, "-y", "-i", video_path,
            "-vn", "-acodec", "aac", "-b:a", "128k",
            audio_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            logger.warning(f"提取音频失败: {result.stderr[:200]}")
            return False

        logger.info(f"音频已提取: {audio_path}")
        return True

    except Exception as e:
        logger.warning(f"提取音频异常: {e}")
        return False
