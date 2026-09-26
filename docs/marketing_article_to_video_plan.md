# 图文链接转营销视频（公众号 → 脚本确认 → Seedance 2.0 系列出片）设计方案

> 状态：设计稿 v5（待评审）。
> - v3：小红书主方案改第三方付费 API（TikHub 主选）+ 供应商抽象。
> - v4（本期实施范围）：**仅实现公众号抓取**；小红书只保留 `XhsProvider` 抓取抽象接口（不写实现，供应商对接留待下期）；Seedance **2.5 纳入白名单**（默认模型）；新增 §4.5 抓取成功后的端到端详细操作流程。
> - v5：图文转视频**新建独立 skill `article-to-video`**（§4.3）；**时长由大模型按内容决定**——2.0 系 5–15s，seedance_2.5 可延长至 30s（§4.3 时长决定规则）。
> - 均附 2026-09-26 真机实测/调研结论。
> 分支：develop_f925（基于 origin/develop 4a9dd118）
> 关联：`docs/marketing_agent.md`、`enterprise/skills/marketing-video/SKILL.md`、`docs/backend/agent_autonomy_level.md`

## 1. 背景与目标

用户在营销智能体中粘贴一条**微信公众号文章**链接（本期范围；小红书下期接入，本期仅预留抽象接口），系统自动：

1. 抓取图文内容（正文 + 图片，图片转存到本系统存储）；
2. 交给营销智能体，基于图文内容生成**视频脚本**（含分镜 prompt、画幅、时长、参考图选择）；
3. **用户确认脚本后**才提交视频生成；
4. 视频生成**仅允许 Seedance 2.0 系列**模型：seedance_2_0（默认推荐用 2.5）、seedance_2_0_fast、seedance_2_0_mini、**seedance_2_5**。

不做的事：不做批量爬取、不做搜索/推荐流抓取、不破解小红书签名算法、不绕过任何登录/风控机制。

## 2. 总体流程

```
用户（营销智能体对话框，session_type=2）
  │ 粘贴小红书/公众号链接
  ▼
Marketing PM ── call_agent ──▶ Marketing Video 专家（marketing expert）
                                 │ 工具 fetch_article_content(url)
                                 ▼
                       services/article_fetch（新增，主仓）
                       ├─ 公众号：curl_cffi AsyncSession GET + BeautifulSoup 解析（免登录）✅ 本期实现
                       └─ 小红书：XhsProvider 抽象接口（本期不实现，预留）
                                 │ 图片转存 upload/ + media_file_mapping 注册
                                 ▼
                       ArticleContent（统一中间结构）注入会话上下文
                                 │
                                 ▼
                       生成视频脚本：标题 / 画幅 / 时长 / 分镜 prompt / 参考图选择
                                 │
                                 ▼
                       ask_user：脚本确认卡片（用户可修改后确认）        ← 第一道确认
                                 │ 用户确认
                                 ▼
                       generate_marketing_video（新包装工具，企业仓）
                       · task_type 白名单强制锁定 Seedance 2.0 系列
                       · 图生视频：image_mode=multi_reference + 抓取图片
                                 ▼
                       /api/ai-app-run(-image) → ai_tools + tasks 异步队列
                                 ▼
                       前端轮询 /api/get-status/{project_id}（现有机制）
```

双重确认保障：脚本确认走 `AskUserMixin.ask_user`（Agent 主动询问）；即使脚本被确认，视频提交仍会经过现有高算力硬门 `ExpertAgent._gate_computing_power`（`script_writer_core/agents/power_confirm.py`）二次拦截。

## 3. 抓取子系统（主仓新增）

### 3.1 模块结构

