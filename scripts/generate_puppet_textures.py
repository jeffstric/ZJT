#!/usr/bin/env python3
"""生成导演舞台人偶的线性法线/AO 贴图。

只依赖标准库和 Pillow。UV 的 v=0 在人偶底部、v=1 在顶部；PNG 按
TextureLoader 默认 flipY=true 的方式书写（图片顶行对应 v=1）。
LatheGeometry 的 +Z 正面位于 u=0/1 接缝，所有正面结构均使用周期、
左右对称的紧致平滑窗，背面 u=0.5 不留这些结构。

用法（可从任意工作目录运行）：
    python scripts/generate_puppet_textures.py
"""
from __future__ import annotations

import math
import random
from array import array
from pathlib import Path
from typing import Callable

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "web" / "assets" / "puppet"
SIZE = 512
SEED = 20261024
NEUTRAL_NORMAL = (128, 128, 255)

HeightField = Callable[[float, float], float]


def _gaussian(value: float, center: float, width: float) -> float:
    z = (value - center) / width
    return math.exp(-0.5 * z * z)


def _front_bump(u: float, radius: float) -> float:
    """以接缝为中心的周期 C2 平滑窗；radius 以外严格为零。"""
    distance = (u + 0.5) % 1.0 - 0.5
    t = abs(distance) / radius
    if t >= 1.0:
        return 0.0
    window = 0.5 + 0.5 * math.cos(math.pi * t)
    return window * window


def _resin_height() -> array:
    """两个八度的周期 quintic value noise，振幅足以仅产生轻微树脂感。"""
    rng = random.Random(SEED)
    octaves = []
    for columns, rows, amplitude in ((24, 24, 0.00011), (64, 64, 0.000030)):
        # u 方向按列取模，确保接缝两侧来自同一个周期随机场。
        lattice = [
            [rng.uniform(-1.0, 1.0) for _ in range(columns)]
            for _ in range(rows + 1)
        ]
        octaves.append((columns, rows, amplitude, lattice))

    def noise(u: float, v: float, columns: int, rows: int, lattice: list[list[float]]) -> float:
        x = u * columns
        x0 = math.floor(x)
        tx = x - x0
        ix0 = x0 % columns
        ix1 = (ix0 + 1) % columns

        y = v * rows
        iy0 = min(math.floor(y), rows - 1)
        ty = y - iy0
        # quintic smootherstep 让高度场在格点处也具有连续二阶导数。
        sx = tx * tx * tx * (tx * (tx * 6.0 - 15.0) + 10.0)
        sy = ty * ty * ty * (ty * (ty * 6.0 - 15.0) + 10.0)

        top = lattice[iy0]
        bottom = lattice[iy0 + 1]
        a = top[ix0] + (top[ix1] - top[ix0]) * sx
        b = bottom[ix0] + (bottom[ix1] - bottom[ix0]) * sx
        return a + (b - a) * sy

    def field(u: float, v: float) -> float:
        return sum(
            amplitude * noise(u, v, columns, rows, lattice)
            for columns, rows, amplitude, lattice in octaves
        )

    return _sample_height(field)


def _sample_height(field: HeightField) -> array:
    height = array("d", [0.0]) * (SIZE * SIZE)
    for y in range(SIZE):
        # PNG 顶行是 v=1，底行是 v=0，适配 TextureLoader.flipY=true。
        v = 1.0 - y / (SIZE - 1)
        row = y * SIZE
        for x in range(SIZE):
            height[row + x] = field(x / (SIZE - 1), v)
    return height


def _to_byte(value: float) -> int:
    return max(0, min(255, math.floor(value * 255.0 + 0.5)))


def _normal_from_height(height: array) -> Image.Image:
    """n=normalize(-dh/du, -dh/dv, 1)，直接编码为无色彩元数据 RGB。"""
    pixels = bytearray(SIZE * SIZE * 3)
    last = SIZE - 1
    central_scale = last / 2.0
    for y in range(SIZE):
        row = y * SIZE
        for x in range(SIZE):
            index = row + x
            # u 是周期方向；第 511 列是第 0 列的重复接缝样本。
            xm = (x - 1) % last
            xp = (x + 1) % last
            dhdu = (height[row + xp] - height[row + xm]) * central_scale
            if y == 0:
                dhdv = (height[index] - height[index + SIZE]) * last
            elif y == last:
                dhdv = (height[index - SIZE] - height[index]) * last
            else:
                dhdv = (height[index - SIZE] - height[index + SIZE]) * central_scale

            nx = -dhdu
            ny = -dhdv
            inv_length = 1.0 / math.sqrt(nx * nx + ny * ny + 1.0)
            offset = index * 3
            pixels[offset] = _to_byte(0.5 + 0.5 * nx * inv_length)
            pixels[offset + 1] = _to_byte(0.5 + 0.5 * ny * inv_length)
            pixels[offset + 2] = _to_byte(0.5 + 0.5 * inv_length)
    return Image.frombytes("RGB", (SIZE, SIZE), bytes(pixels))


