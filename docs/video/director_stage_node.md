# 导演台节点（Director Stage）使用指南

## 概述

导演台节点提供类似 liblib 导演台的 3D 场景调度能力：在 3D 舞台上创建人偶、拖拽移动人偶、调整人偶姿态（预设 + 逐关节微调）、设置虚拟镜头机位，并将镜头画面导出为构图参考快照，供后续生图/生视频节点使用。

## 功能

| 功能 | 说明 |
|------|------|
| 创建人偶 | 五种体型（男人/女人/小孩/胖子/瘦子）；空白人偶或从当前世界角色库创建（角色可按年龄/名称推断体型，循环配色） |
| 移动人偶 | 视口中左键拖拽人偶即在地面上移动（范围 ±9.5m），朝向/身高/离地高度用滑块调 |
| 姿态控制 | 12 种姿态预设（站立/T-Pose/行走/奔跑/坐姿/蹲姿/跳跃/挥手/指向/惊讶/思考/跪地），16 个关节 × XYZ 三轴滑块微调 |
| 镜头设置 | 11 种预设机位（平视/近景/全景/3/4侧/左右侧/背面/仰拍/俯拍/顶摄/过肩），FOV/机位/对焦中心可调，红色相机图标与黄色焦点球可直接拖拽 |
| 镜头预览 | 右上角画中画实时显示最终镜头画面（分辨率随工作流画幅） |
| 导出快照 | 按工作流画幅渲染镜头画面并上传；同时在画布上**自动创建展示该快照的图片节点并连线**（多次导出会依次纵向错开生成多个图片节点），可接入后续生图/生视频流程 |
| 全景环境 | 与 360全景图节点融合：全景节点输出连到导演台绿色环境端口，全景即作为 3D 舞台背景（人偶在真实场景中摆位，快照含环境）；编辑器左栏支持环境旋转（yaw）、刷新、移除；断开连线或 Ctrl+Z 撤销连线后自动清除环境；未覆盖球面用边缘色填充。场景节点可一键生成全景再按此流程接入，见 [director_stage_scene_panorama.md](./director_stage_scene_panorama.md) |
| 数据持久化 | 全部场景数据（人偶/关节角/镜头）序列化进 `node.data.directorData`，随工作流自动保存，重载画布后完整复原 |

## 交互速查

| 操作 | 效果 |
|------|------|
| 悬停对象 | 光标变化（人偶=抓手、相机/焦点=移动箭头）+ 跟随鼠标的气泡提示，说明该对象可做什么 |
| 左键点击人偶 | 选中，右栏显示人偶属性与关节滑块，人偶处出现 RGB 轴 |
| 左键拖拽人偶 | 拖身体：地面平面移动（XZ）；拖红/绿/蓝轴：只沿 X / 高度 / Z 移动 |
| 点击黄色关节球 | 选中该关节，右栏定位到对应滑块 |
| 左键点击/拖拽相机图标 | 选中后出现 RGB 轴（红 X / 绿 Y 高度 / 蓝 Z）和琥珀色焦距轴；拖机身仍是水平移动，拖绿轴改高度，拖焦距轴改 FOV |
| 左键点击/拖拽对焦十字 | 选中后同样出现 RGB 轴；拖绿轴调节焦点高度，红/蓝轴水平移动 |
| 拖拽过程中 | 顶部蓝色横幅实时显示当前模式（旋转视角/平移视角/移动人偶/移动机位/移动对焦中心），并说明是否影响镜头画面 |
| 左键拖拽空白处 | 旋转编辑视角（orbit），横幅提示"只改变观察角度，不影响镜头画面" |
| 右键拖拽 | 平移编辑视角 |
| 滚轮 | 编辑视角推近/拉远 |
| 点击空白 | 取消所有选中（人偶/相机/焦点） |
| Delete | 删除选中人偶 |
| Ctrl+Z / 撤销按钮 | 编辑器内撤销（最多 50 步） |
| Esc / 保存并关闭 | 退出编辑器（数据自动保存） |

> 编辑视角（orbit 视角）只影响观察方式，不影响最终画面；最终画面由红色虚拟相机决定，见右上角画中画。

## 节点数据结构

