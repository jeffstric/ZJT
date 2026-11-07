"""
AIGC 生成合成内容隐式标识（文件元数据）写入模块

法规依据：
- 《互联网信息服务深度合成管理规定》第16条：对生成/编辑的信息内容添加不影响用户使用的隐式标识
- 《人工智能生成合成内容标识办法》（国信办通字〔2025〕2号，2025-09-01 施行）第5条：
  在生成合成内容的文件元数据中添加内容属性信息、服务提供者名称或编码、内容编号等
- GB 45438-2025《网络安全技术 人工智能生成合成内容标识方法》附录E：XMP 元数据隐式标识格式

标识承载方式（全部无损操作）：
- PNG   : iTXt 块 keyword="XML:com.adobe.xmp"（Pillow，像素不变）
- JPEG  : APP1 段字节级插入/替换（禁止重编码，保留原 EXIF）
- MP4   : ffmpeg remux（-c copy -movflags use_metadata_tags -metadata xmp=...），moov 写入 XMP atom
- MP3   : ffmpeg remux（-metadata AIGC=<json> → ID3 TXXX）
- WAV   : ffmpeg remux（-metadata comment=<json> → LIST INFO ICMT）
- GIF/WebP 等其余格式：暂不支持写入，has_aigc_label 返回 None，不阻断业务

调用入口：
- mark_file_for_task()：生成链路落盘标记（容错全包，失败仅告警，不阻断内容交付）
- ensure_marked()：下载/导出出口兜底（幂等：已带标识直接返回）
- has_aigc_label()：读回校验（True=已标识 / False=无标识 / None=格式不支持校验）

常量统一在 config/constant.py（AIGC_*），方案见 docs/compliance/aigc_labeling_plan.md
"""
import json
import logging
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

from config.config_util import get_config_value, resolve_bin_path
from utils.project_path import get_project_root

from config.constant import (
    AIGC_MARK_ENABLED,
    AIGC_CONTENT_PRODUCER,
    AIGC_LABEL_VALUE,
    AIGC_MARK_TIMEOUT_SECONDS,
    AIGC_XMP_NS_URI,
    AIGC_XMP_NS_PREFIX,
    AIGC_PNG_XMP_KEYWORD,
    AIGC_JPEG_APP1_XMP_NS,
)

logger = logging.getLogger(__name__)

# 媒体大类（ContentProp 字段值）
_MEDIA_PROP = {
    'png': 'image', 'jpeg': 'image',
    'mp4': 'video', 'mov': 'video',
    'mp3': 'audio', 'wav': 'audio',
}

# 写入 ffmpeg 时给子进程留的余量（外层调用方还有 wait_for 超时兜底）
_SUBPROCESS_TIMEOUT = max(10, AIGC_MARK_TIMEOUT_SECONDS - 10)


def _get_ffmpeg_path() -> str:
    """从配置读取 ffmpeg 路径（与 utils/video_compressor.py 一致，禁止硬编码）。"""
    ffmpeg = get_config_value("bin", "ffmpeg", default="ffmpeg")
    return resolve_bin_path(ffmpeg, get_project_root())


def _get_ffprobe_path() -> str:
    """从配置读取 ffprobe 路径。"""
    ffprobe = get_config_value("bin", "ffprobe", default="ffprobe")
    return resolve_bin_path(ffprobe, get_project_root())


# ==================== 标识内容构造 ====================

def build_aigc_json(produce_id, media_kind: str) -> str:
    """构造 AIGC 标识 JSON（GB 45438-2025 附录E 字段：Label/ContentProducer/ProduceID/ReservedCode1）。"""
    return json.dumps(
        {
            'Label': AIGC_LABEL_VALUE,
            'ContentProducer': AIGC_CONTENT_PRODUCER,
            'ProduceID': str(produce_id),
            'ReservedCode1': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'ContentProp': _MEDIA_PROP.get(media_kind, media_kind or 'unknown'),
        },
        ensure_ascii=False,
        separators=(',', ':'),
    )


def build_xmp_packet(aigc_json: str) -> str:
    """构造标准 XMP packet（TC260 命名空间，AIGC 属性值为 JSON 字符串）。"""
    # JSON 双引号在 XML 文本节点合法，仅需转义 XML 特殊字符
    json_esc = aigc_json.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    return (
        '<?xpacket begin="\ufeff" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'
        '<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="ZJT AIGC Marker 1.0">\n'
        ' <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">\n'
        f'  <rdf:Description rdf:about="" xmlns:{AIGC_XMP_NS_PREFIX}="{AIGC_XMP_NS_URI}">\n'
        f'   <{AIGC_XMP_NS_PREFIX}:AIGC>{json_esc}</{AIGC_XMP_NS_PREFIX}:AIGC>\n'
        '  </rdf:Description>\n'
        ' </rdf:RDF>\n'
        '</x:xmpmeta>\n'
        '<?xpacket end="w"?>'
    )


