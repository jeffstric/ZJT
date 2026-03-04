"""
图像4宫格切分工具

用于将2x2布局的4宫格图像切分成4个独立的图像文件。
适用于批量生成角色、场景、道具等设计图的场景。
"""

from PIL import Image
import os
from typing import List, Tuple, Optional
from pathlib import Path


class ImageGridSplitter:
    """图像4宫格切分器"""
    
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
        
        # 打开图像
        try:
            img = Image.open(grid_image_path)
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