```
services/article_fetch/
├── __init__.py          # fetch_article(url) 入口，按域名分发（白名单校验、限流）
├── models.py            # ArticleContent 数据结构
├── wechat_fetcher.py    # 公众号（curl_cffi 自研，免登录）——本期实现
├── xhs_fetcher.py       # 小红书分发骨架（按 XHS_DATA_PROVIDER 选 provider，未配置即关闭）——本期实现
├── providers/
│   └── base.py          # XhsProvider 协议： async fetch(url) -> ArticleContent ——本期唯一交付
│   # tikhub.py / rnote.py / self_cookie.py —— 下期实现（对接结论已存档）
└── image_store.py       # 图片下载 + 转存 + media_file_mapping 注册——本期实现
```

### 3.2 统一中间结构 `ArticleContent`

```python
@dataclass
class ArticleContent:
    source_type: str          # "wechat" | "xiaohongshu"
    source_url: str
    title: str
    author: str               # 公众号名 / 小红书作者昵称
    text: str                 # 纯文本正文（已截断至 ARTICLE_FETCH_MAX_TEXT_CHARS）
    images: list[ArticleImage]  # 本地化后的图片（url=/upload/... 路径）
    fetched_at: datetime

@dataclass
class ArticleImage:
    original_url: str
    local_url: str            # /upload/marketing_fetched/... 本地可访问 URL
```

设计要点：

- **纯文本化**：去掉样式/表情/广告节点，保留段落顺序；小红书保留话题标签（#xxx）——对营销脚本有用。
- **图片转存**：复用 `utils/image_upload_utils.download_url_to_temp` + `utils/media_mapping_util.register_uploaded_file_mapping`，落盘 `upload/marketing_fetched/`，映射策略 `MEDIA_CACHE`（不永久占用存储；被采用为视频素材后由现有素材提升机制接管）。图片数量上限 `ARTICLE_FETCH_MAX_IMAGES`（建议 9，恰好等于 Seedance 2.0 的 `max_multi_ref_images`）。
- **主仓库放置**：抓取是通用能力，放主仓 `services/`（可独立测试、开源版可见）；Agent 工具包装注册在 enterprise（见 §4）。

### 3.3 公众号抓取（免登录，纯 HTTP，已实测可行 ✅）

**2026-09-26 实测结论**（`curl_cffi impersonate=chrome`）：

- 普通文章直接 GET 200，`#activity-name`（标题）、`#js_content`（正文 21 段中文）、`data-src` 图片 8 张全部拿到，无需登录、无签名、无风控拦截。
- 图片域名 `mmbiz.qpic.cn` 服务端直接下载 200（有无 Referer 均可）；为稳妥统一带 `Referer: https://mp.weixin.qq.com/`。
- 个别特殊文章（含外链/受限制内容）返回"微信扫一扫可打开此内容"遮罩页（实测用户示例链接即此类型），普通浏览器打开同样受限。检测到该特征（正文空 + 遮罩文案）→ 返回 `ArticleFetchBlockedError`，Agent 如实告知用户"该文章仅限微信内查看"，引导用户手动复制正文（降级路径）。

实现：`curl_cffi.requests.AsyncSession`（原生异步，符合非阻塞红线）GET → BeautifulSoup 解析正文段落与图片列表 → `image_store.py` 下载转存。依赖新增：`curl_cffi` + `beautifulsoup4` + `lxml`。

### 3.4 小红书抓取（本期仅抽象接口，不实现）

**本期范围**：只落地 `providers/base.py` 的 `XhsProvider` 协议与 `xhs_fetcher.py` 的分发骨架（provider 未配置时返回明确的"功能未开通"错误语义），**不实现任何具体供应商**。`providers/tikhub.py`、`rnote.py`、`self_cookie.py` 留待下期（对接调研结论见 v3 存档：TikHub/Rnote 均 $0.01/次按量计费；自研 curl_cffi+登录 cookie 路线可行但需维护 cookie 池）。

```python
# providers/base.py（本期唯一交付物）
class XhsProvider(Protocol):
    async def fetch(self, url: str) -> ArticleContent: ...
```

