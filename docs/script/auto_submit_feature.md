# 自动提交数据库功能

## 功能概述

剧本智能创作系统 (`script_writer.html`) 支持自动提交数据库功能，开启后系统每隔约1分钟自动提交暂存数据到数据库。此外，系统还内置了自动刷新暂存文件和定时刷新算力的功能。

## 功能位置

位于页面顶部导航栏右侧，"提交数据"按钮旁边。

## 提交按钮 Loading

右上角「提交」按钮（`#submit-to-db-btn`）在**整次** `POST /api/submit-to-database` 进行期间会展示 loading：

| 状态 | 表现 |
|------|------|
| 提交中 | **亮点沿按钮自身 border 路径连续绕行**（`.is-submitting` + `.submit-btn-ring` 的 conic-gradient 旋转），文案变为「提交中...」，`aria-busy="true"`，不可重复点击 |
| 提交成功 | 关闭绕行亮点，短暂整圈绿色边框（`.submit-success` ~500ms），恢复「提交」 |
| 提交失败 / 网络异常 | 关闭亮点，恢复可点，错误 toast；便于重试 |
| 未选世界 | 不进入 loading，仅错误提示 |

视觉说明：不是外侧单独转圈的 spinner 环，而是按钮描边上有一个高亮点在转；边框路径即运动轨迹。

实现要点：

- 状态由 `setSubmitButtonLoading(loading, { success })` 统一控制
- `submitToDatabase()` 用 `isSubmitting` 防重入；`finally` 中才关闭 loading，保证请求未结束不会提前结束动效
- **手动点击、自动提交、进入故事板/画布前的预提交** 均走同一函数，因此自动提交时同样会显示环绕 loading

相关文件：`web/script_writer.html`、`web/css/script_writer.css`、`web/js/script_writer.js`

## 使用方式

### UI 控件

| 控件 | 说明 |
|------|------|
| 自动提交开关 | Toggle 开关，开启/关闭自动提交（带滑块样式） |
| 自动标签 | 开关旁显示"自动"文字标签 |

### 操作步骤

1. 打开"自动"开关
2. 系统自动调度下一次提交（固定1分钟 + 随机延迟）
3. 提交完成后自动调度下一次提交
4. 关闭开关将停止所有自动提交

## 随机延迟策略

为避免多用户同时提交造成系统压力，采用随机延迟策略：

- **基础间隔**: 固定1分钟（60秒）
- **随机偏移**: 0-30秒的随机延迟
- **实际间隔**: 基础间隔 + 随机偏移

例如：实际提交间隔为 60-90 秒。

## 设置持久化

用户设置通过 Cookie 保存，有效期1年：

- 开关状态（开启/关闭）

页面刷新后会自动恢复用户设置。

## 内置定时刷新功能

除了自动提交功能外，系统还内置了以下定时刷新功能：

### 自动刷新暂存文件

- **触发时机**：页面加载后自动启动
- **刷新间隔**：67-83秒（随机）
- **功能**：自动刷新暂存文件列表，保持数据最新

### 算力定时刷新

- **触发时机**：页面加载后自动启动
- **刷新间隔**：30-45秒（随机）
- **功能**：自动刷新用户算力余额显示

## 技术实现

### 核心函数

| 函数 | 说明 |
|------|------|
| `toggleAutoSubmit()` | 切换自动提交开关，调用 start/stop 并保存设置 |
| `startAutoSubmit()` | 启动自动提交（调用 scheduleNextSubmit） |
| `stopAutoSubmit()` | 停止自动提交，清除所有定时器 |
| `scheduleNextSubmit()` | 调度下次提交（固定1分钟 + 0-30秒随机延迟） |
| `startCountdownUpdater()` | 启动倒计时更新定时器（每秒执行） |
| `updateCountdownDisplay()` | 更新倒计时显示（当前实现为隐藏状态） |
| `saveAutoSubmitSettings()` | 保存开关状态到 Cookie（有效期1年） |
| `loadAutoSubmitSettings()` | 从 Cookie 加载设置并恢复状态，同时启动自动刷新功能 |
| `startAutoRefresh()` | 启动自动刷新暂存文件功能（67-83秒间隔） |

### 相关文件

- `web/script_writer.html` - HTML 控件和 JavaScript 逻辑
- `web/css/script_writer.css` - 样式定义