# ==================== 格式识别（魔数，不信任扩展名） ====================

def _sniff_format(file_path) -> Optional[str]:
    """按文件头魔数识别格式；无法识别返回 None。"""
    try:
        with open(file_path, 'rb') as f:
            head = f.read(16)
    except OSError:
        return None
    if head[:8] == b'\x89PNG\r\n\x1a\n':
        return 'png'
    if head[:3] == b'\xff\xd8\xff':
        return 'jpeg'
    if head[:4] == b'GIF8':
        return 'gif'
    if head[:4] == b'RIFF':
        if head[8:12] == b'WEBP':
            return 'webp'
        if head[8:12] == b'WAVE':
            return 'wav'
        return None
    if len(head) > 11 and head[4:8] == b'ftyp':
        return 'mp4'  # MP4/MOV 同为 ISO-BMFF 容器（f mp4 重封装无碍）
    if head[:3] == b'ID3':
        return 'mp3'
    if len(head) >= 2 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0:
        return 'mp3'  # MPEG 帧同步
    return None


# ==================== 读回校验 ====================

def _jpeg_find_xmp_payload(data: bytes) -> Optional[bytes]:
    """扫描 JPEG 段结构，返回 XMP APP1 的 payload（namespace 后的内容），无则 None。"""
    pos = 2
    while pos + 4 <= len(data):
        if data[pos] != 0xFF:
            return None
        marker = data[pos + 1]
        if marker in (0xD9, 0xDA):  # EOI / SOS：其后为熵编码数据，停止
            return None
        seg_len = int.from_bytes(data[pos + 2:pos + 4], 'big')
        if seg_len < 2:
            return None
        if marker == 0xE1 and data[pos + 4:pos + 4 + len(AIGC_JPEG_APP1_XMP_NS)] == AIGC_JPEG_APP1_XMP_NS:
            return data[pos + 4 + len(AIGC_JPEG_APP1_XMP_NS):pos + 2 + seg_len]
        pos += 2 + seg_len
    return None


def _ffprobe_format_tags(file_path) -> dict:
    """ffprobe 读取容器级 format tags（读取失败返回空 dict）。

    用 xml 输出而非 json：XMP 值内含双引号会破坏 ffprobe 的 json 转义导致解析失败；
    xml 输出对特殊字符正确转义。subprocess 显式 UTF-8（Windows 默认 GBK 会崩，
    AGENTS.md 第 6 条字符集红线）。
    """
    try:
        r = subprocess.run(
            [_get_ffprobe_path(), '-v', 'error', '-show_entries', 'format_tags',
             '-of', 'xml', str(file_path)],
            capture_output=True, timeout=30,
            encoding='utf-8', errors='replace',
        )
        return {'stdout_xml': r.stdout or ''}
    except Exception as e:  # noqa: BLE001
        logger.debug(f"ffprobe tags 读取失败: {file_path}: {e}")
        return {'stdout_xml': ''}


def _ffprobe_tags_text(file_path) -> str:
    """ffprobe 读取容器级 tags 的原始输出文本（读取失败返回空串）。

    用 xml 输出而非 json：XMP 值内含双引号会破坏 ffprobe 的 json 转义导致解析失败；
    xml 输出对特殊字符正确转义。subprocess 显式 UTF-8（Windows 默认 GBK 会崩，
    AGENTS.md 第 6 条字符集红线）。调用方直接对文本做子串判断，不做 xml 解析。
    """
    try:
        r = subprocess.run(
            [_get_ffprobe_path(), '-v', 'error', '-show_entries', 'format_tags',
             '-of', 'xml', str(file_path)],
            capture_output=True, timeout=30,
            encoding='utf-8', errors='replace',
        )
        return r.stdout or ''
    except Exception as e:  # noqa: BLE001
        logger.debug(f"ffprobe tags 读取失败: {file_path}: {e}")
        return ''


