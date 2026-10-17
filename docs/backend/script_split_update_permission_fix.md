# 剧本拆分智能体缺少"编辑剧本"工具权限修复

## 背景

用户反馈：`web/script_writer.html` 的剧本智能体在执行"拆分小说/剧本"工作流时，当已存在同集数剧本、内容有差异且用户选择"覆盖为新版本"后，拆分智能体（`novel-episode-splitter`）无法完成覆盖，拆分流程卡死或报错。

## 根因分析

权限链路上的三处事实叠加导致"覆盖"路径必然失败：

| 环节 | 位置 | 事实 |
|------|------|------|
| **权限配置** | `script_writer_core/config/agents_config.json` | `novel-episode-splitter.allowed_tools` 只有 `create_script_json`，**没有 `update_script_json`** |
| **权限执行** | `script_writer_core/agents/expert_agent.py` `_execute_tool` | 调用不在 `allowed_tools` 中的工具直接返回 `{"error": "工具 xxx 不在允许列表中"}` |
| **创建即冲突** | `script_writer_core/mcp_tool.py` `create_script_json` | 集数已存在时返回"集数冲突"错误，**不能**用作覆盖 |

也就是说：SKILL 第四步要求"用户选择覆盖为新版本时执行覆盖"，但智能体手里没有任何能执行覆盖的工具——调 `update_script_json` 被权限拦截，调 `create_script_json` 被集数冲突拦截。

## 修复方案

### 修复点 1：补齐权限（根因修复）

**文件**：`script_writer_core/config/agents_config.json`

`novel-episode-splitter.allowed_tools` 增加 `update_script_json`（紧随 `create_script_json`）。

### 修复点 2：SKILL 指引与工具清单对齐

**文件**：`script_writer_core/skills/novel-episode-splitter/SKILL.md`

- 第四步 4.2：明确"覆盖为新版本"必须调用 `update_script_json`，并显式禁止用 `create_script_json` 覆盖（会报集数冲突）
- 第五步：区分"新建集数用 `create_script_json` / 覆盖集数用 `update_script_json`"
- MCP工具使用说明：补充 `update_script_json` 工具文档；修正 `read_script_json` 参数签名（实际只有 `title`，可传集数数字字符串）；删除不存在的 `get_script_by_episode()` 引用
- frontmatter `allowed-tools`：由泛化的 `Read, Write` 改为真实工具清单（与 `agents_config.json` 一致，该字段当前仅作元数据展示，实际权限以 config 为准）

### 修复点 3：回归测试（漂移防护）

**文件**：`tests/script_writer_core/test_agents_config_tools.py`（新增）

- 校验 `novel-episode-splitter` 具备 `update_script_json` 权限
- 校验所有 script 类智能体 + pm_agent 的 `allowed_tools` 均存在于 `MCP_TOOLS` 注册表或内置工具清单（`ask_user`/`call_agent`/`load_sop`），防止权限配置与工具注册表再次漂移
- 校验 config 中配置的工具能出现在下发给 LLM 的工具定义里

> 注：marketing/admin 类工具由企业版运行期动态注册（`register_enterprise_tool`），不在静态校验范围内，已有 `test_enterprise_tool_dynamic_registry.py` 单独覆盖。

## 涉及文件

| 文件 | 改动 |
|------|------|
| `script_writer_core/config/agents_config.json` | `novel-episode-splitter.allowed_tools` 增加 `update_script_json` |
| `script_writer_core/skills/novel-episode-splitter/SKILL.md` | 覆盖流程绑定 `update_script_json`；工具清单与签名修正 |
| `tests/script_writer_core/test_agents_config_tools.py` | 新增权限一致性回归测试 |
