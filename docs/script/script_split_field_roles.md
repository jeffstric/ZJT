# 剧本拆分 · description/action/scene_detail 三字段各司其职

> 分支 develop_f1181（继 4b9c745c/8a1ba3ee 之后）。

## 问题

video_workflow / 故事板的**视频提示词**由 `description + scene_detail + action` 拼接而成。
线上案例（video_workflow id=13 分镜9）：三个字段互相复述同一动作节拍——

```text
描述：【【赵志高】】转头对着【【王小胖】】，手指着李卫国的方向，说道："你看看他…"
场景细节：【【赵志高】】扭头对【【王小胖】】说话，手指向李卫国方向…【【王小胖】】缩着肩膀听着。
动作：【【赵志高】】手指李卫国方向，对【【王小胖】】训话；【【王小胖】】低头缩肩。
```

同一节拍（指着训话/缩肩听）出现三次，视频模型收到三份冗余文本，用户编辑提示词也要改三处。

## 根因（提示词层四处默许重复）

| 位置 | 原文案 | 误导点 |
|---|---|---|
| user prompt 第3条"九列分镜表映射" | "画面内容对应 description/scene_detail/action" | **一个分镜列映射三个字段**，LLM 理解为画面内容三处都写 |
| `JSON_FORMAT_EXAMPLE` scene_detail | "有对白时可在此或 description/action 中写出完整台词" | 主动邀请台词进 scene_detail |
| user prompt 7.2 / SKILL 18.1 | "在 description **和/或** action，**可选** scene_detail 中逐字写出台词" | "和/或+可选"被读成"处处都写" |
| 三字段职责定义 | "镜头简要描述/场景详细描述/动作描述" | 边界模糊：对白镜头里"简要描述"与"动作"天然是同一件事；无任何规则禁止互相复述 |

下游校验（QC `DIALOGUE_NOT_IN_VIDEO_PROMPT`、角色契约 `character_missing_from_video_prompt`）
都是 **三字段合集（union）判定**，因此职责拆开不会破坏任何硬约束。

## 修复（把分工变成显式硬规则）

- **SKILL.md 新增 18.2**【description/action/scene_detail 三字段各司其职·硬性规则】+ 自检法
  （并排读三字段，删掉任一字段后其余仍能完整覆盖"谁做了什么+说了什么"即存在复述）+ 正反例；
  **18.1 收紧**为"台词在 description 或 action **二选一**，严禁三字段重复同一句台词"
- **user prompt 第3条**：九列映射后追加同款职责划分与正反例；**7.2** 同步收紧
- **`JSON_FORMAT_EXAMPLE`** 三字段说明重写：description=核心事件+台词首选载体；
  action=动作节拍表（最细一层）；scene_detail=环境与画面变化（严禁复述角色动作与台词）

## 量化验证（字符 bigram 包含度，`|A∩B|/min(|A|,|B|)`，>0.6 记重度）

同一"训话"剧本（12 镜，deepseek-v4-flash）before/after 对照（temp/f1181_field_*.json）：

| 指标 | before（旧提示词） | after1 | after2 |
|---|---|---|---|
| desc∩action 均值 | 0.150 | 0.198 | 0.231 |
| desc∩scene 均值 | 0.029 | 0.091 | 0.086 |
| action∩scene 均值 | 0.019 | 0.065 | 0.092 |
| 重度复述镜头 | **0/12** | **0/12** | **0/10** |
| 台词多字段重复 | — | **0/6 条** | **0/6 条** |

结论：当前版本基线已较低（用户案例大概率出自更早版本提示词），本次改动把"自发分工"升级为
"显式契约+自检"，消除方差；desc∩action 不可能为 0（同一角色与核心动词必然共现），0.2 左右即健康。

## 关联

- 台词去重（提示词重复的另一半）：见 [script_split_dialogue_in_video_prompt.md](./script_split_dialogue_in_video_prompt.md)
  与前端 `dedupeVideoPromptDialogue`（8a1ba3ee）——本规则从源头减少"动作内台词 + 对话行"的重复来源
