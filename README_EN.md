# ZhiJuTong - AI Short Drama Production Platform

ZhiJuTong is an AI-powered short drama production platform that provides an all-in-one solution for script writing, character management, video generation, and audio synthesis.

## Key Features

- **Script Writing** - AI-assisted script creation, character design, scene planning
- **Video Generation** - Image-to-video, text-to-video, video editing
- **Audio Synthesis** - TTS voice synthesis, background music generation
- **Workflow Editor** - Visual workflow editor with drag-and-drop node connections
- **Task Management** - Background task queue, progress tracking, scheduled tasks

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
| ![Group QR Code](http://ailive.perseids.cn/upload/assert/wx_group.jpg) | ![Personal QR Code](files/二维码.jpg) |
| Scan to join the group | Scan to add author |

© 2025 ZhiJuTong. All rights reserved.