- `xhs_fetcher.py` 行为：读 `XHS_DATA_PROVIDER` 环境变量；未配置/值不是已注册实现 → 抛 `ArticleFetchNotSupported`，Agent 侧文案统一为"小红书抓取暂未开通，可直接粘贴笔记文字与图片"。
- 下期接入新供应商 = 新增一个 provider 文件 + 注册，`fetch_article_content` 工具与前端零改动。

### 3.5 新增常量（config/constant.py）

```python
# ── 图文抓取（article_to_video）──
ARTICLE_FETCH_HTTP_TIMEOUT = 20            # 公众号 HTTP 超时（秒）
ARTICLE_FETCH_XHS_TIMEOUT = 30             # 小红书抓取超时（秒，下期 provider 实现启用）
ARTICLE_FETCH_XHS_MIN_INTERVAL = 10        # 同来源两次小红书抓取最小间隔（下期启用）
ARTICLE_FETCH_MAX_IMAGES = 9               # 图片上限（对齐 Seedance 2.0 多参考上限）
ARTICLE_FETCH_MAX_TEXT_CHARS = 8000        # 正文注入 LLM 的最大字符数
ARTICLE_FETCH_IMAGE_MAX_BYTES = 15 * 1024 * 1024
ARTICLE_FETCH_ALLOWED_HOSTS = (...)        # 域名白名单：mp.weixin.qq.com / xiaohongshu.com 系
ARTICLE_FETCH_RATE_LIMIT_PER_USER_HOUR = 10  # 每用户每小时抓取次数上限
```

- URL 白名单校验放在 `fetch_article()` 入口（域名 + 路径模式），短链 `xhslink.com` 需先跟随跳转再校验最终域名。
- 小红书供应商配置（敏感凭据不入代码库）：环境变量 `XHS_DATA_PROVIDER`（`tikhub`/`rnote`/`self_cookie`，缺省未配置=功能关闭）+ `XHS_PROVIDER_API_KEY`（API 供应商）或 `XHS_WEB_SESSION_COOKIES`（自研兜底）。
- 全部自研 HTTP 请求统一走 `curl_cffi`（`impersonate=chrome` 过 TLS 指纹风控；`AsyncSession` 原生异步）。公众号实测普通 requests/httpx 会被 WAF 按 TLS 指纹 302，`curl_cffi` 是唯一轻量可行选择；对第三方供应商的 REST 调用用 `httpx.AsyncClient` 即可（供应商侧无 TLS 指纹校验）。

## 4. 营销智能体集成（enterprise 仓）

### 4.1 新增工具：`fetch_article_content`

- 文件：`enterprise/tools/content_tools.py`，在 `enterprise/__init__.py` 新增 `_register_marketing_content()` 注册（仿 `_register_marketing_video()`，调 `register_enterprise_tool`）。
- 签名（鸭子类型接口，注意 AGENTS.md 红线 13——本工具为新增而非改 `execute_tool` 签名，不涉及）：

```python
async def fetch_article_content(user_id, world_id, auth_token, url: str) -> dict
```

- 返回：`{title, author, text, image_count, images:[{index, url}], source_type}`，图片 URL 为 `/upload/marketing_fetched/...` 本地路径（前端可直接展示）。
- 限流：复用每用户频次常量，超限返回明确错误文案。
- 防捏造：Agent 只能拿到工具返回的真实图片 URL；`image_to_video` 已有 `_validate_real_media_urls` 防伪造，天然闭环。

### 4.2 新增工具：`generate_marketing_video`（Seedance 2.0 系列锁定，含 2.5）

不在通用工具 `generate_text_to_video` / `image_to_video` 上做校验（影响其他链路），而是**新增专用包装工具**，内部复用其实现并强制白名单：

- 文件：`enterprise/tools/marketing_video_tools.py`，在 `_register_marketing_content()` 一并注册。
- 核心约束（v4：Seedance 2.5 纳入白名单并作为默认模型）：

