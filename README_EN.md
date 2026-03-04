# ZhiJuTong - AI Short Drama Production Platform

![ZhiJuTong](files/广告图.png)

English | [中文](README.md)

ZhiJuTong is an AI-powered short drama production platform that provides an all-in-one solution for script writing, character management, video generation, and audio synthesis.

## Table of Contents

- [Key Features](#key-features)
- [📦 User Guide](#-user-guide)
  - [Quick Start (Windows)](#quick-start-windows)
  - [FAQ (Users)](#faq-users)
- [🛠️ Developer Guide](#️-developer-guide)
- [License](#license)
- [Contact Us](#contact-us)

## Key Features

### 1. End-to-End Automated Script & Storyboard Production

Fully automates the entire script and storyboard workflow - one-click script node splitting, automatic prompt parsing, intelligent matching of scenes, characters, and props. Auto-generates and adapts multi-panel storyboards, ensuring visual consistency while saving computing power. Zero experience required for core creation. Supports character reference images to maintain consistent character appearances across storyboards and scenes, completely solving the "face collapse" problem in AI short dramas and significantly improving production quality.

![Workflow Automation](files/工作流.png)

![Timeline](files/时间轴.png)

### 2. AI Agents for Hit Scripts

Professional AI agent team collaboratively operates the script intelligence - supports conversational script creation, continuation, and novel adaptation throughout the entire process. Automatically completes outline, script, character, scene and prop design generation with compliance verification. Intelligent generation of suspense hooks and emotional curve analysis precisely controls audience emotions, efficiently improving short drama completion rates.

![AI Agent](files/智能体生成剧本.png)

### 3. Professional Infinite Canvas

Features an infinite canvas combining convenience and professionalism, providing flexible and professional creative space for script storyboard creation. Efficiently adapts to multi-panel storyboard generation, splitting, and layout, making storyboard creation more professional and effortless.

![Infinite Canvas](files/无限画布.png)

### 4. Boundless Team Collaboration

No installation required - use directly in browser. Supports LAN deployment and public network remote collaboration, enabling team members to co-create in real-time anytime, anywhere.

### 5. Flexible Computing & Key Management

Supports multi-vendor key configuration with built-in multi-user independent billing system. Can be bound to personal WeChat Pay, adapting to diverse creative needs.

![Billing Management](files/算力.png)

### 6. Battle-Tested + Free & Open Source

Successfully completed short drama production and launch on Hongguo platform - video and image generation stability verified through real projects. Source code is open source, supporting user-driven development and personalized customization.

![Production Verified](files/红果漫剧.png)

### 7. Ready-to-Use with Zero Barriers

Built-in free image hosting, curated prompt library, and TTS voice service. No complex configuration needed - register and start creating.

### 8. Enterprise-Grade Stability

Full API unit test coverage ensures strong system stability, guaranteeing uninterrupted creative workflow.

---

# 📦 User Guide

> If you just want to use ZhiJuTong, please read this section.

📖 **Full Tutorial**: [Feishu Docs](https://bq3mlz1jiae.feishu.cn/wiki/W1h2wCK3mi1CgDk36LEcVqggnLe) (Chinese)

🌐 **Live Demo**: [ailive.perseids.cn](http://ailive.perseids.cn)

## Quick Start (Windows)

### Start the Service

**Double-click `点我启动.exe` (Click to Start)**:

- ✅ System tray icon shows startup status
- ✅ Browser opens automatically when service is ready
- ✅ Right-click menu: Open browser, View logs, Exit
- ✅ All services stop automatically on exit

The configuration file `config.yml` is created automatically on first launch. Usually no modification is needed.

### Access URL

- Frontend: `http://localhost:9003/`

### Stop the Service

- Right-click the system tray icon → Exit
- Or double-click `stop.bat`

## FAQ (Users)

- **"Already running" message** - Check if there's already an icon in the system tray
- **Cannot open webpage** - Wait for startup to complete, or check if the port is occupied
- **Service error** - Check log files in the `logs/` directory

---

# 🛠️ Developer Guide

If you need to modify the code or contribute to development, please read the **[Developer Documentation](docs/README.md)**, which includes:

- Environment requirements and dependency installation
- Multiple startup methods (Windows/Linux/macOS)
- Configuration guide
- Directory structure
- FAQ

---

## License

This project uses a modified Apache License 2.0. See [LICENSE](LICENSE) for details.

Key terms:
- ✅ Commercial use allowed
- ✅ Modification and distribution allowed
- ❌ Multi-workspace service operation requires authorization
- ❌ Frontend LOGO and copyright information must not be removed

## Contact Us

For questions or suggestions, feel free to contact us:

📧 **Email**: jeffstric@qq.com

| WeChat Group | Personal WeChat |
|:---:|:---:|
| <img src="http://ailive.perseids.cn/upload/assert/wx_group.jpg" width="200" alt="Group QR Code"> | <img src="files/二维码.jpg" width="200" alt="Personal QR Code"> |
| Scan to join the group | Scan to add author |

© 2025 ZhiJuTong. All rights reserved.
