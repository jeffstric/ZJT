
from PIL import Image
import httpx
import math
import os
import uuid
import logging
from io import BytesIO
from urllib.parse import urlparse
from typing import List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

VALID_GRID_SIZES = {4, 9, 16, 25}  # 2², 3², 4², 5²


class ImageGridMerger:
    """多图合并为n×n宫格工具类"""

    def __init__(self, upload_dir: str, server_host: str):
        self.upload_dir = upload_dir
        self.server_host = server_host

    def _resolve_local_path(self, url: str) -> Optional[str]:
        """
        判断URL是否指向本服务器的 /upload/ 目录。
        如果是，返回对应的本地磁盘路径；否则返回 None。
        """
        # 相对路径 /upload/xxx
        if url.startswith("/upload/"):
            relative = url[len("/upload/"):]
            local_path = os.path.join(self.upload_dir, *relative.split("/"))
            return local_path if os.path.exists(local_path) else None

        # 绝对URL：直接检查是否以 SERVER_HOST/upload/ 开头
        host = self.server_host.rstrip("/")
        prefix = f"{host}/upload/"
        logger.info(f"[_resolve_local_path] SERVER_HOST='{self.server_host}', prefix='{prefix}', url='{url}', match={url.startswith(prefix)}")
        if url.startswith(prefix):
            relative = url[len(prefix):]
            # 去掉查询参数
            if "?" in relative:
                relative = relative.split("?")[0]
            local_path = os.path.join(self.upload_dir, *relative.split("/"))
            if os.path.exists(local_path):
                return local_path
            logger.warning(f"本地文件不存在: {local_path} (URL: {url})")
            return None

        return None

    async def _load_image(self, url: str, index: int, client: httpx.AsyncClient) -> Image.Image:
        """加载单张图片：优先本地磁盘，否则HTTP下载"""
        local_path = self._resolve_local_path(url)
        if local_path:
            logger.info(f"第{index+1}张图片从本地加载: {local_path}")
            return Image.open(local_path).convert("RGB")

        logger.info(f"第{index+1}张图片从远程下载: {url}")
        resp = await client.get(url)
        resp.raise_for_status()
        return Image.open(BytesIO(resp.content)).convert("RGB")

    async def merge_images(
        self,
        image_urls: List[str],
        grid_size: int,
        black_indices: Optional[List[int]] = None,
    ) -> dict:
        """
        将多张图片合并为 n×n 宫格图片。

        Args:
            image_urls: 图片URL列表，长度必须等于 grid_size
            grid_size: 宫格总数，必须是 4/9/16/25
            black_indices: 需要保持全黑的位置索引列表（从0开始）

        Returns:
            dict: {"image_url": str, "grid_size": int, "cell_count": int, "black_cells": list}

        Raises:
            ValueError: 参数不合法
        """
        if grid_size not in VALID_GRID_SIZES:
            raise ValueError(f"grid_size 必须是 {sorted(VALID_GRID_SIZES)} 中的一个，当前: {grid_size}")

        if len(image_urls) != grid_size:
            raise ValueError(f"image_urls 数量({len(image_urls)})必须等于 grid_size({grid_size})")

        if black_indices is None:
            black_indices = []

        n = int(math.isqrt(grid_size))  # 2, 3, 4, 5

        # 下载所有非黑色位置的图片
        downloaded: dict[int, Image.Image] = {}
        first_size = None
        first_ratio = None

        async with httpx.AsyncClient(timeout=60.0) as client:
            for i, url in enumerate(image_urls):
                if i in black_indices or not url:
                    continue
                try:
                    img = await self._load_image(url, i, client)
                    downloaded[i] = img

                    ratio = img.width / img.height
                    if first_size is None:
                        first_size = img.size
                        first_ratio = ratio
                    else:
                        # 宽高比容差 ±2%
                        if abs(ratio - first_ratio) / first_ratio > 0.02:
                            raise ValueError(
                                f"第{i+1}张图片宽高比 {ratio:.4f} ({img.size}) 与第一张 {first_ratio:.4f} ({first_size}) 不一致"
                            )
                        # 尺寸不同时缩放到第一张的尺寸
                        if img.size != first_size:
                            logger.info(f"第{i+1}张图片从 {img.size} 缩放到 {first_size}")
                            img = img.resize(first_size, Image.LANCZOS)
                            downloaded[i] = img
                except httpx.HTTPStatusError as e:
                    logger.error(f"下载第{i+1}张图片失败: {e}")
                    raise ValueError(f"下载第{i+1}张图片失败: HTTP {e.response.status_code}")
                except ValueError:
                    raise
                except Exception as e:
                    logger.error(f"处理第{i+1}张图片失败: {e}")
                    raise ValueError(f"处理第{i+1}张图片失败: {str(e)}")

        if not downloaded:
            raise ValueError("没有可用的图片进行合并")

        cell_w, cell_h = first_size
        canvas_w = cell_w * n
        canvas_h = cell_h * n

        # 创建黑色画布
        canvas = Image.new("RGB", (canvas_w, canvas_h), (0, 0, 0))

        # 从左到右、从上到下粘贴图片
        for i, img in downloaded.items():
            row = i // n
            col = i % n
            x = col * cell_w
            y = row * cell_h
            canvas.paste(img, (x, y))

        # 保存合并图片
        merged_dir = os.path.join(self.upload_dir, "merged", datetime.now().strftime("%Y%m"))
        os.makedirs(merged_dir, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        unique_id = uuid.uuid4().hex[:8]
        filename = f"merged_{timestamp}_{unique_id}.png"
        file_path = os.path.join(merged_dir, filename)

        canvas.save(file_path, format="PNG")
        logger.info(f"宫格图片已保存: {file_path} ({canvas_w}x{canvas_h})")

        # 清理下载的图片
        for img in downloaded.values():
            img.close()
        canvas.close()

        relative_path = os.path.relpath(file_path, self.upload_dir)
        image_url = f"{self.server_host.rstrip('/')}/upload/{relative_path}"

        return {
            "image_url": image_url,
            "grid_size": grid_size,
            "cell_count": grid_size,
            "black_cells": black_indices,
        }