```python
MARKETING_ARTICLE_ALLOWED_TASK_IDS = (
    TaskTypeId.SEEDANCE_2_0_IMAGE_TO_VIDEO,        # 23
    TaskTypeId.SEEDANCE_2_0_FAST_IMAGE_TO_VIDEO,   # 22
    TaskTypeId.SEEDANCE_2_0_MINI_IMAGE_TO_VIDEO,   # 31
    TaskTypeId.SEEDANCE_2_5_IMAGE_TO_VIDEO,        # 36  ← v4 纳入
)
MARKETING_ARTICLE_DEFAULT_TASK_ID = TaskTypeId.SEEDANCE_2_5_IMAGE_TO_VIDEO  # 36
```

- 签名（**逐 clip 调用**：粒度与现有视频工具一致，失败重试、算力门、前端轮询恢复的粒度都清晰；`duration_seconds` **必填**——时长由 LLM 按内容决定，见 §4.3 时长决定规则）：

```python
async def generate_marketing_video(
    user_id, world_id, auth_token,
    prompt: str,                      # 该 clip 的 Seedance 提示词（必填）
    duration_seconds: int,            # 必填：LLM 决定的时长（2.0 系 5–15，2.5 可到 30）
    task_type: int = 36,              # 必须 ∈ 白名单，默认 SEEDANCE_2_5
    ratio: str = "9:16",
    image_urls: Optional[List[str]] = None,   # 参考图（本系统 /upload/ 路径）
    count: int = 1,
) -> dict   # {project_ids: [...], task_type, computing_power_estimate}
```

- 工具内部校验链（任一失败直接返回错误文本给 Agent，不产生任何扣费）：
  1. `task_type ∈ 白名单`，否则返回可用型号清单（含中文名与时长能力区间）；
  2. `duration_seconds` 落在该 task_type 的 `UnifiedTaskConfig` 时长区间（从 `config/unified_config.py` 读取：2.0 系 5–15s、2.5 为 5–30s，不硬编码）；
  3. `image_urls` 非空时逐个校验为本系统真实文件（复用 `video_tools.py::_validate_real_media_urls` / `try_map_url_to_local_file` 防捏造机制）；任意 `/upload/` 路径均允许（用户上传的图同样可用，不限于抓取图）；
  4. `image_urls` 非空 → 走 `image_to_video`（`image_mode="multi_reference"`）；为空 → 走 `generate_text_to_video`。
- 内部最终仍走 `POST /api/ai-app-run` / `/api/ai-app-run-image`，复用现有算力校验、扣费、队列、重试、退款链路。

### 4.3 新建独立 Skill：`article-to-video`（图文转视频专家）

图文转视频**不挂在 marketing-video 下**，新建独立专家 skill 完整承载该功能（抓取 → 脚本 → 确认 → 生成全流程规范都在此 skill 内），与 marketing-video（普通营销视频生成）平级、互不干扰：

| 层 | 文件 | 内容 |
|---|---|---|
| 专家注册 | `script_writer_core/config/agents_config.json` → `expert_agents` 新增 `"article-to-video": {"expert_type": "marketing"}` | 营销 PM（`allowed_expert_types=["marketing"]`）即可 `call_agent("article-to-video", ...)` 委托；无中央代码注册表，纯配置 |
| 开源版 skill | `agents/skills/article-to-video/SKILL.md` | 占位版：角色定位 + 流程描述；`allowed-tools: ["ask_user", "load_sop"]`；标注视频工具为商业版专属（同 marketing-video 开源占位模式） |
| 企业版 skill | `enterprise/skills/article-to-video/SKILL.md` | 完整版：`allowed-tools: ["fetch_article_content", "generate_marketing_video", "get_user_computing_power", "ask_user", "load_sop"]`；四步流程规范、工具调用规则、失败降级文案（`enterprise/skills` 目录已被 `_register_marketing_video()` 注册进 SkillLoader，新文件即生效，无需改 `enterprise/__init__.py`） |
| SOP | `enterprise/sops/sop-article-to-video.md` | 脚本 JSON 模板（§4.4）、Seedance prompt 写法、参考图选择规则、**时长决定规则**（见下）、画幅建议 |
| PM 路由 | `agents/skills/marketing-pm/SKILL.md`（主仓） | 补充路由：用户贴公众号/小红书链接、或要求"图文转视频"→ 委托 `article-to-video` 专家；开源版无工具时引导用户粘贴文字 |

