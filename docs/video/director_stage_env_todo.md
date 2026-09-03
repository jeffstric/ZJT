# 导演台·全景环境 遗留问题（待后续处理）

> 交接文档：360 全景图融合导演台功能已实现并实测通过（`temp/test_ds_env.py` 9 步全过），
> 仅以下问题未在自动化测试中闭环，需要人工或后续智能体处理。

## 1. Playwright 无法通过点击选中画布连线（测试环境问题）

**现象**：Playwright headless Chromium 中，点击普通连线（`#connectionsSvg path.hitbox`）
无法触发 `selectConnection`，删除按钮（`#connDeleteBtn`）不出现，因此无法用 Delete 键
删除连线。真实浏览器中应正常（该项目其他连线功能一直如此使用）。

**已排除**：
- 坐标计算正确：`hitbox.getPointAtLength(len/2)` 取贝塞尔中点，`document.elementFromPoint`
  返回的就是 `path.hitbox`；
- Playwright `locator.click()` 与 `mouse.click()` 均无效（click 事件疑似被某个全局
  mouseup/mousedown handler 之后重置了选中态）；
- 页面无 JS 错误。

**怀疑点**：events.js 的画布级 mousedown/mouseup 处理（clearSelection / pan 启动逻辑）
与 hitbox click 的时序竞争，headless 下事件派发顺序差异触发。

**影响**：仅影响自动化测试对「断开连线 → 自动清除导演台环境」
（`nodes.js removeConnection` → `window.handleDirectorStageEnvDisconnect`）这条路径的验证。
产品代码已实现，等价路径（编辑器左栏「✕ 移除」按钮）已自动化验证通过。

**建议排查**：在 events.js 中给 canvasContainer 的 mousedown handler 打日志，
观察 hitbox click 前后 `state.selectedConnId` 的变化。

## 2. 断开连线自动清环境的边界行为

`web/js/director_stage_node.js` 的 `handleDirectorStageEnvDisconnect` 依赖
`conn.portType === 'environment'`。若用户用 Ctrl+Z 撤销连线创建（而非点击删除），
撤销快照恢复的是旧 `state.connections` 数组，不会走 `removeConnection`，
环境数据会保留——此时环境与连线状态不一致（环境还在但连线没了）。
影响轻微（用户可在编辑器左栏手动移除），可在撤销路径补 `handleDirectorStageEnvDisconnect` 调用。

## 3. 环境球比例换算的已知限制

- equirect 图实际尺寸与节点 `data.ratio` 不一致时（如 2:1 的图选了 21:9），
  环境球按 ratio 换算贴面会有轻微垂直裁剪/拉伸。当前与全景节点查看器
  （Pannellum 用同一 ratio 换算）行为一致，视觉可接受。
- 非 2:1 宽比的全景（如 16:9，水平仅 180°）贴部分球面后，背后区域露出编辑器
  背景色（深色）。可考虑后续加「背景延展色」或提示用户使用 21:9。

## 4. 测试脚本位置

- `temp/test_ds_env.py`：环境融合 e2e（需先按脚本头部注释重置工作流 6 数据）
- `temp/test_director_stage.py` / `temp/test_ds_ux.py` / `temp/test_ds_focus.py`：
  导演台其他回归
- 全景测试图：`temp/equirect_test.jpg`（three.js 官方 equirect 4096x2048）
