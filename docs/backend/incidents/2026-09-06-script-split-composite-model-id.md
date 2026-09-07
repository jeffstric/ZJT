# 2026-09-06 剧本节点拆分选中本地模型必现 500：复合 model_id 未归一化

## 现象

视频工作流剧本节点拆分模型选择 `qwen3.8:27b`（供应商显示 vllm）后提交拆分，接口直接 500：

```
POST /api/parse-script
{"code": -1, "message": "剧本解析失败: invalid literal for int() with base 10: 'vllm:qwen3.8:27b'"}
```

该下拉中所有 ollama/vllm 本地服务模型均复现（prod 当前唯一可见的本地服务模型即 vllm × qwen3.8:27b）。

## 根因

三层叠加：

1. `/api/models`（`llm_client_factory.get_available_models`）对本地服务供应商（ollama/vllm）下发的 `id` 字段是 `vendor:模型名` 复合串（供 LLMClientFactory 按前缀路由），数值库 ID 在同对象 `model_id` 字段。
2. 剧本节点 `web/js/script_node.js` 的 `appendSplitOption` 写 `data-model-id` 时取 `model.id ?? model.model_id`，优先拿到复合串（对照：故事板 `render.js` 与剧本写作 `script_writer.js` 均为数值优先，故仅剧本节点触发）；`script_split_task.js` 把它原样作为 `model_id` 提交。
3. `server.py` parse_script 在前端已传 `vendor_id=9`（非默认值）时跳过带 try/except 的 vendor 反查分支，随后 request_config 里裸 `int('vllm:qwen3.8:27b')` 抛 ValueError，被接口层 except 包装成 500。

供应商显示为 vllm 本身是正确的：model 1011（qwen3.8:27b）在 vendor_model 表只关联 vendor 9（vllm），且 prod 动态配置 `llm.ollama.enabled=false` / `llm.vllm.enabled=true`（base_url 指向 vLLM 服务，`/v1/models` 确认在跑该模型）。误导来自 model 表 note 文案仍写「Ollama Qwen3.8-27B：…」（同一模型在 Ollama :11434 也有一份 gguf）。

## 修复

- 前端：`appendSplitOption` 改为数值库 ID 优先（`model.model_id ?? model.id`），含 `:` 的值不写入 `data-model-id`；工作流重载按 option.value 恢复选择并重写 `splitModelId`，存量复合串自动纠正。
- 后端：`llm/llm_client_factory.py` 新增 `resolve_composite_model_ref()`（按首个冒号拆分 + vendor/model/vendor_model 三表查库，任一缺失返回 `(None, None)`，拒绝猜测）；`/api/parse-script`（server.py）与故事板 generate-from-script（api/storyboard.py）对非数字 model_id 用 `asyncio.to_thread` 包裹还原，并以解析出的 vendor_id 修正路由；两处 request_config 的 `model_id` 统一为归一化后的数值（无法解析时回退默认 1，与原空值行为一致）。
- 回归测试：`tests/llm/test_resolve_composite_model_ref.py`；文档同步 `docs/backend/vllm_local_model.md`。

## 2026-09-08 后续：归一化收敛为单一实现

评审发现首修只接入了 2 个入口，其余 4 处仍裸 `int(model_id)`（复合串 400/500 行为分叉），且两处已接入入口的 vendor 修正条件不一致（parse-script 用 `vendor==1` 哨兵、发布拆分用 falsy 判断——前端显式回传 vendor_id=1 + 复合串时后者不会用复合串还原的 vendor 修正路由）。收敛：

- `llm/llm_client_factory.py` 新增 `normalize_model_selection_refs(model_id, vendor_id, default_vendor_id=1)`：model_id 数字串直转 / 复合串查库还原；vendor 优先级 = 显式非默认 vendor > 复合串 vendor > 按数值模型反查 > 默认值（显式传默认值 1 与缺省同权，允许被模型实际归属修正——兼容「前端未选择时回传 1」）。同步查库，async 调用方 `asyncio.to_thread` 包裹。
- 接入全部入口：`/api/parse-script`（server.py）、故事板发布拆分与 `scene_ai_chat`（api/storyboard.py，后者原为裸 int 400）。
- 偏好/配置解析类同步路径（`storyboard_agent_cli_service` 的 `_normalize_script_split_model_selection`/`_resolve_split_model_context`、`storyboard_first_frame_grid_service._llm_model_context`、`api/storyboard.py._resolve_storyboard_agent_model`）改用 `coerce_model_id_or_none`：复合串尽力还原、失败返回 None 走默认模型，不再抛 ValueError。

## 遗留

- ~~model 1011 的 note 文案误导~~（已处理）：2026-09-06 按产品决策清除线上库 `model` 表全部 7 行 note（含 model 1011），备份见 `model_note_backup_20260906.json`（未入库）；前端下拉随之只展示模型名。代码读取处均为 `note or ''` 兜底，无需改动。
- 若工作流草稿里存有复合串 `splitModelId` 且模型列表加载失败（走默认 deepseek 选项、不执行恢复逻辑），存量复合串仍会被提交，由后端 `resolve_composite_model_ref` 兜底。
