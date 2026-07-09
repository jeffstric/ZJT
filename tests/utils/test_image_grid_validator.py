import os
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, project_root)

from config.constant import GridConfig
from script_writer_core.image_grid_splitter import ImageGridSplitter
from utils.image_grid_validator import validate_grid_image


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


if __name__ == "__main__":
    unittest.main()
