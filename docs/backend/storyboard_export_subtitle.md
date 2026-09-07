# 故事板一键转视频：字幕逐句显示 + 边距设置 + 部分分镜无字幕调查

> 分支：develop_f784　日期：2026-09-06
> 关联代码：`services/storyboard_subtitle.py`、`services/storyboard_export_service.py`、`services/asr_sentence_client.py`、`api/storyboard.py`、`web/js/storyboard/*`

## 一、字幕显示方式（问题 1：文字太多换行好几行）

### 旧行为
导出时把**整条对白**折行（每行 ~16 字，竖屏更窄）并按最多 3 行/页分页，一条 60 字对白
会在同一时间窗内堆出 3 行大段文字，竖屏下一口气换好几行，观感差。

### 新行为：smart 逐句字幕（默认）
- 一键转视频时，对每条对白 wav 调 l3 SenseVoice ASR 的句级转写，得到该音频内
  每句话的真实时间轴 `[{start, end, text}]`；
- 字幕按句显示：同一时刻最多一句（超行宽才折行），随语音推进逐句切换；
- **字幕文本仍显示对白原文**（避免 ASR 同音字错字），ASR 只提供时间轴与切句点；
  原文按各句"去标点字符占比"找切点，切点向就近标点吸附
  （`split_text_by_asr_sentences`，窗口内找不到标点则按占比硬切）；
- ASR 识别出的时间轴与对白 audio.duration 按 `window_dur / ASR末句end` 等比缩放，
  比例超出 [0.5, 2.0] 视为不可信，该条对白回退旧 block 模式；
- 每条对白 ASR 失败/超时/服务关闭 → 该条回退 block 整段分页，**不影响导出**；
- 全片 ASR 总预算 `SENTENCES_TOTAL_BUDGET_SECONDS=300s`，超预算后剩余对白直接
  回退 block，避免导出被 ASR 拖死。

### block 模式
保留旧行为（整条折行分页），字幕设置面板可切换。

## 二、字幕左右边距可视化调整（问题 2）

- 预览控制条"字幕"复选框旁新增 **齿轮按钮**，点开字幕设置小面板：
  - 显示方式：逐句（smart）/ 整段（block）；
  - 左右边距滑杆：0~18%（步进 1%，默认 7%）；
- 滑杆拖动时预览画面实时显示示例字幕（非播放态），所见即所得；
- 边距随 UI 配置持久化（`serializeUiConfig/restoreUiConfig`：
  `subtitleMode`、`subtitleSideMarginRatio`）；
- 一键转视频时透传 `subtitle_mode`、`subtitle_side_margin` 到后端，
  写入 ASS `MarginL/MarginR`（`write_ass_file(side_margin_ratio=)`，夹取 0~0.18）；
- 面板开合走预览控制条局部刷新（`patchTimelineChrome` 重挂 `.subtitle-settings`）。
  曾因该局部刷新不重建此区域导致"点击齿轮无反应"（state 已翻转但 DOM 不变），
  已修复，回归测试 `web/tests/storyboard_subtitle_settings_panel.test.js`。

## 三、l3 ASR 服务（新增句级端点）

- 位置：`jeffS3(l3)` GPU1，`/content/SenseVoice/asr_server.py`（7861 端口，内网），
  启动脚本 `start_asr.sh`（systemd 外的 nohup 常驻）；
- **新增端点** `POST /api/v1/asr_sentences`：`file`(音频) + `lang`(默认 auto)，返回
  `{"result": [{start, end, text}...], "count": n}`（秒，相对音频起点）；
- 实现：FunASR VAD 切段 → 每段 SenseVoice 推理带 `output_timestamp=True`
  （字级时间戳 `[token, t0, t1]`，与文本一一对应）→ 段内按句末标点切句、
  超 24 字在句中标点断句、48 字硬断；已有 `.bak_sentences` 备份；
