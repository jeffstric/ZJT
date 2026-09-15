# 视频工作流自动保存上传去重门 + 服务端内容哈希 CAS

## 背景：ECS 公网出带宽周期性打满

生产入口流量经 frp 转发（用户 → ECS:80 → frp 隧道 → 本机 5173）。曾出现 ECS
公网出带宽周期性高峰（均值 ~5 Mbps、峰值 8.3 Mbps 触顶），排查结论：

1. **触发链**：前端每 60s 轮询 `/api/video-workflow/{id}/poll-status`
   （`web/js/workflow.js` 的 `pollWorkflowNodeStatus`），只要返回的
   `updated_nodes` 非空就调用 `autoSaveWorkflow()` 做**全量 PUT**。
2. **空转放大**：poll-status 服务端只返回「`project_id` 非空且 `url` 为空」
   的节点。**失败节点**（status=-1 永远没有结果 url）与 **CDN PENDING 节点**
   每一轮都会重复返回；前端对前者只是重复赋相同的 `error` 文案、对后者不写
   任何字段——**序列化内容逐字节不变，却每 60 秒全量上传一次**。
3. **请求体巨大**：`workflow_data` 存在结构性冗余（每个 `shot_frame` 节点嵌入
   全量 `scriptData`，`videoPrompt` 与 `shotJson` 内容重复），单个工作流可达
   9~18MB。多个挂机页面叠加即打满带宽。

## 方案：body 基线 + 服务端权威内容哈希双条件去重，PUT 携带 CAS

纯前端基线（仅比较本地已确认 body）存在一个无法自愈的窗口：在途旧请求
迟到落库（abort 对已到达服务端的请求不可撤回）、或其他标签页/用户写入时，
前端无从感知服务端内容已变，门可能继续错误地跳过。因此引入**服务端权威
内容哈希**，前端只持有/比较/透传，**绝不自行计算**：

- `workflow_data` 是 MySQL `json` 列，入库会被规范化（key 排序/空白/数字
  格式），JS 与 Python 的序列化差异无法对齐——哈希只能由服务端对解析后的
  Python 对象规范化计算（`model/video_workflow.py` 的
  `compute_content_hash()`：`json.dumps(sort_keys=True, separators=...)` +
  PUT 可写标量字段，sha256）；前端本地比对仍用字符串 `===`
  （http 非 secure context 下 `crypto.subtle` 不可用，且零碰撞零依赖）。
  **例外：`workflow_data.viewport`（panX/panY/zoom）不参与哈希**——视口是
  各端本地视图状态，不同用户缩放/平移必然不同，参与会导致「内容没变、仅
  视角不同」也互相 CAS 409；存储与恢复不受影响。
- 哈希实时计算，**无 schema 变更**；poll-status 每轮搭车返回，不增加请求。
- **非阻塞**：`workflow_data` 单工作流可达 9~18MB，解析+序列化+sha256 是
  数百毫秒级 CPU——GET/poll/PUT 全部经 `asyncio.to_thread` 在工作线程计算
  （`server.py` 的 `_content_hash_of` 辅助函数；GET/poll 复用已解析的 dict，
  避免大 JSON 二次解析；PUT 的 CAS 校验与写后回读哈希在单个线程跳转内完成）。
  `compute_content_hash(workflow, workflow_data=None)` 支持调用方传入已解析
  dict 复用，口径不变。

### 服务端（`server.py`）

| 端点 | 行为 |
|------|------|
| GET `/api/video-workflow/{id}` | 响应 `data.content_hash` |
| GET `/poll-status` | 响应 `data.content_hash`（含无节点早退分支），每轮刷新前端「最近一次看到的服务端哈希」 |
| PUT `/api/video-workflow/{id}` | 携带 `X-Base-Hash` 头时做 CAS：当前哈希不一致 → **拒绝写入**，返回 **HTTP 409** + `{"code": 409, data: {content_hash}}`（以真实 HTTP 状态码返回，网关/监控才能统计冲突率；前端按 `result.code === 409` 判断不受影响）；成功返回 `data.content_hash`（写入后最新值）。头部缺省 = 不做 CAS（兼容旧客户端） |

