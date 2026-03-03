"""
启动器 - 运行 start_silent.vbs
打包命令: pyinstaller --onefile --noconsole --name "点我启动" --icon=icon.ico launcher.py
"""
import os
import sys
import subprocess


def main():
    # 获取当前脚本所在目录
    if getattr(sys, 'frozen', False):
        # 打包后的 exe
        current_dir = os.path.dirname(sys.executable)
    else:
        # 直接运行 py 文件
        current_dir = os.path.dirname(os.path.abspath(__file__))
    
    vbs_path = os.path.join(current_dir, "start_silent.vbs")
    
    if not os.path.exists(vbs_path):
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            0, 
            f"找不到启动脚本:\n{vbs_path}", 
            "错误", 
            0x10  # MB_ICONERROR
        )
        sys.exit(1)
    
    # 运行 VBS 脚本
    subprocess.Popen(["wscript", vbs_path], cwd=current_dir)


if __name__ == "__main__":
    main()
