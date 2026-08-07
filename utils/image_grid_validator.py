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


def _validation_min_coverage(grid_size: int) -> float:
    """按 grid_size 取分割线 coverage 阈值，缺失回退标量默认值。"""
    by_size = getattr(GridConfig, "VALIDATION_MIN_LINE_COVERAGE_BY_SIZE", None)
    if isinstance(by_size, dict) and grid_size in by_size:
        return float(by_size[grid_size])
    return float(GridConfig.VALIDATION_MIN_LINE_COVERAGE)


def _validation_min_uniformity(grid_size: int) -> float:
    """按 grid_size 取 cell uniformity 阈值，缺失回退标量默认值。"""
    by_size = getattr(GridConfig, "VALIDATION_MIN_CELL_UNIFORMITY_BY_SIZE", None)
    if isinstance(by_size, dict) and grid_size in by_size:
        return float(by_size[grid_size])
    return float(GridConfig.VALIDATION_MIN_CELL_UNIFORMITY)


def validate_grid_image(image_path: str, grid_size: int) -> GridValidationResult:
    """Validate whether an image is a uniform 2x2 or 3x3 grid.

    双轨（模式 B）：先跑原有严格校验（全内容宫格图零回归）；仅当严格校验失败、且图像
    含占位格（纯黑/纯白纯色 cell，批量生图凑不满宫格时常见）时，再尝试占位格友好旁路：
    对占位格区域不惩罚其缺失的分割线，用理论位置兜底。两条路径任一通过即判有效。
    """
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

    # ---- 轨道一：原有严格校验（逻辑不变，仅阈值改为按 grid_size 取）----
    strict_result = _strict_validate(arr, grid_size, rows, cols, width, height)
    if strict_result.is_valid:
        return strict_result

    # ---- 轨道二：占位格友好旁路（仅当含占位格时触发）----
    bypass_result = _validate_with_placeholder_tolerance(
        arr, grid_size, rows, cols, width, height,
    )
    if bypass_result.is_valid:
        return bypass_result

    # 两条轨道均失败 → 维持严格校验的失败结论（保留更具体的失败原因）
    return strict_result