#### 原子性：content_version 列（迁移 no_130）

读哈希（`asyncio.to_thread`，含 await 点）与 UPDATE 之间仍可能并发写入，
check-then-act 在多 worker 部署下会互相覆盖。因此 UPDATE 追加乐观锁条件：

```sql
UPDATE video_workflow SET ..., content_version = content_version + 1
WHERE id = ? AND content_version = ?   -- 读哈希时读到的版本号
```

affected = 0（版本竞争失败，并发写已抢先）同样按 HTTP 409 拒绝并返回当前
哈希——校验与写入收敛为单条原子 CAS，不再依赖「近似串行」。版本号为服务端
内部状态，客户端仍只交互 `X-Base-Hash`/`content_hash`，协议不变。强制覆盖
路径（不带 `X-Base-Hash`）不加版本条件，但仍自增版本号，使并发 CAS 写立刻
失效。副作用修复：版本号自增使同值保存也稳定 affected=1，不再受 pymysql
「只计值变化行」口径影响。

### 前端状态机（`web/js/auto_save_state.js`）

| 方法 | 说明 |
|------|------|
| `setConfirmedBody(workflowId, body, serverHash)` | 记录服务端已确认的 body 基线及其内容哈希 |
| `isConfirmedBody(workflowId, body)` | 去重门：body 逐字节一致 **且**（双方哈希已知时）最近一次 poll 哈希 == 基线哈希；任一侧哈希未知退化为纯 body 比较（滚动发布兼容） |
| `noteServerHash(workflowId, hash)` | 每轮 poll-status/GET/PUT 响应刷新「服务端当前哈希」——服务端被改写的唯一感知通道 |
| `getConfirmedHash(workflowId)` | PUT 的 `X-Base-Hash` 取值（CAS 基值） |
| `getLastSeenServerHash(workflowId)` | 最近感知到的服务端哈希，仅用于去重门失效判断；**不得**用作冲突快照的 `baseHash`（否则刷新重放会覆盖他人内容） |
| `noteConflict(workflowId)` / `isConflictBlocked(workflowId)` | 409 冲突熔断：自动保存静默跳过直到成功保存/reset 解除 |
| `confirmSkipped()` | 门命中跳过上传后推进 `confirmedVersion`，保证关页 `isDirty()` 归零、不会触发 keepalive 补发绕过门 |
| `reset()` | 同时清理基线与已知服务端哈希 |

### 门的位置与基线来源（`web/js/workflow.js`）

`autoSaveWorkflow()` 在 body 构造后、发起请求前过门；手动 `saveWorkflow()`
同样过门（内容未变且服务端未漂移时跳过 PUT 并提示「内容没有变化，无需
保存」——无变化的手动保存若落库，serialize/restore 往返差异会翻动服务端
哈希，误伤其他在线用户的 CAS）。基线有三个写入点：

1. **自动/手动 PUT 返回 `code === 0`**——以响应 `data.content_hash` 滚动基线
   （失败不记录，下次照常重传，不存在假确认丢数据）；
2. **`loadWorkflow` 成功后**——加载即基线；哈希取 `baselineHash`：从 GET
   返回值起步，加载期内本页自写 PUT（`from_world_id` 世界同步、世界画风
   自动继承）每成功一次就用其响应 `data.content_hash` 滚动一次（见下节）；
3. 恢复重放（`maybeRecoverPendingAutoSave`）成功后重新 `loadWorkflow`，
   基线随重放后的最新服务端内容重建；
4. **`loadWorkflow` 建基线 3s 后延迟重建一次**（用户无编辑 `isDirty()` 为
   false、基线哈希未被重放/保存滚动时）——吸收还原期异步回填（见下下节），
   回填值与服务端等价，不落库、只对齐基线。

