# 开发调试指南

本文档包含前端 Debug 模式和后端测试模式的完整使用说明。

---

## 一、前端 Debug 模式

### 功能概述

Debug 模式是一个前端调试功能，允许开发人员直接查看节点的完整数据结构，方便排查问题和理解节点状态。

### 启用 Debug 模式

#### 1. 配置密码

在配置文件中设置 Debug 模式密码：

```yaml
# config.yml
frontend:
  debug_password: "your_debug_password"  # 设置你的 Debug 密码
```

默认密码为 `debug123`（在 `config.example.yml` 中定义）。

#### 2. 开启 Debug 模式

通过 URL 参数直接传入密码开启：

```
http://localhost:端口/video_workflow.html?debug=你的密码
```

例如，如果密码是 `debug123`，则访问：

```
http://localhost:端口/video_workflow.html?debug=debug123
```

密码验证通过后，Debug 模式将被激活。

#### 3. 视觉反馈

- 所有节点的标题栏会出现一个 🐛 调试按钮

### 使用 Debug 功能

#### 查看节点信息

1. 确保 Debug 模式已开启
2. 找到需要调试的节点
3. 点击节点标题栏中的 🐛 按钮
4. 节点的完整信息将输出到浏览器控制台

#### 输出内容

点击调试按钮后，控制台会输出以下信息：

- **ID**: 节点的唯一标识符
- **Type**: 节点类型（如 `video`, `image`, `script`, `shot_frame` 等）
- **Title**: 节点标题
- **Position**: 节点在画布上的坐标 `{x, y}`
- **Data**: 节点的完整数据对象（包含所有配置、状态、文件引用等）
- **完整节点对象**: 节点的完整对象引用

#### 查看控制台

在浏览器中打开开发者工具：

- **Chrome/Edge**: 按 `F12` 或 `Ctrl+Shift+I` (Windows/Linux) / `Cmd+Option+I` (Mac)
- **Firefox**: 按 `F12` 或 `Ctrl+Shift+K` (Windows/Linux) / `Cmd+Option+K` (Mac)
- **Safari**: 按 `Cmd+Option+C` (Mac)

切换到 **Console** 标签页查看输出的节点信息。

### 关闭 Debug 模式

刷新页面或移除 URL 中的 `debug` 参数即可关闭 Debug 模式。

### 常见使用场景

#### 1. 排查节点数据问题

当节点行为异常时，可以通过 Debug 模式查看节点的完整数据，检查：
- 数据是否正确保存
- 文件 URL 是否有效
- 配置参数是否符合预期

#### 2. 理解节点结构

开发新功能时，可以查看现有节点的数据结构，了解：
- 节点数据的组织方式
- 不同类型节点的数据差异
- 连接关系的存储方式

#### 3. 验证工作流保存/加载

检查工作流保存和加载功能是否正常：
- 保存前查看节点数据
- 重新加载后再次查看
- 对比数据是否一致

### 技术实现

- **状态管理**: 在 `state.js` 中添加 `debugMode` 状态
- **事件处理**: 在 `workflow.js` 中实现密码验证和 UI 更新
- **节点按钮**: 在各节点创建函数中调用 `addDebugButtonToNode()` 添加调试按钮
- **API 接口**: 在 `server.py` 中添加 `/api/config/debug-password` 接口返回密码

---

## 二、后端测试模式

### 功能概述

测试模式允许你在不调用真实外部 API 的情况下测试图生视频、文生视频、图片编辑等功能的完整业务流程。这对于开发和测试非常有用，可以：

- 避免消耗真实的 API 调用额度
- 加快测试速度
- 使用预定义的测试资源验证业务逻辑
- 完整测试从任务提交到结果返回的整个流程

### 配置方法

#### 1. 修改配置文件

在 `config.yml` 中添加或修改 `test_mode` 配置段：

```yaml
# Test mode configuration
test_mode:
  enabled: true  # 设置为 true 启用测试模式
  mock_videos:
    image_to_video: "http://example.com/test_image_to_video.mp4"  # 图生视频的测试视频URL
    text_to_video: "http://example.com/test_text_to_video.mp4"    # 文生视频的测试视频URL
  mock_images:
    image_edit: "http://example.com/test_image_edit.png"          # 图片编辑的测试图片URL
    text_to_image: "http://example.com/test_text_to_image.png"    # 文生图的测试图片URL
```

