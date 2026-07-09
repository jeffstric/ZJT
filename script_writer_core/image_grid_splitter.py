"""
图像宫格切分工具

支持将 N×N 布局的宫格图像切分成独立图像文件：
  - 2x2 四宫格（4 格，向后兼容）
  - 3x3 九宫格（9 格，子场景参考图）
适用于批量生成角色、场景、道具等设计图的场景。

新增宫格规格时，在 config/constant.py 的 GridConfig.VALID_SIZES 中登记即可，
本模块按 int(sqrt(grid_size)) 自动推导行列数。
"""

from PIL import Image
import os
import math
from typing import List, Optional
from pathlib import Path

from config.constant import GridConfig
from utils.image_grid_validator import validate_grid_image

# 位置标签（行优先）：用于日志输出，超出范围时回退为 "区域N"
_POSITION_LABELS_2X2 = ["左上", "右上", "左下", "右下"]


class ImageGridSplitter:
    """图像宫格切分器（支持 2x2 / 3x3 等 N×N 布局）"""

    def __init__(self):
        """初始化切分器"""
        pass

    def split_grid(
        self,
        grid_image_path: str,
        output_dir: str,
        grid_size: int = GridConfig.SIZE_2X2,
        output_names: Optional[List[str]] = None,
        output_format: str = "png",
        validate: bool = True,
    ) -> List[str]:
        """
        将 N×N 宫格图像切分成独立图像。

        Args:
            grid_image_path: 宫格图像的路径
            output_dir: 输出目录
            grid_size: 宫格总数（4=2x2, 9=3x3），必须在 GridConfig.VALID_SIZES 中
            output_names: 输出文件名列表（不含扩展名）。
                          - None → 使用默认 {stem}_shot{i} 命名
                          - 长度必须等于 grid_size
            output_format: 输出格式，默认为 png

        Returns:
            List[str]: 切分后的图像路径列表，行优先顺序
            （2x2: [左上, 右上, 左下, 右下]；3x3: 从左上到右下逐行）

        Raises:
            FileNotFoundError: 如果输入图像不存在
            ValueError: grid_size 非法、output_names 长度不符、或图像无法打开
        """
        if grid_size not in GridConfig.VALID_SIZES:
            raise ValueError(
                f"不支持的 grid_size={grid_size}，当前允许: {GridConfig.VALID_SIZES}"
            )

        # 按平方根推导行列数（4→2, 9→3）
        cols = int(math.sqrt(grid_size))
        if cols * cols != grid_size:
            raise ValueError(
                f"grid_size={grid_size} 必须是完全平方数（当前仅支持 2x2=4 / 3x3=9）"
            )
        rows = cols

        # 检查输入文件是否存在
        if not os.path.exists(grid_image_path):
            raise FileNotFoundError(f"图像文件不存在: {grid_image_path}")

        if validate:
            validation = validate_grid_image(grid_image_path, grid_size)
            if not validation.is_valid:
                raise ValueError(
                    f"Invalid grid image: {validation.reason}; "
                    f"confidence={validation.confidence:.2f}"
                )

        # 创建输出目录
        os.makedirs(output_dir, exist_ok=True)

        # 打开图像
        try:
            img = Image.open(grid_image_path)
        except Exception as e:
            raise ValueError(f"无法打开图像文件: {e}")

        width, height = img.size
        sub_width = width // cols
        sub_height = height // rows

        # 生成行优先的 region 坐标
        regions = []
        labels = []
        for r in range(rows):
            for c in range(cols):
                left = c * sub_width
                upper = r * sub_height
                right = width if c == cols - 1 else (c + 1) * sub_width
                lower = height if r == rows - 1 else (r + 1) * sub_height
                regions.append((left, upper, right, lower))
                idx = r * cols + c
                if grid_size == GridConfig.SIZE_2X2 and idx < len(_POSITION_LABELS_2X2):
                    labels.append(_POSITION_LABELS_2X2[idx])
                else:
                    labels.append(f"区域{idx + 1}")

        # 设置输出文件名
        if output_names is None:
            base_name = Path(grid_image_path).stem
            output_names = [f"{base_name}_shot{i + 1}" for i in range(grid_size)]
        elif len(output_names) != grid_size:
            raise ValueError(
                f"output_names必须包含{grid_size}个名称，当前提供了{len(output_names)}个"
            )

        # 切分并保存图像
        output_paths = []
        for i, (region, name) in enumerate(zip(regions, output_names)):
            sub_img = img.crop(region)
            output_path = os.path.join(output_dir, f"{name}.{output_format}")
            sub_img.save(output_path, format=output_format.upper())
            output_paths.append(output_path)
            print(f"已保存: {output_path} (位置: {labels[i]})")

        img.close()
        return output_paths

    def split_2x2_grid(
        self,
        grid_image_path: str,
        output_dir: str,
        output_names: Optional[List[str]] = None,
        output_format: str = "png"
    ) -> List[str]:
        """
        将2x2的4宫格图像切分成4个独立图像（向后兼容包装）。

        Returns:
            List[str]: 切分后的图像路径列表，顺序为[左上, 右上, 左下, 右下]
        """
        return self.split_grid(
            grid_image_path=grid_image_path,
            output_dir=output_dir,
            grid_size=GridConfig.SIZE_2X2,
            output_names=output_names,
            output_format=output_format,
        )

    def split_3x3_grid(
        self,
        grid_image_path: str,
        output_dir: str,
        output_names: Optional[List[str]] = None,
        output_format: str = "png"
    ) -> List[str]:
        """
        将3x3的九宫格图像切分成9个独立图像。

        Returns:
            List[str]: 切分后的图像路径列表，行优先（左上→右上→...→右下）
        """
        return self.split_grid(
            grid_image_path=grid_image_path,
            output_dir=output_dir,
            grid_size=GridConfig.SIZE_3X3,
            output_names=output_names,
            output_format=output_format,
        )

    def split_2x2_grid_batch(
        self,
        grid_image_paths: List[str],
        output_dir: str,
        output_names_list: Optional[List[List[str]]] = None,
        output_format: str = "png"
    ) -> List[List[str]]:
        """
        批量切分多个2x2的4宫格图像

        Args:
            grid_image_paths: 4宫格图像路径列表
            output_dir: 输出目录
            output_names_list: 每个4宫格对应的输出文件名列表，如果为None则使用默认命名
            output_format: 输出格式，默认为png

        Returns:
            List[List[str]]: 每个4宫格切分后的图像路径列表
        """
        all_output_paths = []

        for i, grid_path in enumerate(grid_image_paths):
            output_names = None
            if output_names_list and i < len(output_names_list):
                output_names = output_names_list[i]

            try:
                output_paths = self.split_2x2_grid(
                    grid_image_path=grid_path,
                    output_dir=output_dir,
                    output_names=output_names,
                    output_format=output_format
                )
                all_output_paths.append(output_paths)
                print(f"✅ 成功切分第{i+1}个4宫格图像")
            except Exception as e:
                print(f"❌ 切分第{i+1}个4宫格图像失败: {e}")
                all_output_paths.append([])

        return all_output_paths


