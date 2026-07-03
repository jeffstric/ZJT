"""
图片上传相关工具函数
支持本地图片和局域网URL上传到图床
"""
import aiohttp
import os
import asyncio
import concurrent.futures
import logging
import time
import uuid
from typing import List, Optional, Dict, Any
from urllib.parse import urlparse, unquote, parse_qs
from pathlib import Path
from datetime import datetime

from concurrent.futures import TimeoutError as FutureTimeoutError

from config.constant import (
    FilePathConstants,
    IMAGE_UPLOAD_STORAGE_UPLOAD_TIMEOUT,
    IMAGE_UPLOAD_SYNC_WRAPPER_TIMEOUT,
    IMAGE_URL_PROBE_TOTAL_TIMEOUT,
    IMAGE_URL_PROBE_CONNECT_TIMEOUT,
    IMAGE_URL_PROBE_CONCURRENCY,
    IMAGE_URL_REFRESH_SYNC_WRAPPER_TIMEOUT,
)
from utils.network_utils import is_local_path, is_local_file_path
from utils.file_storage import get_file_storage
from utils.image_compressor import compress_image_to_limit, get_image_size_mb
from utils.media_cache import get_temp_date_dir
from utils.media_mapping_util import extract_local_path_from_url

logger = logging.getLogger(__name__)

# 项目根目录
_PROJECT_ROOT = Path(__file__).parent.parent
_SYNC_WRAPPER_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=4,
    thread_name_prefix="image_upload_sync_wrapper",
)

# 外层 future.result 比内层 asyncio.wait_for 多留的余量（秒）。
# 内层 wait_for 超时后仍需时间取消协程、让 asyncio.run 干净退出（关闭事件循环）；
# 若内外用同一 timeout，线程调度抖动会使外层先抛 FutureTimeoutError，而内层 asyncio.run
# 仍在跑、占用 worker，最坏耗尽 4 个 worker → 后续同步包装全部"排队→假超时"。
# （符合 CLAUDE.md rule 10：模块级长寿 executor + 内层超时保护的精神）
_SYNC_WRAPPER_OUTER_MARGIN_SECONDS = 5


def _run_coro_sync(coro, timeout: float, timeout_result, operation: str):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        try:
            return asyncio.run(asyncio.wait_for(coro, timeout=timeout))
        except asyncio.TimeoutError:
            logger.error("%s超时: timeout=%ss", operation, timeout)
            return timeout_result

    future = _SYNC_WRAPPER_EXECUTOR.submit(
        asyncio.run,
        asyncio.wait_for(coro, timeout=timeout),
    )
    try:
        # 外层比内层多留 _SYNC_WRAPPER_OUTER_MARGIN_SECONDS，确保内层 wait_for 超时后
        # asyncio.run 能干净退出，不长期占用线程池 worker（避免 worker 耗尽→假超时连锁）
        return future.result(timeout=timeout + _SYNC_WRAPPER_OUTER_MARGIN_SECONDS)
    except (FutureTimeoutError, asyncio.TimeoutError):
        logger.error("%s超时: timeout=%ss", operation, timeout)
        return timeout_result


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
            logger.warning(f"[图片上传诊断] URL域名不匹配: url_netloc={url_netloc}, config_server_netloc={server_netloc}, url={url}")
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
    temp_path = None
    success = False
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
                    success = True
                    return temp_path
                else:
                    logger.error(f"下载图片失败，状态码: {response.status}")
                    return None
    except Exception as e:
        logger.error(f"下载图片异常: {str(e)}")
        return None
    finally:
        if not success and temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


async def _probe_url_status(url: str) -> str:
    """主动探测第三方 URL 当前可访问性（Range: bytes=0-0，仅取 1 字节）。

    用于判断「非自有 CDN」的第三方签名 URL 是否已过期。过期 URL 会立即返回
    401/403（不等超时）；只有「不可达」(DNS/连接失败) 才会卡满 connect 超时。

    Returns:
        'ok' (2xx，含 206) / 'auth_failed' (401,403=签名失效) /
        'other' (404,5xx,网络错误等不确定情况)
    """
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                headers={"Range": "bytes=0-0"},
                timeout=aiohttp.ClientTimeout(
                    total=IMAGE_URL_PROBE_TOTAL_TIMEOUT,
                    connect=IMAGE_URL_PROBE_CONNECT_TIMEOUT,
                ),
                allow_redirects=True,
            ) as resp:
                if 200 <= resp.status < 300:
                    return "ok"
                if resp.status in (401, 403):
                    return "auth_failed"
                return "other"
    except Exception:
        return "other"