**时长决定规则（写入 SOP 与 skill）**：每个 clip 的时长由大模型根据内容决定，不设固定默认值——

- 2.0 系模型（22/23/31）：**5–15s**；
- seedance_2_5（36，默认）：可延长至 **5–30s**；
- 决策依据：单一动作/氛围镜头取 5–8s；含叙事递进或卖点展示的镜头取 10–15s；2.5 承载多卖点/完整小故事的 clip 可取 15–30s；
- 工具侧按 `UnifiedTaskConfig` 各型号区间硬校验兜底（LLM 越界时返回区间让模型自纠，不静默改值）。

### 4.4 脚本结构（确认卡片内容）

```json
{
  "type": "article_to_video_script",
  "source": {"source_type": "wechat", "url": "https://mp.weixin.qq.com/s/xxx", "title": "原文标题"},
  "video_title": "视频标题",
  "ratio": "9:16",
  "overall_style": "整体风格/氛围一句话",
  "clips": [
    {
      "index": 1,
      "duration_seconds": 12,
      "task_type": 36,
      "task_type_name": "seedance_2_5",
      "mode": "image_to_video",
      "reference_images": [
        {"index": 0, "url": "/upload/marketing_fetched/xxx.jpg"}
      ],
      "prompt": "Seedance 分镜 prompt……",
      "negative_prompt": "可选"
    }
  ],
  "notes": "旁白/BGM/字幕建议（不参与生成，仅展示）"
}
```

- `type` 字段是前端识别标记：`ask_user` 消息内含 `type=article_to_video_script` 的 JSON 代码块时，渲染为结构化脚本卡片（见 §4.5 步骤 3）。
- `duration_seconds` 由 LLM 按内容决定（§4.3 时长决定规则）：2.0 系 5–15s、2.5 可到 30s，示例中的 12 仅为示意。
- 单条图文默认产出 1 个 clip，图文内容多时最多 3 个 clip（常量 `MARKETING_ARTICLE_MAX_CLIPS`），避免一次确认消耗过多算力。
- `mode=image_to_video` 时 `reference_images` 指向抓取图片（转存后的 `/upload/marketing_fetched/` 本地路径）——让模型参考原图风格/主体；纯文生模式用于图文仅文字的场景。
- Seedance 2.5（36）为默认 `task_type`：时长区间最大（5–30s）、参考图上限 30 张，营销叙事最合适；用户可在确认卡片要求换 2.0/2.0fast/2.0mini。

### 4.5 抓取成功后的端到端操作流程（详细）

> 责任方标注：【Agent】= LLM 自主行为；【后端】= Python 工具/服务代码；【前端】= marketing_agent.js；【系统】= 现有基础设施自动行为。

