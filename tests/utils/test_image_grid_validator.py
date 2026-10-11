import os
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

import numpy as np

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, project_root)

from config.constant import GridConfig
from script_writer_core.image_grid_splitter import ImageGridSplitter
from utils.image_grid_validator import (
    _build_placeholder_mask,
    _cell_is_placeholder,
    validate_grid_image,
)


class TestImageGridValidator(unittest.TestCase):
    def _save_image(self, image: Image.Image, tmpdir: str, name: str) -> str:
        path = Path(tmpdir) / name
        image.save(path)
        return str(path)

    def _draw_grid(self, size: int, cells: int, line_width: int = 6) -> Image.Image:
        image = Image.new("RGB", (size, size), "white")
        draw = ImageDraw.Draw(image)
        palette = [
            "#bb3e03", "#0a9396", "#ae2012",
            "#005f73", "#9b2226", "#ee9b00",
            "#3a86ff", "#8338ec", "#ff006e",
        ]
        cell_size = size // cells
        for row in range(cells):
            for col in range(cells):
                idx = row * cells + col
                left = col * cell_size
                top = row * cell_size
                right = size if col == cells - 1 else (col + 1) * cell_size
                bottom = size if row == cells - 1 else (row + 1) * cell_size
                draw.rectangle((left, top, right, bottom), fill=palette[idx])

        for step in range(1, cells):
            pos = step * cell_size
            half = line_width // 2
            draw.rectangle((pos - half, 0, pos + half, size), fill="white")
            draw.rectangle((0, pos - half, size, pos + half), fill="white")
        return image

    def _draw_thin_line_grid(self, size: int, cells: int, line_width: int = 2) -> Image.Image:
        """模拟 AI 生成宫格：中灰调 cell + 2px 灰白色细分隔线（非纯白粗线）"""
        image = Image.new("RGB", (size, size), "white")
        draw = ImageDraw.Draw(image)
        palette = [
            "#8a7f70", "#6e665c", "#9a8f80",
            "#5d564d", "#877d6e", "#74695c",
            "#968b7a", "#665e52", "#7f7668",
        ]
        cell_size = size // cells
        for row in range(cells):
            for col in range(cells):
                idx = row * cells + col
                left = col * cell_size
                top = row * cell_size
                right = size if col == cells - 1 else (col + 1) * cell_size
                bottom = size if row == cells - 1 else (row + 1) * cell_size
                draw.rectangle((left, top, right, bottom), fill=palette[idx])

        for step in range(1, cells):
            pos = step * cell_size
            half = line_width // 2
            draw.rectangle((pos - half, 0, pos - half + line_width - 1, size), fill="#d8d8d8")
            draw.rectangle((0, pos - half, size, pos - half + line_width - 1), fill="#d8d8d8")
        return image

    def _draw_bottom_span_fake_2x2(self) -> Image.Image:
        image = Image.new("RGB", (420, 630), "#111111")
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, 210, 210), fill="#bb3e03")
        draw.rectangle((210, 0, 420, 210), fill="#0a9396")
        draw.rectangle((0, 210, 210, 420), fill="#ae2012")
        draw.rectangle((210, 210, 420, 420), fill="#005f73")
        draw.rectangle((0, 420, 420, 630), fill="#3a86ff")
        draw.rectangle((207, 0, 213, 420), fill="white")
        draw.rectangle((0, 207, 420, 213), fill="white")
        draw.rectangle((0, 417, 420, 423), fill="white")
        return image

    def test_accepts_uniform_2x2_grid(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._save_image(self._draw_grid(420, 2), tmpdir, "grid_2x2.png")

            result = validate_grid_image(path, GridConfig.SIZE_2X2)

            self.assertTrue(result.is_valid, result.reason)
            self.assertEqual(result.rows, 2)
            self.assertEqual(result.cols, 2)

    def test_accepts_uniform_3x3_grid(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._save_image(self._draw_grid(450, 3), tmpdir, "grid_3x3.png")

            result = validate_grid_image(path, GridConfig.SIZE_3X3)

            self.assertTrue(result.is_valid, result.reason)
            self.assertEqual(result.rows, 3)
            self.assertEqual(result.cols, 3)

    def test_accepts_3x3_grid_with_thin_faint_lines(self):
        # 回归：AI 宫格常为 1-2px 灰白细线，缩略图均值稀释后旧实现会误判无效
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._save_image(
                self._draw_thin_line_grid(2048, 3), tmpdir, "grid_3x3_thin.png"
            )

            result = validate_grid_image(path, GridConfig.SIZE_3X3)

            self.assertTrue(result.is_valid, result.reason)

    def test_rejects_fake_2x2_when_bottom_cell_spans_two_columns(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._save_image(self._draw_bottom_span_fake_2x2(), tmpdir, "fake_2x2.png")

            result = validate_grid_image(path, GridConfig.SIZE_2X2)

            self.assertFalse(result.is_valid)
            self.assertIn("separator", result.reason.lower())

    def test_splitter_rejects_fake_2x2_before_writing_cells(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._save_image(self._draw_bottom_span_fake_2x2(), tmpdir, "fake_2x2.png")
            output_dir = Path(tmpdir) / "out"

            with self.assertRaisesRegex(ValueError, "Invalid grid image"):
                ImageGridSplitter().split_grid(
                    grid_image_path=path,
                    output_dir=str(output_dir),
                    grid_size=GridConfig.SIZE_2X2,
                    output_names=["a", "b", "c", "d"],
                )

            self.assertFalse(output_dir.exists())

    # ---------- 占位格友好旁路（模式 B 双轨 OR）----------
    # 批量生图常凑不满 grid_size 个真实场景，缺位用纯黑占位格补齐。占位区没有分割线
    # 特征（prompt 即要求纯黑占位），原严格校验会误判为不合格。旁路对占位区缺失的分割线
    # 免于惩罚，改用理论位置兜底。

    def _draw_grid_with_placeholders(
        self, cells: int, content_cells: set, size: int = 900, line_width: int = 6,
    ) -> Image.Image:
        """绘制含纯黑占位格的宫格：content_cells 里的格子填彩色内容，其余纯黑占位。

        content_cells: (row, col) 元组集合，标明哪些格子是真实内容。
        """
        image = Image.new("RGB", (size, size), "black")
        draw = ImageDraw.Draw(image)
        palette = [
            "#bb3e03", "#0a9396", "#ae2012",
            "#005f73", "#9b2226", "#ee9b00",
            "#3a86ff", "#8338ec", "#ff006e",
        ]
        cell_size = size // cells
        palette_idx = 0
        for row in range(cells):
            for col in range(cells):
                if (row, col) not in content_cells:
                    continue  # 纯黑占位，保持黑色
                left = col * cell_size
                top = row * cell_size
                right = size if col == cells - 1 else (col + 1) * cell_size
                bottom = size if row == cells - 1 else (row + 1) * cell_size
                draw.rectangle((left, top, right, bottom), fill=palette[palette_idx % len(palette)])
                palette_idx += 1
        # 白色分割线贯穿（含占位区，模拟 AI 实际输出）
        for step in range(1, cells):
            pos = step * cell_size
            half = line_width // 2
            draw.rectangle((pos - half, 0, pos + half, size), fill="white")
            draw.rectangle((0, pos - half, size, pos + half), fill="white")
        return image

    def test_accepts_3x3_with_mostly_placeholders(self):
        # 回归：1 真实内容 + 8 黑色占位（如子场景参考图只生成 1 个子场景）
        # 修复前 cell uniformity 0.82 < 0.90 误判失败；修复后旁路兜底通过
        with tempfile.TemporaryDirectory() as tmpdir:
            img = self._draw_grid_with_placeholders(3, {(0, 0)})
            path = self._save_image(img, tmpdir, "grid_3x3_placeholder.png")

            result = validate_grid_image(path, GridConfig.SIZE_3X3)

            self.assertTrue(result.is_valid, result.reason)

    def test_accepts_2x2_with_placeholders(self):
        # 1 真实内容 + 3 黑色占位（分镜首帧宫格只 1 个分镜时）
        with tempfile.TemporaryDirectory() as tmpdir:
            img = self._draw_grid_with_placeholders(2, {(0, 0)})
            path = self._save_image(img, tmpdir, "grid_2x2_placeholder.png")

            result = validate_grid_image(path, GridConfig.SIZE_2X2)

            self.assertTrue(result.is_valid, result.reason)

    def test_accepts_3x3_partial_placeholders(self):
        # 3 真实内容（第一行）+ 6 占位
        with tempfile.TemporaryDirectory() as tmpdir:
            img = self._draw_grid_with_placeholders(3, {(0, 0), (0, 1), (0, 2)})
            path = self._save_image(img, tmpdir, "grid_3x3_partial.png")

            result = validate_grid_image(path, GridConfig.SIZE_3X3)

            self.assertTrue(result.is_valid, result.reason)

    # ---------- 占位格判定加固（中位数 + 极暗/极亮像素占比 双条件）----------
    # 回归：夜景插画等暗色场景的近黑象限 median ≤ 15，曾被单中位数条件误判为纯黑
    # 占位格，进而放行占位格旁路，把一整张连续单图当宫格拆碎（线上事故 2026-10-11
    # #16195：夜景单图过旁路通过并被切 4 块废图）。

    def _draw_dark_scene_like_image(self, size: int = 1024) -> Image.Image:
        """模拟暗色调连续单图：全图近黑底 + 每个象限一片月光亮带（占比约 30%）。

        每个 cell median ≈ 10（≤15，旧中位数条件会判成占位格），但极暗像素占比
        仅约 0.7（<0.90，新占比条件判非占位格）。
        """
        image = Image.new("RGB", (size, size), (10, 10, 10))
        draw = ImageDraw.Draw(image)
        half = size // 2
        for row in range(2):
            for col in range(2):
                x0, y0 = col * half, row * half
                # 月光/灯光亮带：从 cell 左上斜穿的宽条，灰度 80（>DARK_MAX=15）
                draw.polygon(
                    [(x0, y0), (x0 + half, y0 + half // 3), (x0 + half, y0 + half // 2), (x0, y0 + half // 3 + half // 8)],
                    fill=(80, 80, 80),
                )
        # 模糊亮带边缘：真实夜景的明暗过渡是渐变而非直线硬边，避免亮带边缘被
        # ridge 检测误认成宫格分割线
        return image.filter(ImageFilter.GaussianBlur(6))

    def test_dark_scene_cells_are_not_placeholder(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._save_image(self._draw_dark_scene_like_image(), tmpdir, "dark_scene.png")
            with Image.open(path) as img:
                rgb = img.convert("RGB")
                rgb.thumbnail((GridConfig.VALIDATION_MAX_SCAN_SIZE, GridConfig.VALIDATION_MAX_SCAN_SIZE), Image.Resampling.LANCZOS)
                arr = np.asarray(rgb, dtype=np.float32)

            mask = _build_placeholder_mask(arr, 2, 2)

            # 全图无占位格 → 占位格旁路不得触发，暗色单图仍走严格校验拦截
            self.assertFalse(any(any(cell for cell in row) for row in mask))

    def test_pure_black_cell_with_separator_lines_is_still_placeholder(self):
        # 纯黑占位格穿白色分割线：极暗像素占比仍 >0.9，不受新占比条件影响
        image = Image.new("RGB", (300, 300), "black")
        draw = ImageDraw.Draw(image)
        draw.rectangle((147, 0, 153, 300), fill="white")
        draw.rectangle((0, 147, 300, 153), fill="white")
        arr = np.asarray(image.convert("RGB"), dtype=np.float32)

        self.assertTrue(_cell_is_placeholder(arr))

    def test_pure_white_cell_with_separator_lines_is_still_placeholder(self):
        image = Image.new("RGB", (300, 300), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((147, 0, 153, 300), fill=(200, 180, 160))
        arr = np.asarray(image.convert("RGB"), dtype=np.float32)

        self.assertTrue(_cell_is_placeholder(arr))

    def test_mid_tone_scene_cell_is_not_placeholder(self):
        image = Image.new("RGB", (300, 300), (90, 95, 100))
        arr = np.asarray(image.convert("RGB"), dtype=np.float32)

        self.assertFalse(_cell_is_placeholder(arr))


if __name__ == "__main__":
    unittest.main()