async def ensure_fresh_image_url(
    image_url: str,
    config: Dict[str, Any],
    project_root: str = None,
) -> str:
    """确保图片 URL 新鲜可访问，返回可直接交给下游/网络的 URL（始终返回 str）。

    决策树：
    1. 空 / 本地路径 → 原样返回（本地源的上传交由调用方处理）。
    2. 自有 CDN URL（CDNUtil.is_cdn_url 命中）→ refresh_cdn_signed_url 重签名
       （零成本，纯本地 HMAC；配置不全/异常时返回原 URL）。**自有图床从不抛异常**。
    3. 第三方 URL → 主动探测：
       - 'ok' (2xx) → 原样返回（此刻仍可用）；
       - 'auth_failed' (401/403，已过期) → 抛 ImageExpiredError（第三方无法重签、
         下载转存同样 401，无法救回，需提示用户重新上传）；
       - 'other' (404/5xx/网络错误) → 降级原样返回（不阻断，交下游尝试）。
    """
    if not image_url or not isinstance(image_url, str):
        return image_url
    if not image_url.startswith(("http://", "https://")):
        return image_url

    from utils.cdn_util import CDNUtil

    # (1) 自有 CDN：零成本重签名，不探测、不抛异常
    if CDNUtil.is_cdn_url(image_url):
        return CDNUtil.refresh_cdn_signed_url(image_url)

    # (2) 第三方 URL：先检查 /upload/ 本地映射（本服务文件即使域名未在 CDN 配置中
    #     也能通过本地副本恢复，避免误判过期抛异常）
    if project_root:
        local_rel = extract_local_path_from_url(image_url)
        if local_rel:
            candidate = os.path.join(project_root, local_rel)
            if os.path.exists(candidate):
                # 本地有副本：返回原 URL，由下载/透传链路用本地映射恢复
                return image_url

    # 主动探测是否过期
    status = await _probe_url_status(image_url)
    if status == "ok":
        return image_url
    if status == "auth_failed":
        # 延迟导入避免循环依赖
        from task.visual_drivers.exceptions import ImageExpiredError
        raise ImageExpiredError(
            f"输入图片已过期或不可访问，请重新上传: {image_url[:80]}"
        )
    # 'other'：不确定（404/5xx/网络波动），降级原样返回
    return image_url


def ensure_fresh_image_url_sync(
    image_url: str,
    config: Dict[str, Any],
    project_root: str = None,
) -> str:
    """ensure_fresh_image_url 的同步包装（供同步上下文的驱动使用）。

    超时时降级返回原 URL（不阻断主流程）；ImageExpiredError 等业务异常正常传播。
    """
    return _run_coro_sync(
        ensure_fresh_image_url(image_url, config, project_root),
        IMAGE_URL_REFRESH_SYNC_WRAPPER_TIMEOUT,
        image_url,
        "同步刷新图片URL",
    )


async def _upload_one_to_cdn(
    source: str,
    storage,
    config: Dict[str, Any],
    project_root: str,
) -> str:
    """把单个本地文件 / 局域网 URL 上传到 CDN，返回带签名的 CDN URL。

    从原 upload_local_images_to_cdn 的本地分支抽取，供串行上传复用。
    失败抛 RuntimeError（与原行为一致）。
    """
    temp_file = None
    try:
        if is_local_file_path(source):
            # 本地文件路径 — 若原路径不存在，尝试拼接项目根目录
            resolved_path = source
            if not os.path.exists(resolved_path) and project_root:
                candidate = os.path.join(project_root, source.lstrip('/').lstrip('\\'))
                if os.path.exists(candidate):
                    resolved_path = candidate
            if not os.path.exists(resolved_path):
                error_msg = f"本地图片文件不存在: {source}"
                if resolved_path != source:
                    error_msg += f" (尝试解析: {resolved_path})"
                logger.error(error_msg)
                raise RuntimeError(error_msg)
            file_to_upload = resolved_path
            filename = os.path.basename(resolved_path)
        else:
            # 局域网 URL：优先映射本地，否则 HTTP 下载
            local_file = try_map_url_to_local_file(source, config, project_root)
            if local_file:
                file_to_upload = local_file
                filename = os.path.basename(local_file)
            else:
                logger.info(f"检测到局域网URL，准备下载: {source}")
                temp_file = await download_url_to_temp(source, project_root)
                if not temp_file:
                    error_msg = f"下载局域网图片失败: {source}"
                    logger.error(error_msg)
                    raise RuntimeError(error_msg)
                file_to_upload = temp_file
                parsed = urlparse(source)
                filename = os.path.basename(unquote(parsed.path)) or "image.png"

        key = storage.generate_key_with_datetime(filename)
        logger.info(f"上传图片到图床: {file_to_upload} -> {key}")
        try:
            upload_result = await asyncio.wait_for(
                storage.upload_file(key, file_to_upload),
                timeout=IMAGE_UPLOAD_STORAGE_UPLOAD_TIMEOUT,
            )
        except asyncio.TimeoutError as exc:
            error_msg = f"图片上传到CDN超时: {source}"
            logger.error(error_msg)
            raise RuntimeError(error_msg) from exc

        if upload_result.success:
            cdn_url = storage.get_download_url(upload_result.key)
            logger.info(f"图片上传成功，CDN链接: {cdn_url}")
            return cdn_url
        error_msg = f"图片上传到CDN失败: {source}, 错误: {upload_result.error}"
        logger.error(error_msg)
        raise RuntimeError(error_msg)
    except RuntimeError:
        raise
    except Exception as e:
        error_msg = f"上传图片到CDN异常: {source}, 错误: {str(e)}"
        logger.error(error_msg)
        raise RuntimeError(error_msg) from e
    finally:
        if temp_file and os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except Exception:
                pass


