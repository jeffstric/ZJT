# 场景图生成 360 全景，再接入导演台

## 背景

导演台已能把 **360 全景图节点** 的输出接到环境口，作为 3D 舞台背景。用户希望 **先从场景图出发** 生成 360 全景，而不是在导演台里另开一套生成入口。

画布「360全景图」节点已具备文生/图生 equirect（`POST /api/text-to-image` 或 `/api/image-edit`，`buildPanoramaPrompt` 补投影后缀）。本能力 **不新开生图后端、不改导演台环境接入**，只在场景节点上加一键入口，把场景图连到现有全景节点。

## 目标

1. 场景节点上有 **「生成360度全景图」** 按钮。
2. 点击后：创建（或复用）360 全景图节点，并把场景输出连到全景输入（参考图）。
3. 用场景名称 + 描述填入全景提示词；有参考图则走图生全景，没有则文生。
4. 后续流程不变：全景节点自己生成、预览；全景输出再连导演台绿色环境口。

## 非目标

- 不在导演台左栏再做一套「输入场景生成全景」表单。
- 不新增生图供应商或专用 360 模型接口。
- 不自动把新全景连到导演台（用户按原流程自己连，或连已有全景）。

## 用户流程

```
场景节点  →  [生成360度全景图]
                │
                ▼
        创建/复用 360全景图节点
        连线：场景 output → 全景 input
        填入名称+描述，提交生成
                │
                ▼
        全景节点查看器（原有）
                │
                ▼
        全景 output → 导演台环境口（原有）
```

1. 画布上已有场景节点（从「添加素材 → 场景」放入，带参考图或描述）。
2. 点场景节点上的 **生成360度全景图**。
3. 右侧出现 360 全景图节点，连线已接上；提示词带入场景名和描述，开始生成。
4. 生成完成后，在全景节点里拖拽预览。
5. 把全景节点输出拖到导演台绿色环境口（与原来一样）。

也可不点按钮，手动把场景输出端口拖到全景输入端口，再在全景节点里点「生成全景图」。

同一场景再次点击按钮：复用已连接的全景节点并重新生成，不重复铺节点。

## 场景输入从哪来

| 来源 | 提示词 | 参考图 | 说明 |
|------|--------|--------|------|
| 场景节点 | `{名称}。{描述}` + 全景后缀 | `reference_image`（若有） | 主路径 |
| 仅有参考图、无描述 | 默认英文「与参考图同一地点、完整 360 环绕」 | 参考图 | 走图生全景 |
| 仅有描述、无参考图 | 名称+描述 + 全景后缀 | 无 | 走文生全景 |
| 两者都无 | — | — | toast，不创建节点 |

中文描述照常提交；`buildPanoramaPrompt` 会补 `360 degree equirectangular panorama, seamless horizontal wrap, horizon at the vertical center` 和工作流画风。

## 架构

```
场景节点按钮
        │
        ▼
window.createPanoramaFromLocation(locationNodeId)
        │  创建或复用 panorama 节点
        │  state.connections: location → panorama
        │  写入 prompt（空才填）
        ▼
el._generatePanorama()                 // panorama_node.js 现有提交+轮询
        │  参考图：getPanoramaRefImageUrl()
        │    image → data.url / preview
        │    location → data.reference_image
        │  POST /api/image-edit 或 /api/text-to-image
        ▼
poll 成功 → node.data.url（查看器点亮）
        │
        ▼
用户把全景输出连到导演台环境口（不变）
        │  已有 onConnect：写入 directorData.environment
        ▼
setupEnvironment() + fitEnvironment()
```

### 改动文件

| 文件 | 职责 |
|------|------|
| `web/js/panorama_node.js` | 输入口接受 `image` + `location`；`getPanoramaRefImageUrl`；`createPanoramaFromLocation`；抽出 `el._generatePanorama` |
| `web/js/events.js` | 场景节点按钮；场景拖线可吸附全景输入口 |
| `web/i18n/locales/{zh-CN,en}/video_workflow.json` | 按钮与 toast 文案 |

工作流重载：场景节点 `createLocationNodeWithData` 会重新画出按钮并绑定；连线在 `state.connections` 里随工作流恢复。

## 失败与降级

- 场景无图无描述：toast，不创建节点。
- 全景任务已在生成中：选中已有全景节点，toast「正在生成」，不重复提交。
- 无 VL / 生图失败：全景节点自己报错；导演台环境接入不受影响。
- 未配置 VL 时，导演台对齐仍走手动滑块（与本入口无关）。
