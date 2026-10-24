# 分镜 3D 空间：LLM 直出 three.js 代码方案（v2，现行）

- 状态：已实施（第二期，替代第一期「结构化 JSON + 确定性转换」方案；
  机位编辑见 §9）
- 日期：2026-10-15（§9 机位编辑 2026-10-16）
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
- **渲染**：世界对象（角色人偶为 LibTV 风格胶囊小人——蛋形无脸头、
  面甲深色带指示朝向、球关节四肢；道具、半透明场景体块）+ 机位视锥
  取景框 + **镜头视角画中画**（用本镜 setCamera 的相机经 setScissor 分屏
  渲染，右下角取景器，DOM 只画边框标题）。取景画幅跟随故事板
  `workflowRatio`（9:16 竖屏故事板 → 竖屏 PiP 与竖窄视锥），空镜可见性
  检查同比例；不得硬编码 16:9。
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
  代码↔布局的自动交叉校验。**例外**：3D 预览与导演台转换均已内置「空镜
  检查」（`cameraSeesActors` 视锥投影，重放后计算角色是否在机位视野内；
  实测 LLM 会产出"机位背对所有角色"的空镜，如分镜机位先行等待角色走位
  的规划），空镜时预览一致性诊断报 warning、导演台转换 toast 提示。
- 代码沙箱可访问注入对象的原型链（three.js 对象方法），不做深度隔离；预览
  为只读场景，风险面收敛在渲染函数内部。
- 快速模式（fast）不产出 three_scene_code，无 3D 入口（`hasSpatialLayout`
  同时认代码与存量 spatial_layout）。
- LLM 偶发引用未创建实体（如 moveProp 引用没有 makeProp 过的道具），重放
  按契约报错收集（预览诊断/导演台 console.warn），不中断后续镜头。

## 9. 机位编辑（第三期，2026-10-16）

预览从只读升级为可编辑：**手动控制 + 对话调整**，二者共用同一条保存管线。
`setCamera` 行是机位唯一真源——所有修改都是改写本镜 `three_scene_code`
的最后一个 `setCamera(...)` 调用参数并保存（`PUT /scene/{id}/prompt`），
增量链下游镜头不受影响（每镜必调 setCamera，改本镜只影响本镜取景）。

### 9.1 手动控制（参考导演台 `director_stage_editor.js`）

- **主视图拖拽**：机位 gizmo 的相机方块（`userData.dragKind='camera'`）
  在 `y=eye.y` 水平面拖动改位置、黄色焦点球（`'focus'`，仿导演台）在
  `y=target.y` 平面拖动改朝向；未命中 gizmo 仍是轨道观察，互不干扰。
- **侧栏「机位控制」**：FOV / 机位高度 / 焦点高度 / 焦点前后 / 焦点左右
  五滑杆 + 11 个预设机位（正面平视/近景/全景、3/4 侧、左右侧、背面、
  仰拍、俯拍、顶摄；预设相对场景包围盒中心计算，移植导演台
  `CAMERA_PRESETS` 并适配任意焦点）。
- **保存**：滑杆 change / 拖拽松手 / 预设点击 → 600ms 防抖
  `rewriteSetCamera` 改写 → 保存 → 失败回滚缓存；切镜与关闭前强制
  flush（防串镜）。旧 JSON 方案分镜不开放机位编辑。

### 9.2 对话改机位（入口：弹窗底部输入条）

```
输入指令 + 当前 cameraInfo + 重放对象清单（actors/props/stage 坐标与朝向）
  → POST /api/storyboard/scene/{id}/camera-chat（storyboard:update）
  → services/storyboard_camera_chat.py：单轮文本 LLM 参数提取
    （SYSTEM_PROMPT 摄影指导契约，get_llm_client + asyncio.to_thread 非阻塞）
  → 返回 {success, camera:{eye,target,fov}, reason}
  → 前端 _applyShotCamera 应用（画中画/gizmo 即时更新）+ 同 §9.1 保存管线
```

- 服务模式仿 `director_stage_env_fit.py`（单轮提取 + JSON 解析 + clamp
  + 失败降级文案）；超时/范围常量在 `config/constant.py`
  `SB_CAMERA_CHAT_*`。
- API 不落库：解析与保存解耦，机位写入仍走统一的 setCamera 改写管线，
  保证「代码唯一真源」不被第二条写路破坏。
- 模型取故事板顶栏当前选中的对话模型（`resolveSelectedLlmModel`）。

### 9.3 测试

- `web/tests/spatial_camera_edit.test.js`（vitest 14 例）：
  `findLastSetCameraCall` 定位/跨行/fov 省略/防 resetCamera 误匹配、
  `rewriteSetCamera` 替换与追加/幂等、clamp、预设计算。
- `tests/services/test_storyboard_camera_chat.py`（8 例）：消息组装
  （机位/实体清单/截断）、JSON 解析（围栏/超界 clamp/缺字段）、缺模型降级。

### 9.4 导出至导演台（工作流画布）

故事板 → 工作流转换时 `three_scene_code` 随 shotJson 透传到分镜帧节点；
分镜帧「🎬 打开导演台（3D 空间）」按钮经轻量记录器重放（不依赖
three.js）把该镜空间映射为导演台人偶与机位，首次点击自动创建导演台
节点并连线。详见
`docs/storyboard/storyboard_workflow_conversion.md` §3D 空间 → 导演台；
实现 `web/js/director_stage_from_storyboard.js`，测试
`web/tests/director_stage_from_storyboard.test.js`（13 例）。

**画布导演台也支持对话改机位**：编辑器视口左下对话条（模型下拉 + 输入
+ 发送），走 `POST /api/video-workflow/camera-chat`（与故事板共用
`parse_camera_instruction`；LLM 输入注入导演台人偶坐标）。应用后随
工作流 400ms 防抖自动保存落库。机位 eye/target 双格式（数组/对象）
在前后端全链路兼容。
