"""
AIGC 显式标识（明水印）烧录模块

法规依据：
- 《互联网信息服务深度合成管理规定》第17条：合成人声、人脸生成等可能导致公众混淆或误认的
  服务须添加显著标识；其他服务应提供显著标识功能
- 《人工智能生成合成内容标识办法》第4条：文本加提示/音频加语音或节奏提示/图片适当位置加标识/
  视频起始画面及周边加标识；第9条：用户申请不添加显式标识的须通过协议明确义务责任并留痕 >= 6 个月

分级策略（docs/compliance/aigc_labeling_plan.md 3.3）：
- L1 强制默认烧录：数字人视频（人脸生成，compose 链）、TTS 合成人声（开头节奏提示）；
  用户申请关闭走 aigc_explicit_opt_out_log 留痕（第9条），挂点查询跳过
- L2 提供显著标识功能：普通图片/视频——前端结果卡按钮按需烧录（POST /api/aigc/explicit-label）

实现要点：
- 图片：Pillow 右下角"AI生成"角标（黑底半透明条 + NotoSansSC 白字，独立 overlay
  alpha_composite 真混合，JPEG 混合后落 RGB，JPEG/PNG 观感一致）；JPEG 重存 quality=95
- 视频：ffmpeg drawtext 起始画面右下角角标（enable=between(t,0,N)，位置/半透明条样式与图片一致），
  全片重编码（滤镜需解码），音频 copy；
  ⚠️ ffmpeg 滤镜串里 Windows 盘符冒号必须转义——统一以项目根为 cwd 用相对路径绕开
- 音频：开头拼接节奏提示资产（第4条允许"语音或节奏提示"；资产由 _ensure_notice_audio 用 ffmpeg 合成）
- 烧录会重编码/重存丢原元数据，统一在烧录成功后以 extra_fields={'ExplicitLabel':'1'}
  重写隐式标识（utils/aigc_marking.mark_file），幂等判定依据 has_explicit_label
- 失败不阻断交付：burn_explicit_label 全容错仅告警
"""
import logging
import os
import subprocess
from pathlib import Path

from config.constant import (
    AIGC_EXPLICIT_LABEL_TEXT,
    AIGC_EXPLICIT_VIDEO_DISPLAY_SECONDS,
    AIGC_EXPLICIT_BURN_TIMEOUT_SECONDS,
    AIGC_EXPLICIT_FONT_REL,
    AIGC_EXPLICIT_NOTICE_AUDIO_REL,
    AIGC_EXPLICIT_FONT_SIZE_RATIO,
    AIGC_EXPLICIT_IMAGE_BURN_ENABLED,
    AIGC_EXPLICIT_VIDEO_BURN_ENABLED,
    AIGC_EXPLICIT_X264_PRESET,
    AIGC_EXPLICIT_VIDEO_CRF,
)
from model.ai_tools import AIToolsModel
from model.aigc_explicit_opt_out import AigcExplicitOptOutModel
from utils.aigc_marking import (
    mark_file,
    has_explicit_label,
    has_aigc_label,
    _sniff_format,
    _get_ffmpeg_path,
    _get_ffprobe_path,
)
from utils.project_path import get_project_root

logger = logging.getLogger(__name__)


# ==================== 公共 ====================

def _ffprobe_video_size(file_path: Path) -> tuple:
    """读取视频宽高（失败返回 (0, 0)）。"""
    try:
        r = subprocess.run(
            [_get_ffprobe_path(), '-v', 'error', '-select_streams', 'v:0',
             '-show_entries', 'stream=width,height', '-of', 'json', str(file_path)],
            capture_output=True, timeout=30, encoding='utf-8', errors='replace',
        )
        import json
        streams = (json.loads(r.stdout or '{}').get('streams') or [{}])
        return int(streams[0].get('width') or 0), int(streams[0].get('height') or 0)
    except Exception as e:  # noqa: BLE001
        logger.debug(f"ffprobe 视频尺寸读取失败: {file_path}: {e}")
        return 0, 0


def _load_font():
    """加载中文角标字体（文件缺失返回 None，调用方跳过文字）。"""
    from PIL import ImageFont
    font_path = Path(get_project_root()) / AIGC_EXPLICIT_FONT_REL
    if font_path.is_file():
        return str(font_path)
    logger.warning(f"AIGC 显式标识字体缺失: {font_path}")
    return None


# ==================== 图片角标 ====================