async def upload_local_images_to_cdn(
    image_urls: List[str],
    config: Dict[str, Any],
    project_root: str = None
) -> List[str]:
    """
    将本地图片/局域网URL上传到图床，外网URL确保新鲜后透传，返回CDN链接列表。

    - 外网 URL：经 ensure_fresh_image_url 刷新（自有 CDN 重签名 / 第三方探测），
      多张并发(IMAGE_URL_PROBE_CONCURRENCY)避免串行累积卡住调度；自有 CDN 重签名
      失败时尝试 /upload/ 本地映射兜底（命中本地副本则转入上传流程得到新鲜 URL），
      避免透传过期 URL 给下游。
    - 本地文件 / 局域网 URL：串行上传到图床（复用 _upload_one_to_cdn）。
    - 结果按输入顺序一一对应（首帧/尾帧/参考图正确回填）。

    Args:
        image_urls: 图片路径列表（本地路径 / 局域网URL / 外网URL 混合）
        config: 配置字典，包含 file_storage 和 server 配置
        project_root: 项目根目录，用于URL到本地文件的映射

    Returns:
        List[str]: 与输入顺序对应的CDN链接/刷新后URL列表（跳过空字符串项）
    """
    if not image_urls:
        return image_urls

    if not project_root:
        project_root = os.getcwd()

    # 按原索引记录结果，保证输出顺序与输入一一对应
    results: List[Optional[str]] = [None] * len(image_urls)
    # 待串行上传的本地源：(原索引, 源路径)
    pending_local: List[tuple] = []

    # 1. 分类：外网URL → 并发处理；本地/局域网源 → 待串行上传
    sem = asyncio.Semaphore(IMAGE_URL_PROBE_CONCURRENCY)

    async def _handle_remote(idx: int, url: str) -> None:
        async with sem:
            fresh = await ensure_fresh_image_url(url, config, project_root)
            if fresh != url:
                # 自有CDN重签名成功 → 用 fresh
                results[idx] = fresh
                return
            # fresh == url：第三方探测 ok/other 原样，或自有CDN重签名失败降级。
            # 尝试 /upload/ 本地映射兜底（自有图床文件本地有副本则转上传，避免用过期URL）
            local_rel = extract_local_path_from_url(url)
            if local_rel:
                candidate = os.path.join(project_root, local_rel)
                if os.path.exists(candidate):
                    pending_local.append((idx, candidate))
                    return
            # 本地无副本：原样透传（下游尝试，或调用方报错）
            results[idx] = url

    remote_tasks = []
    for idx, raw in enumerate(image_urls):
        if not isinstance(raw, str):
            raw = str(raw) if raw is not None else ""
        url = raw.strip()
        if not url:
            continue
        if not is_local_path(url):
            remote_tasks.append(_handle_remote(idx, url))
        else:
            pending_local.append((idx, url))

    # 2. 并发处理外网URL（自有CDN重签名 / 第三方探测 / 本地映射兜底）
    if remote_tasks:
        await asyncio.gather(*remote_tasks)

    # 3. 串行上传本地文件（含上一步转本地的兜底项）；复用单个 storage 实例
    #    延迟初始化：全外网URL场景无需 file_storage 配置
    storage = None
    for idx, source in pending_local:
        if storage is None:
            storage = get_file_storage(config)
        results[idx] = await _upload_one_to_cdn(source, storage, config, project_root)

    # 4. 按原顺序输出（跳过空字符串项，与原行为一致）
    return [r for r in results if r is not None]


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
    return _run_coro_sync(
        upload_local_images_to_cdn(image_urls, config, project_root),
        IMAGE_UPLOAD_SYNC_WRAPPER_TIMEOUT,
        [],
        "同步上传图片到图床",
    )


