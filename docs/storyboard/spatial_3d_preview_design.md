# 分镜 3D 空间：LLM 直出 three.js 代码方案（v2，现行）

- 状态：已实施（第二期，替代第一期「结构化 JSON + 确定性转换」方案）
- 日期：2026-10-15
- 适用范围：效果模式（`sequence_mode=quality`）拆分链路；故事板编辑器
  （`web/storyboard.html`）分镜卡片「3D 空间」预览
- 相关文档：
  - `docs/script/script_split_quality_spatial_dependency_design.md`（效果模式空间依赖调度）
  - `docs/script/script_split_quality_incremental_spatial_state_design.md`

## 1. 决策记录：空间表达载体改为 three.js 代码（用户指令）

第一期曾采纳「LLM 输出结构化 spatial_layout JSON、后端确定性转换为 three.js
场景 JSON、前端只渲染不执行」的方案（理由：安全红线、下游可消费、确定性校验、
token）。**该决策已被用户否决并反转**：空间表达必须直接是 three.js 代码——

1. **第一个分镜（空间序列首镜）必须构建一个极简的 three.js 空间**：场景体块
   （makeStage）+ 角色站位（makeActor）+ 机位（setCamera）。
2. **每个分镜必须确定镜头位置**：每镜必须调用 `setCamera(...)`。
3. **空间关系保持的下一个分镜必须基于前一个分镜增量调整**（如人物运动
   `moveActor`），禁止重建场景；场景切换（硬切）才以 `startScene(...)` 重建
   新序列。

第一期结构化 JSON 契约（spatial_intent / spatial_layout / canonical_state
状态机物化）**继续保留**，负责角色/道具逻辑空间状态与质检；three.js 代码是
空间表达与预览的唯一渲染真源，两者由同一次 LLM 输出并行产生，语义必须一致。

## 2. 数据契约

### 2.1 每镜字段 `three_scene_code`（字符串，JavaScript）

LLM 在效果模式拆分时为每个 shot 输出。执行环境（沙箱）注入：

| 名称 | 类型 | 说明 |
| --- | --- | --- |
| `THREE` | 命名空间 | three.js（r128 UMD） |
| `scene` | `THREE.Group` | 世界根节点（对象挂载处） |
| `camera` | `PerspectiveCamera` | 本镜相机 |
| `actors` / `props` / `stage` | 对象表 | 已注册实体（如 `actors.林晓`） |
| `startScene(label)` | helper | 开始新空间序列：清空世界并重建 |
| `makeStage(name,w,d,x,z,{h,y,color})` | helper | 场景体块（车/桌/墙），落地 |
| `makeActor(name,x,z,{facing})` | helper | 角色站位人偶；facing 度（0=+Z，90=+X） |
| `makeProp(name,x,z,{y})` | helper | 道具 |
| `moveActor(name,x,z,{facing})` | helper | 人物运动（增量镜） |
| `moveProp(name,x,z,{y})` | helper | 道具移动 |
| `setCamera(ex,ey,ez,tx,ty,tz,fov=50)` | helper | **每镜必须调用**：机位+朝向+fov |

坐标系：three.js 常规 Y-up，地面 y=0，单位约米。序列首镜判定标记：代码含
`startScene(`（前后端同一判定，见 `services/storyboard_spatial/three_code.py`
`SCENE_START_MARKER`）。

### 2.2 prompt 契约（`llm/script_parser.py`）

- `THREE_SCENE_CODE_REQUIREMENTS`：效果模式分段 prompt 硬约束块（规则 +
  正例），v2/v3 链路共用，随 `segment_context_block` 注入。
- v3 增量链：`_build_incremental_spatial_prompt` 注入上一镜
  `three_scene_code`（来自 spatial handoff），要求继承段首镜基于它增量调整。
- v2 链路：handoff JSON 序列化文本中自然携带上游末镜代码。

### 2.3 透传链路

```
LLM shot.three_scene_code
  → spatial handoff（enterprise .../spatial_handoff.py，段间交接上一镜代码）
  → v3 物化（spatial_materializer.py：代码链校验诊断，缺码/缺相机=error 质检拦截）
  → 合并结果 shot 字段保留
  → build_storyboard_scenes_from_parsed_script（api/storyboard.py）
    → prompt_json.three_scene_code（规范化 markdown 围栏后落库）
```

## 3. 校验（`services/storyboard_spatial/three_code.py`，社区/企业通用）