def _strict_validate(
    arr: np.ndarray,
    grid_size: int,
    rows: int,
    cols: int,
    width: int,
    height: int,
) -> GridValidationResult:
    """原有严格校验逻辑（阈值按 grid_size 取）。行为与改造前等价。"""
    vertical = tuple(_detect_expected_separators(arr, "x", cols))
    horizontal = tuple(_detect_expected_separators(arr, "y", rows))

    min_coverage = _validation_min_coverage(grid_size)
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
    min_uniformity = _validation_min_uniformity(grid_size)
    if uniformity < min_uniformity:
        return GridValidationResult(
            is_valid=False,
            grid_size=grid_size,
            rows=rows,
            cols=cols,
            confidence=_confidence(vertical, horizontal, uniformity),
            reason=(
                f"cell size uniformity {uniformity:.2f} below "
                f"{min_uniformity:.2f}"
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


# ==================== 占位格友好旁路（轨道二）====================
# 背景：批量生图常凑不满 grid_size 个真实场景，缺位用纯黑/纯白占位格补齐。占位格区域
# 没有分割线特征（prompt 即要求"纯黑背景占位"），原有严格校验会把"占位区无线"误判为
# "宫格不合规"。本旁路只在严格校验失败、且图像确实含占位格时触发，对占位格区域不惩罚
# 其缺失的分割线，改用理论位置兜底，避免合法的含占位宫格图被误杀。


def _cell_is_placeholder(cell_arr: np.ndarray) -> bool:
    """判断一个 cell 区域是否为纯色占位格（纯黑/纯白）。

    用灰度中位数判定，而非标准差：占位格内常穿有白色分割线，导致 std 偏高（实测可达
    40+），但中位数不受占比小的分割线像素影响（纯黑占位格 median≈0）。真实场景内容
    即便偏暗也因有明暗对比，median 普遍 >20。
    """
    if cell_arr.size == 0:
        return False
    gray = cell_arr.mean(axis=2) if cell_arr.ndim == 3 else cell_arr
    median = float(np.median(gray))
    if median <= GridConfig.VALIDATION_PLACEHOLDER_DARK_MAX:
        return True
    if median >= GridConfig.VALIDATION_PLACEHOLDER_BRIGHT_MIN:
        return True
    return False


def _build_placeholder_mask(
    arr: np.ndarray, rows: int, cols: int,
) -> List[List[bool]]:
    """按理论位置把图切成 rows×cols 个 cell，返回每个 cell 是否为占位格的布尔矩阵。"""
    height, width = arr.shape[:2]
    mask: List[List[bool]] = []
    for r in range(rows):
        y0 = int(round(height * r / rows))
        y1 = int(round(height * (r + 1) / rows))
        row_mask: List[bool] = []
        for c in range(cols):
            x0 = int(round(width * c / cols))
            x1 = int(round(width * (c + 1) / cols))
            cell = arr[y0:y1, x0:x1, :]
            row_mask.append(_cell_is_placeholder(cell))
        mask.append(row_mask)
    return mask


def _detect_separator_with_placeholders(
    arr: np.ndarray,
    axis: str,
    cells: int,
    placeholder_mask: List[List[bool]],
) -> List[GridSeparatorDetection]:
    """占位格感知的分割线检测。

    竖线(axis=x)是第 c 列与 c+1 列的分界，两侧的 cell 是 (所有行, c) 与 (所有行, c+1)；
    横线(axis=y)是第 r 行与 r+1 行的分界，两侧的 cell 是 (r, 所有列) 与 (r+1, 所有列)。
    把线按另一方向的 cell 边界切成若干段：段两侧 cell 都是占位 → 用理论位置、coverage 标
    记为通过(1.0)；否则在段内正常检测并统计 coverage。最终位置取有内容段的检测值（占位
    段贡献理论值），coverage 取有内容段的覆盖度均值。
    """
    if cells <= 1:
        return []

    length = arr.shape[1] if axis == "x" else arr.shape[0]
    tolerance = max(4, int(length * GridConfig.VALIDATION_POSITION_TOLERANCE_RATIO))
    detections: List[GridSeparatorDetection] = []

    for step in range(1, cells):
        expected_ratio = step / cells
        expected = int(round(length * expected_ratio))

        # 确定本条分割线的"另一轴"分段：竖线按行切，横线按列切
        if axis == "x":
            # 竖线 step 分隔第(step-1)列与 step 列
            left_col, right_col = step - 1, step
        else:
            # 横线 step 分隔第(step-1)行与 step 行
            left_col, right_col = step - 1, step
        other_cells = cells  # 正方形宫格，另一轴 cell 数 == cells

        detected_positions: List[int] = []
        segment_coverages: List[float] = []
        all_segments_placeholder = True

        for seg in range(other_cells):
            if axis == "x":
                cell_left = placeholder_mask[seg][left_col]
                cell_right = placeholder_mask[seg][right_col]
            else:
                cell_left = placeholder_mask[left_col][seg]
                cell_right = placeholder_mask[right_col][seg]

            # 段在"另一轴"的坐标范围
            seg_start = int(round(length * seg / other_cells))
            seg_end = int(round(length * (seg + 1) / other_cells))

            if cell_left and cell_right:
                # 两侧都是占位格：分割线本就不可检测，用理论位置、不惩罚
                detected_positions.append(expected)
                # 不计入 coverage 统计（占位段不算分母，避免拉低均值）
                continue

            all_segments_placeholder = False
            # 有内容的段：在 [seg_start, seg_end] 与理论容差窗口的交集内搜索最佳位置。
            # 段端点各留 1px 余量，避免 _separator_coverage 因越界返回 0（其内部会访问
            # pos±half±side_width 邻域）。
            search_start = max(seg_start + 1, expected - tolerance)
            search_end = min(seg_end - 2, expected + tolerance)
            if search_start > search_end:
                # 段太窄无法搜索，退回理论位置，coverage 取该段实际检测值
                detected_positions.append(expected)
                seg_coverage = _separator_coverage(arr, axis, expected)
                segment_coverages.append(seg_coverage)
                continue

            best_pos = expected
            best_coverage = -1.0
            for pos in range(search_start, search_end + 1):
                coverage = _separator_coverage(arr, axis, pos)
                if coverage > best_coverage or (
                    math.isclose(coverage, best_coverage)
                    and abs(pos - expected) < abs(best_pos - expected)
                ):
                    best_pos = pos
                    best_coverage = coverage
            detected_positions.append(best_pos)
            segment_coverages.append(max(0.0, min(1.0, best_coverage)))

        # 整条线所有段都是占位（两侧全占位）：无法提供任何信号，用理论位置视为通过
        if all_segments_placeholder:
            detections.append(
                GridSeparatorDetection(
                    axis=axis,
                    expected_ratio=expected_ratio,
                    expected_position=expected,
                    detected_position=expected,
                    coverage=1.0,  # 占位区无线属正常，不惩罚
                )
            )
            continue

        # detected_position 取有内容段中检测位置最接近理论的值（占位段已贡献理论值）
        detected = (
            min(detected_positions, key=lambda p: abs(p - expected))
            if detected_positions else expected
        )
        coverage = (
            sum(segment_coverages) / len(segment_coverages)
            if segment_coverages else 1.0
        )
        detections.append(
            GridSeparatorDetection(
                axis=axis,
                expected_ratio=expected_ratio,
                expected_position=expected,
                detected_position=detected,
                coverage=max(0.0, min(1.0, coverage)),
            )
        )

    return detections


def _validate_with_placeholder_tolerance(
    arr: np.ndarray,
    grid_size: int,
    rows: int,
    cols: int,
    width: int,
    height: int,
) -> GridValidationResult:
    """占位格友好旁路：只在图像含占位格时对占位区缺失的分割线免于惩罚。

    返回 is_valid=True 表示旁路通过（应接受该图）；is_valid=False 表示旁路也无法通过
    （维持严格校验的失败结论）。
    """
    placeholder_mask = _build_placeholder_mask(arr, rows, cols)
    # 必须至少有 1 个占位格才进旁路（否则这张图本就该走严格校验，旁路无意义）
    has_placeholder = any(any(cell for cell in row) for row in placeholder_mask)
    if not has_placeholder:
        return _invalid(grid_size, rows, cols, "no placeholder cell detected")
    # 同时必须至少有 1 个非占位格（全占位=整图纯色，确属无效图）
    total = rows * cols
    placeholder_count = sum(1 for row in placeholder_mask for cell in row if cell)
    if placeholder_count >= total:
        return _invalid(grid_size, rows, cols, "image is entirely placeholder (no content)")

    vertical = tuple(_detect_separator_with_placeholders(arr, "x", cols, placeholder_mask))
    horizontal = tuple(_detect_separator_with_placeholders(arr, "y", rows, placeholder_mask))

    min_coverage = _validation_min_coverage(grid_size)
    for det in (*vertical, *horizontal):
        if det.coverage < min_coverage:
            return GridValidationResult(
                is_valid=False,
                grid_size=grid_size,
                rows=rows,
                cols=cols,
                confidence=_confidence(vertical, horizontal, 0.0),
                reason=(
                    f"placeholder-tolerant: separator {det.axis}@{det.expected_position} "
                    f"coverage {det.coverage:.2f} below {min_coverage:.2f}"
                ),
                vertical_separators=vertical,
                horizontal_separators=horizontal,
            )

    uniformity = _cell_uniformity(width, height, vertical, horizontal)
    min_uniformity = _validation_min_uniformity(grid_size)
    if uniformity < min_uniformity:
        return GridValidationResult(
            is_valid=False,
            grid_size=grid_size,
            rows=rows,
            cols=cols,
            confidence=_confidence(vertical, horizontal, uniformity),
            reason=(
                f"placeholder-tolerant: cell size uniformity {uniformity:.2f} below "
                f"{min_uniformity:.2f}"
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
        reason="passed via placeholder-tolerant path",
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
        strip = arr[:, pos - half:pos + half + 1, :]
        left = arr[:, pos - half - side_width:pos - half, :].mean(axis=1)
        right = arr[:, pos + half + 1:pos + half + 1 + side_width, :].mean(axis=1)
    else:
        strip = arr[pos - half:pos + half + 1, :, :].transpose(1, 0, 2)
        left = arr[pos - half - side_width:pos - half, :, :].mean(axis=0)
        right = arr[pos + half + 1:pos + half + 1 + side_width, :, :].mean(axis=0)

    # Thin-line friendly: AI-generated separators are often 1-2px off-white
    # lines which get diluted below the brightness thresholds when averaged
    # across the strip width on the downscaled scan image. Pool per column
    # and take the extremes instead of the mean.
    col_gray = strip.mean(axis=2)
    col_chroma = strip.max(axis=2) - strip.min(axis=2)
    neutral = col_chroma <= 70

    bright_separator = ((col_gray >= 205) & neutral).any(axis=1)
    dark_separator = ((col_gray <= 40) & neutral).any(axis=1)

    strip_high = col_gray.max(axis=1)
    strip_low = col_gray.min(axis=1)
    left_gray = left.mean(axis=1)
    right_gray = right.mean(axis=1)
    bright_ridge = ((strip_high - left_gray) >= 35) & ((strip_high - right_gray) >= 35)
    dark_ridge = ((left_gray - strip_low) >= 35) & ((right_gray - strip_low) >= 35)

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