def has_aigc_label(file_path) -> Optional[bool]:
    """读回校验文件是否已携带 AIGC 隐式标识。

    统一以 'ProduceID'（标识 JSON 必含字段）作为判定子串：
    XMP 里 JSON 值与 ID3/LIST INFO 的 JSON 值都含该字段，而标签名 <TC260:AIGC> 无引号、
    JSON 键中也不存在带引号的 "AIGC"，故不能用 AIGC 本身做判定。

    Returns:
        True=已标识；False=无标识；None=格式不支持校验（GIF/WebP 等）
    """
    kind = _sniff_format(file_path)
    if kind == 'png':
        try:
            from PIL import Image
            with Image.open(file_path) as img:
                xmp = (img.info or {}).get(AIGC_PNG_XMP_KEYWORD) or ''
            return 'ProduceID' in xmp if xmp else False
        except Exception as e:  # noqa: BLE001
            logger.debug(f"PNG 读回失败: {file_path}: {e}")
            return None
    if kind == 'jpeg':
        try:
            payload = _jpeg_find_xmp_payload(Path(file_path).read_bytes())
            return bool(payload and b'ProduceID' in payload)
        except Exception as e:  # noqa: BLE001
            logger.debug(f"JPEG 读回失败: {file_path}: {e}")
            return None
    if kind in ('mp4', 'mov'):
        xml_text = _ffprobe_tags_text(file_path)
        return ('ProduceID' in xml_text) if xml_text else False
    if kind == 'mp3':
        xml_text = _ffprobe_tags_text(file_path)
        return ('ProduceID' in xml_text) if xml_text else False
    if kind == 'wav':
        xml_text = _ffprobe_tags_text(file_path)
        return ('ProduceID' in xml_text) if xml_text else False
    return None


# ==================== 写入实现 ====================

def _atomic_replace(tmp_path, target_path):
    os.replace(tmp_path, target_path)


def _write_png(file_path: Path, xmp_packet: str) -> bool:
    """PNG：Pillow 添加 iTXt XMP 块（无损，保留 ICC profile）。"""
    from PIL import Image
    from PIL.PngImagePlugin import PngInfo

    with Image.open(file_path) as img:
        meta = PngInfo()
        meta.add_itxt(AIGC_PNG_XMP_KEYWORD, xmp_packet)
        save_kwargs = {'pnginfo': meta}
        icc = (img.info or {}).get('icc_profile')
        if icc:
            save_kwargs['icc_profile'] = icc
        tmp_path = f"{file_path}.aigc_{os.getpid()}.tmp"
        img.save(tmp_path, 'PNG', **save_kwargs)
    _atomic_replace(tmp_path, file_path)
    return True


def _jpeg_upsert_xmp(data: bytes, xmp_packet: str) -> Optional[bytes]:
    """JPEG 字节级插入/替换 XMP APP1 段（不重编码，保留原 EXIF）。

    - 已有 XMP APP1 → 原位替换 payload
    - 无 XMP 但有 EXIF APP1 → 插在其后（保持 EXIF 在前，符合 Adobe 规范建议）
    - 都没有 → 直接插在 SOI 之后
    """
    if data[:3] != b'\xff\xd8\xff':
        return None
    payload = AIGC_JPEG_APP1_XMP_NS + xmp_packet.encode('utf-8')
    if len(payload) > 65533:  # APP1 段长度上限（2 字节长度 - marker - 长度字段）
        return None
    new_seg = b'\xff\xe1' + len(payload).to_bytes(2, 'big') + payload

    pos = 2
    insert_at = None
    while pos + 4 <= len(data):
        if data[pos] != 0xFF:
            return None  # 段结构异常，放弃（不破坏文件）
        marker = data[pos + 1]
        if marker in (0xD9, 0xDA):
            break  # EOI / SOS：其后为熵编码数据，不可按段解析
        seg_len = int.from_bytes(data[pos + 2:pos + 4], 'big')
        if seg_len < 2 or pos + 2 + seg_len > len(data):
            return None
        if marker == 0xE1:
            if data[pos + 4:pos + 4 + len(AIGC_JPEG_APP1_XMP_NS)] == AIGC_JPEG_APP1_XMP_NS:
                return data[:pos] + new_seg + data[pos + 2 + seg_len:]  # 原位替换
            if insert_at is None:
                insert_at = pos + 2 + seg_len  # EXIF APP1 之后
        pos += 2 + seg_len
    if insert_at is None:
        insert_at = 2
    return data[:insert_at] + new_seg + data[insert_at:]


def _write_jpeg(file_path: Path, xmp_packet: str) -> bool:
    """JPEG：字节级 APP1 插入。"""
    data = file_path.read_bytes()
    new_data = _jpeg_upsert_xmp(data, xmp_packet)
    if new_data is None:
        logger.warning(f"JPEG 段结构异常，跳过标识写入: {file_path}")
        return False
    tmp_path = f"{file_path}.aigc_{os.getpid()}.tmp"
    with open(tmp_path, 'wb') as f:
        f.write(new_data)
    _atomic_replace(tmp_path, file_path)
    return True


