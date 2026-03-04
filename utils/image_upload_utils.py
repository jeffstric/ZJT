"""
图片上传相关工具函数
支持本地图片和局域网URL上传到图床
"""
import os
import asyncio
import tempfile
import logging
import uuid
from typing import List, Optional, Dict, Any
from urllib.parse import urlparse, unquote

from config.constant import FilePathConstants
from utils.network_utils import is_local_path, is_local_file_path
from utils.file_storage import get_file_storage

logger = logging.getLogger(__name__)


def try_map_url_to_local_file(url: str, config: Dict[str, Any], project_root: str = None) -> Optional[str]:
    """
    尝试将URL映射到本地文件路径（当URL域名与server.host匹配时）

    Args:
        url: 图片URL
        config: 配置字典，包含 server.host
        project_root: 项目根目录，默认为当前工作目录

    Returns:
        Optional[str]: 本地文件路径，如果无法映射返回None
    """
    try:
        # 获取 server.host 配置
        server_host = config.get("server", {}).get("host", "")
        if not server_host:
            return None

        # 解析配置的 server.host
        server_parsed = urlparse(server_host)
        server_netloc = server_parsed.netloc.lower()

        # 解析图片URL
        url_parsed = urlparse(url)
        url_netloc = url_parsed.netloc.lower()

        # 检查域名是否匹配（包括端口）
        if server_netloc != url_netloc:
            return None

        # URL路径映射到本地文件
        # 例如: /upload/temp/xxx.png -> ./upload/temp/xxx.png
        url_path = unquote(url_parsed.path)
        if url_path.startswith("/"):
            url_path = url_path[1:]  # 移除开头的斜杠

        # 获取项目根目录
        if project_root is None:
            project_root = os.getcwd()
        local_path = os.path.join(project_root, url_path)

        # 检查文件是否存在
        if os.path.exists(local_path):
            logger.info(f"URL映射到本地文件: {url} -> {local_path}")
            return local_path
        else:
            logger.warning(f"映射的本地文件不存在: {local_path}")
            return None

    except Exception as e:
        logger.error(f"URL映射异常: {str(e)}")
        return None


async def download_url_to_temp(url: str, app_dir: str = None) -> Optional[str]:
    """
    下载URL到临时文件（使用 files/tmp/pic/年月日/ 目录）

    Args:
        url: 图片URL
        app_dir: 应用根目录，默认为当前工作目录

    Returns:
        Optional[str]: 临时文件路径，失败返回None
    """
    import aiohttp

    try:
        # 获取图片临时目录（按年月日分组）
        if app_dir is None:
            app_dir = os.getcwd()
        pic_tmp_dir = FilePathConstants.get_pic_tmp_dir(app_dir)

        # 从URL中提取文件名
        parsed = urlparse(url)
        path = unquote(parsed.path)
        filename = os.path.basename(path) or "image.png"

        # 生成唯一的临时文件名
        suffix = os.path.splitext(filename)[1] or ".png"
        unique_name = f"{uuid.uuid4().hex}{suffix}"
        temp_path = os.path.join(pic_tmp_dir, unique_name)

        logger.info(f"下载局域网图片: {url} -> {temp_path}")

        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                if response.status == 200:
                    content = await response.read()
                    with open(temp_path, 'wb') as f:
                        f.write(content)
                    return temp_path
                else:
                    logger.error(f"下载图片失败，状态码: {response.status}")
                    os.remove(temp_path)
                    return None
    except Exception as e:
        logger.error(f"下载图片异常: {str(e)}")
        return None


async def upload_local_images_to_cdn(
    image_urls: List[str],
    config: Dict[str, Any],
    project_root: str = None
) -> List[str]:
    """
    将本地图片上传到图床并返回CDN链接

    Args:
        image_urls: 图片路径列表（可能是本地路径或URL）
        config: 配置字典，包含 file_storage 和 server 配置
        project_root: 项目根目录，用于URL到本地文件的映射

    Returns:
        List[str]: 上传后的CDN链接列表
    """
    if not image_urls:
        return image_urls

    result_urls = []
    storage = get_file_storage(config)

    for image_path in image_urls:
        image_path = image_path.strip()
        if not image_path:
            continue

        # 如果是外网URL，直接使用
        if not is_local_path(image_path):
            result_urls.append(image_path)
            continue

        temp_file = None
        file_to_upload = None

        try:
            # 判断是本地文件还是局域网URL
            if is_local_file_path(image_path):
                # 本地文件路径
                if not os.path.exists(image_path):
                    logger.warning(f"本地图片文件不存在: {image_path}")
                    result_urls.append(image_path)
                    continue
                file_to_upload = image_path
                filename = os.path.basename(image_path)
            else:
                # 局域网URL，优先尝试映射到本地文件
                local_file = try_map_url_to_local_file(image_path, config, project_root)
                if local_file:
                    # URL域名与server.host匹配，直接使用本地文件
                    file_to_upload = local_file
                    filename = os.path.basename(local_file)
                else:
                    # 无法映射，需要HTTP下载
                    logger.info(f"检测到局域网URL，准备下载: {image_path}")
                    temp_file = await download_url_to_temp(image_path, project_root)
                    if not temp_file:
                        logger.error(f"下载局域网图片失败: {image_path}")
                        result_urls.append(image_path)
                        continue
                    file_to_upload = temp_file
                    # 从URL中提取文件名
                    parsed = urlparse(image_path)
                    filename = os.path.basename(unquote(parsed.path)) or "image.png"

            # 生成带日期时间前缀的key
            key = storage.generate_key_with_datetime(filename)

            logger.info(f"上传图片到图床: {file_to_upload} -> {key}")

            # 上传文件
            upload_result = await storage.upload_file(key, file_to_upload)

            if upload_result.success:
                # 获取私有下载链接
                cdn_url = storage.get_download_url(upload_result.key)
                logger.info(f"图片上传成功，CDN链接: {cdn_url}")
                result_urls.append(cdn_url)
            else:
                logger.error(f"图片上传失败: {upload_result.error}")
                result_urls.append(image_path)
        except Exception as e:
            logger.error(f"上传图片异常: {str(e)}")
            result_urls.append(image_path)
        finally:
            # 清理临时文件
            if temp_file and os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except Exception:
                    pass

    return result_urls


def upload_local_images_to_cdn_sync(
    image_urls: List[str],
    config: Dict[str, Any],
    project_root: str = None
) -> List[str]:
    """
    同步方式上传本地图片到图床

    Args:
        image_urls: 图片路径列表
        config: 配置字典
        project_root: 项目根目录

    Returns:
        List[str]: 上传后的CDN链接列表
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # 如果事件循环已在运行，创建新任务
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(
                    asyncio.run,
                    upload_local_images_to_cdn(image_urls, config, project_root)
                )
                return future.result()
        else:
            return loop.run_until_complete(
                upload_local_images_to_cdn(image_urls, config, project_root)
            )
    except RuntimeError:
        # 没有事件循环，创建新的
        return asyncio.run(upload_local_images_to_cdn(image_urls, config, project_root))