### 还原期幽灵修改必须消灭（「多会话零操作互判冲突」根因修复）

**约定：`restoreWorkflow` 的节点还原必须保证 serialize/restore 往返一致
——还原后的序列化结果必须与 GET 到的服务端内容逐字节等价；任何"打开页面
就改内容"的代码都会转化为零操作自动保存落库，并使其他在线会话的 CAS 基线
过期（409 冲突框）。**

事故链（修复前，双标签页实测复现）：同一工作流开两个标签页 A/B。A 打开时
还原缺陷把 `splitModel*` 清空后又回填、8 个分镜节点 `videoResolution`
被强制纠正 `480P→720P`、视频节点标题 `分镜视频→视频`、`duration/lastError`
被 `|| 默认值` 改变类型——这些幽灵修改使去重门失效，A 的自动保存全量落库，
服务端哈希从 H0 变 H1；B（基线 H0，body 带自己的幽灵修改）3 分钟后自动保存，
`X-Base-Hash: H0` 过期且 incoming≠current → 409 → 弹「已被其他会话覆盖」
冲突框。**全程无任何真实用户编辑**；`content_hashes_for_cas` 的同内容兜底
救不了它，因为两份 body 本身就不同。

修复点（三类）：

1. **同步还原被异步回写清空**（`web/js/script_node.js`）：`restoreWorkflow`
   还原 splitModel select 的 UI 后会 `dispatchEvent('change')`
   （workflow.js），但模型目录是异步加载的，此刻选中项没有
   `dataset.vendorId/modelId`，change 处理器把刚恢复的
   `splitModelId/splitModelVendorId/splitModelVendorName` 全部覆盖为空串
   （~500ms 后目录加载完成又回填，值碰巧相同，但基线已建在空值窗口期）。
   修复：change 处理器遇到无 `dataset.vendorId` 的选中项（目录未加载）直接
   return，不覆盖已恢复字段。**目录选项由 `appendSplitOption` 填充，必有
   `dataset.vendorId`（默认 1）；新增占位 option 时注意保持该判定成立。**
2. **还原丢字段 / 归一化改类型**（`web/js/workflow.js`
   `createVideoNodeWithData`）：① `node.title` 从不恢复——历史标题
   （"分镜视频"）每次打开都被默认标题（"视频"）覆盖；已补恢复并同步 header
   DOM（保留图标 svg，仅替换文本节点）。② `duration/lastError` 用
   `|| 默认值` 归一，把服务端的缺 key/空串改写为 0/空串——
   `createVideoNode` 初始 data 不含这两个字段，改用严格 `!== undefined`
   判断保持服务端原值（含缺 key 状态），保证往返一致。
3. **防御性纠正在写回 node.data**（`web/js/shot_group_node.js`
   `updateShotGroupResolutionOptions`）：保存的分辨率不在当前模型支持列表
   时纠正为默认值并写回——该纠正合理但属真实数据变更，必须 `markDirty()`
   让它尽快正常落库（一次性，落库后不再触发）；否则它既没被服务端确认也没
   被标记，落库后同样使其他会话基线过期，且刷新后会重复纠正。
   **区分原则：值与服务端等价的回填（splitModel 回写）不落库、由延迟基线
   吸收；值与服务端不同的纠正（分辨率纠正）必须 markDirty 落库。**

**新增节点类型 / 还原逻辑时必须自检往返一致**：打开页面 → Network 无任何
PUT（3 分钟内）→ `autoSaveState.isConfirmedBody(id, buildAutoSaveBody())`
在异步初始化稳定后为 true。违反即回归「零操作 409」。

### 旁路 PUT 必须滚动基线（「零操作也被提示冲突」误报修复）

**约定：任何绕过 `autoSaveWorkflow()` 的直连 PUT，只要写了参与内容哈希的
字段（`workflow_data` / `style` / `style_reference_image` /
`default_world_id` / `workflow_ratio`），成功后必须用响应
`data.content_hash` 滚动基线（`setConfirmedBody`），否则本页自己的写入会让
自己的 CAS 基线过期。**