#### 2. 配置说明

- **enabled**: 布尔值，控制是否启用测试模式
  - `true`: 启用测试模式，所有 API 调用将被 mock
  - `false`: 关闭测试模式，使用真实 API

- **mock_videos**: 视频任务的测试资源配置
  - `image_to_video`: 图生视频任务返回的测试视频 URL
  - `text_to_video`: 文生视频任务返回的测试视频 URL

- **mock_images**: 图片任务的测试资源配置
  - `image_edit`: 图片编辑任务返回的测试图片 URL
  - `text_to_image`: 文生图任务返回的测试图片 URL

#### 3. 准备测试资源

你需要准备实际的测试视频和图片文件，并将它们放置在可访问的位置。可以选择：

1. **使用本地文件**：将测试文件放在 `upload` 目录下
   ```yaml
   mock_videos:
     image_to_video: "http://localhost:5178/upload/test_video.mp4"
   ```

2. **使用远程 URL**：使用任何可访问的 HTTP/HTTPS URL
   ```yaml
   mock_videos:
     image_to_video: "https://your-server.com/test_video.mp4"
   ```

### 工作原理

#### 测试模式流程

1. **任务提交阶段**
   - 用户通过 API 提交图生视频/文生视频任务
   - 系统检测到测试模式已启用
   - `duomi_api_requset.py` 生成一个特殊的 mock task_id（格式：`mock_task_xxxxxxxx_timestamp`）
   - 任务正常记录到数据库，状态为 0（队列中）

2. **任务处理阶段**
   - 定时脚本 `task/video_task.py` 检测到待处理任务
   - 调用 `create_image_to_video` 等函数提交任务
   - 函数检测到测试模式，返回 mock task_id
   - 数据库更新任务状态为 1（处理中）

3. **结果查询阶段**
   - 定时脚本继续轮询任务状态
   - 调用 `get_ai_task_result` 查询结果
   - 函数检测到 mock task_id（以 `mock_task_` 开头）
   - 直接返回配置文件中指定的测试视频/图片 URL
   - 任务标记为完成（状态 2）

#### Mock Task ID 识别

测试模式使用特殊的 task_id 格式来识别 mock 任务：

```
mock_task_{16位随机字符}_{时间戳}
```

例如：`mock_task_a1b2c3d4e5f6g7h8_1704614400`

系统通过检测 task_id 是否以 `mock_task_` 开头来判断是否为测试任务。

### 使用示例

#### 示例 1: 测试图生视频功能

1. **启用测试模式**
   ```yaml
   test_mode:
     enabled: true
     mock_videos:
       image_to_video: "http://localhost:5178/upload/test_video.mp4"
   ```

2. **调用 API**
   ```bash
   curl -X POST http://localhost:5178/api/ai-app-run-image \
     -F "prompt=一个美丽的风景" \
     -F "images=@test_image.jpg" \
     -F "ratio=9:16" \
     -F "duration_seconds=15" \
     -F "user_id=123" \
     -F "auth_token=your_token"
   ```

3. **观察日志**
   ```
   [TEST MODE] create_image_to_video - Generated mock task_id: mock_task_a1b2c3d4e5f6g7h8_1704614400
   [TEST MODE] Submitting task 456 (type: 3)
   [TEST MODE] Checking status for mock task mock_task_a1b2c3d4e5f6g7h8_1704614400
   [TEST MODE] Returning mock video URL: http://localhost:5178/upload/test_video.mp4
   ```

4. **查询结果**
   ```bash
   curl http://localhost:5178/api/get-status/456
   ```
   
   返回：
   ```json
   {
     "tasks": [{
       "project_id": "456",
       "status": "SUCCESS",
       "results": [{
         "file_url": "http://localhost:5178/upload/test_video.mp4"
       }]
     }]
   }
   ```

#### 示例 2: 测试文生视频功能

1. **配置**
   ```yaml
   test_mode:
     enabled: true
     mock_videos:
       text_to_video: "http://localhost:5178/upload/test_text_video.mp4"
   ```