def _burn_image(file_path: Path) -> bool:
    """图片右下角烧录"AI生成"角标（PNG 无损重存；JPEG quality=95 重存）。"""
    from PIL import Image, ImageDraw, ImageFont

    with Image.open(file_path) as img:
        img.load()
        if getattr(img, 'is_animated', False):
            logger.warning(f"动图暂不支持显式标识烧录，跳过: {file_path}")
            return False
        icc = (img.info or {}).get('icc_profile')  # 重存前取原 ICC（convert 链可能丢 info）
        # 半透明必须经 alpha 真混合实现：JPEG 无 alpha 通道，落盘前才转 RGB，
        # 保证 JPEG/PNG 观感一致（直接画 RGB 会丢 alpha 成纯黑条）
        drop_alpha = file_path.suffix.lower() in ('.jpg', '.jpeg') or img.mode != 'RGBA'
        if img.mode != 'RGBA':
            img = img.convert('RGBA')
        w, h = img.size
        font_size = max(14, int(min(w, h) * AIGC_EXPLICIT_FONT_SIZE_RATIO))
        font_path = _load_font()
        font = ImageFont.truetype(font_path, font_size) if font_path else None

        # 角标画在独立 overlay 上再 alpha_composite：直接画底图是像素替换而非混合
        overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        # 文本尺寸（Pillow 10 兼容：无 textsize 时用 textbbox）
        if font:
            bbox = draw.textbbox((0, 0), AIGC_EXPLICIT_LABEL_TEXT, font=font)
            text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        else:
            text_w, text_h = font_size * 3, font_size  # 无字体兜底：跳过
        margin = max(8, int(h * 0.02))
        pad = max(4, font_size // 3)
        bar_w = text_w + pad * 2
        bar_h = text_h + pad * 2
        x1 = w - bar_w - margin
        y1 = h - bar_h - margin
        # 黑底半透明条 + 白字（第4条：图片适当位置添加标识）
        draw.rectangle([x1, y1, x1 + bar_w, y1 + bar_h], fill=(0, 0, 0, 160))
        if font:
            draw.text((x1 + pad, y1 + pad), AIGC_EXPLICIT_LABEL_TEXT,
                      fill=(255, 255, 255, 255), font=font)
        img = Image.alpha_composite(img, overlay)

        save_kwargs = {'quality': 95} if file_path.suffix.lower() in ('.jpg', '.jpeg') else {}
        if icc:
            save_kwargs['icc_profile'] = icc
        tmp_path = f"{file_path}.aigc_exp_{os.getpid()}.tmp"
        # tmp 扩展名无法供 Pillow 推断格式，显式指定（按原文件类型）
        img_format = 'JPEG' if file_path.suffix.lower() in ('.jpg', '.jpeg') else 'PNG'
        if drop_alpha:
            img = img.convert('RGB')
        img.save(tmp_path, img_format, **save_kwargs)
    os.replace(tmp_path, file_path)
    return True


# ==================== 视频起始画面 drawtext ====================

def _burn_video(file_path: Path) -> bool:
    """视频起始画面烧录"AI生成"文字提示（全片重编码，音频 copy）。

    cwd=项目根 + 相对路径传字体：绕开 ffmpeg 滤镜串对 Windows 盘符冒号的转义问题。
    """
    w, h = _ffprobe_video_size(file_path)
    if not h:
        logger.warning(f"视频尺寸读取失败，跳过显式标识烧录: {file_path}")
        return False
    fontsize = max(16, int(h * AIGC_EXPLICIT_FONT_SIZE_RATIO))
    display_secs = AIGC_EXPLICIT_VIDEO_DISPLAY_SECONDS
    # 与图片角标一致：右下角黑底半透明条 + 白字（boxborderw≈图片 pad，边距≈图片 margin）
    margin = max(8, int(h * 0.02))
    borderw = max(4, fontsize // 3)
    box_alpha = f"{160 / 255:.3f}"  # 与图片条 alpha=160 一致
    # 位置：右下角（第4条：视频起始画面及周边添加标识）
    # 注意：x/y 表达式只用 text_w/text_h 渲染常量（ffmpeg 4.x 无 boxborderw 变量），
    # borderw/margin 在 Python 侧算成数值，避免依赖高版本 ffmpeg 表达式变量
    vf = (
        f"drawtext=fontfile={AIGC_EXPLICIT_FONT_REL}"
        f":text={AIGC_EXPLICIT_LABEL_TEXT}"
        f":fontsize={fontsize}:fontcolor=white"
        f":box=1:boxcolor=black@{box_alpha}:boxborderw={borderw}"
        f":x=w-text_w-{borderw + margin}:y=h-text_h-{borderw + margin}"
        f":enable='between(t,0,{display_secs})'"
    )
    tmp_path = f"{file_path}.aigc_exp_{os.getpid()}.tmp.mp4"
    try:
        cmd = [
            _get_ffmpeg_path(), '-y', '-loglevel', 'error',
            '-i', str(file_path), '-vf', vf,
            '-c:v', 'libx264', '-preset', AIGC_EXPLICIT_X264_PRESET,
            '-crf', str(AIGC_EXPLICIT_VIDEO_CRF),
            '-c:a', 'copy',
            '-movflags', '+faststart',
            tmp_path,
        ]
        r = subprocess.run(cmd, capture_output=True, timeout=AIGC_EXPLICIT_BURN_TIMEOUT_SECONDS,
                           encoding='utf-8', errors='replace', cwd=str(get_project_root()))
        if r.returncode != 0 or not os.path.isfile(tmp_path) or os.path.getsize(tmp_path) == 0:
            raise RuntimeError(f"ffmpeg drawtext 失败: {(r.stderr or '')[-300:]}")
        os.replace(tmp_path, file_path)
        return True
    finally:
        if os.path.isfile(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


# ==================== 音频节奏提示 ====================

def _ensure_notice_audio() -> Path:
    """确保节奏提示音资产存在（无则用 ffmpeg 合成三短音节奏提示，资产生成一次复用）。"""
    notice_path = Path(get_project_root()) / AIGC_EXPLICIT_NOTICE_AUDIO_REL
    if notice_path.is_file():
        return notice_path
    notice_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = f"{notice_path}.aigc_{os.getpid()}.tmp"
    try:
        # 三短音节奏提示（880Hz，tremolo 4Hz 全深度调制出 ~3 个脉冲，0.8s），
        # 峰值约 -9 dBFS。⚠️ ffmpeg sine 源默认 1/8 幅值（-18dB）且 4.x 无 amplitude
        # 选项，响度只能经 volume 补偿（旧版 volume=0.5 实测峰值 -24dB，不可闻）
        cmd = [
            _get_ffmpeg_path(), '-y', '-loglevel', 'error',
            '-f', 'lavfi', '-i', 'sine=frequency=880:duration=0.8',
            '-filter_complex',
            "volume=2.8,tremolo=f=4:d=1,afade=t=in:st=0:d=0.02,"
            "afade=t=out:st=0.75:d=0.05,atrim=0:0.8",
            '-c:a', 'libmp3lame', '-q:a', '3',
            '-f', 'mp3',
            tmp_path,
        ]
        r = subprocess.run(cmd, capture_output=True, timeout=60,
                           encoding='utf-8', errors='replace')
        if r.returncode != 0 or not os.path.isfile(tmp_path):
            raise RuntimeError(f"提示音合成失败: {(r.stderr or '')[-200:]}")
        os.replace(tmp_path, notice_path)
        logger.info(f"AIGC 节奏提示音资产已生成: {notice_path}")
        return notice_path
    finally:
        if os.path.isfile(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def _burn_audio(file_path: Path) -> bool:
    """音频开头拼接节奏提示（第4条：音频加语音或节奏提示），保持原容器格式。"""
    notice_path = _ensure_notice_audio()
    suffix = file_path.suffix.lower().lstrip('.') or 'mp3'
    out_format = 'wav' if suffix == 'wav' else 'mp3'
    acodec = 'pcm_s16le' if out_format == 'wav' else 'libmp3lame'
    tmp_path = f"{file_path}.aigc_exp_{os.getpid()}.tmp.{suffix}"
    try:
        # concat filter 要求输入参数一致：提示音与源音频统一重采样到 44.1kHz/fltp/mono
        fc = ('[0:a]aresample=44100,aformat=sample_fmts=fltp:channel_layouts=mono[n0];'
              '[1:a]aresample=44100,aformat=sample_fmts=fltp:channel_layouts=mono[n1];'
              '[n0][n1]concat=n=2:v=0:a=1[out]')
        cmd = [
            _get_ffmpeg_path(), '-y', '-loglevel', 'error',
            '-i', str(notice_path), '-i', str(file_path),
            '-filter_complex', fc,
            '-map', '[out]',
            '-c:a', acodec, *( ['-q:a', '3'] if out_format == 'mp3' else [] ),
            '-f', out_format,
            tmp_path,
        ]
        r = subprocess.run(cmd, capture_output=True, timeout=AIGC_EXPLICIT_BURN_TIMEOUT_SECONDS,
                           encoding='utf-8', errors='replace')
        if r.returncode != 0 or not os.path.isfile(tmp_path) or os.path.getsize(tmp_path) == 0:
            raise RuntimeError(f"音频提示拼接失败: {(r.stderr or '')[-300:]}")
        os.replace(tmp_path, file_path)
        return True
    finally:
        if os.path.isfile(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


# ==================== 对外入口 ====================

def burn_explicit_label(file_path, produce_id, media_kind: str = 'auto',
                        user_id=None) -> bool:
    """烧录显式标识（明水印）并重写隐式标识。全容错：失败仅告警返回 False。

    - 幂等：已烧录（隐式 JSON 含 ExplicitLabel）直接返回 True，避免角标叠加
    - 成功后统一 mark_file(extra_fields={'ExplicitLabel':'1'}) 重写隐式标识
      （图片重存/视频重编码/音频拼接都会丢原元数据）

    Args:
        file_path: 本地媒体文件路径
        produce_id: 内容编号
        media_kind: 'auto' 或显式指定
        user_id: 调用方用户（仅日志）
    """
    try:
        path = Path(file_path)
        if not path.is_file():
            logger.warning(f"AIGC 显式标识烧录跳过：文件不存在 {path}")
            return False
        if has_explicit_label(path):
            return True  # 幂等：已烧录

        sniffed = _sniff_format(path)
        if sniffed in ('png', 'jpeg'):
            ok = _burn_image(path)
        elif sniffed in ('mp4', 'mov'):
            ok = _burn_video(path)
        elif sniffed in ('mp3', 'wav'):
            ok = _burn_audio(path)
        else:
            logger.warning(f"AIGC 显式标识烧录暂不支持该格式({sniffed})，跳过: {path}")
            return False

        if not ok:
            return False

        # 重写隐式标识（含显式烧录标记）——隐式标识是强制义务，烧录丢元数据后必须补
        marked = mark_file(path, produce_id, extra_fields={'ExplicitLabel': '1'})
        if not marked:
            logger.warning(
                f"AIGC 显式烧录成功但隐式标识重写未生效: {path} (produce_id={produce_id})")
        logger.info(
            f"AIGC 显式标识烧录成功: {path} (produce_id={produce_id}, user={user_id})")
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning(f"AIGC 显式标识烧录异常（不阻断交付）: {file_path}: {e}")
        return False


# ==================== 生成链默认烧录入口（L1，图片/视频） ====================

def maybe_burn_generated_media(result_url, ai_tool_id, media_type: str) -> bool:
    """生成产物默认烧录 L1 显式标识（图片/视频）。

    2026-11-11 产品决策（保守合规）：系统无法检测产出内容是否含人脸，全部生成
    图片/视频按"人脸生成/可能造成公众混淆"对待，默认烧录"AI生成"标识；
    用户可在设置中全局关闭（标识办法第9条留痕 aigc_explicit_opt_out_log）。
    详见 docs/compliance/aigc_labeling_plan.md 3.3。

    生成链三处调用点（download_queue worker / visual_task 入队失败兜底 /
    sync_task_executor），调用方必须保证本函数先于 transition_with_cdn_sync /
    建 media_file_mapping 执行——上传线程触发后才读本地文件，时序保证 CDN
    对象与本地文件一致带标。

    - 非本地 /upload/ 文件、开关关闭（AIGC_EXPLICIT_*_BURN_ENABLED）、
      音频等其他类型（音频走 volcengine_tts_service 自身挂点）、
      opt-out 用户 → 跳过返回 False
    - 全容错：任何异常仅告警返回 False（失败不阻断交付，隐式标识已先行写入）

    阻塞操作（Pillow/ffmpeg），须在 to_thread 或同步 worker 中调用，勿放事件循环。
    """
    try:
        if media_type == 'image':
            if not AIGC_EXPLICIT_IMAGE_BURN_ENABLED:
                return False
        elif media_type == 'video':
            if not AIGC_EXPLICIT_VIDEO_BURN_ENABLED:
                return False
        else:
            return False
        if not (result_url or '').startswith('/upload/'):
            return False
        path = Path(get_project_root()) / result_url.lstrip('/')
        if not path.is_file():
            logger.warning(f"AIGC 显式标识跳过：产物文件不存在 {path}")
            return False
        tool = AIToolsModel.get_by_id(ai_tool_id)
        uid = getattr(tool, 'user_id', None)
        if not uid:
            logger.warning(f"AIGC 显式标识跳过：任务无 user_id ai_tool={ai_tool_id}")
            return False
        if AigcExplicitOptOutModel.has_opt_out_user(uid):
            return False  # 用户级明水印关闭生效中（第9条留痕；隐式标识保留）
        return burn_explicit_label(str(path), str(ai_tool_id), media_type, uid)
    except Exception as e:  # noqa: BLE001
        logger.warning(
            f"AIGC 生成产物显式标识异常(不阻断交付): ai_tool={ai_tool_id} {result_url}: {e}")
        return False