误报链（修复前）：`loadWorkflow` 用 GET 时的哈希 H0 建基线，但建基线**之前**
有两处无 CAS 且丢弃响应的自写 PUT——① `from_world_id` 跳转时
`saveDefaultWorld` 写 `default_world_id`；② 工作流画风为空且关联世界有画风
时自动继承并 PUT `style + workflow_data + workflow_ratio`。PUT 后服务端哈希
变 H1，基线仍是 H0 → 60s 轮询感知 H1 → 去重门失效 → 下一次自动保存（3 分钟
定时器 / poll 发现节点完成 / 任何交互防抖 1.5s）全量 PUT 携带
`X-Base-Hash: H0` → 服务端 409 → 前端自动弹出「已被其他会话覆盖」冲突框。
全程用户零操作，且服务端内容与本页内容完全一致（CAS 拒绝的是自己刚写的
相同内容），属纯误报。同类变体：手动切换世界下拉
（`world.js` `handleWorldSelectionChange`）触发 `saveDefaultWorld` +
`_saveWorldStyleToWorkflow` 两次旁路 PUT，切完世界后下一次自动保存必 409。

修复（`web/js/world.js` / `web/js/workflow.js`）：`saveDefaultWorld` 与
`_saveWorldStyleToWorkflow` 成功后返回 `data.content_hash`；后者额外直接
`setConfirmedBody` 滚动基线。`loadWorkflow` 引入 `baselineHash` 变量贯穿：
GET 起步 → 世界同步/画风继承 PUT 各自滚动 → 最终以 `baselineHash` 建基线
（同时 `noteServerHash` 对齐，避免首轮门即失效）。`handleWorldSelectionChange`
接住哈希后同样滚动基线。`setConfirmedBody` 带 `serverHash` 时同步
`noteServerHash`（否则去重门第二条件立刻失效）。画风弹窗
`saveStyleSettings` 同样滚基线。**新增旁路 PUT 时必须遵守此约定**，
否则回归为「零操作弹冲突框」。

### 服务端同内容不报 409（漏网兜底）

CAS 在 `X-Base-Hash != 当前哈希`（以及 `content_version` 竞争 affected=0）
时，先把本次 PUT 字段叠到当前行上算 `incoming_hash`
（`content_hashes_for_cas`，viewport 仍不参与）：

- `incoming_hash == 当前哈希` → **当成功**（不写库），返回 `code=0` +
  当前 `content_hash`，前端按普通成功滚基线。覆盖：本页旁路自写导致基线
  过期、只改视口、同内容恢复重放、两请求抢版本但内容没变。
- `incoming_hash != 当前哈希` → 仍 HTTP 409，弹冲突框（真的两份内容）。

前端漏滚基线时用户也不会再看到假冲突框。

自动保存与手动保存共用 `buildAutoSaveBody()`（`{workflow_data,
default_world_id, workflow_ratio}`）保证 body 严格同构——构造不一致会导致
基线永不命中（退化为总是上传，安全方向）。`X-Base-Hash` 走 HTTP 头而非
JSON body，正是为了避免改变 body 使基线永不命中。beforeunload 补发路径
（`node_base.js`）同样**复用** `buildAutoSaveBody()`（仅保留加载顺序异常时
的内联兜底），不再人肉双写第二份构造——两处失同步会让关页补发永远过不了
去重门基线。

### 并发与乱序的收敛保证

- **迟到落库的旧请求**（abort 失败）：下轮 poll 哈希漂移 → 门失效 → 重传
  当前 UI 内容（带最新 base_hash）→ 服务端接受，收敛；不依赖 abort 成功。
- **多人/多标签同时编辑**：后到 PUT 的 `X-Base-Hash` 与服务端当前哈希不符
  → 409 拒绝 + toast 提示刷新；被拒方的本地修改有 IndexedDB 恢复快照兜底，
  不静默丢失。
