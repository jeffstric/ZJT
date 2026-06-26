# 智剧通启动器打包工具

本目录提供两种生成 `点我启动.exe` 的方式，**强烈推荐第一种（原生 .NET）**。

## ✅ 方式一：原生 .NET 启动器（推荐·零误报·~80KB）

用 Windows 自带的 C# 编译器 (csc.exe) 把极简的 `launcher_exe.cs` 编译成一个
原生 .NET 可执行文件。这个 exe **只做一件事**：调用同目录的 `launcher_me.bat`
（后者通过 uv 运行 `scripts/launchers/launcher.py` 启动托盘）。

**为什么不再用 PyInstaller**：PyInstaller 打包的 exe 自带 bootloader 特征 + 自解压
机制，极易被杀毒软件误报。原生 .NET exe 无这些特征，**杀毒软件不会按 PyInstaller
特征误报**，且体积仅 ~80KB（PyInstaller 版 10MB+），无需安装任何打包工具。

### 编译

```bash
python scripts/build/build_launcher_exe.py
```

或直接调用 csc（Windows 自带）：

```bat
C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe /target:winexe /optimize+ /reference:System.dll /win32icon:files\logo.ico /out:点我启动.exe scripts\build\launcher_exe.cs
```

### 产物（项目根目录）

- `点我启动.exe` —— 中文名，国内用户，~80KB，双击即调用 `launcher_me.bat` 启动
- `launcher_me.exe` —— 英文名，海外用户，~80KB，逻辑相同

### 相关文件

- `launcher_exe.cs` —— C# 源码（极简：调用 bat + 失败时弹错误框）
- `build_launcher_exe.py` —— Python 编译脚本

### 注意

- `点我启动.exe` 本身不含业务逻辑，只调用 `launcher_me.bat`；托盘/服务逻辑全在
  `launcher_me.bat` → `launcher.py`。首次启动仍需 uv 准备 Python 环境（约 1~3 分钟）。
- 该 exe 仍**未代码签名**，SmartScreen 首次可能提示「未知发布者」，点「仍要运行」即可；
  但 AV 静态误报问题已消除（与 PyInstaller 版「被直接删除」有本质区别）。

## ⚠️ 方式二：PyInstaller 打包（备选·易被杀毒误报）

> 不推荐。PyInstaller 打包的 exe 因 bootloader 特征 + 自解压，常被杀毒软件误报删除。
> 仅在确实需要「自带完整 Python 环境、脱离 uv」的独立 exe 时使用。

`build_launcher.py` 会自动：检查模块（pystray、PIL、PyInstaller）→ 安装缺失 → 清理 → 打包 → 验证。

```bash
scripts\build\build.bat      # 或 python scripts\build\build_launcher.py
```

环境：Python 3.10+、Windows、网络连接；依赖 `pip install pystray Pillow pyinstaller`。

## 托盘功能（两种方式通用）

启动后的程序都具备：
- 系统托盘图标显示
- 启动状态指示（橙色=启动中，绿色=就绪，红色=错误）
- 右键菜单（打开浏览器、查看日志、退出）
- 自动打开浏览器