```
步骤1 抓取完成，内容注入会话
─────────────────────────────────────────────
【后端】fetch_article_content 返回 JSON：
  {source_type, source_url, title, author,
   text(≤8000字), images:[{index, url}](≤9张, /upload/marketing_fetched/)}
        │ 作为 tool result 进入 Agent 上下文
        ▼
【前端】SSE 已有的 tool-call 卡片流式展示
  抓取完成 → 渲染"图文素材卡"：标题、作者、
  正文摘要（前200字）、图片九宫格缩略图
  （缩略图直接 <img src="/upload/...">，本地路径无需鉴权拼接）
        │
        ▼
步骤2 脚本生成（纯 LLM 推理，无工具调用）
─────────────────────────────────────────────
【Agent】按 sop-article-to-video.md 生成 §4.4 结构的脚本 JSON：
  · 提炼原文核心卖点/场景/情绪 → 转写为 1~3 个 clip
  · 每个 clip 的 prompt 按 Seedance 写法（主体+场景+动作+镜头+光影）
  · 时长由 Agent 按内容决定：单一动作/氛围镜头 5~8s，
    叙事递进/卖点展示 10~15s；2.5 承载完整小故事可到 30s
    （约束：2.0 系 5~15s，2.5 5~30s，工具侧区间校验兜底）
  · mode=image_to_video 时从 images 里挑 1~3 张做 reference_images
  · 默认 task_type=36(seedance_2_5)、ratio=9:16
        │
        ▼
步骤3 脚本确认（ask_user，第一道确认）
─────────────────────────────────────────────
【Agent】调用 ask_user 工具：
  question = "请确认以下视频脚本：" + ```json(脚本全文)```
  options = [确认生成 / 修改脚本 / 取消]
        │ AskUserMixin 现有机制：任务挂起等待回答
        ▼
【前端】检测 question 中的 type=article_to_video_script JSON
  → 渲染结构化"脚本确认卡"（不再显示原始 JSON 文本）：
  ┌──────────────────────────────────┐
  │ 视频标题（来源：公众号文章标题）        │
  │ 画幅 9:16 · 共2段 · seedance_2_5    │
  │ ┌ Clip 1 · 12s · 图生视频 ────────┐ │
  │ │ 参考图 [缩略图][缩略图]           │ │
  │ │ prompt 全文（secureRender 渲染） │ │
  │ └────────────────────────────────┘ │
  │ ┌ Clip 2 …… ─────────────────────┐ │
  │ [✓ 确认生成] [✎ 修改脚本] [取消]     │
  └──────────────────────────────────┘
  · 确认生成 → 回答 "confirm"（作为 ask_user 结果返回）
  · 修改脚本 → 用户文本输入修改意见 → 【Agent】修订脚本
    → 再次 ask_user（循环直至确认/取消，无次数上限）
  · 取消 → 回答 "cancel" → 【Agent】终止流程，不产生任何费用
        │ 用户点了"确认生成"
        ▼
步骤4 提交视频生成（逐 clip）
─────────────────────────────────────────────
【Agent】对每个 clip 调用一次 generate_marketing_video：
  prompt=clip.prompt, task_type=clip.task_type,
  ratio, duration_seconds, image_urls=参考图 url 列表
        │
        ▼
【后端】工具校验链（§4.2）：白名单→时长区间→图片真实存在
  → 内部复用 generate_text_to_video / image_to_video
  → POST /api/ai-app-run(-image)
        │
        ▼
【系统】高算力硬门（第二道确认，现有自动机制）：
  ExpertAgent._gate_computing_power 估算扣费 → 前端弹
  "预计消耗 N 算力"确认框 → 用户再点一次确认才真正提交
  （若脚本确认时用户已知费用，此门仅展示不阻断——见 autonomy 配置）
        │
        ▼
【系统】ai_tools(PENDING) + tasks(QUEUED) 入队
  → scheduler 每5秒拉取 → Seedance driver 提交火山/网关
  → 返回 project_ids 给 Agent
        │
        ▼
步骤5 轮询与结果
─────────────────────────────────────────────
【Agent】输出"已提交 N 条视频生成中：预计3~5分钟"（现有文案规范）
【前端】sessionTaskRegistry 现有机制轮询 /api/get-status/{project_id}：
  · 生成中 → 进度卡片（现有样式）
  · 成功 → 视频卡片内嵌会话（可预览/下载）
  · 失败 → 现有重试/退款机制接管；失败卡片提示
    用户可让 Agent"重新生成第2段"（Agent 只重提该 clip）
【前端】页面刷新恢复：__PENDING_TASK__ 机制已覆盖，
  提交过的 project_ids 刷新后自动恢复轮询（零新增代码）
```

