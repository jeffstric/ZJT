# 导演台节点（Director Stage）使用指南

## 概述

导演台节点提供类似 liblib 导演台的 3D 场景调度能力：在 3D 舞台上创建人偶、拖拽移动人偶、调整人偶姿态（预设 + 逐关节微调）、设置虚拟镜头机位，并将镜头画面导出为构图参考快照，供后续生图/生视频节点使用。支持时间轴关键帧调度：记录不同时刻的角色走位与运镜，播放预览整段调度动画。

## 功能

| 功能 | 说明 |
|------|------|
| 创建人偶 | 五种体型（男人/女人/小孩/胖子/瘦子）；空白人偶或从当前世界角色库创建（角色可按年龄/名称推断体型，循环配色） |
| 移动人偶 | 视口中左键拖拽人偶即在地面上移动（范围 ±9.5m），朝向/身高/离地高度用滑块调 |
| 姿态控制 | 12 种姿态预设（站立/T-Pose/行走/奔跑/坐姿/蹲姿/跳跃/挥手/指向/惊讶/思考/跪地），16 个关节 × XYZ 三轴滑块微调 |
| 镜头设置 | 11 种预设机位（平视/近景/全景/3/4侧/左右侧/背面/仰拍/俯拍/顶摄/过肩），FOV/机位/对焦中心可调，红色相机图标与黄色焦点球可直接拖拽 |
| 多机位 | 右栏「机位」组可添加多个命名机位（复制当前配置新建）：点击行切换为当前编辑机位（PiP/图标立即跟随），「更新」把当前相机存入该机位，✕ 删除（至少保留 1 个）；编辑全程直接改当前机位，`serializeData` 落盘时回写激活机位；旧数据仅有单 `camera` 字段时自动迁移为「镜头 1」 |
| 录制视频 | 顶栏「⏺ 录制视频」：时间轴回 0 从头播放，`MediaRecorder` 实时录制镜头画面（PiP canvas `captureStream(30)`，按浏览器支持优先 mp4 否则 webm）；播放结束自动停止，也可点「⏹ 结束录制」提前结束保留已录部分；上传后存 `node.data.recordUrl` 并在画布自动生成**视频节点**连线（可预览/下载/接后续生视频流程、加时间轴）；录制中关闭编辑器自动丢弃 |
| 镜头预览 | 右上角画中画实时显示最终镜头画面（分辨率随工作流画幅） |
| 时间轴调度 | 底部时间轴（时长 1~60 秒），**多轨道**：相机轨 + 每个人偶一条独立轨道，轨道左侧 ◆ 只记录该角色/相机、✕ 只删本轨最近键，各轨道关键帧密度/拖动互不影响；顶栏「◆ 记录关键帧」一次记录全部角色 + 相机；关键帧标记可点击跳转、拖动改时刻 |
| 切镜头 | 时间轴**每机位一条相机轨**：键落在哪条机位轨，画面就归哪个机位——跨轨接管即隐式硬切（到点瞬间跳变，无需开关）；同轨相邻键默认平滑运镜，轨上「切」按钮可把本轨最近键改为跳切（橙色竖条） |
| 播放动作 | 播放/暂停（空格）/停止按钮：逐轨道按时间插值驱动角色走位（位置/朝向线性插值、角度走最短路径）与相机运镜（机位/焦点/FOV 线性，cut 键阶梯跳变），移动中的人偶自动叠加行走步态摆动（髋/膝/手臂反相摆 + 重心起伏），拖拽人偶或相机会自动暂停 |
| 导出快照 | 按工作流画幅渲染镜头画面并上传；同时在画布上**自动创建展示该快照的图片节点并连线**（多次导出会依次纵向错开生成多个图片节点），可接入后续生图/生视频流程；播放中导出即当前帧画面 |
| 全景环境 | 与 360全景图节点融合：全景节点输出连到导演台绿色环境端口，全景即作为 3D 舞台背景（人偶在真实场景中摆位，快照含环境）；编辑器左栏支持环境旋转（yaw）、刷新、移除；断开连线或 Ctrl+Z 撤销连线后自动清除环境；未覆盖球面用边缘色填充。场景节点可一键生成全景再按此流程接入，见 [director_stage_scene_panorama.md](./director_stage_scene_panorama.md) |
| 数据持久化 | 全部场景数据（人偶/关节角/镜头/时间轴关键帧）序列化进 `node.data.directorData`，随工作流自动保存，重载画布后完整复原 |

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
| Delete | 删除选中人偶。导演台打开时 Delete / Backspace 不再冒泡到画布（不会删节点、不会拆掉录制和 WebGL）；输入框内仍留给文本编辑 |
| Ctrl+Z / 撤销按钮 | 编辑器内撤销（最多 50 步，含时间轴关键帧改动） |
| 空格 | 时间轴播放/暂停（输入框聚焦时不抢占） |
| 时间轴：点击/拖动空白轨道 | 移动播放头（scrub），视口实时应用该时刻插值位形 |
| 时间轴：轨道左侧 ◆ / ✕ | 在播放头时刻记录**该轨道**（单个角色或相机）/ 删除该轨道播放头附近的最近键 |
| 时间轴：机位轨（🎥 镜头 N） | 添加/删除机位自动增删对应相机轨；键落在某机位轨 = 该时刻起画面归该机位（跨轨硬切）；轨上 ◆/✕ 只操作本轨 |
| 时间轴：机位轨「切」 | 本轨最近键改为跳切（橙色竖条）/ 恢复平滑运镜；跨机位切换本身是硬切，无需此开关 |
| 时间轴：顶栏 ◆ 记录关键帧 | 一次记录所有角色 + 相机（兼容老用法） |
| 时间轴：点击关键帧标记 | 跳转到该关键帧时刻 |
| 时间轴：拖动关键帧标记 | 修改该关键帧时刻（仅本轨内重排，与相邻关键帧过近自动合并，不影响其他轨） |
| 机位：右栏「机位」组 | 点击行=切换为当前编辑机位；「更新」=当前相机存入该机位；「＋添加」=复制当前配置新建机位；✕=删除（至少保留 1 个） |
| ⏺ 录制视频 | 从头播放并实时录制镜头画面；再点一次或播完自动结束；上传后画布生成视频节点 |
| Esc / 保存并关闭 | 退出编辑器（数据自动保存；录制中关闭会丢弃未完成的录制） |

