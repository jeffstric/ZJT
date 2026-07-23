import math
import os
from dataclasses import dataclass
from typing import List, Sequence, Tuple

import numpy as np
from PIL import Image

from config.constant import GridConfig


@dataclass(frozen=True)
class GridSeparatorDetection:
    axis: str
    expected_ratio: float
    expected_position: int
    detected_position: int
    coverage: float


@dataclass(frozen=True)
class GridValidationResult:
    is_valid: bool
    grid_size: int
    rows: int
    cols: int
    confidence: float
    reason: str
    vertical_separators: Tuple[GridSeparatorDetection, ...] = ()
    horizontal_separators: Tuple[GridSeparatorDetection, ...] = ()


def validate_grid_image(image_path: str, grid_size: int) -> GridValidationResult:
    """Validate whether an image is a uniform 2x2 or 3x3 grid."""
    rows, cols = _grid_shape(grid_size)

    if not image_path or not os.path.exists(image_path):
        return _invalid(grid_size, rows, cols, f"image file not found: {image_path}")

    try:
        with Image.open(image_path) as img:
            rgb = img.convert("RGB")
            rgb.thumbnail(
                (GridConfig.VALIDATION_MAX_SCAN_SIZE, GridConfig.VALIDATION_MAX_SCAN_SIZE),
                Image.Resampling.LANCZOS,
            )
            arr = np.asarray(rgb, dtype=np.float32)
    except Exception as exc:
        return _invalid(grid_size, rows, cols, f"cannot open image: {exc}")

    height, width = arr.shape[:2]
    if width < cols * 20 or height < rows * 20:
        return _invalid(grid_size, rows, cols, "image is too small for grid validation")

    vertical = tuple(_detect_expected_separators(arr, "x", cols))
    horizontal = tuple(_detect_expected_separators(arr, "y", rows))

    min_coverage = GridConfig.VALIDATION_MIN_LINE_COVERAGE
    for det in (*vertical, *horizontal):
        if det.coverage < min_coverage:
            return GridValidationResult(
                is_valid=False,
                grid_size=grid_size,
                rows=rows,
                cols=cols,
                confidence=_confidence(vertical, horizontal, 0.0),
                reason=(
                    f"separator {det.axis}@{det.expected_position} coverage "
                    f"{det.coverage:.2f} below {min_coverage:.2f}"
                ),
                vertical_separators=vertical,
                horizontal_separators=horizontal,
            )

    uniformity = _cell_uniformity(width, height, vertical, horizontal)
    if uniformity < GridConfig.VALIDATION_MIN_CELL_UNIFORMITY:
        return GridValidationResult(
            is_valid=False,
            grid_size=grid_size,
            rows=rows,
            cols=cols,
            confidence=_confidence(vertical, horizontal, uniformity),
            reason=(
                f"cell size uniformity {uniformity:.2f} below "
                f"{GridConfig.VALIDATION_MIN_CELL_UNIFORMITY:.2f}"
            ),
            vertical_separators=vertical,
            horizontal_separators=horizontal,
        )

    confidence = _confidence(vertical, horizontal, uniformity)
    return GridValidationResult(
        is_valid=True,
        grid_size=grid_size,
        rows=rows,
        cols=cols,
        confidence=confidence,
        reason="ok",
        vertical_separators=vertical,
        horizontal_separators=horizontal,
    )


def _grid_shape(grid_size: int) -> Tuple[int, int]:
    if grid_size not in GridConfig.VALID_SIZES:
        raise ValueError(f"unsupported grid_size={grid_size}, allowed={GridConfig.VALID_SIZES}")
    cols = int(math.sqrt(grid_size))
    if cols * cols != grid_size:
        raise ValueError(f"grid_size={grid_size} must be a square grid")
    return cols, cols


def _invalid(grid_size: int, rows: int, cols: int, reason: str) -> GridValidationResult:
    return GridValidationResult(
        is_valid=False,
        grid_size=grid_size,
        rows=rows,
        cols=cols,
        confidence=0.0,
        reason=reason,
    )


