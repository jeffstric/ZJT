# 🎬 ZhiJuTong - AI Short Drama Production Platform

> Collaborate with AI agents to generate professional short dramas in minutes
> All-in-one solution: Script Creation → Storyboard Generation → Video Synthesis

![ZhiJuTong](files/广告图.png)

English | [中文](README.md) | [Live Demo](http://ailive.perseids.cn) | [Full Tutorial](https://bq3mlz1jiae.feishu.cn/wiki/W1h2wCK3mi1CgDk36LEcVqggnLe)

---

## ✨ Core Features

| 🤖 Multi-Agent Collaboration | 🎨 Professional Storyboarding | 📹 One-Click Drama Generation | 🌍 Multi-Model Support |
|:---:|:---:|:---:|:---:|
| 8 expert agents working in concert, ask_user tool enables agent-user interaction | Infinite canvas + multi-panel storyboard design | Auto script→storyboard→video generation | 10+ LLMs with flexible switching |

| 👥 Unlimited Team Collaboration | 💰 Flexible Computing Power Management | 🔒 Enterprise-Grade Stability | 📦 Ready-to-Use |
|:---:|:---:|:---:|:---:|
| Browser-based collaboration, LAN & public network support | User-level accounts with independent billing | Full API unit tests, production-verified | Built-in image hosting, prompt library, TTS |

| 🖥️ Cross-Platform Support | 🐳 Docker Deployment | 🧪 Complete Test Coverage | 🎓 Education-Ready |
|:---:|:---:|:---:|:---:|
| Windows / Linux / macOS native support | Container deployment | Full API tests, production-ready | User-level billing, cost-transparent |

---

## 🚀 Quick Start

### Try Online (No Installation) ✨
👉 **[ailive.perseids.cn](http://ailive.perseids.cn)** - Full features demo (no setup or installation required)

---

### Windows Users (Recommended) ⭐

📥 **Download the latest "Click-to-Start.exe" from GitHub Release page**
👉 [github.com/jeffstric/ZJT/releases](https://github.com/jeffstric/ZJT/releases)

```bash
# 1. Download pre-built executable
Get the latest "Click-to-Start.exe" from Release page

# 2. Double-click to run (one-click startup)
Click-to-Start.exe

# 3. Wait for startup
✅ System tray icon shows status
✅ Browser opens automatically
✅ Access http://localhost:9003/

# 4. Right-click menu
Open Browser | View Logs | Exit
```

### macOS Users (Recommended) ⭐

📥 **Download the latest compressed package from GitHub Release page and extract it**
👉 [github.com/jeffstric/ZJT/releases](https://github.com/jeffstric/ZJT/releases)

```bash
# 1. Extract the downloaded file
unzip ZJT-mac.zip
cd ZJT

# 2. Double-click startup script (one-click startup)
open start.command

# Or start via command line
bash start.command

# 3. Wait for startup to complete
✅ Browser opens automatically
✅ Access http://localhost:9003/

# Stop the service
bash stop.command
```

📖 **Detailed configuration**: See [docs/README.md](docs/README.md)

### Linux Users
```bash
# 1. Clone the repository
git clone https://github.com/jeffstric/zjt
cd zjt

# 2. Install dependencies
uv sync

# 3. Start the service
python3 scripts/running/run_prod.py

# 4. Open in browser
http://localhost:9003/
```

### Docker Deployment (Recommended for Servers) 🐳
```bash
# 1. Navigate to Docker directory
cd docker

# 2. Start containers
docker-compose up -d

# 3. View logs
docker-compose logs -f

# 4. Access application
http://localhost:9003/

# Common commands
docker-compose down           # Stop services
docker-compose build          # Rebuild images
docker-compose exec app bash  # Enter container
```

### Developer Setup
```bash
# 1. Set development environment
export comfyui_env="dev"
uv sync

# 2. Start development server
python3 scripts/running/run_dev.py

# 3. View DEBUG logs
http://localhost:9003/admin.html
```

---

## 🚀 Core Innovations

### 1️⃣ Real-Time Team Collaboration (Zero-Latency Teamwork)

![Infinite Canvas](files/无限画布.png)

ZhiJuTong **breaks the traditional single-creator model** with true team collaboration:

- **Browser-based real-time editing** - No plugins needed. Multiple team members edit scripts, storyboards, and character profiles simultaneously
- **Simple permission management** - Two-tier system: admin and regular user
- **LAN + Public network support** - Works for local team collab and global remote production
- **Real-time sync** - WebSocket + SSE dual-channel sync with millisecond latency, no conflicts
- **Complete workflow**: Script Agent → Infinite Canvas → Storyboard Draft

**Scenario**: 5-person content team (writer, art director, producer) edit simultaneously while AI Agent generates storyboards in parallel → **300%+ efficiency gain**

---

### 2️⃣ User-Level Independent Compute Accounts (Revolution in EdTech/Team Cost Management)

![Compute Management](files/算力.png)

**Traditional approach**: Single platform account, all members share, no cost control
**ZhiJuTong approach**: Independent account per user, transparent, flexible, fully managed

**Core capabilities**:

- **Per-user independent accounts** - Each student/member has separate compute quota, zero conflicts
- **Per-user vendor selection** - Multi-vendor redundancy architecture ensures uninterrupted creation, no single point of failure
  - **LLM Model Selection**
    - Premium users: Claude (strong function calling, primary model)
    - Regular users: Qwen (excellent Chinese understanding, cost-effective)
    - Local deployment: Ollama (zero cost, privacy-focused)
  - **Image/Video Generation Vendor Selection**
    - Nano, Banana can flexibly switch between ZhiJuTong Official, Duomi, ComfyUI and other channels
    - Automatic seamless failover when a vendor is down, ensuring continuous creative workflow
- **Admin hot-update capability** - Platform admin can update in real-time:
  - Model configs and pricing
  - Vendor priority
  - User quotas and limits
  - No restart needed, instant effect
- **Platform-level cost management** - Admin sets total budget, auto-tracks spending, precise to cent
- **WeChat Pay integration** - Users self-service top-up, transparent billing

**Use Cases**:
- 📚 **Online Education**: 1000 students × 100¥ quota = fully managed 100k¥ budget
- 🏢 **Corporate Training**: Different departments, different quotas, cost attribution by dept
- 🎨 **Creative Studio**: Team members manage their own budgets, transparency + performance tracking

---

### 🧠 AI Multi-Agent System

![AI Agent](files/智能体生成剧本.png)

ZhiJuTong uses multi-agent architecture: **PM Agent (Project Manager)** + **8 Expert Agents (Specialists)**

#### 8 Expert Agents

| Role | Responsibility | Capabilities |
|------|------|------|
| **Story Writer** | Write script, dialogue | Smart outline, dialogue writing, emotional arc design |
| **Character Creator** | Character setup, traits | Character profiles, backstory, OOC checks |
| **Location Creator** | Scenes, backgrounds, style | Scene design, prop lists, visual style guidance |
| **Plot Analyzer** | Plot, tension, pacing | Three-act structure, tension setup, rhythm optimization |
| **Content Compliance** | Content moderation | Banned word detection, policy compliance, safety checks |
| **Novel Splitter** | Novel adaptation, episode split | Auto episode split, chapter alignment, content decomposition |
| **Character Designer** | Character image design | Consistent character reference images, style unity |
| **Location Designer** | Location, prop design | Scene reference images, prop library building |

#### Agent-User Interaction

Agents support **ask_user tool** for proactive user engagement:
```
Expert: "Designing protagonist... Three directions:"
  1️⃣ Ancient Beauty (elegant, classical)
  2️⃣ Modern Executive (sharp, professional)
  3️⃣ Young Girl (cute, energetic)

User selects → Expert continues → Precise result, no revisions needed
```

---

## 🎯 Complete Production Workflow

### From Script to Final Video - Fully Automated

```
Step 1: Script Creation
  ↓ Input: Story concept, target audience, style preference
  ↓ PM Agent analyzes requirements
  ↓ Story Writer creates outline
  ↓ Output: Complete 5000+ word script

Step 2: Character & Scene Design
  ↓ Parallel execution by agents
  ↓ Character Creator: 8 character profiles
  ↓ Location Creator: 12+ scene descriptions
  ↓ Output: Complete world-building document

Step 3: Content Review & Optimization
  ↓ Content Compliance checks legal/policy compliance
  ↓ Plot Analyzer optimizes pacing
  ↓ Output: Final reviewed script

Step 4: Intelligent Storyboard Generation
  ↓ Auto-split script into 30-60 shots
  ↓ Auto-extract storyboard prompts (scene, action, emotion)
  ↓ Smart match scenes, characters, props
  ↓ Output: Complete storyboard list

Step 5: Storyboard Image Generation
  ↓ Auto 2x2, 3x3 multi-panel layout
  ↓ Character image locking (solves "face collapse")
  ↓ Multi-style support (3D, anime, photorealistic)
  ↓ Output: 80+ consistent reference images

Step 6: Video Synthesis
  ↓ Workflow-driven processing: API orchestration for video generation
  ↓ Support RunningHub, Duomi, Vidu APIs
  ↓ Workflow-driven processing: TTS voice + background music synthesis
  ↓ Output: Complete MP4 short drama
```

> 💡 **Real-World Experience Insight**: Video and audio processing use **workflow-driven processing rather than full automation**, a key decision based on Hongguo platform's production experience. Workflow processing ensures:
> - ✅ Stable and consistent quality of video/audio output
> - ✅ Flexible API switching and fault tolerance
> - ✅ Fine-grained parameter tuning
> - ✅ Better generation controllability

### Automation Comparison

| Traditional Method | ZhiJuTong |
|---------|--------|
| Manual script writing (8-16 hours) | AI script generation (10 min) + ask_user refinement |
| Hand-drawn storyboards (16-24 hours) | Auto storyboard list (5 min) |
| Manual reference images (8-12 hours) | AI-generated 80+ images (15 min) |
| Video & audio synthesis (6-10 hours) | Auto synthesis (30 min) |
| **Total: 38-62 hours** | **Total: 1-2 hours** |

---

## 🎨 Professional Creation Tools

### 1. Infinite Canvas Editor
- Flexible shot arrangement space
- Drag, adjust, organize with ease
- Real-time preview + multi-panel layout
- Professional-grade experience

### 2. Multi-Panel Storyboard Design
- Auto 2x2, 3x3 multi-panel layouts
- Consistency guarantee (same character, same appearance)
- Local editing & refresh support
- Smart optimization, 50%+ compute savings

### 3. Unlimited Team Collaboration
- Browser-based, no installation needed
- LAN & public network remote collaboration
- Real-time sync via WebSocket + SSE
- **Permission management**: Admin and regular user two-tier system

### 4. Flexible Computing Power Management (🎓 Perfect for EdTech)
- **User-Level Independent Accounts** - Each student/user has separate billing, zero conflicts
- **User-Level Vendor Selection** - Multi-vendor redundancy, LLM and image/video generation can be selected independently, ensuring uninterrupted creation
- **Admin Hot-Update Capability** - Platform admin can update in real-time:
  - Model configs and pricing
  - Vendor priority
  - User quotas and limits
  - No restart needed, instant effect
- **WeChat Pay Integration** - Users self-service top-up, transparent billing

**Use Cases**:
- 📚 **Online Education** - Allocate compute budgets per student
- 🏢 **Corporate Training** - Department-level cost management
- 🎨 **Creative Teams** - Individual member billing, transparent costs
- 🚀 **Startup Incubators** - Provide compute support to startups

### 5. Built-In Resource Library
- 500+ curated prompt templates
- Free image hosting with CDN
- TTS service (10+ languages)
- Extensible custom resources

---

## 🔧 Tech Stack & Capabilities

### LLM Multi-Model Support

| Provider | Models | Highlights |
|----------|--------|-----------|
| **Claude** | Claude Haiku, Claude 4.5 | Strong function calling, primary model |
| **Ollama** | Llama 2, Mistral, CodeLlama | Local deployment, zero cost |
| **Alibaba Qwen** | qwen-turbo, qwen-plus | Excellent Chinese understanding |
| **Baidu ERNIE** | ERNIE series | Native Chinese support |
| **More...** | VolcEngine, etc. | Continuously expanding |

### Video Generation APIs

| API | Strength | Use Case |
|-----|----------|----------|
| **RunningHub** | High quality, stable | Professional production |
| **Duomi** | Image-to-video | Reference image to video |
| **Vidu** | Text-to-video + image-to-video | All-in-one solution |

### Core Toolset (50+ Tools)

**Data Management Tools**
- Create/read/update world, characters, scripts, locations, props
- File synchronization & persistence
- Complete version management

**AI Generation Tools**
- Text-to-image (single + multi-panel)
- Character multi-panel generation
- Location/props multi-panel generation
- Reference image upload & prompt engineering

**Interactive Tools**
- `ask_user` - Ask users questions (innovation)
- `get_long_user_input` - Collect user input
- Script diagnostic & optimization

---

## 📊 System Architecture

### Layered Architecture

```
┌─────────────────────────────────────────┐
│         Web UI (Frontend)               │
│  • Script editor                        │
│  • Infinite canvas                      │
│  • Video workflow                       │
│  • Admin dashboard                      │
└─────────────────────────────────────────┘
                      ↓
┌─────────────────────────────────────────┐
│      FastAPI Router (API)               │
│  • /api/session - Session management    │
│  • /api/task - Task management          │
│  • /api/verification - User verification│
│  • /api/world-files - Resource files    │
└─────────────────────────────────────────┘
                      ↓
┌─────────────────────────────────────────┐
│   Business Logic                        │
│  • PM Agent / Expert Agents (LLMs)      │
│  • Task Manager                         │
│  • MCP Tool Executor                    │
│  • SSE Stream (Real-time push)          │
└─────────────────────────────────────────┘
                      ↓
┌─────────────────────────────────────────┐
│      MCP Tools (50+ tools)              │
│  • Data management, AI generation       │
│  • Seamless LLM integration             │
└─────────────────────────────────────────┘
                      ↓
┌─────────────────────────────────────────┐
│    External Services                    │
│  • LLM APIs (Gemini, GPT, etc.)        │
│  • Video APIs (RunningHub, etc.)        │
│  • TTS service                          │
│  • CDN & storage                        │
└─────────────────────────────────────────┘
```

### Real-Time Data Flow

```
User Input → SSE Stream Connect → PM Agent Analysis
  ↓
Expert Agents Execute → Tool Invocations
  ↓
ask_user Query Users (Optional)
  ↓
User Response → SSE Real-time Progress
  ↓
Result Aggregation → Database Persistence
  ↓
Frontend UI Update → Show Final Output
```

---

## 🏆 Technical Highlights

| Feature | Description | Advantage |
|---------|-------------|-----------|
| **Multi-Agent Synergy** | 8 experts vs single AI | Output quality ↑50%, accuracy ↑70% |
| **ask_user Tool** | Agents interact with users | Revision-free rate ↑30% |
| **Real-Time SSE** | Streaming task progress | Perceived time ↓60% |
| **Multi-Model Support** | 10+ LLMs flexible switching | Cost ↓40%, quality ↑ |
| **Auto Storyboarding** | Smart split + prompt filling | Workload ↓80% |
| **Character Locking** | Consistency guarantee | Solves "face collapse" problem |
| **Admin Hot-Update** | Update configs, prices, priorities in real-time | No restart needed, instant effect |
| **Cross-Platform Support** | Windows / Linux / macOS native | One codebase, multiple platforms |
| **Docker Deployment** | Container-ready | Cloud deployment simplified |
| **Complete Test Coverage** | Full API endpoint tests | Core features covered, production-ready |
| **Production-Verified** | Real Hongguo platform deployment | Reliability ⭐⭐⭐⭐⭐ |

---

## 💡 Use Cases

### 📱 Content Creators
- ✅ Generate viral short drama scripts rapidly
- ✅ Refine creative direction via ask_user
- ✅ Auto-generate storyboards & reference images
- ✅ Lower creation barrier and cost

### 👥 Team Collaboration
- ✅ Real-time multi-user editing
- ✅ Permission & version management
- ✅ Transparent workflows
- ✅ LAN & public network support

### 🏢 Enterprise
- ✅ Fast brand video production
- ✅ Auto marketing content generation
- ✅ Cost control (flexible billing)
- ✅ Enterprise-grade reliability

### 🎓 Education & Training (Highly Recommended)
- ✅ **Per-Student Independent Accounts** - Each learner has their own computing credit
- ✅ **User-Level Vendor Selection** - Different classes/learner can flexibly choose providers for cost optimization
- ✅ **Admin Hot-Update** - Institutions can dynamically adjust model configs and prices
- ✅ **Platform Cost Management** - Institutions can set total compute budgets
- ✅ **Creation History & Feedback** - Track student work, enable instructor-student interaction
- ✅ **Cross-Platform Accessibility** - Students create on Windows/Mac/Linux devices
- ✅ **Private Server Deployment** - Institutions can self-host with Docker, data security guaranteed

**Typical Scenarios**:
- High school / University media production courses
- Online creative writing training programs
- Animation / Game design storyboard teaching
- Content creator professional certifications

---

## 📈 Results & Impact

### Battle-Tested
- ✅ Successfully deployed on Hongguo platform
- ✅ Verified stability in real production
- ✅ 30% higher completion rate vs traditional

### Engineering Quality
- ✅ Full API unit test coverage
- ✅ Automated database migrations
- ✅ Complete configuration management
- ✅ Production-grade error handling

---

## 📖 Documentation

### 👤 User Guide
- 📌 [Quick Start Guide](docs/README.md#quick-start)
- 📌 [Full Tutorial](https://bq3mlz1jiae.feishu.cn/wiki/W1h2wCK3mi1CgDk36LEcVqggnLe) (Chinese)
- 📌 [FAQ](docs/README.md#faq)

### 👨‍💻 Developer Guide
- 📌 [Complete Developer Docs](docs/README.md)
- 📌 [Windows Setup Guide](docs/Windows启动开发说明.md)
- 📌 [Database Migration](docs/database_migration.md)
- 📌 [API Documentation](docs/backend/)

### 🏗️ Architecture
- 📌 [Agent Implementation](ExpertAgent_实现总结.md)
- 📌 [Video Workflow Design](docs/video_workflow_feedback.md)
- 📌 [System Configuration](docs/系统配置要求.md)
- 📌 [Permission System](docs/权限系统)

### 🔧 In-Depth Articles
- 📌 [SMS Driver Architecture](docs/短信驱动架构说明.md)
- 📌 [Media Caching Strategy](docs/媒体文件缓存管理方案.md)
- 📌 [Constants Usage](docs/常量使用示例.md)

---

## 📦 License

This project uses a modified Apache License 2.0. See [LICENSE](LICENSE) for details.

### Key Terms
- ✅ **Commercial use allowed**
- ✅ **Modification and distribution allowed**
- ✅ **Private deployment allowed**
- ❌ **Multi-workspace SaaS requires authorization**
- ❌ **Frontend LOGO and copyright must not be removed**

---

## 🤝 Contact & Support

### Get Help
- 📧 **Email**: jeffstricg@gmail.com
- 💬 **GitHub Issues**: [Report bugs / request features](https://github.com/jeffstric/zjt/issues)

### Join Community
| WeChat Group | Personal WeChat |
|:---:|:---:|
| [Group QR Code](http://ailive.perseids.cn/upload/assert/wx_group.jpg) | <img src="files/二维码.jpg" width="200" alt="Personal QR Code"> |
| Scan to join | Add author if group is full |

---

## 🎉 Quick Summary

| Dimension | ZhiJuTong | Traditional |
|-----------|-----------|-------------|
| **Creation Speed** | 1-2 hours | 38-62 hours |
| **Quality** | AI synergy + ask_user | Manual creativity |
| **Skill Required** | Zero barrier | Requires expertise |
| **Setup Difficulty** | One-click (Windows) | Complex config |
| **Cost** | Flexible, controllable | High fixed cost |
| **Stability** | Full API unit test coverage | Manual-dependent |
| **Scalability** | 10+ LLMs + APIs | Single tool |

---

© 2025 ZhiJuTong. All rights reserved.