边界情况约定：

| 情况 | 行为 |
|---|---|
| 用户在 ask_user 挂起期间关闭页面 | ask_user 状态持久化在 agent_tasks，重新打开会话恢复问题卡片（现有机制） |
| 用户改脚本后再次确认 | 以最后一次确认的脚本为准，Agent 按最终版提交 |
| 部分 clip 提交成功、后续 clip 校验失败 | Agent 停止提交剩余 clip，如实告知已提交数与失败原因；已提交的不回滚（用户可取消？——否，视频生成无法撤回，走生成后不满意的重新生成） |
| 脚本里 task_type 被用户改成非白名单 | 工具校验链拦截并返回可选型号，Agent 自动改回默认 36 重试一次 |
| 同一会话反复抓取同一 URL | 每次真实抓取（P0 不做缓存）；限流兜底 |
| 用户贴的是小红书链接（本期未开通） | `ArticleFetchNotSupported` → Agent 文案"小红书抓取暂未开通，可粘贴笔记文字与图片"，粘贴的图片走现有 `/upload-agent-image` 上传通道进入素材 |

## 5. 前端（marketing_agent 页）

改动集中在 `web/js/marketing_agent.js`（+ 必要的独立 css/js 文件，遵守 AGENTS.md 第 3 条）。交互细节已在 §4.5 时序图中标注，此处列改动点：

1. **零门槛入口**：不做新页面。用户在现有对话框直接粘贴链接；消息渲染时检测白名单域名，给链接加"图文转视频"标签徽标（提示用户直接发送即可）。
2. **图文素材卡**：`fetch_article_content` 完成后渲染标题/作者/正文摘要/图片九宫格（本地 `/upload/marketing_fetched/` 路径直接预览）。
3. **脚本确认卡片**（唯一新增组件）：`ask_user` 消息内检测 `type=article_to_video_script` JSON → 渲染结构化卡片（§4.5 步骤 3 样式），按钮【确认生成】【修改脚本】【取消】分别回复 `confirm`/修改意见/`cancel`。XSS 防线：prompt 与原文内容渲染必须走 `window.secureRenderMarkdown` / `escapeHtml`（AGENTS.md 红线 14）。
4. **生成与轮询**：`project_ids` 返回后复用现有 `sessionTaskRegistry` 轮询 `/api/get-status/{id}` 与 `__PENDING_TASK__` 刷新恢复机制，无新增状态代码。

## 6. 数据与存储

- **P0 不新增表**：抓取图片 → `upload/marketing_fetched/` + `media_file_mapping`（策略 `MEDIA_CACHE`）；正文/脚本 → Agent 会话消息记录（现有表）。无 alembic 迁移。
- **P2 可选**：`marketing_fetch_history` 表（source_url、source_type、user_id、状态、错误、耗时），用于防重复抓取缓存（同一 URL 短期内直接复用）与运营审计。若实装，用 `python scripts/new_migration.py <描述>` 生成 `no_<N>_<YYYYMMDD>_<描述>.py`，并同步 `model/` 文件末尾 SQL。

## 7. 非阻塞与兼容性（红线对照）