```jsonc
{
  "type": "director_stage",
  "data": {
    "directorData": {
      "version": 1,
      "environment": {          // 全景环境（来自 360全景图节点连线；null 表示无）
        "url": "/upload/workflow/1/pano.jpg",
        "ratio": "21:9",        // 决定环境球贴面范围（换算同 panorama 的 computePanoramaFov）
        "yaw": 0,               // 环境水平旋转（度）
        "horizonY": 1.5,        // 照片地平线对应的世界高度（米），默认 1.5
        "sceneScale": 1,        // 人偶相对全景的倍率（0.5~4）
        "groundY": 0,           // 脚底高度（米），负值下落到可见地面，避免悬空
        "autoFitDone": false    // 已做过 VL 对齐或已降级手动，避免每次打开都重跑
      },
      "puppets": [
        {
          "id": "p1", "name": "主角", "color": "#4f8ef7",
          "bodyType": "man",                 // man / woman / child / fat / thin
          "characterId": null, "characterName": "",
          "x": -0.6, "z": 0, "rotY": 0,        // 地面位置与朝向（度）
          "rootYOffset": 0, "scale": 1,          // 离地下沉(坐/蹲)与身高缩放
          "pose": "run",                          // 预设名，手动调过后为 "custom"
          "joints": { "shoulderL": [58,0,12], "..." : [x,y,z] }  // 关节欧拉角(度)
        }
      ],
      "camera": {
        "pos": [0, 1.5, 4.2],      // 机位坐标
        "target": [0, 1.05, 0],    // 对焦中心
        "fov": 35                  // 垂直视场角
      }
    },
    "snapshotUrl": "/upload/workflow/1/workflow_xxx.jpg",  // 最近导出快照
    "snapshotRatio": "16:9"
  }
}
```

关节名与轴约定（人偶面向 +Z，度）：

- 肩/髋 `X:-θ` = 向前抬；肘 `X:-θ` = 向前弯；膝 `X:+θ` = 向后弯
- 侧抬臂 `Z`：左臂为正、右臂为负（如左侧平举 `shoulderL.Z=+86`）
- 躯干（腰/胸）`X:+θ` = 前倾；头颈三轴自由

## 文件结构

| 文件 | 说明 |
|------|------|
| `web/assets/vendor/three.min.js` | three.js r128（UMD 本地化，MIT） |
| `web/js/director_stage_editor.js` | 3D 编辑器核心：人偶骨骼构建、姿态预设、镜头控制、raycast 交互、快照渲染导出、撤销栈 |
| `web/js/director_stage_node.js` | 节点壳：菜单注册、缩略图/统计显示、生成图片节点 |
| `web/css/director_stage.css` | 编辑器 overlay 与节点壳样式（编辑器固定深色主题） |

## 实现要点

