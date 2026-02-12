
from PIL import Image
import os
from typing import List, Tuple, Optional
from pathlib import Path


class ImageGridSplitter:
    """图像宫格切分器（支持4宫格和9宫格）"""
    
    def __init__(self):
        """初始化切分器"""
        pass
    
    def split_2x2_grid(
        self, 
        grid_image_path: str, 
        output_dir: str,
        output_names: Optional[List[str]] = None,
        output_format: str = "png"
    ) -> List[str]:
        """
        将2x2的4宫格图像切分成4个独立图像
        
        Args:
            grid_image_path: 4宫格图像的路径
            output_dir: 输出目录
            output_names: 输出文件名列表（不含扩展名），如果为None则使用默认命名
            output_format: 输出格式，默认为png
            
        Returns:
            List[str]: 切分后的图像路径列表，顺序为[左上, 右上, 左下, 右下]
            
        Raises:
            FileNotFoundError: 如果输入图像不存在
            ValueError: 如果图像尺寸不合适
        """
        # 检查输入文件是否存在
        if not os.path.exists(grid_image_path):
            raise FileNotFoundError(f"图像文件不存在: {grid_image_path}")
        
        # 创建输出目录
        os.makedirs(output_dir, exist_ok=True)
        
        # 打开图像并强制加载全部像素数据（避免惰性加载导致crop不完整）
        try:
            img = Image.open(grid_image_path)
            img.load()
        except Exception as e:
            raise ValueError(f"无法打开图像文件: {e}")
        
        # 获取图像尺寸
        width, height = img.size
        
        # 计算每个子图像的尺寸
        sub_width = width // 2
        sub_height = height // 2
        
        # 定义4个区域的坐标 (left, upper, right, lower)
        regions = [
            (0, 0, sub_width, sub_height),              # 左上 (Shot 1)
            (sub_width, 0, width, sub_height),          # 右上 (Shot 2)
            (0, sub_height, sub_width, height),         # 左下 (Shot 3)
            (sub_width, sub_height, width, height)      # 右下 (Shot 4)
        ]
        
        # 设置输出文件名
        if output_names is None:
            base_name = Path(grid_image_path).stem
            output_names = [
                f"{base_name}_shot1",
                f"{base_name}_shot2",
                f"{base_name}_shot3",
                f"{base_name}_shot4"
            ]
        elif len(output_names) != 4:
            raise ValueError(f"output_names必须包含4个名称，当前提供了{len(output_names)}个")
        
        # 切分并保存图像
        output_paths = []
        for i, (region, name) in enumerate(zip(regions, output_names)):
            # 裁剪图像
            sub_img = img.crop(region)
            
            # 构建输出路径
            output_path = os.path.join(output_dir, f"{name}.{output_format}")
            
            # 保存图像
            sub_img.save(output_path, format=output_format.upper())
            output_paths.append(output_path)
            
            print(f"已保存: {output_path} (位置: {'左上' if i==0 else '右上' if i==1 else '左下' if i==2 else '右下'})")
        
        # 关闭原图像
        img.close()
        
        return output_paths
    
    def split_3x3_grid(
        self, 
        grid_image_path: str, 
        output_dir: str,
        output_names: Optional[List[str]] = None,
        output_format: str = "png"
    ) -> List[str]:
        """
        将3x3的9宫格图像切分成9个独立图像
        
        Args:
            grid_image_path: 宫格图像路径
            output_dir: 输出目录
            output_names: 输出文件名列表（不含扩展名），默认为 ["1", "2", ..., "9"]
            output_format: 输出格式，默认为 "png"
            
        Returns:
            List[str]: 输出文件路径列表
            
        布局：
        [1] [2] [3]
        [4] [5] [6]
        [7] [8] [9]
        """
        if not os.path.exists(grid_image_path):
            raise FileNotFoundError(f"宫格图像不存在: {grid_image_path}")
        
        os.makedirs(output_dir, exist_ok=True)
        
        if output_names is None:
            output_names = [str(i) for i in range(1, 10)]
        elif len(output_names) != 9:
            raise ValueError("output_names 必须包含9个元素")
        
        try:
            img = Image.open(grid_image_path)
            img.load()  # 强制加载全部像素数据，避免惰性加载导致crop不完整
        except Exception as e:
            raise ValueError(f"无法打开图像文件: {e}")
        width, height = img.size
        
        cell_width = width // 3
        cell_height = height // 3
        
        output_paths = []
        positions = [
            (0, 0), (cell_width, 0), (cell_width * 2, 0),
            (0, cell_height), (cell_width, cell_height), (cell_width * 2, cell_height),
            (0, cell_height * 2), (cell_width, cell_height * 2), (cell_width * 2, cell_height * 2)
        ]
        
        for i, (x, y) in enumerate(positions):
            box = (x, y, x + cell_width, y + cell_height)
            cell_img = img.crop(box)
            
            output_path = os.path.join(output_dir, f"{output_names[i]}.{output_format}")
            cell_img.save(output_path, format=output_format.upper())
            output_paths.append(output_path)
        
        return output_paths