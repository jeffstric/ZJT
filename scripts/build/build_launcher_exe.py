#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
智剧通原生启动器编译脚本

用 Windows 自带的 .NET Framework C# 编译器 (csc.exe) 把 launcher_exe.cs
编译成两个等价的极简原生 .NET 程序，都仅负责调用 launcher_me.bat：
- launcher_me.exe —— 英文名，海外用户
- 点我启动.exe    —— 中文名，国内用户

相比 PyInstaller 打包的 exe（scripts/build/build_launcher.py），本方式：
- 无 PyInstaller bootloader 特征，杀毒软件不会按 PyInstaller 特征误报
- 体积极小（~80KB vs PyInstaller 10MB+）
- 无需安装任何额外工具（csc.exe 是 Windows 自带）

用法：python scripts/build/build_launcher_exe.py
"""
import os
import subprocess
import sys

# csc.exe 候选路径（.NET Framework 4.x，Windows 自带）
CSC_CANDIDATES = [
    r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe",
    r"C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe",
]


def find_csc():
    for path in CSC_CANDIDATES:
        if os.path.exists(path):
            return path
    return None


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(os.path.dirname(script_dir))

    src = os.path.join(script_dir, "launcher_exe.cs")
    icon = os.path.join(project_root, "files", "logo.ico")

    # 两个等价 exe：逻辑完全相同（都调 launcher_me.bat），仅文件名/语言不同
    outputs = [
        os.path.join(project_root, "launcher_me.exe"),  # English name, overseas users
        os.path.join(project_root, "点我启动.exe"),       # Chinese name, CN users
    ]

    if not os.path.exists(src):
        print("[ERROR] source not found: " + src)
        return False

    csc = find_csc()
    if not csc:
        print("[ERROR] csc.exe not found (.NET Framework C# compiler)")
        print("        Please ensure .NET Framework 4.x is installed (ships with Windows)")
        return False

    print("[INFO] compiler: " + csc)
    print("[INFO] source:   " + src)

    icon_arg = []
    if os.path.exists(icon):
        icon_arg = ["/win32icon:" + icon]
    else:
        print("[WARN] icon not found, building without icon: " + icon)

    all_ok = True
    for out in outputs:
        cmd = [
            csc, "/target:winexe", "/nologo", "/optimize+",
            "/reference:System.dll",
            "/out:" + out,
        ] + icon_arg + [src]
        print("[INFO] building: " + out)
        try:
            subprocess.check_call(cmd)
        except subprocess.CalledProcessError as e:
            print("[ERROR] compile failed for " + out + ": " + str(e))
            all_ok = False
            continue
        if os.path.exists(out):
            size_kb = os.path.getsize(out) / 1024
            print("[OK] built: " + out + " (%.1f KB)" % size_kb)
        else:
            print("[ERROR] output not found: " + out)
            all_ok = False

    return all_ok


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