def _ao_image(occlusion: HeightField) -> Image.Image:
    pixels = bytearray(SIZE * SIZE)
    for y in range(SIZE):
        v = 1.0 - y / (SIZE - 1)
        row = y * SIZE
        for x in range(SIZE):
            shade = occlusion(x / (SIZE - 1), v)
            pixels[row + x] = max(0, min(255, math.floor(255.0 - shade + 0.5)))
    return Image.frombytes("L", (SIZE, SIZE), bytes(pixels))


def _torso_height(u: float, v: float) -> float:
    # 单块宽胸廓与宽腹部，不绘制左右胸肌、六块腹肌或横向肌肉线。
    chest = 0.0090 * _front_bump(u, 0.43) * _gaussian(v, 0.73, 0.15)
    abdomen = 0.0055 * _front_bump(u, 0.36) * _gaussian(v, 0.38, 0.17)
    return chest + abdomen


def _head_height(u: float, v: float) -> float:
    # 只保留宽而浅的下巴；无五官人台不需要眼窝/唇缝/鼻孔等面部项。
    chin = 0.0032 * _front_bump(u, 0.29) * _gaussian(v, 0.24, 0.085)
    return chin


def _torso_occlusion(u: float, v: float) -> float:
    # 胸腹交界只有最高约 4% 的宽柔和遮蔽，背面严格保持白色。
    return 10.0 * _front_bump(u, 0.40) * _gaussian(v, 0.525, 0.038)


def _head_occlusion(u: float, v: float) -> float:
    # 下颌/颈部接触阴影位于头部 UV 下部。
    return 14.0 * _front_bump(u, 0.36) * _gaussian(v, 0.085, 0.048)


def _validate(path: Path, expected_mode: str, check_back: bool) -> object:
    with Image.open(path) as image:
        image.load()
        if image.size != (SIZE, SIZE):
            raise ValueError(f"{path.name}: 尺寸错误 {image.size}")
        if image.mode != expected_mode:
            raise ValueError(f"{path.name}: 模式错误 {image.mode}")
        colour_metadata = {"icc_profile", "gamma", "srgb"}.intersection(image.info)
        if colour_metadata:
            raise ValueError(f"{path.name}: 含非线性色彩元数据 {colour_metadata}")

        pixels = image.load()
        neutral = NEUTRAL_NORMAL if expected_mode == "RGB" else 255
        for y in range(SIZE):
            if pixels[0, y] != pixels[SIZE - 1, y]:
                raise ValueError(f"{path.name}: u=0/1 接缝不连续，行 {y}")
            if check_back and pixels[SIZE // 2, y] != neutral:
                raise ValueError(f"{path.name}: 背面 u=0.5 非中性，行 {y}")
        return image.getextrema()


def _save(image: Image.Image, filename: str, check_back: bool) -> None:
    path = OUTPUT_DIR / filename
    # 新建无元数据图像并不传 ICC/gAMA/sRGB 参数，PNG 数值按线性数据解释。
    image.save(path, format="PNG", optimize=False)
    extrema = _validate(path, image.mode, check_back)
    relative = path.relative_to(ROOT)
    print(f"{relative} | {image.mode} {SIZE}x{SIZE} | extrema={extrema}")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _save(_normal_from_height(_resin_height()), "resin_normal.png", check_back=False)
    _save(_normal_from_height(_sample_height(_torso_height)), "torso_normal.png", check_back=True)
    _save(_ao_image(_torso_occlusion), "torso_ao.png", check_back=True)
    _save(_normal_from_height(_sample_height(_head_height)), "head_normal.png", check_back=True)
    _save(_ao_image(_head_occlusion), "head_ao.png", check_back=True)
    print(f"完成：seed={SEED}，接缝连续，背面中性，未写入 ICC/gAMA/sRGB 色彩元数据。")


if __name__ == "__main__":
    main()