def _detect_expected_separators(
    arr: np.ndarray,
    axis: str,
    cells: int,
) -> List[GridSeparatorDetection]:
    if cells <= 1:
        return []

    length = arr.shape[1] if axis == "x" else arr.shape[0]
    tolerance = max(4, int(length * GridConfig.VALIDATION_POSITION_TOLERANCE_RATIO))
    detections: List[GridSeparatorDetection] = []

    for step in range(1, cells):
        expected_ratio = step / cells
        expected = int(round(length * expected_ratio))
        start = max(1, expected - tolerance)
        end = min(length - 2, expected + tolerance)

        best_pos = expected
        best_coverage = -1.0
        for pos in range(start, end + 1):
            coverage = _separator_coverage(arr, axis, pos)
            if coverage > best_coverage or (
                math.isclose(coverage, best_coverage) and abs(pos - expected) < abs(best_pos - expected)
            ):
                best_pos = pos
                best_coverage = coverage

        detections.append(
            GridSeparatorDetection(
                axis=axis,
                expected_ratio=expected_ratio,
                expected_position=expected,
                detected_position=best_pos,
                coverage=max(0.0, min(1.0, best_coverage)),
            )
        )

    return detections


def _separator_coverage(arr: np.ndarray, axis: str, pos: int) -> float:
    half = GridConfig.VALIDATION_SEPARATOR_HALF_WIDTH
    side_width = GridConfig.VALIDATION_SEPARATOR_SIDE_WIDTH
    size = arr.shape[1] if axis == "x" else arr.shape[0]
    if pos - half - side_width < 0 or pos + half + side_width >= size:
        return 0.0

    if axis == "x":
        strip = arr[:, pos - half:pos + half + 1, :].mean(axis=1)
        left = arr[:, pos - half - side_width:pos - half, :].mean(axis=1)
        right = arr[:, pos + half + 1:pos + half + 1 + side_width, :].mean(axis=1)
    else:
        strip = arr[pos - half:pos + half + 1, :, :].mean(axis=0)
        left = arr[pos - half - side_width:pos - half, :, :].mean(axis=0)
        right = arr[pos + half + 1:pos + half + 1 + side_width, :, :].mean(axis=0)

    strip_gray = strip.mean(axis=1)
    left_gray = left.mean(axis=1)
    right_gray = right.mean(axis=1)
    strip_chroma = strip.max(axis=1) - strip.min(axis=1)

    bright_separator = (strip_gray >= 205) & (strip_chroma <= 70)
    dark_separator = (strip_gray <= 40) & (strip_chroma <= 70)
    bright_ridge = ((strip_gray - left_gray) >= 35) & ((strip_gray - right_gray) >= 35)
    dark_ridge = ((left_gray - strip_gray) >= 35) & ((right_gray - strip_gray) >= 35)

    mask = bright_separator | dark_separator | bright_ridge | dark_ridge
    mask = _close_small_gaps(mask, max_gap=max(2, len(mask) // 100))
    return float(mask.mean())


def _close_small_gaps(mask: np.ndarray, max_gap: int) -> np.ndarray:
    if max_gap <= 0 or mask.size == 0:
        return mask

    closed = mask.copy()
    false_indices = np.flatnonzero(~closed)
    if false_indices.size == 0:
        return closed

    start = None
    previous = None
    for idx in false_indices:
        if start is None:
            start = idx
        elif previous is not None and idx != previous + 1:
            _fill_gap_if_bounded(closed, start, previous, max_gap)
            start = idx
        previous = idx
    if start is not None and previous is not None:
        _fill_gap_if_bounded(closed, start, previous, max_gap)
    return closed


def _fill_gap_if_bounded(mask: np.ndarray, start: int, end: int, max_gap: int) -> None:
    if end - start + 1 > max_gap:
        return
    if start == 0 or end == mask.size - 1:
        return
    if mask[start - 1] and mask[end + 1]:
        mask[start:end + 1] = True


def _cell_uniformity(
    width: int,
    height: int,
    vertical: Sequence[GridSeparatorDetection],
    horizontal: Sequence[GridSeparatorDetection],
) -> float:
    x_positions = [0, *[det.detected_position for det in vertical], width]
    y_positions = [0, *[det.detected_position for det in horizontal], height]
    x_uniformity = _segment_uniformity(x_positions)
    y_uniformity = _segment_uniformity(y_positions)
    return min(x_uniformity, y_uniformity)


def _segment_uniformity(positions: Sequence[int]) -> float:
    lengths = [max(1, positions[i + 1] - positions[i]) for i in range(len(positions) - 1)]
    return min(lengths) / max(lengths)


def _confidence(
    vertical: Sequence[GridSeparatorDetection],
    horizontal: Sequence[GridSeparatorDetection],
    uniformity: float,
) -> float:
    detections = [*vertical, *horizontal]
    if not detections:
        return 0.0
    coverage = sum(det.coverage for det in detections) / len(detections)
    return max(0.0, min(1.0, coverage * 0.85 + uniformity * 0.15))