- **409 后熔断自动保存**（`noteConflict`/`isConflictBlocked`）：base_hash 不变
  必然再冲突，若无熔断，dirty 状态会让每轮 poll 都全量 PUT 重试，重新打满
  带宽。熔断后自动保存不再 PUT，但**每轮把最新本地内容写入 IndexedDB 恢复
  快照**（`baseHash` 保留**过期的确认基线** `getConfirmedHash`——绝不能取
  409 响应下发的最新服务端哈希，否则刷新重放 CAS 会通过，本地旧内容静默
  覆盖他人新内容），关页/刷新有兜底；toast 仅首次提示；同时
  右上角保存按钮变为黄色脉冲态（`markSaveConflict()`，文案「⚠ 保存冲突」）
  并弹出冲突解决对话框，由用户二选一（`resolveSaveConflict()`）：
  **「用本地版本覆盖」**——不携带 `X-Base-Hash` 强制 PUT（服务端跳过 CAS），
  成功后 `setConfirmedBody` 滚动基线并解除熔断、丢弃冲突快照、按钮恢复；
  **「使用服务器版本」**——置 `acceptServerVersionPending` 标志（阻止
  beforeunload 熔断分支重写快照）→ 丢弃本地冲突快照 → `location.reload()`
  加载服务器最新内容。冲突态下点击保存按钮会重新打开该对话框；成功保存或
  reset（刷新/loadWorkflow 重建）解除熔断。
- **熔断快照刷新后的恢复语义**：刷新 → 重放携带过期基线做 CAS → 服务端已被
  他人推进 → 必然 409 → 放弃重放并清除快照，以服务端最新数据为准（toast
  告知本地未送达修改未恢复）。例外：服务端恰好回到基线内容（他人撤销了
  修改）时 CAS 通过、本地修改写回，属可接受的极端边角。
- **恢复快照重放也走 CAS**：快照 meta 记录写入时的 `baseHash`，重放携带
  `X-Base-Hash`；冲突说明服务端已有更新版本 → 放弃重放并清除快照（避免
  兜底机制覆盖他人内容）。无 `baseHash` 的存量快照维持强制重放兼容。
- **门命中分支的清理**：尽力 `abortInFlight()`（防御层，非正确性依据）+
  `WorkflowRecovery.discardOwnSnapshot()` 清除本页此前失败/被取代发送的
  残留快照（仅本页 writerId，不碰其他标签页），防止下次会话重放复活
  已撤销的内容。

## 效果

挂机页面的稳态流量从「每 60s × 全量 body 永续」降为**零**；真实变化按事件
上传（有限次）。多页面同开的周期性带宽尖峰随之消失；并发编辑从「静默互相
覆盖」变为「后到者被拒 + 用户感知」。

## 测试

- `web/tests/auto_save_upload_gate.test.js`：基线命中/不命中、跨工作流隔离、
  哈希漂移使门失效、哈希未知退化、409 冲突熔断/解除、`confirmSkipped`
  与关页决策兼容、`setConfirmedBody` 同步 lastSeen 等用例；
- `web/tests/auto_save_unload.test.js`：`discardOwnSnapshot`（本页清除/他页
  不动/无快照）、`baseHash` 持久化等，复用 fake IndexedDB；
- `tests/crud/test_video_workflow_content_hash.py`：`compute_content_hash`
  纯函数用例（dict/str 一致、key 序不敏感、任一内容字段变化即变、
  None/损坏 JSON 健壮、viewport 不参与）+ `content_hashes_for_cas`
  （同内容/仅视口 incoming==current，内容变化则不等）。

## 后续优化（未包含在本改动）

`workflow_data` 结构性瘦身（`shot_frame` 不嵌入全量 `scriptData`、
`videoPrompt` 与 `shotJson` 二选一）可把单个工作流从 18MB 降到 ~3MB，
从根本上降低保存/加载/序列化成本。见《ECS 带宽问题调查》相关记录。
