"""
图片压缩工具
支持压缩图片到指定大小限制
"""
import os
import io
import logging
import math
import uuid
from typing import Optional, Tuple
from PIL import Image

logger = logging.getLogger(__name__)


def compress_image_to_limit(
    image_path: str,
    max_size_mb: float = 10.0,
    output_path: Optional[str] = None,
    quality_start: int = 95,
    quality_min: int = 60
) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    【通用图片体积压缩】把图片文件压到指定体积以内，尽量保留画质。

    这是**保画质的通用压缩**，与 `compress_local_image_to_base64` 那套为 LLM 省 token 的
    激进压缩相对。适合需要保留细节的通用场景（视频参考图、图生图首帧、对外提供的图片等）。

    策略：
    - 原图体积 ≤ max_size_mb → **原样返回，不重编码**（零损耗）；
    - 超限时：JPEG 质量从 `quality_start`(95) 二分下降到 `quality_min`(60)；
    - 若降到最低质量仍超限，再按 0.9 等比缩小尺寸（最后手段）；
    - PNG 会转为 JPEG 以获得更好压缩比（透明通道压平为白底）。

    注意：本函数 **不做 LLM 式强制像素缩放**，只按体积压；返回的是**文件路径**（非 base64）。
    若需 base64 data URL，请在本函数处理后再自行读取文件转 base64，或用
    `compress_local_image_to_base64(max_pixels=0)`（等价于先调本函数再转 base64）。

    Args:
        image_path: 输入图片路径
        max_size_mb: 最大文件大小（MB），默认 10MB
        output_path: 输出路径，如果为 None 则覆盖原文件
        quality_start: 起始压缩质量（1-100），默认 95
        quality_min: 最低压缩质量（1-100），默认 60

    Returns:
        Tuple[bool, Optional[str], Optional[str]]:
            - 是否成功
            - 输出文件路径（成功时；未超限时即原路径）
            - 错误信息（失败时）
    """
    try:
        # 检查文件是否存在
        if not os.path.exists(image_path):
            return False, None, f"文件不存在: {image_path}"
        
        # 获取原始文件大小
        original_size_mb = os.path.getsize(image_path) / (1024 * 1024)
        logger.info(f"原始图片大小: {original_size_mb:.2f} MB")
        
        # 如果文件已经小于限制，直接返回
        if original_size_mb <= max_size_mb:
            logger.info(f"图片大小 {original_size_mb:.2f} MB 未超过限制 {max_size_mb} MB，无需压缩")
            return True, image_path, None
        
        # 打开图片
        try:
            img = Image.open(image_path)
            img.load()
        except Exception as e:
            return False, None, f"无法打开图片: {str(e)}"
        
        # 确定输出路径
        if output_path is None:
            output_path = image_path
        
        # 获取图片格式
        img_format = img.format or 'JPEG'
        if img_format.upper() == 'PNG':
            # PNG 转换为 JPEG 以获得更好的压缩效果
            if img.mode in ('RGBA', 'LA', 'P'):
                # 处理透明通道
                background = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                background.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
                img = background
            else:
                img = img.convert('RGB')
            img_format = 'JPEG'
            # 如果输出路径是原路径，修改扩展名
            if output_path == image_path and output_path.lower().endswith('.png'):
                output_path = output_path[:-4] + '.jpg'
        
        # 智能选择起始质量：根据原始大小和目标大小的比例
        size_ratio = original_size_mb / max_size_mb
        if size_ratio <= 1.2:
            # 超出不多（<=20%），从高质量开始
            smart_quality_start = 95
        elif size_ratio <= 1.5:
            # 超出 20%-50%，从中高质量开始
            smart_quality_start = 85
        elif size_ratio <= 2.0:
            # 超出 50%-100%，从中等质量开始
            smart_quality_start = 75
        else:
            # 超出很多（>100%），从较低质量开始
            smart_quality_start = 70
        
        # 使用用户指定的 quality_start 和智能推荐值的较小者
        quality_start = min(quality_start, smart_quality_start)
        logger.info(f"图片超出目标 {size_ratio:.1f} 倍，智能选择起始质量: {quality_start}")
        
        # 二分查找最佳质量参数
        quality = quality_start
        best_quality = quality_min
        best_buffer = None
        
        max_size_bytes = max_size_mb * 1024 * 1024
        
        logger.info(f"开始压缩图片，目标大小: {max_size_mb} MB")
        
        # 尝试不同的质量参数
        for q in range(quality_start, quality_min - 1, -5):
            buffer = io.BytesIO()
            
            # 保存到内存缓冲区
            save_kwargs = {'format': img_format, 'quality': q}
            if img_format == 'JPEG':
                save_kwargs['optimize'] = True
                save_kwargs['progressive'] = True
            
            img.save(buffer, **save_kwargs)
            
            size = buffer.tell()
            size_mb = size / (1024 * 1024)
            
            logger.info(f"质量 {q}: {size_mb:.2f} MB")
            
            if size <= max_size_bytes:
                best_quality = q
                best_buffer = buffer
                break
            
            # 如果还是太大，继续降低质量
            if q == quality_min:
                # 已经到最低质量，尝试缩小尺寸
                logger.warning(f"质量 {quality_min} 仍超过限制，尝试缩小图片尺寸")
                best_buffer = buffer
                best_quality = q
        
        # 如果最低质量仍然超过限制，缩小图片尺寸
        if best_buffer is None or best_buffer.tell() > max_size_bytes:
            logger.info("降低质量无效，开始缩小图片尺寸")
            
            scale_factor = 0.9
            max_iterations = 10
            iteration = 0
            
            while iteration < max_iterations:
                # 计算新尺寸
                new_width = int(img.width * scale_factor)
                new_height = int(img.height * scale_factor)
                
                # 缩小图片
                resized_img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                
                buffer = io.BytesIO()
                save_kwargs = {'format': img_format, 'quality': quality_min}
                if img_format == 'JPEG':
                    save_kwargs['optimize'] = True
                    save_kwargs['progressive'] = True
                
                resized_img.save(buffer, **save_kwargs)
                
                size = buffer.tell()
                size_mb = size / (1024 * 1024)
                
                logger.info(f"缩小到 {new_width}x{new_height}, 大小: {size_mb:.2f} MB")
                
                if size <= max_size_bytes:
                    best_buffer = buffer
                    img = resized_img
                    break
                
                scale_factor *= 0.9
                iteration += 1
            
            if best_buffer is None or best_buffer.tell() > max_size_bytes:
                return False, None, f"无法将图片压缩到 {max_size_mb} MB 以下"
        
        # 保存压缩后的图片
        with open(output_path, 'wb') as f:
            f.write(best_buffer.getvalue())
        
        final_size_mb = os.path.getsize(output_path) / (1024 * 1024)
        logger.info(f"压缩完成: {original_size_mb:.2f} MB -> {final_size_mb:.2f} MB (质量: {best_quality})")
        
        return True, output_path, None
        
    except Exception as e:
        logger.error(f"压缩图片异常: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return False, None, f"压缩图片异常: {str(e)}"


def resize_image_to_pixel_limit(
    image_path: str,
    max_total_pixels: int = 36_000_000,
    output_path: Optional[str] = None
) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    等比缩放图片，使总像素不超过限制

    Args:
        image_path: 输入图片路径
        max_total_pixels: 最大总像素数（width * height），默认 36,000,000
        output_path: 输出路径，如果为 None 则保存到临时文件

    Returns:
        Tuple[bool, Optional[str], Optional[str]]:
            - 是否成功
            - 输出文件路径（成功时）
            - 错误信息（失败时）
    """
    try:
        if not os.path.exists(image_path):
            return False, None, f"文件不存在: {image_path}"

        img = Image.open(image_path)
        img.load()

        total_pixels = img.width * img.height

        # 像素未超限，直接返回原路径
        if total_pixels <= max_total_pixels:
            img.close()
            return True, image_path, None

        # 计算等比缩放比例
        scale = math.sqrt(max_total_pixels / total_pixels)
        new_width = int(img.width * scale)
        new_height = int(img.height * scale)

        logger.info(f"图片总像素 {total_pixels:,} 超过限制 {max_total_pixels:,}，等比缩放: {img.width}x{img.height} -> {new_width}x{new_height}")

        # 等比缩放
        resized_img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

        # 确定输出路径
        if output_path is None:
            from utils.media_cache import get_temp_date_dir
            from datetime import datetime
            temp_dir = get_temp_date_dir(datetime.now())
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            ext = os.path.splitext(image_path)[1] or ".jpg"
            output_path = str(temp_dir / f"pixel_resized_{timestamp}_{uuid.uuid4().hex[:8]}{ext}")

        # 保存缩放后的图片，保持原格式
        img_format = img.format or 'JPEG'
        save_kwargs = {'format': img_format}
        if img_format == 'JPEG':
            save_kwargs['quality'] = 95
            save_kwargs['optimize'] = True
        elif img_format == 'PNG':
            save_kwargs['optimize'] = True

        resized_img.save(output_path, **save_kwargs)

        actual_pixels = new_width * new_height
        logger.info(f"像素缩放完成: {total_pixels:,} -> {actual_pixels:,} px, 保存到: {output_path}")

        img.close()
        resized_img.close()
        return True, output_path, None

    except Exception as e:
        logger.error(f"像素缩放异常: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return False, None, f"像素缩放异常: {str(e)}"


def get_image_size_mb(image_path: str) -> Optional[float]:
    """
    获取图片文件大小（MB）
    
    Args:
        image_path: 图片路径
    
    Returns:
        Optional[float]: 文件大小（MB），失败返回 None
    """
    try:
        if not os.path.exists(image_path):
            return None
        return os.path.getsize(image_path) / (1024 * 1024)
    except Exception:
        return None


def compress_local_image_to_base64(
    local_path: str,
    max_size_mb: float = 2.0,
    max_pixels: int = 0,
    cleanup: bool = False
) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    【⚠️ 用途限定：LLM 视觉理解专用】从本地文件读取图片，压缩并返回 base64 data URL。

    本函数为「把图片喂给大模型做视觉理解（Vision-Language，即日志中的 [VL]）」而设计，
    核心目标是 **省 token**，因此压缩偏激进。处理流程：

    1. 若 max_pixels > 0：先把图等比缩放到 max_pixels 以内，并以 JPEG quality=85 重编码
       （顺带把 PNG / 带透明通道的图压平为白底 JPEG）——用于控制送入 LLM 的像素/token 消耗；
    2. 再按 max_size_mb 做体积压缩（转调 compress_image_to_limit，质量 95→60 自适应）。

    不涉及任何 HTTP 下载，仅处理本地磁盘上的文件。

    ⚠️ 误用警告（重要）：
        max_pixels > 0 会触发「强制缩放 + JPEG q85 重编码」，对需要保留细节的场景有损。
        曾因对**视频生成参考图**误传 max_pixels=2_073_600，把 1.3MB 的图压成 45KB、
        导致生成视频里人物细节丢失。**若你的场景需要保留图片细节**（视频参考图、图生图
        首帧、需要高保真的输入），请：
        - 传 `max_pixels=0`（跳过强制缩放+JPEG-q85，仅按体积温和压缩）；或
        - 直接用更通用的 `compress_image_to_limit`（仅按体积压、不强制缩放）。

    Args:
        local_path: 本地图片文件路径
        max_size_mb: 最大文件大小（MB），默认 2MB。**仅当原图超此体积才压缩，否则原样返回**（保留画质）。
        max_pixels: 最大总像素数（width * height）。这是本函数最易误用的参数：
            - **0（默认）= 不做像素缩放**，仅按体积压缩（温和、保留细节，适合通用场景）；
            - **>0 = 触发 LLM 式强制缩放 + JPEG q85 重编码**（激进、省 token、有损，仅限喂 LLM）。
        cleanup: 是否在完成后清理临时文件（当输入文件本身就是临时文件时设为 True）

    Returns:
        Tuple[bool, Optional[str], Optional[str]]:
            - 是否成功
            - base64 data URL（如 "data:image/jpeg;base64,..."）
            - 错误信息（失败时）
    """
    import base64

    if not os.path.exists(local_path):
        return False, None, f"本地文件不存在: {local_path}"

    _temp_files = []  # 跟踪所有临时文件，确保最终清理
    if cleanup:
        _temp_files.append(local_path)

    try:
        logger.info(f"[VL] 处理本地图片: {local_path}")

        # 像素限制 + 强制 PNG→JPEG 转换（LLM 按像素消耗 token，必须处理）
        file_to_compress = local_path
        if max_pixels > 0:
            try:
                img = Image.open(local_path)
                total_pixels = img.width * img.height
                needs_resize = total_pixels > max_pixels
                needs_convert = (img.format or '').upper() == 'PNG' or img.mode in ('RGBA', 'LA', 'P')

                if needs_resize or needs_convert:
                    # 转 RGB（去掉透明通道，为 JPEG 做准备）
                    if img.mode != 'RGB':
                        background = Image.new('RGB', img.size, (255, 255, 255))
                        if img.mode == 'P':
                            img = img.convert('RGBA')
                        if img.mode in ('RGBA', 'LA'):
                            background.paste(img, mask=img.split()[-1])
                        img = background
                        needs_convert = True

                    # 缩放
                    if needs_resize:
                        scale = math.sqrt(max_pixels / total_pixels)
                        new_w = int(img.width * scale)
                        new_h = int(img.height * scale)
                        img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                        logger.info(f"[VL] 像素缩放: {total_pixels:,} -> {new_w * new_h:,} px")

                    # 强制保存为 JPEG
                    jpeg_path = local_path.rsplit('.', 1)[0] + '_llm.jpg'
                    img.save(jpeg_path, 'JPEG', quality=85, optimize=True)
                    img.close()
                    _temp_files.append(jpeg_path)
                    file_to_compress = jpeg_path
                    jpeg_size_kb = os.path.getsize(jpeg_path) // 1024
                    logger.info(f"[VL] 强制转 JPEG 完成: {jpeg_size_kb} KB")
                else:
                    img.close()
            except Exception as e:
                logger.warning(f"[VL] 像素/格式处理失败，回退到普通压缩: {e}")

        # 文件大小压缩
        success, compressed_path, error = compress_image_to_limit(file_to_compress, max_size_mb=max_size_mb)
        if compressed_path and compressed_path != file_to_compress:
            _temp_files.append(compressed_path)
        if not success:
            return False, None, error or '压缩失败'

        # 读取并转 base64
        with open(compressed_path, 'rb') as f:
            data = f.read()

        cext = os.path.splitext(compressed_path)[1].lower()
        mime_map = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.webp': 'image/webp'}
        mime_type = mime_map.get(cext, 'image/jpeg')

        b64 = base64.b64encode(data).decode('utf-8')
        data_url = f"data:{mime_type};base64,{b64}"

        size_kb = len(data) // 1024
        logger.info(f"[VL] 图片压缩转 base64 完成: {size_kb} KB")

        return True, data_url, None

    except Exception as e:
        logger.error(f"[VL] 处理本地图片异常: {e}", exc_info=True)
        return False, None, f"处理图片异常: {e}"
    finally:
        for f in _temp_files:
            try:
                os.remove(f)
            except Exception:
                pass


def download_and_compress_to_base64(
    image_url: str,
    max_size_mb: float = 2.0,
    max_pixels: int = 0
) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    【⚠️ 用途限定：LLM 视觉理解专用】从 URL 下载图片，压缩并返回 base64 data URL。

    供 PM Agent 在专家返回图片 URL 后，将图片注入到 LLM 对话历史。下载后转调
    `compress_local_image_to_base64`，因此**继承其 LLM 式激进压缩特性与 max_pixels 陷阱**：
    - 仅允许 http/https 协议（其它协议如 ftp/file/data 一律拒绝并返回错误）；
    - max_pixels > 0 会强制缩放 + JPEG q85 重编码（为 LLM 省 token，对细节有损）。
    ⚠️ 若需保留细节（视频参考图等），请传 `max_pixels=0`，详见
    `compress_local_image_to_base64` 的「误用警告」。

    Args:
        image_url: 图片 URL（仅 http/https）
        max_size_mb: 最大文件大小（MB），默认 2MB；仅超限时才压缩。
        max_pixels: 最大总像素数。**0=仅按体积温和压缩（保留细节，推荐）**；
            >0=LLM 式强制缩放+JPEG q85（有损）。详见 compress_local_image_to_base64。

    Returns:
        Tuple[bool, Optional[str], Optional[str]]:
            - 是否成功
            - base64 data URL（如 "data:image/jpeg;base64,..."）
            - 错误信息（失败时）
    """
    import httpx

    # 验证 URL 格式：仅允许 http/https 协议
    from urllib.parse import urlparse
    parsed_url = urlparse(image_url)
    if parsed_url.scheme not in ('http', 'https'):
        return False, None, f"不支持的 URL 协议: {parsed_url.scheme}"

    temp_path = None
    try:
        # 下载图片（使用 httpx 同步客户端，避免阻塞事件循环）
        logger.info(f"[VL] 下载图片: {image_url[:100]}...")
        headers = {'User-Agent': 'Mozilla/5.0'}
        with httpx.Client(timeout=30, verify=False) as client:
            resp = client.get(image_url, headers=headers)
            resp.raise_for_status()
            img_data = resp.content

        if not img_data:
            return False, None, "下载图片为空"

        # 保存到临时文件
        from utils.media_cache import get_temp_date_dir
        from datetime import datetime
        temp_dir = get_temp_date_dir(datetime.now())
        url_path = image_url.split('?')[0]
        ext = os.path.splitext(url_path)[1].lower() or '.jpg'
        if ext not in ('.jpg', '.jpeg', '.png', '.webp', '.gif'):
            ext = '.jpg'
        temp_path = str(temp_dir / f"vl_gen_{uuid.uuid4().hex[:8]}{ext}")

        with open(temp_path, 'wb') as f:
            f.write(img_data)

        logger.info(f"[VL] 图片已下载: {len(img_data) // 1024} KB")

        # 复用本地压缩函数（cleanup=True 表示临时文件需要清理）
        return compress_local_image_to_base64(temp_path, max_size_mb, max_pixels, cleanup=True)

    except httpx.HTTPStatusError as e:
        logger.error(f"[VL] 下载图片网络错误: {e}")
        return False, None, f"下载图片失败: {e}"
    except Exception as e:
        logger.error(f"[VL] 下载压缩图片异常: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False, None, f"处理图片异常: {e}"


def url_to_base64(image_url: str, max_size_mb: float = 2.0, max_pixels: int = 0) -> Optional[str]:
    """
    【⚠️ LLM 视觉理解专用】URL 转 base64 data URL（同步）。

    封装 download_and_compress_to_base64()，失败时返回 None。**继承 LLM 式激进压缩与
    max_pixels 陷阱**：需保留细节的场景（视频参考图等）请传 `max_pixels=0`，详见
    compress_local_image_to_base64 的「误用警告」。

    Args:
        image_url: 图片 HTTP URL（仅 http/https）
        max_size_mb: 最大文件大小（MB），默认 2MB；仅超限时才压缩
        max_pixels: 最大总像素数。**0=仅体积温和压缩（保留细节，推荐）**；
            >0=LLM 式强制缩放+JPEG q85（有损）

    Returns:
        base64 data URL（如 "data:image/jpeg;base64,..."），失败返回 None
    """
    success, data_url, error = download_and_compress_to_base64(image_url, max_size_mb, max_pixels)
    if success and data_url:
        return data_url
    logger.warning(f"url_to_base64 失败 ({image_url[:80]}): {error}")
    return None


async def async_download_and_compress_to_base64(
    image_url: str,
    max_size_mb: float = 2.0,
    max_pixels: int = 0
) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    【⚠️ LLM 视觉理解专用】异步版本：从 URL 下载图片，压缩并返回 base64 data URL。

    使用 httpx.AsyncClient 进行网络请求，PIL 图片处理通过 asyncio.to_thread 协载到线程池，
    适合在异步事件循环中调用（避免阻塞）。逻辑与同步版 `download_and_compress_to_base64`
    一致，**同样继承 LLM 式激进压缩与 max_pixels 陷阱**：仅允许 http/https；max_pixels>0
    会强制缩放+JPEG q85（有损）。需保留细节的场景请传 `max_pixels=0`，详见
    `compress_local_image_to_base64` 的「误用警告」。

    Args:
        image_url: 图片 URL（仅 http/https）
        max_size_mb: 最大文件大小（MB），默认 2MB；仅超限时才压缩
        max_pixels: 最大总像素数。**0=仅体积温和压缩（保留细节，推荐）**；
            >0=LLM 式强制缩放+JPEG q85（有损）

    Returns:
        Tuple[bool, Optional[str], Optional[str]]:
            - 是否成功
            - base64 data URL
            - 错误信息（失败时）
    """
    import base64
    import asyncio
    import httpx

    # 验证 URL 格式：仅允许 http/https 协议
    from urllib.parse import urlparse
    parsed_url = urlparse(image_url)
    if parsed_url.scheme not in ('http', 'https'):
        return False, None, f"不支持的 URL 协议: {parsed_url.scheme}"

    temp_path = None
    _temp_files = []  # 跟踪所有临时文件，确保最终清理
    try:
        # 异步下载图片
        logger.info(f"[VL] 异步下载图片: {image_url[:100]}...")
        headers = {'User-Agent': 'Mozilla/5.0'}
        async with httpx.AsyncClient(timeout=30, verify=False) as client:
            resp = await client.get(image_url, headers=headers)
            resp.raise_for_status()
            img_data = resp.content

        if not img_data:
            return False, None, "下载图片为空"

        # 保存到临时文件
        from utils.media_cache import get_temp_date_dir
        from datetime import datetime
        temp_dir = get_temp_date_dir(datetime.now())
        url_path = image_url.split('?')[0]
        ext = os.path.splitext(url_path)[1].lower() or '.jpg'
        if ext not in ('.jpg', '.jpeg', '.png', '.webp', '.gif'):
            ext = '.jpg'
        temp_path = str(temp_dir / f"vl_gen_{uuid.uuid4().hex[:8]}{ext}")
        _temp_files.append(temp_path)

        with open(temp_path, 'wb') as f:
            f.write(img_data)

        logger.info(f"[VL] 图片已下载: {len(img_data) // 1024} KB")

        # PIL 图片处理卸载到线程池，避免阻塞事件循环
        file_to_compress = temp_path
        if max_pixels > 0:
            def _process_pixels():
                img = Image.open(temp_path)
                total_pixels = img.width * img.height
                needs_resize = total_pixels > max_pixels
                needs_convert = (img.format or '').upper() == 'PNG' or img.mode in ('RGBA', 'LA', 'P')

                if needs_resize or needs_convert:
                    if img.mode != 'RGB':
                        background = Image.new('RGB', img.size, (255, 255, 255))
                        if img.mode == 'P':
                            img = img.convert('RGBA')
                        if img.mode in ('RGBA', 'LA'):
                            background.paste(img, mask=img.split()[-1])
                        img = background
                        needs_convert = True

                    if needs_resize:
                        scale = math.sqrt(max_pixels / total_pixels)
                        new_w = int(img.width * scale)
                        new_h = int(img.height * scale)
                        img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                        logger.info(f"[VL] 像素缩放: {total_pixels:,} -> {new_w * new_h:,} px")

                    jpeg_path = temp_path.rsplit('.', 1)[0] + '_llm.jpg'
                    img.save(jpeg_path, 'JPEG', quality=85, optimize=True)
                    img.close()
                    return jpeg_path, True
                else:
                    img.close()
                    return temp_path, False

            try:
                result_path, converted = await asyncio.to_thread(_process_pixels)
                file_to_compress = result_path
                if converted:
                    _temp_files.append(result_path)
                    jpeg_size_kb = os.path.getsize(result_path) // 1024
                    logger.info(f"[VL] 强制转 JPEG 完成: {jpeg_size_kb} KB")
            except Exception as e:
                logger.warning(f"[VL] 像素/格式处理失败，回退到普通压缩: {e}")

        # 文件大小压缩（CPU 密集，卸载到线程池）
        success, compressed_path, error = await asyncio.to_thread(
            compress_image_to_limit, file_to_compress, max_size_mb
        )
        if compressed_path and compressed_path not in _temp_files:
            _temp_files.append(compressed_path)
        if not success:
            return False, None, error or '压缩失败'

        # 读取并转 base64
        with open(compressed_path, 'rb') as f:
            data = f.read()

        cext = os.path.splitext(compressed_path)[1].lower()
        mime_map = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.webp': 'image/webp'}
        mime_type = mime_map.get(cext, 'image/jpeg')

        b64 = base64.b64encode(data).decode('utf-8')
        data_url = f"data:{mime_type};base64,{b64}"

        size_kb = len(data) // 1024
        logger.info(f"[VL] 图片压缩转 base64 完成: {size_kb} KB")

        return True, data_url, None

    except httpx.HTTPStatusError as e:
        logger.error(f"[VL] 下载图片网络错误: {e}")
        return False, None, f"下载图片失败: {e}"
    except Exception as e:
        logger.error(f"[VL] 下载压缩图片异常: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False, None, f"处理图片异常: {e}"
    finally:
        # 清理所有临时文件
        for f in _temp_files:
            try:
                os.remove(f)
            except Exception:
                pass


async def async_url_to_base64(image_url: str, max_size_mb: float = 2.0, max_pixels: int = 0) -> Optional[str]:
    """
    【⚠️ LLM 视觉理解专用】异步版本：URL 转 base64 data URL。

    封装 async_download_and_compress_to_base64()，失败返回 None。**继承 LLM 式激进压缩与
    max_pixels 陷阱**：需保留细节的场景（视频参考图等）请传 `max_pixels=0`，详见
    compress_local_image_to_base64 的「误用警告」。

    Args:
        image_url: 图片 HTTP URL（仅 http/https）
        max_size_mb: 最大文件大小（MB），默认 2MB；仅超限时才压缩
        max_pixels: 最大总像素数。**0=仅体积温和压缩（保留细节，推荐）**；
            >0=LLM 式强制缩放+JPEG q85（有损）

    Returns:
        base64 data URL（如 "data:image/jpeg;base64,..."），失败返回 None
    """
    success, data_url, error = await async_download_and_compress_to_base64(image_url, max_size_mb, max_pixels)
    if success and data_url:
        return data_url
    logger.warning(f"async_url_to_base64 失败 ({image_url[:80]}): {error}")
    return None
