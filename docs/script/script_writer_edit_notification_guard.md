# 剧本创作页：用户编辑通知误触发形象图自动重生成的防护

## 问题（2026-10-13 线上事故还原）

用户在 script-writer 页面编辑角色卡（清空形象图准备自行上传）保存后，PM 智能体收到前端自动发出的「系统通知：角色卡 "X" 已被用户编辑更新，请重新读取最新内容」，读取后发现 `reference_image` 为空，便依据 SOP「为所有缺少 reference_image 的角色生成形象设计图」的补全规则，**未经确认自动调用 character-image-designer 重新生成形象图**。约 2 分钟后异步生图完成回写 `reference_image`，把用户刚手动上传的新图挤入 `image_history`（金伟杰 17:00:46 上传的图被 17:03:06 完成的 AI 任务 56278 覆盖）。用户反复清空/上传形成循环，单个会话内产生 7 次多余生成（约 14 算力浪费）。

## 根因

1. **PM 提示词无护栏**：`script_writer_core/skills/script-orchestrator/` 的 SKILL.md 专家路由表只有「缺失资产时调用对应专家补全」，没有区分"创作流程缺图"与"用户编辑后图为空"，也没有对系统通知的任何处理规定。PM 自行推断「用户清空了图片 = 想让 AI 重新生成」（对话记录 reasoning 原文），且首轮 `ask_user` 确认 5 分钟超时（`ask_user_mixin.py` timeout=300）后，后续通知到达时不再询问。
2. **前端畸形通知 bug**：`web/js/script_writer.js` 的 `saveEditedFile()` 在成功回调（多次 `await` 之后）才读取 `currentEditFile.fileType/fileName` 拼装通知；而 `closeEditModal()` 会把 `currentEditFile` 重置为 `{'',''}`。并发触发保存（如双击）时，第二次调用的回调读到重置后的空值，向智能体发出「系统通知：undefined "" 已被用户编辑更新」畸形消息，同样触发了一轮扫描与生成尝试（16:53:27 实录）。

## 修复

### 1. PM 护栏（提示词层）

- `script_writer_core/skills/script-orchestrator/SKILL.md`「与专家的协调」路由表处新增最高优先级规则：**用户编辑通知不是生成指令**——收到「已被用户编辑更新」类系统通知时只重新读取内容同步状态，严禁据此自动生成；若重读后发现 `reference_image` 为空（用户主动清空，通常准备自行上传），必须先 `ask_user` 确认「是否需要 AI 重新生成形象图」，获肯定答复后才能调用形象生成专家。该规则优先于专家路由表与各 SOP 的缺图自动补全流程。
- `sops/sop-new-script.md` 与 `sops/sop-continue-script.md` 的步骤 4.5（character-image-designer）、5.5（location-prop-image-designer）各增加「用户编辑通知例外」提醒，指向上述 SKILL.md 规则。

### 2. 前端保存竞态（`web/js/script_writer.js`）

`saveEditedFile()`：

- **进入函数即快照** `fileType` / `fileName`（任何 `await` 之前），fetch URL、成功提示、刷新列表、通知消息全部改用快照，不再依赖会被 `closeEditModal()` 重置的 `currentEditFile`；快照为空直接返回。
- **新增 `isSavingEditedFile` 防重入标志**：保存请求进行中忽略再次触发（`try/finally` 释放），杜绝双击导致的重复保存与重复通知。

## 未包含（后续待办）

- 生图任务完成回写 `reference_image` 前缺少版本校验（任务提交后用户若已改卡会被覆盖）——已列为待办，本次不实施。

## 验证建议

1. 编辑角色卡清空形象图并保存：对话中应出现 PM 的 `ask_user` 确认弹窗，而非直接提交生图任务。
2. 双击编辑弹窗「保存」按钮：仅应发出一次保存请求与一条格式完整的「系统通知：角色卡 "X" 已被用户编辑更新…」，不再出现 `undefined ""`。
