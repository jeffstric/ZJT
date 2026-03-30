"""
图片压缩工具
支持压缩图片到指定大小限制
"""
import os
import io
import logging
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
    压缩图片到指定大小限制
    
    Args:
        image_path: 输入图片路径
        max_size_mb: 最大文件大小（MB），默认 10MB
        output_path: 输出路径，如果为 None 则覆盖原文件
        quality_start: 起始压缩质量（1-100），默认 95
        quality_min: 最低压缩质量（1-100），默认 60
    
    Returns:
        Tuple[bool, Optional[str], Optional[str]]: 
            - 是否成功
            - 输出文件路径（成功时）
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