> 编辑视角（orbit 视角）只影响观察方式，不影响最终画面；最终画面由红色虚拟相机决定，见右上角画中画。

## 节点数据结构

```jsonc
{
  "type": "director_stage",
  "data": {
    "directorData": {
      "version": 2,
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
      "cameras": [                           // 多机位（version 4）：命名机位列表
        { "id": "cam1", "name": "镜头 1",
          "pos": [0, 1.5, 4.2], "target": [0, 1.05, 0], "fov": 35 }
      ],
      "activeCameraId": "cam1",              // 当前激活机位（编辑直接改运行时相机，落盘时回写该机位）
      "camera": { "pos": [0,1.5,4.2], "target": [0,1.05,0], "fov": 35 },
                                           // 冗余旧字段（= 激活机位快照，兼容旧版前端）；旧数据无 cameras 时自动迁移
      "timeline": {                        // 时间轴关键帧调度（version 2 新增；旧数据缺省为空）
        "duration": 6,                     // 总时长（秒，1~60）
        "tracks": [                        // 多轨道（version 3）：每机位一条相机轨 + 各人偶轨，键按时刻排序
          {                                // version 4 起相机轨带 id（机位）；v3 无 id 相机轨并入激活机位
            "kind": "camera",
            "id": "cam1",                  // 机位 id：键落在哪条机位轨，画面就归哪个机位（跨轨=硬切）
            "keys": [
              { "t": 0, "pos": [0,1.5,4.2], "target": [0,1.05,0], "fov": 35, "cut": false, "camId": "cam1" }
            ]                              // cut=true = 同轨跳切：到达该键前保持本轨上一键机位，到点跳变
          },
          {
            "kind": "camera",
            "id": "cam2",
            "keys": [
              { "t": 3, "pos": [1,1.2,3], "target": [0,1.05,0], "fov": 40, "cut": false, "camId": "cam2" }
            ]                              // 2.9s 前画面归 cam1 轨；3s 起 cam2 键接管 → 瞬间切到该机位
          },                             // camId = 记录时激活的机位（显示/排查用，求值仍以配置快照为准）
          {
            "kind": "puppet",
            "id": "p1",
            "keys": [
              { "t": 0, "x": -2, "z": 0,   "rotY": 0 },
              { "t": 3, "x": 2,  "z": 1.5, "rotY": 45 }
            ]
          }
        ]
      }
    },
    "snapshotUrl": "/upload/workflow/1/workflow_xxx.jpg",  // 最近导出快照
    "snapshotRatio": "16:9",
    "recordUrl": "/upload/workflow/1/workflow_xxx.webm"     // 最近录制视频（mp4/webm，随浏览器支持）
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
| `web/js/director_stage_timeline.js` | 时间轴模块：关键帧记录/拖动、插值驱动（角色走位 + 运镜）、播放控制与行走步态摆动；通过 `DirectorStageTimelineModule.attach` 挂载编辑器原型方法 |
| `web/js/director_stage_node.js` | 节点壳：菜单注册、缩略图/统计显示（人偶数/FOV/环境/关键帧数）、生成图片节点 |
| `web/css/director_stage.css` | 编辑器 overlay 与节点壳样式（编辑器固定深色主题，含时间轴样式） |

## 实现要点

- **节点注册**：与 camera_control 相同，走 `registerNodeType('director_stage', {createFn, createWithDataFn})`；重载画布时由 `restoreNodeByRegistry` 复原，再由 `updateDirectorStageNodeShell` 回填缩略图与统计。
- **人偶骨骼**：`buildPuppetRig` 按体型拼装（`BODY_TYPES`）。每个体型用一条躯干侧轮廓控制点列 `profile: [y, rx, rz, zOffset]`（y 相对髋节，zOffset 为该高度截面前移量）描述身体曲线，经 Catmull-Rom 插值成密集轮廓后，由髋/腰/胸三段 `LatheGeometry` 旋转曲面拼成一体成型躯干（苹果形胖子/沙漏女人/圆肚小孩等只靠改 profile）；三段分别挂 hipsY/spine/chest 关节，弯腰转胸时联动。四肢也是 lathe 肌肉轮廓曲面（上臂肱二头、小腿腓肠肌鼓起），两端收进体色加深的关节球；头部有下颌/鼻梁/眼睛，胖子带双下巴。体型 `man/woman/child/fat/thin` 共用同一关节层级。旧工作流缺 `bodyType` 时按男人复原。右栏可换体型。实现细节三条红线：① 轮廓插值必须用 Catmull-Rom，smoothstep 在控制点导数为零会留下环状棱线；② 躯干分段延伸段要从分界处连续收细（内段收细伸入外段），平行重叠会 z-fighting 出条纹；③ lathe 环绕接缝处的重复顶点要用 `weldLatheSeam` 焊平法线，否则正面留竖直接缝。
- **双渲染器**：主 renderer 渲染编辑视角；PiP renderer 以快照分辨率渲染虚拟相机画面，导出快照直接 `toDataURL`（隐藏网格/关节球/相机图标/名牌后渲染）。
- **相机/焦点/人偶拾取**：射线拾取的线段容差（`raycaster.params.Line.threshold`）必须收窄（设 0.05）。选中机位、对焦中心或人偶后显示世界坐标 RGB 轴（红 X / 绿 Y / 蓝 Z）；机位额外显示沿视线的琥珀色「焦距」轴。人偶绿轴改 `rootYOffset`（离地高度；鼠标世界位移除以人偶世界缩放，避免轴慢物快），红/蓝轴改地面 XZ。轴拖拽用「包含该轴、尽量朝向观察相机」的平面求交。快照渲染时隐藏轴向把手。
- **对焦标记与视线**：焦点为对焦十字 Sprite（Canvas 圆环+准线，自动面向渲染相机，带呼吸脉冲动画），相机到焦点画 LineDashedMaterial 虚线；选中焦点时标记与虚线变青色。这些 helper 在快照渲染时自动隐藏。
- **快照上传与图片节点**：dataURL → Blob → `uploadFile()`（`/api/video-workflow/upload`），URL 存入 `node.data.snapshotUrl`；随后调用 `createDirectorStageImageNode()` 在导演台节点右侧创建图片节点（`createImageNode` + 回填 `.image-preview` 预览与比例 + `state.connections` 连线），与 camera_control 生成图片节点的流程一致。
- **自动保存**：编辑器内每次结构性修改调用 `markDirty()`（防抖 400ms 后 `safeAutoSave()`），关闭时 `flushAutoSave()`。
- **时间轴模块**：`director_stage_timeline.js` 通过 `DirectorStageTimelineModule.attach(DirectorEditor, {clamp, round2, deg2rad})` 给编辑器原型挂载 `restoreTimeline / serializeTimeline / setupTimeline / recordTimelineKey(OnTrack) / deleteTimelineKeyAtPlayhead(OnTrack) / toggleCameraCutAtPlayhead / applyTimelineAt / tickTimeline / stopTimelineForClose` 等方法，编辑器在 `restoreFromData / serializeData / open / startLoop / close` 五个生命周期点接线。**多轨道模型**（version 3/4）：`tl.tracks` 为**每机位一条相机轨**（v4 起带机位 `id`）+ 每个人偶独立轨道，各自记录/拖动/删除互不影响；插值时逐轨 bracket 线性 lerp（朝向走最短角路径并归一到 ±180°），无轨人偶保持当前编辑位形，末键之后保持末帧。**切镜头**：相机键带 `cut` 标志（默认 false=平滑运镜），`cut=true` 表示到达该键瞬间硬切——段内保持上一键机位（u=0），到点跳变，求值在 `applyTimelineAt` 内阶梯化。播放只做预览：写回 `puppet.x/z/rotY` 与 `virtualCamCfg`（所见即所得，可停在任意帧继续编辑/记录），但**不 markDirty**，只有记录/删除/拖动关键帧、切镜、改时长才落盘；关闭时 `stopTimelineForClose` 停播、把播放头归零，并用 `restoreCommittedEditPose` 收回上次 `directorData` 里的站位（丢掉未提交的插值），再恢复关节姿态。重开后 `restoreFromData` 再 `applyTimelineAt(0)`，使 0 秒画面与起始关键帧一致，避免用末帧姿态覆盖 0 秒键。播放中移动速度 > 0.22m/s 的人偶叠加步态摆动（直接改 rig 关节旋转，`jointDeg` 不动；暂停/静止时 `applyJointDeg` 复原），用户拖拽人偶/相机时自动暂停避免插值打架。**兼容**：旧工作流无 `timeline` 字段按空时间轴复原；version 2 的 `keys` 全局快照在 `restoreTimeline` 自动迁移为 tracks（v1→v2→v3 兼容链）。序列化丢弃已删除人偶的轨道。节点壳 ⏱ 统计兼容两种格式。单测见 `web/js/director_stage_timeline.test.js`（vitest，fake 编辑器驱动插值/关键帧/播放/迁移/切镜逻辑）。
- **多机位**：`directorData.cameras` 为命名机位列表（`activeCameraId` 指向激活机位）。`virtualCamCfg` 仍是运行时唯一编辑对象（渲染/拖拽/gizmo 零改动）：切换机位 = 机位配置 copy 进 `virtualCamCfg`；编辑全程直接改 `virtualCamCfg`，`serializeData` 落盘时统一回写激活机位（零侵入同步点）。序列化同时输出冗余旧字段 `camera`（= 激活机位快照）兼容旧版前端；restore 优先 `cameras`，旧数据仅 `camera` 时自动迁移单镜头。撤销（`rebuildFromSnapshot`）走同一个 `restoreCamerasFromData`，并且必须在 `restoreTimeline` 之前完成：否则激活机位还停在撤销前，紧接着的 `serializeData` 会把上一台机位的姿态写进当前机位，已删除机位的相机轨也会在序列化时被滤掉。**时间轴每机位一条相机轨**（`{kind:'camera', id}`，添加/删除机位自动增删 lane）。
- **切镜头求值（多机位接管）**：任一相机轨的键 = 「该时刻起画面归该机位」。求值找 ≤t 的最后一个键（跨存活机位轨）→ 所在轨为接管轨，在接管轨内按自己的键插值（同轨相邻键线性运镜、`cut=true` 跳切；未激活机位的轨仍按自己的键插值，重新接管时呈现其当前位形）；**跨轨接管即隐式硬切**（到点瞬间跳变）。机位删除后其轨不参与求值且序列化剔除。旧数据迁移：v3 无 id 相机轨整体并入激活机位轨（cut 语义原样保留），v2 全局快照同路径。时间轴相机键带 `camId`（记录时激活机位，显示用）。
- **录制视频**：顶栏「⏺ 录制视频」= `pipCanvas.captureStream(30)` + `MediaRecorder`（mime 按 `isTypeSupported` 探测 mp4→webm），时间轴回 0 从头播放，播完/停止自动 `stop()`，`onstop` 里 Blob→`uploadFile`（上传白名单已支持 mp4/webm 魔数）→ `node.data.recordUrl` + `createDirectorStageVideoNode` 画布视频节点（预览回填逻辑与 `workflow.js createVideoNodeWithData` 一致：`setupVideoThumbnail` + name/duration 元数据）。录制中关闭编辑器 `discardRecording` 丢弃半成品；播放中 scrub 自动暂停只停画面推进，录制仍按实时继续（实时录制语义）。接线断言见 `web/tests/director_stage_camera_record.test.js`。
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
- 时间轴关键帧只记录人偶位置/朝向与相机三要素：关节姿态、身高/离地/缩放不参与插值（姿态在整个时间轴上保持关键帧记录时的关节角）；步态摆动仅为播放预览效果，不出现在关键帧数据与快照中。
- 录制视频为**实时 1x 录制**（60s 时间轴需录 60s）、无音频轨；产出格式随浏览器（Chrome/Edge 多为 webm，部分环境可 mp4）；需要精确帧率/非实时合成可后续扩展"离线逐帧渲染 + 后端 ffmpeg"方案。

## 使用流程

1. 画布左下 `+` → 添加节点 → **导演台**，点击画布放置节点。
2. 点击节点上的 **🎬 打开导演台** 进入全屏编辑器。
3. 左栏 **＋添加人偶**：先选体型（男人/女人/小孩/胖子/瘦子），再添加空白人偶或世界角色 → 拖拽摆位。选中后可在右栏改体型。
4. 选中人偶后从左栏姿态预设一键应用，或在右栏逐关节微调。
5. 右栏切换 **镜头设置**：顶部「机位」组管理多个命名机位（＋添加复制当前配置，点击行切换，「更新」回存）；选择预设机位并微调 FOV/焦点，观察右上角画中画。
6. （可选）时间轴调度：把播放头停在 0s，摆好起始走位与机位 → 顶栏 **◆ 记录关键帧**（或只记录某条轨：轨道左侧 ◆）→ 拖动播放头到下一时刻，移动人偶/调整相机 → 再记录。多人场景各人偶轨道互不影响，可分别布键。**切镜头（多机位）**：时间轴上每个机位一条相机轨（添加机位自动出现）。在要切换的时刻，先点机位组里目标机位那行（激活它），再在其时间轴轨道上 ◆ 记录——播放到该键画面瞬间切到该机位（跨轨即硬切）；同一机位轨内布多个键则是平滑运镜，需要跳切时把播放头移到键上点「切」变橙色竖条。→ **▶ 播放**（空格）预览，随时暂停微调后重记。
7. 点击 **📷 导出快照**：镜头画面上传后，节点缩略图更新，画布右侧自动生成展示该快照的图片节点并连线（播放中导出即当前帧画面）。
8. （可选）点击 **⏺ 录制视频**：时间轴从头播放并实时录制镜头画面（含走位/运镜/切镜/步态摆动），播放结束自动停止；上传后存 `node.data.recordUrl`，画布自动生成**视频节点**并连线，可预览、下载、接入生视频节点或加入主时间轴。
9. **保存并关闭**；图片/视频节点可直接接入后续生图/生视频流程。