- **节点注册**：与 camera_control 相同，走 `registerNodeType('director_stage', {createFn, createWithDataFn})`；重载画布时由 `restoreNodeByRegistry` 复原，再由 `updateDirectorStageNodeShell` 回填缩略图与统计。
- **人偶骨骼**：`buildPuppetRig` 按体型拼装（`BODY_TYPES`）。每个体型用一条躯干侧轮廓控制点列 `profile: [y, rx, rz, zOffset]`（y 相对髋节，zOffset 为该高度截面前移量）描述身体曲线，经 Catmull-Rom 插值成密集轮廓后，由髋/腰/胸三段 `LatheGeometry` 旋转曲面拼成一体成型躯干（苹果形胖子/沙漏女人/圆肚小孩等只靠改 profile）；三段分别挂 hipsY/spine/chest 关节，弯腰转胸时联动。四肢也是 lathe 肌肉轮廓曲面（上臂肱二头、小腿腓肠肌鼓起），两端收进体色加深的关节球；头部有下颌/鼻梁/眼睛，胖子带双下巴。体型 `man/woman/child/fat/thin` 共用同一关节层级。旧工作流缺 `bodyType` 时按男人复原。右栏可换体型。实现细节三条红线：① 轮廓插值必须用 Catmull-Rom，smoothstep 在控制点导数为零会留下环状棱线；② 躯干分段延伸段要从分界处连续收细（内段收细伸入外段），平行重叠会 z-fighting 出条纹；③ lathe 环绕接缝处的重复顶点要用 `weldLatheSeam` 焊平法线，否则正面留竖直接缝。
- **双渲染器**：主 renderer 渲染编辑视角；PiP renderer 以快照分辨率渲染虚拟相机画面，导出快照直接 `toDataURL`（隐藏网格/关节球/相机图标/名牌后渲染）。
- **相机/焦点/人偶拾取**：射线拾取的线段容差（`raycaster.params.Line.threshold`）必须收窄（设 0.05）。选中机位、对焦中心或人偶后显示世界坐标 RGB 轴（红 X / 绿 Y / 蓝 Z）；机位额外显示沿视线的琥珀色「焦距」轴。人偶绿轴改 `rootYOffset`（离地高度；鼠标世界位移除以人偶世界缩放，避免轴慢物快），红/蓝轴改地面 XZ。轴拖拽用「包含该轴、尽量朝向观察相机」的平面求交。快照渲染时隐藏轴向把手。
- **对焦标记与视线**：焦点为对焦十字 Sprite（Canvas 圆环+准线，自动面向渲染相机，带呼吸脉冲动画），相机到焦点画 LineDashedMaterial 虚线；选中焦点时标记与虚线变青色。这些 helper 在快照渲染时自动隐藏。
- **快照上传与图片节点**：dataURL → Blob → `uploadFile()`（`/api/video-workflow/upload`），URL 存入 `node.data.snapshotUrl`；随后调用 `createDirectorStageImageNode()` 在导演台节点右侧创建图片节点（`createImageNode` + 回填 `.image-preview` 预览与比例 + `state.connections` 连线），与 camera_control 生成图片节点的流程一致。
- **自动保存**：编辑器内每次结构性修改调用 `markDirty()`（防抖 400ms 后 `safeAutoSave()`），关闭时 `flushAutoSave()`。
- **全景环境连线**：环境端口走主 `state.connections`，`portType: 'environment'`。`serializeWorkflow` 会持久化该字段；旧快照缺 `portType` 时，恢复阶段把「全景 → 导演台」补成环境连线。删除连线走 `removeConnection` → `handleDirectorStageEnvDisconnect`；Ctrl+Z 走 `restoreWorkflow` → `syncDirectorStageEnvironments()`，避免「连线没了但环境还在」。
- **环境球**：贴面范围与全景节点 `computePanoramaFov` 一致；未覆盖区域用全景图边缘色做内壁衬底，左栏在非 360° 或比例不一致时给出提示。
- **人偶与房间尺度**：360 只有角度没有米。加载环境时球心默认抬到 `horizonY=1.5m`。随后用镜头预览图调用 `POST /api/video-workflow/fit-environment` 估计 `horizonY` / `sceneScale` / `groundY`（贴地，负值把脚落到可见地面）。接口必须携带 `Authorization`，并只读取 token 所属用户的 `upload/workflow/<user_id>` 图片；越权路径、路径穿越和非图片扩展名会被拒绝。未配置视觉模型时 `fallback=manual`，用左栏「地平线」「场景比例」「贴地」滑块手动调。
- **连线点选**：画布 `mousedown` 忽略 `path.hitbox`，避免重建 SVG 吞掉 click（真实点击与 Playwright 均可选中后 Delete）。
- **i18n**：节点壳文案走 `web/i18n/locales/{zh-CN,en}/video_workflow.json`（`director_stage_*` 前缀）；编辑器内部为中文固定文案。
- **事件清理**：编辑器所有监听收集在 `bound` 数组，关闭时统一移除并 dispose 两个 renderer 与几何体/纹理，避免内存泄漏。

## 已知限制

- 人偶为风格化木偶（非真实人体模型），快照适合作为构图/姿态参考图，配合图片生成节点的参考图能力使用效果最佳。
- 过肩机位基于选中人偶（或第一个人偶）动态计算。
- 编辑器视角的平移/缩放不会持久化，重开编辑器回到默认视角（虚拟相机数据始终保留）。
- 全景环境球按节点 `ratio` 换算贴面（与 Pannellum 一致）。2:1 图配 21:9 仍会有轻微垂直裁剪/拉伸；非 360° 画幅的缺口用边缘色填充，左栏会提示建议使用 2:1 全景。

## 使用流程

1. 画布左下 `+` → 添加节点 → **导演台**，点击画布放置节点。
2. 点击节点上的 **🎬 打开导演台** 进入全屏编辑器。
3. 左栏 **＋添加人偶**：先选体型（男人/女人/小孩/胖子/瘦子），再添加空白人偶或世界角色 → 拖拽摆位。选中后可在右栏改体型。
4. 选中人偶后从左栏姿态预设一键应用，或在右栏逐关节微调。
5. 右栏切换 **镜头设置**，选择预设机位并微调 FOV/焦点，观察右上角画中画。
6. 点击 **📷 导出快照**：镜头画面上传后，节点缩略图更新，画布右侧自动生成展示该快照的图片节点并连线。
7. **保存并关闭**；图片节点可直接接入后续生图/生视频流程。
