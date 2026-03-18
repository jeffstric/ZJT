#!/usr/bin/env python3
"""
ZJT 打包脚本
生成三个平台的发布包：Windows、macOS x86_64、macOS ARM
"""

import argparse
import os
import shutil
import subprocess
import zipfile
from datetime import datetime
from pathlib import Path


# ============================================
# 配置
# ============================================

# NAS 盘路径（存放二进制文件）
NAS_PATH = Path(r"H:\智剧通")

# 当前脚本所在目录（代码目录）
# 获取项目根目录（scripts 的父目录）
CODE_PATH = Path(__file__).parent.parent.resolve()

# 输出目录
OUTPUT_PATH = CODE_PATH / "dist"

# 不需要打包的目录
EXCLUDE_DIRS = [
    "bin",
    ".git",
    "__pycache__",
    "dist",
    "auto_test",
    ".python-version",
    "upload",
    "data",
    "logs",
    "script_parser_logs",
    ".pytest_cache",
    ".venv",
    "build",
]

# 不需要打包的目录（相对路径，只排除特定子目录）
EXCLUDE_SUBDIRS = [
    "files/script_writer",
    "files/tmp",
]

# 不需要打包的文件
EXCLUDE_FILES = [
    "config_unit.yml",
    "config_prod.yml",
    "config_dev.yml",
    "package.py",
    "package.bat",
]


# ============================================
# 平台配置
# ============================================

PLATFORMS = {
    "Windows": {
        "mysql_src": "mysql",
        "mysql_dst": "mysql",
        "ffmpeg_src": "ffmpeg",
        "ffmpeg_dst": "ffmpeg",
        "uv_src": "uv.exe",
        "uv_dst": "uv.exe",
        "extra_files": ["start.bat"],
        "exclude_files": ["start.command", "create_mac_app.sh"],
    },
    "macOS-x86": {
        "mysql_src": "mysql-macos-x86",
        "mysql_dst": "mysql",
        "ffmpeg_src": "ffmpeg_mac",
        "ffmpeg_dst": "ffmpeg",
        "uv_src": "mac_x86_uv",
        "uv_dst": "uv",
        "extra_files": ["start.command", "create_mac_app.sh"],
        "exclude_files": ["start.bat"],
    },
    "macOS-ARM": {
        "mysql_src": "mysql-macos-arm",
        "mysql_dst": "mysql",
        "ffmpeg_src": "ffmpeg_mac",
        "ffmpeg_dst": "ffmpeg",
        "uv_src": "mac_arm_uv",
        "uv_dst": "uv",
        "extra_files": ["start.command", "create_mac_app.sh"],
        "exclude_files": ["start.bat"],
    },
}


# ============================================
# 工具函数
# ============================================

