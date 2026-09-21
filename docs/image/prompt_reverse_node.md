# 提示词反推节点

## 功能

视频工作流画布新增「提示词反推」节点（添加节点菜单 → 提示词反推）：

1. 图片节点连线到反推节点（输入端口，50px 吸附）；
2. 后端 VL 视觉大模型看图反推出**可直接用于文生图的中文提示词**
   （主体 → 环境 → 艺术风格 → 构图镜头 → 光线色调 → 画质关键词）；
3. 反推成功后**自动在右侧创建一个新的空图片节点**，提示词已填入其提示词框，
   并建立反推节点 → 图片节点的连线；用户点击「生成图片」即可复现类似图片
   （衔接图片节点文生图功能）。

节点上的「反推结果」文本域可编辑，编辑会实时同步到已生成的图片节点提示词；
再次点击「反推提示词」按钮可重新反推，结果更新到既有图片节点（不重复建节点）。
图片节点被删除后再反推会重新创建。

节点上提供「反推模型」下拉，**列表里只显示已配置密钥的 VL 视觉模型**（`supports_vl`），
默认「自动（后端推荐）」由后端按偏好挑选（火山引擎 `doubao-seed-2-0-lite`，
见 `config/constant.py` 的 `IMAGE_DESCRIBE_PREFERRED_*`）；模型列表来自
`GET /api/models`（参考 marketing_agent 的用法），加载失败时下拉保留自动模式。
选中具体模型后，反推请求会把 `model` / `model_id` / `vendor_id` 传给后端；
所选模型被下架/改配后，后端 `pick_vl_model` 自动降级到其他可用 VL 模型，不报错。

## 数据流

```
图片节点 ──connections──▶ 提示词反推节点 ──自动建线──▶ 空图片节点(prompt=反推结果)
```

- 反推节点 `node.data`：`reversedPrompt`（反推结果）、`generatedImageNodeId`
  （生成的图片节点 id）、`lastError`（失败原因持久化，重载恢复显示）、
  `reverseModelName` / `reverseModelId` / `reverseVendorId`（反推模型选择，
  全空 = 自动模式；重载按 model_id + vendor_id 双键回填，模型不在列表则回落自动）。
- 工作流重载：回填文本域/源图缩略图/失败原因/模型选择，**不自动重新反推**（重连或点按钮触发）。

## 后端

复用 `POST /api/video-workflow/describe-image`，新增可选字段：

```json
{ "image_url": "...", "purpose": "image_prompt" }
```

- `purpose`（默认 `panorama`，存量全景节点行为不变）：
  - `panorama`：360 全景环境场景描述（原有系统提示词）；
  - `image_prompt`：文生图提示词反推（新系统提示词，输出 60~150 字关键词组合）；
  - 未知值回落默认。
- 可选字段 `model` / `model_id` / `vendor_id`：提示词反推节点选中具体模型时回传，
  `services/vl_gateway.pick_vl_model` 按精确名称（可按 vendor 过滤）挑选；未传或
  模型已下架时按偏好降级（含偏好名匹配 → 第一个可用 VL 模型）。
- `services/image_describe.py`：`describe_image(..., purpose=...)` 按用途选择
  `(system_prompt, user_text)`，其余链路（模型挑选 / 图片压缩 / VL 调用 /
  token 计费 / 清洗截断）不变，全异步非阻塞。

## 关键文件

- `web/js/prompt_reverse_node.js`：节点实现（注册 `prompt_reverse` 类型 +
  输入端口注册表，连线后自动反推）。
- `web/video_workflow.html`：添加节点菜单项 + 脚本引入。
- `web/js/events.js`：菜单点击 → 创建节点并进入放置模式。
- `server.py` / `services/image_describe.py`：`purpose` 参数扩展 + `model` /
  `model_id` / `vendor_id` 可选字段。
- `tests/services/test_image_describe.py`：purpose 选择/回落单测。
- `web/tests/prompt_reverse_model_select.test.js`：模型下拉仅 VL 过滤、请求体回传、
  重载恢复/降级回落的行为层 + 源码断言。

## 人工测试要点

1. 新建提示词反推节点，从有图的图片节点拖线 → 自动反推，右侧出现填好提示词的图片节点。
2. 编辑反推结果文本域 → 图片节点提示词同步变化。
3. 源图片节点换图后再点「反推提示词」→ 结果更新到同一图片节点。
4. 连接无图的图片节点 → 显示占位提示，不报错；图片生成后点按钮可反推。
5. 删除生成的图片节点 → 再反推会新建节点。
6. 保存刷新工作流 → 反推结果与连线正确复原，不触发重复反推。
7. 「反推模型」下拉 → 只看到 VL 视觉模型（非 VL 模型不出现）；默认「自动」时
   反推行为与旧版一致。
8. 选择具体模型后反推 → 走所选模型；保存刷新 → 模型选择复原。
9. 选择模型后运营将其下架 → 再反推自动降级到其他可用 VL 模型，不报错。