- 主服务配置：`config.yml` 顶层 `asr.api_url`（未配置时兜底
  `StoryboardAsrConstants.DEFAULT_API_URL` = `http://192.168.10.108:7861`）、
  `asr.enabled`（**opt-in：缺省 false**，未配置 asr 段的环境一律回退 block 分页，
  避免对不可达内网地址逐条等 30s 超时及用户音频默认外发；example 默认 false、
  prod.base 显式 true，现场按实际内网地址覆盖）；
- 客户端 `services/asr_sentence_client.py`：同步 urllib（仅导出后台线程调用），
  失败一律返回 `[]`。

## 四、接口变更

`POST /api/storyboard/{id}/export-full-video` body 新增可选字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `subtitle_mode` | str | `smart`（默认）/ `block` |
| `subtitle_side_margin` | float | 0~0.18，缺省 0.07 |

## 五、部分分镜字幕查看不到：根因调查（问题 3，**待确认，未实施**）

### 根因 1：字幕与视频的"分镜时长"口径不一致 → 后续字幕整体错位
- 视频合成 `build_merged_video`：`span = max(sc.duration, 2.0)`（短于 2s 的分镜
  实际渲染 2s）；
- 字幕轴 `build_subtitle_cues`：`span = sc.duration or 2.0`（0.5s 的分镜只排 0.5s）；
- 一旦存在 duration < 2s 的分镜，**该镜之后所有字幕 cue 时间提前**，字幕出现在
  前一镜画面上、本镜没字幕，且越往后错位越大。

### 根因 2：对白超出分镜时长被静默丢弃 → 该对白完全没字幕
`build_subtitle_cues` 逐条对白推进 `t_local`，`remaining = span - t_local` 用尽即
`break`。以下场景后面的对白**直接没有字幕**（配音声音仍在播）：
- 用户在分镜编辑弹框手动改小 `duration`；
- `recalc_scene_duration_if_all_completed` 是 best-effort：LLM 估算值未刷新
  （估算 < 实际配音总长）时按估算值排字幕；
- `storyboard_dialogue_audio.duration` 与实际 wav 不符（旧数据/手动替换配音），
  累计偏移把后面的对白挤出窗口。

### 根因 3：超长对白 + 超短窗口 → 只显示第一页 + "…"
`fit_pages_to_duration` 在窗口 < 0.8s×页数 时只保留第一页并加省略号，观感为
"字幕只有半句/看不到全文"。

### 待确认的修复方案
1. **统一口径（必修，小改动）**：`build_subtitle_cues` 的每镜 span 改为
   `max(duration, 2.0)`，与视频合成一致；或由 `build_merged_video` 把实际用的
   per-scene spans 传入字幕构建，从根上消除两处各算各的。
2. **对白超出 span 不再静默丢弃（必修）**：本镜所有对白按音频实际总时长延伸
   字幕窗口（字幕窗口以"音频总长"为准，而不是 scene.duration），即声音播到哪、
   字幕跟到哪；同时保留 video span 补齐逻辑不变。
3. **smart 模式缓解（已随本次上线）**：ASR 直接量测 wav 真实时间轴，
   DB `duration` 漂移不再影响字幕窗口；但方案 1/2 仍需做，smart 回退 block 时
   同样受根因 1/2 影响。
4. **建议**：导出 job 增加诊断字段（哪些镜字幕被截断/无字幕），前端在导出完成后
   提示；分镜编辑保存时若 `duration` 与已完成配音总长偏差 > 1s 给出提示。

> 确认后按 1 → 2 顺序实施（1 是几十行的低风险修改，2 涉及 cue 构建重构约 100 行）。

## 六、测试

- `tests/storyboard/test_storyboard_subtitle_smart.py`：占比切分/标点吸附/时间缩放/
  smart 与 block 模式/ASR 缺失回退/边距透传；
- `tests/storyboard/test_asr_sentence_client.py`：成功解析/禁用回退/请求失败回退/
  非法项过滤（mock 网络，不发真实请求）；
- 存量 `test_storyboard_subtitle.py` 全部保持通过。
