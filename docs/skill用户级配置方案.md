# Skill 用户级可编辑方案

## Context

当前 9 个 skill 的 prompt 内容以 `SKILL.md` 文件形式写死在 `script_writer_core/skills/` 目录下。需要让每个用户都能自定义自己的 skill prompt，配置入口放在 `web/index.html` 的 AI工具箱中。

## 核心设计

- **用户级别配置**：每个用户可自定义 skill 的 prompt，未自定义的 skill 回退到文件系统默认值
- **一张表**：`skill_definitions`，通过 `user_id` 区分系统默认和用户自定义
- **SkillLoader 改造**：接受 `user_id` 参数，优先加载用户自定义内容，回退到文件系统
- **UI**：在 AI工具箱中新增"技能配置"卡片，点击进入独立页面，列出所有 skill 并支持编辑

## 实现步骤

### 步骤 1：数据库表

新建 `alembic/versions/20260504_create_skill_definitions.py`：

```sql
CREATE TABLE skill_definitions (
  id int NOT NULL AUTO_INCREMENT,
  user_id int DEFAULT NULL COMMENT '用户ID，NULL=系统默认',
  skill_name varchar(128) NOT NULL COMMENT '技能名称',
  display_name varchar(255) DEFAULT NULL COMMENT '显示名称',
  description varchar(1024) DEFAULT NULL COMMENT '描述',
  prompt_content longtext COMMENT '用户自定义的 prompt 内容',
  created_at datetime DEFAULT CURRENT_TIMESTAMP,
  updated_at datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_user_skill (user_id, skill_name),
  KEY idx_skill_name (skill_name)
) COMMENT='技能定义表（用户级）';
```

**数据分层逻辑**：
- `user_id = NULL` → 系统默认（管理员可通过 admin API 设置，暂不实现）
- `user_id = 具体ID` → 该用户的自定义配置
- 查询优先级：`user_id=X AND skill_name=Y` → 回退到文件系统 `SKILL.md`

### 步骤 2：数据模型

新建 `model/skill_definitions.py`（参照 `model/system_config.py` 模式）：

```python
class SkillDefinitionsModel:
    @staticmethod
    def get_user_skill(user_id: int, skill_name: str) -> Optional[Dict]:
        """获取用户自定义的 skill，不存在返回 None"""

    @staticmethod
    def upsert_user_skill(user_id: int, skill_name: str, prompt_content: str, ...) -> int:
        """创建或更新用户自定义 skill"""

    @staticmethod
    def get_user_all_skills(user_id: int) -> List[Dict]:
        """获取用户所有自定义 skill"""

    @staticmethod
    def delete_user_skill(user_id: int, skill_name: str) -> bool:
        """删除用户自定义 skill（回退到默认）"""
```

### 步骤 3：API 端点

在 `api/script_writer.py` 中新增（用户级接口，非 admin）：

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/api/skills` | 获取所有 skill 列表（含用户是否自定义标记） |
| GET | `/api/skills/{name}` | 获取单个 skill 详情（优先返回用户自定义，回退文件系统） |
| PUT | `/api/skills/{name}` | 保存用户自定义 prompt |
| DELETE | `/api/skills/{name}` | 删除用户自定义，回退到默认 |

所有接口需要验证用户登录（`auth_token`）。

**GET /api/skills 返回示例**：
```json
{
  "skills": [
    {
      "skill_name": "script-orchestrator",
      "display_name": "剧本架构师",
      "description": "剧本的主要负责人...",
      "has_custom": true,
      "file_size": 54655
    },
    {
      "skill_name": "story-writer",
      "display_name": "故事创作大师",
      "description": "负责根据PM的指示...",
      "has_custom": false,
      "file_size": 31200
    }
  ]
}
```

### 步骤 4：SkillLoader 改造

修改 `script_writer_core/skill_loader.py`：

**关键改动**：构造函数增加 `user_id` 参数，加载逻辑增加数据库查询层。

```python
class SkillLoader:
    def __init__(self, skills_dir=None, user_id=None):
        self.user_id = user_id
        # ... 原有初始化 ...
        self._load_all_skills_metadata()

    def get_skill_prompt(self, skill_name: str) -> Optional[str]:
        # 1. 如果有 user_id，优先查用户自定义
        if self.user_id:
            user_skill = self._load_from_db(self.user_id, skill_name)
            if user_skill:
                return user_skill['prompt_content']
        # 2. 回退到文件系统
        return self._load_from_file(skill_name)

    def invalidate_cache(self, skill_name=None):
        """清除缓存（供 API 调用）"""