| 红线 | 措施 |
|---|---|
| 1 非阻塞接口 | 公众号抓取用 `curl_cffi.requests.AsyncSession`（原生异步）；对第三方供应商的 REST 调用（下期）用 `httpx.AsyncClient`；禁止 requests/httpx 同步客户端出现在异步函数中；图片下载同样走异步客户端 |
| 9 Future 超时 | 所有 HTTP 调用显式 timeout 常量（§3.5）；如引入线程池包装一律带 `timeout=` |
| 10 同步包装异步 | 不引入 `with ThreadPoolExecutor()` 包装；图片处理（Pillow 压缩等同步 CPU 操作）走 `asyncio.to_thread` 且协程内 `try/finally` 清理临时文件 |
| 11 函数内 import | 所有 import 置于模块顶部 |
| 6 三系统兼容 | 路径用 `pathlib`/`os.path`；`curl_cffi` 是纯 pip 依赖（自带 curl-impersonate 二进制），无浏览器/系统组件，三系统零额外部署；UTF-8 显式编码 |
| 14 前端安全 | 脚本/图文内容渲染走 secureRenderMarkdown/escapeHtml；认证走 Authorization 头 |

## 8. 实施计划

| 阶段 | 内容 | 仓库 | 预估 |
|---|---|---|---|
| P1-1 | `services/article_fetch` 公众号抓取 + `providers/base.py` 小红书抽象接口（不实现）+ 常量 + requirements（`curl_cffi`/`beautifulsoup4`/`lxml`）+ 单测（域名白名单、限流、失败语义、公众号真实链接） | 主仓 | 2 天 |
| P1-2 | `fetch_article_content` / `generate_marketing_video` 企业工具（含白名单 22/23/31/36、时长区间校验）+ 注册 | enterprise | 1 天 |
| P1-3 | 新建 `article-to-video` skill：`agents_config.json` 注册（expert_type=marketing）+ 开源占位 SKILL.md + 企业版 SKILL.md（工具规范+四步流程+时长规则）+ `sop-article-to-video.md` + marketing-pm 路由更新 | 双仓 | 1 天 |
| P1-4 | 前端：链接徽标、图文素材卡、脚本确认卡片（§4.5 步骤 3）、secureRender 渲染 | 主仓 | 2 天 |
| P1-5 | 端到端联调（真实公众号链接 → 脚本 → 确认 → seedance_2_5 出片）+ 文档转正（`docs/marketing_agent.md` 增补） | 双仓 | 1 天 |

**下期预留**（本期不做）：小红书 provider 实现（TikHub 对接约 0.5 天含验证）、P2 `marketing_fetch_history` 抓取缓存表。

## 9. 风险与待确认项

| # | 风险/问题 | 应对 |
|---|---|---|
| 1 | 公众号特殊文章"仅微信内查看"遮罩 | 已实测覆盖：检测特征 → `ArticleFetchBlockedError` → 引导用户粘贴正文（降级路径） |
| 2 | 公众号抓取被风控（同一出口 IP 高频） | 每用户限流 + 单条抓取；实测正常频率无风控；出现"环境异常"页特征时报错降级 |
| 3 | Seedance 白名单（22/23/31/36）的能力差异导致脚本参数越界 | 工具校验链按 `UnifiedTaskConfig` 动态校验时长/参考图数，越界返回能力区间让 Agent 自行修正 |
| 4 | 抓取内容版权 | 前端与确认卡片附提示：用户需确保对所用图文拥有合法权利；服务端仅处理用户主动提交的单条公开内容 |
| 5 | 长图文 token 超限 | `ARTICLE_FETCH_MAX_TEXT_CHARS` 截断 + 摘要化；图片只注入清单（索引+URL+简介），原图不进 LLM 上下文 |
| 6 | 下期小红书接入 | 抽象接口本期定型（`XhsProvider` 协议 + 错误语义），接入供应商时工具/前端零改动；调研结论已存档于 git 历史（v3 版本本文档） |

## 10. 待用户决策

1. 单条图文默认出 1 条视频（时长由 LLM 按内容决定：2.0 系 5–15s、2.5 最长 30s）、最多 3 条，是否符合预期？
2. 画幅默认 9:16 竖屏是否符合投放渠道（视频号/小红书/抖音）？
3. P2 的 `marketing_fetch_history` 表（同 URL 缓存复用省重复抓取 + 审计）下期是否需要？