字符串级确定性校验（无 IO、无许可证门禁）：

| code | severity | 含义 |
| --- | --- | --- |
| `three_code_missing` | error | 分镜缺少 three_scene_code |
| `three_code_camera_missing` | error | 未调用 setCamera（每镜必须确定镜头位置） |
| `three_code_scene_build_missing` | error | 序列首镜未以 startScene 构建 |
| `three_code_sequence_start_empty` | error | startScene 后无任何构建 |
| `three_code_too_long` | warning | 代码超 8000 字符 |
| `three_code_no_upstream_scene` | warning | 增量镜无上游代码基座 |

v3 物化器按整段代码链校验（`audit_three_scene_codes_for_shots`）：段首镜是否
必须自建序列由依赖类型决定（`strategy.materialize_segment_result`：继承段且
上游末镜带代码 → 增量；否则 → 必须 startScene）。error 诊断进入
`_spatial_diagnostics`，`validate_materialized_segment` 收集后触发质检重拆。

## 4. API

`GET /api/storyboard/{storyboard_id}/spatial-previews`（`storyboard:view`）：

- 优先返回代码载荷：`previews[].three_scene = {kind: "three_code", code,
  is_sequence_start, diagnostics}`；`diagnostic_summary` 汇总 error/warning。
- 存量分镜（只有结构化 spatial_layout，无代码）回退第一期 JSON 载荷
  （企业版空间引擎转换，无许可证 403——预存行为）。
- 纯计算经 `asyncio.to_thread` 包装（非阻塞红线）。

## 5. 前端预览（`web/js/storyboard/spatial_3d_preview.js`）

- **重放执行**：查看第 N 镜时，从该镜往前找最近的 `startScene` 序列起点，
  将起点→第 N 镜的代码在 `new Function` 作用域沙箱内**按序执行**（只注入
  THREE/scene/camera/对象表/helper，不暴露 window/document），得到该镜完整
  空间状态——「下一镜基于前镜调整」由此天然成立。存量 JSON 镜头即链边界。
- **渲染**：世界对象（角色人偶含朝向鼻锥、道具、半透明场景体块）+ 机位视锥
  取景框 + **镜头视角画中画**（用本镜 setCamera 的相机经 setScissor 分屏
  渲染，右下角取景器，DOM 只画边框标题）。
- **侧栏**：空间对象清单（站位坐标）+ 本镜 three.js 代码（`escapeHtml` 转义
  展示）+ 序列信息（首镜/基于第 X 镜累计重放 N 段）+ 诊断（含代码执行异常）。
- 交互与生命周期同第一期：轨道旋转/平移/缩放、←/→ 切镜、关闭时完整 dispose。

## 6. 安全边界（相对第一期决策的调整说明）

第一期以「执行不可信代码风险高」为由拒绝代码方案。本期按用户指令采纳代码
方案，同时收敛执行面：代码在 `Function` 作用域沙箱内执行，仅注入渲染所需
变量与 helper；不经 innerHTML 注入 DOM；执行异常被捕获并作为诊断展示。
该边界变更由用户明确指令授权（2026-10-15）。

## 7. 测试

- `tests/services/test_storyboard_spatial_three_code.py`：15 例——围栏规范化、
  序列起点判定、逐镜/整段校验、断链重建设定、继承段增量首镜、预览载荷、
  落库透传、handoff 携带代码。
- `enterprise/tests/services/test_script_split_spatial_materializer.py`：夹具
  带代码链，新增 4 例物化器集成（缺码 error、缺相机 error、首镜缺构建、
  继承段免自建）。
- `tests/services/test_storyboard_spatial_three_scene.py`：第一期 JSON 转换器
  测试保留（存量回退路径仍用）。
- 注意：涉及企业版门禁的用例在无许可证本地环境会 `LicenseAccessDenied`
  （预存行为，与本功能无关）。

## 8. 已知边界

- 结构化 spatial_layout 与 three_scene_code 由同一 LLM 输出并行产生，二者
  语义一致性目前靠 prompt 约束 + 人工核对（画中画取景器即核对工具），未做
  代码↔布局的自动交叉校验。
- 代码沙箱可访问注入对象的原型链（three.js 对象方法），不做深度隔离；预览
  为只读场景，风险面收敛在渲染函数内部。
- 快速模式（fast）不产出 three_scene_code，无 3D 入口（`hasSpatialLayout`
  同时认代码与存量 spatial_layout）。