def get_version():
    """获取版本号，优先使用 git tag，否则使用日期"""
    try:
        result = subprocess.run(
            ["git", "describe", "--tags", "--abbrev=0"],
            cwd=CODE_PATH,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return datetime.now().strftime("%Y%m%d")


def should_exclude_dir(name: str) -> bool:
    """判断目录是否应该被排除"""
    return name in EXCLUDE_DIRS


def should_exclude_file(name: str, rel_path: str = "") -> bool:
    """判断文件是否应该被排除"""
    # Windows 特殊设备文件名（不区分大小写）
    windows_device_names = {"nul", "con", "prn", "aux"} | {f"com{i}" for i in range(1, 10)} | {f"lpt{i}" for i in range(1, 10)}
    if name.lower() in windows_device_names:
        return True
    # 检查文件名匹配
    if name in EXCLUDE_FILES:
        return True
    # 检查根目录下的压缩包
    if not rel_path or rel_path == name:
        if any(name.endswith(ext) for ext in [".zip", ".tar", ".tar.gz", ".7z", ".rar"]):
            return True
    return False


def fix_line_endings(file_path: Path, extensions: list[str] = [".sh", ".command"]):
    """将文本文件的 CRLF 行尾符转换为 LF（Unix 格式）"""
    # 只处理指定扩展名的文件
    if not any(file_path.name.lower().endswith(ext) for ext in extensions):
        return

    try:
        # 读取文件内容
        content = file_path.read_text(encoding="utf-8")
        # 替换 CRLF 为 LF
        content = content.replace("\r\n", "\n")
        # 写回文件（使用 newline="" 禁止 Windows 自动转换 \n 为 \r\n）
        file_path.write_text(content, encoding="utf-8", newline="")
        print(f"      - Fixed line endings: {file_path.name}")
    except Exception:
        # 忽略非文本文件或其他错误
        pass


def copy_source_files(src_dir: Path, dst_dir: Path, exclude_files: list):
    """复制源代码文件（递归处理，排除指定目录和文件）"""

    def copy_recursive(current_src: Path, current_dst: Path, rel_path: str = ""):
        for item in current_src.iterdir():
            item_rel_path = f"{rel_path}/{item.name}" if rel_path else item.name

            # 跳过排除的目录
            if item.is_dir():
                if should_exclude_dir(item.name):
                    continue
                # 检查是否是排除的子目录
                if any(item_rel_path == sub or item_rel_path.startswith(sub + "/") for sub in EXCLUDE_SUBDIRS):
                    continue
                # 递归复制
                new_dst = current_dst / item.name
                new_dst.mkdir(parents=True, exist_ok=True)
                copy_recursive(item, new_dst, item_rel_path)
            else:
                # 跳过排除的文件
                if should_exclude_file(item.name, item_rel_path):
                    continue
                if item.name in exclude_files:
                    continue
                # 复制文件
                shutil.copy2(item, current_dst / item.name)
                # 修复 shell 脚本的行尾符
                fix_line_endings(current_dst / item.name)

    copy_recursive(src_dir, dst_dir)


def copy_binaries(dst_dir: Path, platform_config: dict):
    """复制二进制文件"""
    bin_dir = dst_dir / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)

    # 复制 MySQL
    mysql_src = NAS_PATH / "bin" / platform_config["mysql_src"]
    mysql_dst = bin_dir / platform_config["mysql_dst"]
    print(f"    - MySQL: {platform_config['mysql_src']} -> {platform_config['mysql_dst']}")
    shutil.copytree(mysql_src, mysql_dst)

    # 复制 FFmpeg
    ffmpeg_src = NAS_PATH / "bin" / platform_config["ffmpeg_src"]
    ffmpeg_dst = bin_dir / platform_config["ffmpeg_dst"]
    print(f"    - FFmpeg: {platform_config['ffmpeg_src']} -> {platform_config['ffmpeg_dst']}")
    shutil.copytree(ffmpeg_src, ffmpeg_dst)

    # 复制 UV
    uv_src = NAS_PATH / "bin" / "uv" / platform_config["uv_src"]
    uv_dst_dir = bin_dir / "uv"
    uv_dst_dir.mkdir(parents=True, exist_ok=True)
    uv_dst = uv_dst_dir / platform_config["uv_dst"]
    print(f"    - UV: {platform_config['uv_src']} -> uv/{platform_config['uv_dst']}")
    shutil.copy2(uv_src, uv_dst)


def is_executable_file(file_path: Path, rel_path: Path) -> bool:
    """判断文件是否应该是可执行的（白名单模式）"""
    filename = file_path.name

    # MySQL 可执行文件
    mysql_executables = {"mysqld", "mysql", "mysqladmin", "mysqld_safe", "mysqlcheck", "mysqldump"}

    # FFmpeg 可执行文件
    ffmpeg_executables = {"ffmpeg", "ffprobe", "ffplay"}

    # UV 可执行文件
    uv_executables = {"uv"}

    # 检查是否在对应的目录下
    # arcname 格式为: ZJT-macOS-ARM/bin/ffmpeg/ffmpeg
    # parts[0] = 包名, parts[1] = bin, parts[2] = 子目录名, parts[3] = 文件名
    parts = rel_path.parts

    # 查找 bin 目录的位置（可能在 parts[0] 或 parts[1]）
    bin_index = -1
    for i, part in enumerate(parts):
        if part == "bin":
            bin_index = i
            break

    if bin_index >= 0 and len(parts) >= bin_index + 3:
        subdir = parts[bin_index + 1]
        if subdir == "mysql" and filename in mysql_executables:
            return True
        if subdir == "ffmpeg" and filename in ffmpeg_executables:
            return True
        if subdir == "uv" and filename in uv_executables:
            return True

    # shell 脚本
    if file_path.suffix in [".sh", ".command"]:
        return True

    return False