def _ffmpeg_remux(file_path: Path, meta_args: list, out_format: str) -> bool:
    """ffmpeg 无损重封装写 metadata（-c copy，不转码）。"""
    tmp_path = f"{file_path}.aigc_{os.getpid()}.tmp"
    try:
        cmd = [_get_ffmpeg_path(), '-y', '-loglevel', 'error',
               '-i', str(file_path), '-c', 'copy', *meta_args, '-f', out_format, tmp_path]
        r = subprocess.run(cmd, capture_output=True, timeout=_SUBPROCESS_TIMEOUT,
                           encoding='utf-8', errors='replace')
        if r.returncode != 0 or not os.path.isfile(tmp_path) or os.path.getsize(tmp_path) == 0:
            raise RuntimeError(f"ffmpeg remux 失败: {(r.stderr or '')[-300:]}")
        _atomic_replace(tmp_path, file_path)
        return True
    finally:
        if os.path.isfile(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def _write_mp4(file_path: Path, xmp_packet: str) -> bool:
    """MP4/MOV：moov 写入 XMP atom（use_metadata_tags）。"""
    return _ffmpeg_remux(
        file_path,
        ['-movflags', 'use_metadata_tags', '-metadata', f'xmp={xmp_packet}'],
        'mp4',
    )


def _write_mp3(file_path: Path, aigc_json: str) -> bool:
    """MP3：ID3 TXXX 帧（自定义 key AIGC）。"""
    return _ffmpeg_remux(file_path, ['-metadata', f'AIGC={aigc_json}'], 'mp3')


def _write_wav(file_path: Path, aigc_json: str) -> bool:
    """WAV：LIST INFO ICMT（comment key，WAV muxer 不支持任意自定义 key）。"""
    return _ffmpeg_remux(file_path, ['-metadata', f'comment={aigc_json}'], 'wav')


# ==================== 对外入口 ====================

def mark_file(file_path, produce_id, media_kind: str = 'auto') -> bool:
    """为单个媒体文件写入 AIGC 隐式标识（幂等：已带标识直接返回 True）。

    Args:
        file_path: 媒体文件路径（本地绝对/相对均可）
        produce_id: 内容编号（标识办法第5条；主链路传 ai_tools.id，拼接链传 compose_id）
        media_kind: 'auto' 按魔数识别，或显式指定 png/jpeg/mp4/mp3/wav

    Returns:
        True=已标识（含幂等命中）；False=未标识（不支持格式/写入失败/功能关闭）
    """
    if not AIGC_MARK_ENABLED:
        return False
    path = Path(file_path)
    if not path.is_file():
        logger.warning(f"AIGC 标识写入跳过：文件不存在 {path}")
        return False

    kind = media_kind if media_kind in _MEDIA_PROP else None
    if kind is None:
        kind = _sniff_format(path)
    if kind is None:
        logger.warning(f"AIGC 标识写入跳过：无法识别媒体格式 {path}")
        return False

    # 幂等：已带标识不重写（下载重试/重复落盘/出口兜底场景）
    if has_aigc_label(path):
        return True

    if kind not in _MEDIA_PROP:
        logger.warning(f"AIGC 标识写入暂不支持该格式({kind})，跳过: {path}")
        return False

    aigc_json = build_aigc_json(produce_id, kind)
    if kind == 'png':
        ok = _write_png(path, build_xmp_packet(aigc_json))
    elif kind == 'jpeg':
        ok = _write_jpeg(path, build_xmp_packet(aigc_json))
    elif kind in ('mp4', 'mov'):
        ok = _write_mp4(path, build_xmp_packet(aigc_json))
    elif kind == 'mp3':
        ok = _write_mp3(path, aigc_json)
    else:  # wav
        ok = _write_wav(path, aigc_json)

    if ok:
        verified = has_aigc_label(path)
        if verified is False:
            logger.warning(f"AIGC 标识写后校验未通过（文件可能未生效）: {path}")
            return False
    return ok


def mark_file_for_task(file_path, task_id, media_type_hint: str = None) -> bool:
    """生成链路落盘标记入口：全容错，失败仅告警，绝不阻断内容交付。

    Args:
        file_path: 落盘后的本地文件路径
        task_id: ai_tools.id（ProduceID 源）
        media_type_hint: 调用方的媒体类型提示（video/image/audio），仅辅助归类，实际格式以魔数为准
    """
    try:
        ok = mark_file(file_path, str(task_id))
        if ok:
            logger.info(f"AIGC 隐式标识写入成功: {file_path} (produce_id={task_id})")
        else:
            logger.warning(f"AIGC 隐式标识写入未生效（不阻断交付）: {file_path}")
        return ok
    except Exception as e:  # noqa: BLE001
        logger.warning(f"AIGC 隐式标识写入异常（不阻断交付）: {file_path}: {e}")
        return False


def ensure_marked(file_path, produce_id) -> bool:
    """分发出口兜底（标识办法第4条：下载/导出时确保文件含有标识）。

    已标识直接返回 True（读校验开销毫秒级）；漏标则补写。
    """
    try:
        return mark_file(file_path, produce_id)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"AIGC 出口兜底标识异常（不阻断下载）: {file_path}: {e}")
        return False