async def resolve_url_to_local_file(
    url: str,
    config: Dict[str, Any],
    project_root: str = None
) -> Optional[str]:
    """
    将 URL 解析为本地文件路径
    
    处理逻辑：
    1. 如果是本地文件路径 → 直接返回
    2. 如果是本地服务 URL → 使用 try_map_url_to_local_file 映射
    3. 如果是其他 URL → 下载到临时目录
    
    Args:
        url: 图片 URL 或本地路径
        config: 配置字典
        project_root: 项目根目录
    
    Returns:
        本地文件路径，失败返回 None
    """
    if not url:
        return None

    # project_root 为空时，使用当前工作目录作为兜底
    if not project_root:
        project_root = os.getcwd()

    # 如果是本地文件路径，直接返回
    if is_local_file_path(url):
        if os.path.exists(url):
            return url
        # 尝试拼接项目根目录
        if project_root:
            candidate = os.path.join(project_root, url.lstrip('/').lstrip('\\'))
            if os.path.exists(candidate):
                return candidate
        logger.warning(f"本地文件不存在: {url}")
        return None
    
    # 如果是 URL，尝试映射到本地文件（域名匹配 server.host）
    local_file = try_map_url_to_local_file(url, config, project_root)
    if local_file:
        return local_file

    # /upload/ 本地映射兜底（与域名无关，命中本服务文件直接读，绕过URL有效性）
    local_rel = extract_local_path_from_url(url)
    if local_rel:
        candidate = os.path.join(project_root, local_rel)
        if os.path.exists(candidate):
            logger.info(f"URL 通过 /upload/ 映射到本地文件: {url} -> {candidate}")
            return candidate

    # 确保URL新鲜（自有CDN重签名 / 第三方探测，过期抛 ImageExpiredError），再下载
    fresh_url = await ensure_fresh_image_url(url, config, project_root)
    logger.info(f"下载 URL 到临时目录: {fresh_url[:120]}")
    temp_file = await download_url_to_temp(fresh_url, project_root)
    return temp_file


def resolve_url_to_local_file_sync(
    url: str,
    config: Dict[str, Any],
    project_root: str = None
) -> Optional[str]:
    """
    同步方式将 URL 解析为本地文件路径
    
    Args:
        url: 图片 URL 或本地路径
        config: 配置字典
        project_root: 项目根目录
    
    Returns:
        本地文件路径，失败返回 None
    """
    return _run_coro_sync(
        resolve_url_to_local_file(url, config, project_root),
        IMAGE_UPLOAD_SYNC_WRAPPER_TIMEOUT,
        None,
        "同步解析URL到本地文件",
    )