def create_zip(src_dir: Path, output_file: Path):
    """创建 ZIP 压缩包（保留 Unix 可执行权限）"""
    with zipfile.ZipFile(output_file, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(src_dir):
            for file in files:
                file_path = Path(root) / file
                arcname = file_path.relative_to(src_dir.parent)

                # 判断是否需要可执行权限
                is_exec = is_executable_file(file_path, arcname)

                # 创建 ZipInfo 对象
                zinfo = zipfile.ZipInfo(str(arcname))
                zinfo.compress_type = zipfile.ZIP_DEFLATED

                # 设置 Unix 权限（对 Windows 无影响，对 macOS/Linux 有效）
                # create_system = 3 表示 Unix 格式，解压工具会根据运行环境自动处理
                zinfo.create_system = 3
                if is_exec:
                    # Unix 可执行权限: 0o100755 (S_IFREG | 0755)
                    zinfo.external_attr = 0o100755 << 16
                    print(f"    [EXEC] {arcname} -> 0o755")
                else:
                    # 普通文件权限: 0o100644 (S_IFREG | 0644)
                    zinfo.external_attr = 0o100644 << 16

                # 读取文件内容并写入
                with open(file_path, "rb") as f:
                    zf.writestr(zinfo, f.read())


def build_platform(name: str, config: dict, version: str):
    """构建单个平台的发布包"""
    print(f"[{name}] Building...")

    # 创建临时目录
    temp_dir = OUTPUT_PATH / "temp"
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)

    # 包目录
    package_name = f"ZJT-{name}"
    package_dir = temp_dir / package_name
    package_dir.mkdir(parents=True, exist_ok=True)

    # 复制源代码
    print("  - Copying source files...")
    copy_source_files(CODE_PATH, package_dir, config["exclude_files"])

    # 复制二进制文件
    print("  - Copying binaries...")
    copy_binaries(package_dir, config)

    # 复制额外的启动文件
    print("  - Copying startup files...")
    for extra_file in config["extra_files"]:
        src = CODE_PATH / extra_file
        if src.exists():
            shutil.copy2(src, package_dir / extra_file)
            # 修复额外脚本文件的行尾符
            fix_line_endings(package_dir / extra_file)

    # 创建 ZIP
    output_file = OUTPUT_PATH / f"{package_name}-{version}.zip"
    print(f"  - Creating archive: {output_file.name}...")
    create_zip(package_dir, output_file)

    # 清理临时目录
    shutil.rmtree(temp_dir)

    print(f"  [OK] {package_name}-{version}.zip")
    print()

    return output_file


# ============================================
# 主函数
# ============================================

def main():
    # 解析命令行参数
    parser = argparse.ArgumentParser(description="ZJT Package Builder")
    parser.add_argument(
        "-v", "--version",
        type=str,
        default=None,
        help="指定版本号（默认使用 git tag 或日期）"
    )
    parser.add_argument(
        "-p", "--platform",
        type=str,
        choices=list(PLATFORMS.keys()) + ["all"],
        default="all",
        help="指定构建平台（默认: all）"
    )
    args = parser.parse_args()

    print()
    print("=" * 50)
    print("  ZJT Package Builder")
    print("=" * 50)
    print()

    # 检查 NAS 路径
    if not NAS_PATH.exists():
        print(f"[ERROR] NAS path not found: {NAS_PATH}")
        print("[INFO] Please ensure NAS drive is connected")
        input("\nPress Enter to exit...")
        return

    # 创建输出目录
    OUTPUT_PATH.mkdir(parents=True, exist_ok=True)

    # 获取版本号（优先使用命令行参数）
    version = args.version if args.version else get_version()
    print(f"[INFO] Version: {version}")
    print(f"[INFO] Source: {CODE_PATH}")
    print(f"[INFO] Binaries: {NAS_PATH}")
    print(f"[INFO] Output: {OUTPUT_PATH}")
    print()

    # 确定要构建的平台
    if args.platform == "all":
        platforms_to_build = list(PLATFORMS.items())
    else:
        platforms_to_build = [(args.platform, PLATFORMS[args.platform])]

    # 构建各平台
    output_files = []
    for i, (name, config) in enumerate(platforms_to_build, 1):
        print(f"[{i}/{len(platforms_to_build)}] ", end="")
        output_file = build_platform(name, config, version)
        output_files.append(output_file)

    # 完成
    print("=" * 50)
    print("  Build Complete!")
    print("=" * 50)
    print()
    print("Output files:")
    for f in output_files:
        size_mb = f.stat().st_size / (1024 * 1024)
        print(f"  - {f.name} ({size_mb:.1f} MB)")
    print()
    print(f"Location: {OUTPUT_PATH}")
    print()

    input("Press Enter to exit...")


if __name__ == "__main__":
    main()