```

**3 处调用方需要传入 user_id**：
- `pm_agent.py:40` → `SkillLoader(user_id=user_id)` （已有 user_id 参数）
- `expert_agent.py:44` → `SkillLoader(user_id=user_id)` （已有 user_id 参数）
- `mcp_tool.py:74` → 全局单例暂不传 user_id（MCP 工具场景不涉及用户自定义）

### 步骤 5：前端 UI

在 `web/index.html` 的 AI工具箱网格中新增卡片，作为新路由页面。

**5.1 新增工具卡片**（AI工具箱网格中）：
```html
<div class="tool-card" @click="$router.push({name:'skill-config'})">
  <div class="tool-card-icon teal">⚙️</div>
  <div class="tool-card-info">
    <div class="tool-card-title">技能配置</div>
    <div class="tool-card-desc">自定义 AI 专家的能力</div>
  </div>
</div>
```

**5.2 新增 SkillConfig Vue 组件**（新路由页面）：

页面结构：
```
┌──────────────────────────────────────────┐
│ ← 返回     技能配置                       │
├──────────────────────────────────────────┤
│ 自定义 AI 专家的工作方式，修改将影响你      │
│ 后续的所有剧本创作。未配置的技能使用默认值。  │
├──────────────────────────────────────────┤
│ ┌────────────────────────────────────┐   │
│ │ 📋 script-orchestrator  剧本架构师  │   │
│ │    剧本的主要负责人...               │   │
│ │    ✅ 已自定义    [编辑] [重置]      │   │
│ └────────────────────────────────────┘   │
│ ┌────────────────────────────────────┐   │
│ │ 📝 story-writer  故事创作大师       │   │
│ │    负责根据PM的指示...              │   │
│ │    默认配置       [编辑]            │   │
│ └────────────────────────────────────┘   │
│ ...更多 skill 卡片...                    │
└──────────────────────────────────────────┘
```

**5.3 编辑弹窗**（大弹窗，因为 prompt 可能很大）：

```
┌──────────────────────────────────────────┐
│ 编辑技能 - story-writer          [关闭 X] │
├──────────────────────────────────────────┤
│ 描述: 故事创作大师，负责根据PM的指示...    │
│                                          │
│ ┌──────────────────────────────────────┐ │
│ │ # 角色定位                            │ │
│ │ 你是一位资深的剧本创作大师...           │ │
│ │ ...                                  │ │
│ │ (textarea, 等宽字体, min-height 500px)│ │
│ └──────────────────────────────────────┘ │
│ 共 31200 字符                             │
│                                          │
│          [恢复默认]  [保存]               │
└──────────────────────────────────────────┘
```

**5.4 新增路由**：
```javascript
{ path: '/skill-config', name: 'skill-config', component: SkillConfig }
```

### 步骤 6：样式

在 `web/css/index.css` 中追加技能配置页面的样式（复用现有的 tool-card、modal 样式）。

## 关键文件清单

| 文件 | 操作 |
|------|------|
| `alembic/versions/20260504_create_skill_definitions.py` | 新建 - 迁移脚本 |
| `model/skill_definitions.py` | 新建 - 数据模型 |
| `script_writer_core/skill_loader.py` | 改造 - 增加 user_id + DB 查询 |
| `api/script_writer.py` | 追加 - 4 个 skill API 端点 |
| `web/index.html` | 修改 - AI工具箱卡片 + SkillConfig 组件 + 路由 |
| `web/css/index.css` | 追加 - 技能配置页面样式 |

## 验证方式

1. `alembic upgrade head` 建表
2. 访问首页 → AI工具箱 → 点击"技能配置"卡片
3. 看到 skill 列表（含剧本/营销等专家 skill，以及 `script-parser` 剧本解析 system prompt），未改的显示"默认配置"
4. 点击某个 skill 的"编辑"，修改 prompt 保存
5. 该 skill 显示"已自定义"标记
6. 进入剧本创作页面发起新会话，验证使用了用户自定义的 prompt；修改 `script-parser` 后发起分镜拆分，验证 system prompt 已生效
7. 点击"重置"删除自定义，验证回退到默认 prompt

## 补充：script-parser（非 Agent 专家 skill）

| 项 | 说明 |
|----|------|
| 路径 | `script_writer_core/skills/script-parser/SKILL.md` |
| 用途 | 仅承载 `parse_script_to_shots` 的 **system prompt**（纯静态规则） |
| 消费方 | `llm/script_parser.get_script_parser_system_prompt(user_id)` |
| 与专家 skill 差异 | 不走 MCP `skill` 工具加载；拆分链路直接读 skill 文本作为 LLM system 消息 |
| 未纳入 | user prompt、条件块、QC/分段动态上下文仍由代码拼装 |