2. **调用 API**
   ```bash
   curl -X POST http://localhost:5178/api/ai-app-run \
     -F "prompt=一只可爱的小猫在玩耍" \
     -F "ratio=16:9" \
     -F "duration_seconds=10" \
     -F "user_id=123" \
     -F "auth_token=your_token"
   ```

### 日志输出

启用测试模式后，系统会在日志中输出明显的标识：

```
============================================================
TEST MODE ENABLED - Using mock API responses
============================================================
```

每次 mock 操作都会有 `[TEST MODE]` 前缀的日志输出，方便调试。

### 支持的任务类型

测试模式支持以下任务类型：

| 任务类型 | type 值 | API 接口 | 配置项 |
|---------|---------|----------|--------|
| 图片编辑 | 1, 7 | `/api/image-edit` | `mock_images.image_edit` |
| 文生图 | 1, 7 | `/api/image-edit` (无图片) | `mock_images.text_to_image` |
| 文生视频 | 2 | `/api/ai-app-run` | `mock_videos.text_to_video` |
| 图生视频 | 3 | `/api/ai-app-run-image` | `mock_videos.image_to_video` |

---

## 三、注意事项

### 前端 Debug 模式

1. **仅用于开发调试**: Debug 模式仅供开发人员使用，不应在生产环境中启用
2. **密码保护**: 请妥善保管 Debug 密码，避免泄露
3. **性能影响**: Debug 模式本身不会影响性能，但频繁输出大量节点数据可能会占用控制台资源
4. **浏览器兼容性**: 确保使用现代浏览器（Chrome、Firefox、Edge、Safari 最新版本）
5. **安全考虑**: 密码验证在前端进行，主要用于防止误操作，不应将 Debug 密码视为高安全性的保护措施

### 后端测试模式

1. **生产环境禁用**: 测试模式仅用于开发和测试环境，在生产环境中务必设置 `enabled: false`
2. **算力扣除**: 测试模式下仍会正常扣除和返还算力，如果需要跳过算力验证，需要在 `server.py` 中设置 `CHECK_AUTH_TOKEN = False`
3. **数据库记录**: 测试模式下的任务仍会正常记录到数据库，mock task_id 会被保存，可以通过前缀 `mock_task_` 识别
4. **测试资源准备**: 确保配置的测试视频/图片 URL 可以正常访问，建议使用本地文件以提高测试速度
5. **重启服务**: 修改配置文件后需要重启服务才能生效，测试模式配置在服务启动时加载

---

## 四、故障排查

### 前端 Debug 模式

**问题**: Debug 模式未生效

**解决方案**:
1. 检查 URL 参数是否正确（`?debug=密码`）
2. 确认密码与配置文件中的一致
3. 查看浏览器控制台是否有错误信息

### 后端测试模式

#### 问题 1: 测试模式未生效

**症状**: 仍然调用真实 API

**解决方案**:
1. 检查 `config.yml` 中 `test_mode.enabled` 是否为 `true`
2. 确认已重启服务
3. 查看日志是否有 "TEST MODE ENABLED" 提示

#### 问题 2: 返回的测试资源无法访问

**症状**: 任务完成但无法下载结果

**解决方案**:
1. 检查配置的 URL 是否正确
2. 确认测试文件是否存在
3. 验证文件路径和权限

#### 问题 3: Mock task_id 未被识别

**症状**: 测试任务调用了真实 API

**解决方案**:
1. 检查 task_id 是否以 `mock_task_` 开头
2. 确认 `duomi_api_requset.py` 中的测试模式逻辑正确
3. 查看日志中的 task_id 生成记录

---

## 五、相关文件

### 前端 Debug 模式

- **状态管理**: `web/js/state.js`
- **事件处理**: `web/js/workflow.js`
- **节点按钮**: `web/js/nodes.js`
- **API 接口**: `server.py` (`/api/config/debug-password`)

### 后端测试模式

- **配置文件**: `config.yml`, `config.example.yml`
- **API Mock**: `duomi_api_requset.py`
- **任务处理**: `task/video_task.py`
- **服务入口**: `server.py`

---

## 更新历史

- 2026-03-10: 合并 Debug 模式和测试模式文档
- 2026-01-07: 初始版本，支持图生视频、文生视频、图片编辑的测试模式