async def compress_and_upload_image(
    image_url: str,
    config: Dict[str, Any],
    max_size_mb: float = 10.0,
    is_local: bool = False,
    project_root: str = None
) -> tuple[bool, Optional[str], Optional[str]]:
    """
    压缩图片并上传/保存到可访问位置

    处理流程：
    1. 解析 URL 到本地路径
    2. 检查图片大小
    3. 如需要，压缩图片到临时目录
    4. 保存到可访问目录并返回新 URL

    Args:
        image_url: 图片 URL 或本地路径
        config: 配置字典
        max_size_mb: 最大文件大小（MB）
        is_local: 是否为本地环境（需要上传到 CDN）
        project_root: 项目根目录

    Returns:
        (success, new_url, error_message)
    """
    temp_downloaded_file = None
    compressed_file = None

    try:
        # 1. 解析 URL 到本地路径
        local_path = await resolve_url_to_local_file(image_url, config, project_root)
        if not local_path:
            return False, None, f"无法解析图片 URL: {image_url}"

        # 记录下载的临时文件用于清理
        if not is_local_file_path(image_url) and not try_map_url_to_local_file(image_url, config, project_root):
            temp_downloaded_file = local_path

        # 2. 检查图片大小
        img_size_mb = get_image_size_mb(local_path)
        if img_size_mb is None:
            return False, None, f"无法获取图片大小: {local_path}"

        file_to_upload = local_path

        # 3. 如果超过限制，压缩图片
        if img_size_mb > max_size_mb:
            logger.info(f"图片 {image_url} 大小 {img_size_mb:.2f} MB 超过 {max_size_mb} MB 限制，开始压缩")
            
            # 生成临时压缩文件路径（复用统一的临时目录逻辑）
            current_time = datetime.now()
            temp_dir = get_temp_date_dir(current_time)
            
            timestamp = current_time.strftime("%Y%m%d_%H%M%S")
            unique_id = str(uuid.uuid4())[:8]
            ext = os.path.splitext(local_path)[1] or ".jpg"
            compressed_filename = f"compressed_{timestamp}_{unique_id}{ext}"
            compressed_path = str(temp_dir / compressed_filename)

            # 执行压缩
            success, output_path, error = compress_image_to_limit(
                local_path,
                max_size_mb=max_size_mb,
                output_path=compressed_path,
                quality_start=95,
                quality_min=60
            )
            
            if not success:
                return False, None, f"图片压缩失败: {error}"
            
            logger.info(f"图片压缩成功: {output_path}")
            compressed_file = output_path
            file_to_upload = output_path
        
        # 4. 保存到可访问位置
        if is_local:
            # 本地环境，上传到 CDN
            logger.info(f"本地环境，上传图片到 CDN: {file_to_upload}")
            uploaded_urls = await upload_local_images_to_cdn([file_to_upload], config, project_root)
            if uploaded_urls and uploaded_urls[0]:
                return True, uploaded_urls[0], None
            else:
                return False, None, "上传图片到 CDN 失败"
        else:
            # 服务器环境，返回本地 URL
            if compressed_file:
                # 如果压缩了，返回压缩后的文件 URL
                server_host = config.get("server", {}).get("host", "")
                compressed_path_obj = Path(compressed_file)
                relative_path = compressed_path_obj.relative_to(_PROJECT_ROOT)
                url = f"{server_host}/{relative_path.as_posix()}"
                return True, url, None
            else:
                # 没有压缩，返回原 URL
                return True, image_url, None
    
    except Exception as e:
        logger.error(f"压缩并上传图片失败: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return False, None, f"处理图片失败: {str(e)}"
    
    finally:
        # 清理临时下载的文件
        if temp_downloaded_file and os.path.exists(temp_downloaded_file):
            try:
                os.remove(temp_downloaded_file)
                logger.debug(f"清理临时下载文件: {temp_downloaded_file}")
            except Exception:
                pass


def compress_and_upload_image_sync(
    image_url: str,
    config: Dict[str, Any],
    max_size_mb: float = 10.0,
    is_local: bool = False,
    project_root: str = None
) -> tuple[bool, Optional[str], Optional[str]]:
    """
    同步方式压缩图片并上传/保存到可访问位置

    Args:
        image_url: 图片 URL 或本地路径
        config: 配置字典
        max_size_mb: 最大文件大小（MB）
        is_local: 是否为本地环境
        project_root: 项目根目录

    Returns:
        (success, new_url, error_message)
    """
    return _run_coro_sync(
        compress_and_upload_image(image_url, config, max_size_mb, is_local, project_root),
        IMAGE_UPLOAD_SYNC_WRAPPER_TIMEOUT,
        (False, None, "timeout"),
        "同步压缩并上传图片",
    )


def upload_media_to_cdn_sync(
    media_url: str,
    config: Dict[str, Any],
    project_root: str = None
) -> tuple[bool, Optional[str], Optional[str]]:
    """
    将媒体文件（音频/视频）上传到 CDN，返回可访问的 CDN URL

    与 compress_and_upload_image_sync 的区别：不进行图片压缩，适用于音频/视频等非图片文件。
    底层复用 upload_local_images_to_cdn 的通用上传逻辑。

    处理流程：
    1. 如果是外网 URL，直接返回
    2. 如果是本地文件或局域网 URL，上传到七牛云 CDN
    3. 返回带签名的 CDN 下载链接

    Args:
        media_url: 媒体文件 URL 或本地路径
        config: 配置字典
        project_root: 项目根目录

    Returns:
        (success, cdn_url, error_message)
    """
    if not media_url:
        return False, None, "媒体 URL 为空"

    # 外网 URL 直接返回
    if not is_local_path(media_url):
        return True, media_url, None

    try:
        uploaded_urls = upload_local_images_to_cdn_sync([media_url], config, project_root)
        if uploaded_urls and uploaded_urls[0]:
            return True, uploaded_urls[0], None
        else:
            return False, None, f"上传媒体到 CDN 失败: {media_url}"
    except Exception as e:
        logger.error(f"上传媒体到 CDN 异常: {media_url}, 错误: {str(e)}")
        return False, None, f"上传媒体到 CDN 异常: {str(e)}"