def split_character_grid(
    grid_image_path: str,
    character_names: List[str],
    output_dir: str = "./characters"
) -> List[str]:
    """
    便捷函数：切分角色4宫格图像
    
    Args:
        grid_image_path: 4宫格图像路径
        character_names: 4个角色的名称列表
        output_dir: 输出目录，默认为./characters
        
    Returns:
        List[str]: 切分后的角色图像路径列表
    """
    if len(character_names) != 4:
        raise ValueError(f"必须提供4个角色名称，当前提供了{len(character_names)}个")
    
    splitter = ImageGridSplitter()
    return splitter.split_2x2_grid(
        grid_image_path=grid_image_path,
        output_dir=output_dir,
        output_names=character_names,
        output_format="png"
    )


def split_location_grid(
    grid_image_path: str,
    location_names: List[str],
    output_dir: str = "./locations"
) -> List[str]:
    """
    便捷函数：切分场景4宫格图像
    
    Args:
        grid_image_path: 4宫格图像路径
        location_names: 4个场景的名称列表
        output_dir: 输出目录，默认为./locations
        
    Returns:
        List[str]: 切分后的场景图像路径列表
    """
    if len(location_names) != 4:
        raise ValueError(f"必须提供4个场景名称，当前提供了{len(location_names)}个")
    
    splitter = ImageGridSplitter()
    return splitter.split_2x2_grid(
        grid_image_path=grid_image_path,
        output_dir=output_dir,
        output_names=location_names,
        output_format="png"
    )


def split_prop_grid(
    grid_image_path: str,
    prop_names: List[str],
    output_dir: str = "./props"
) -> List[str]:
    """
    便捷函数：切分道具4宫格图像
    
    Args:
        grid_image_path: 4宫格图像路径
        prop_names: 4个道具的名称列表
        output_dir: 输出目录，默认为./props
        
    Returns:
        List[str]: 切分后的道具图像路径列表
    """
    if len(prop_names) != 4:
        raise ValueError(f"必须提供4个道具名称，当前提供了{len(prop_names)}个")
    
    splitter = ImageGridSplitter()
    return splitter.split_2x2_grid(
        grid_image_path=grid_image_path,
        output_dir=output_dir,
        output_names=prop_names,
        output_format="png"
    )


# 示例用法
if __name__ == "__main__":
    # 示例1: 切分角色4宫格
    print("=== 示例1: 切分角色4宫格 ===")
    try:
        character_paths = split_character_grid(
            grid_image_path="./test_grid.png",
            character_names=["张三", "李四", "王五", "赵六"],
            output_dir="./output/characters"
        )
        print(f"角色图像已保存到: {character_paths}")
    except Exception as e:
        print(f"示例1失败: {e}")
    
    # 示例2: 使用类进行更灵活的切分
    print("\n=== 示例2: 使用ImageGridSplitter类 ===")
    try:
        splitter = ImageGridSplitter()
        paths = splitter.split_2x2_grid(
            grid_image_path="./test_grid.png",
            output_dir="./output/custom",
            output_names=["image1", "image2", "image3", "image4"],
            output_format="jpg"
        )
        print(f"图像已保存到: {paths}")
    except Exception as e:
        print(f"示例2失败: {e}")
    
    # 示例3: 批量切分多个4宫格
    print("\n=== 示例3: 批量切分 ===")
    try:
        splitter = ImageGridSplitter()
        all_paths = splitter.split_2x2_grid_batch(
            grid_image_paths=["./grid1.png", "./grid2.png"],
            output_dir="./output/batch",
            output_names_list=[
                ["角色1", "角色2", "角色3", "角色4"],
                ["角色5", "角色6", "角色7", "角色8"]
            ]
        )
        print(f"批量切分完成，共{len(all_paths)}个4宫格")
    except Exception as e:
        print(f"示例3失败: {e}")
