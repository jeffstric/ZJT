// 自动保存上传去重门测试（正式套件：npm test / vitest run）
//
// 背景：poll-status 对失败/CDN PENDING 节点每轮重复返回相同 updated_nodes，
// 前端内容实际未变却全量 PUT（大工作流十余 MB，经 frp 转发周期性打满 ECS
// 公网出带宽）。去重门按"body 与服务端最近确认基线逐字节一致"跳过上传。
//
// 覆盖：
//  - 基线命中/不命中：内容相同跳过，内容变化（哪怕一个字符）放行
//  - 跨工作流隔离：A 工作流的基线不能挡 B 工作流的上传
//  - 服务端权威哈希双条件：noteServerHash 漂移（服务端被其他会话/迟到
//    请求改写）使门失效重传收敛；哈希未知时退化为纯 body 比较
//  - getConfirmedHash：PUT CAS（X-Base-Hash）基值随成功响应滚动
//  - 跳过后状态机推进：confirmSkipped 使 isDirty() 归零——关页补发
//    （dispatchBeforeUnloadSave）不会误判"有未确认修改"而绕过门重发
//  - 基线只在确认后建立：setConfirmedBody 之前门不命中（失败不挡重传）
//  - reset() 清理基线与已知服务端哈希（切工作流/重置场景）
//  - 关页路径与门的兼容：内容=基线时 planUnloadSend 返回 none

// vitest globals（describe/test/expect/beforeAll/vi）由 vitest.config.js 的
// globals: true 注入，不能 require('vitest')（CJS 下被禁用）
const { createAutoSaveState } = require('../js/auto_save_state.js');

function createState(){
  return createAutoSaveState();
}

// 与 workflow.js buildAutoSaveBody 同构的最小 body
function body(url){
  return JSON.stringify({
    workflow_data: { nodes: [{ id: 'n1', type: 'image', data: { url: url } }] },
    default_world_id: 1,
    workflow_ratio: '16:9'
  });
}

describe('上传去重门（isConfirmedBody / setConfirmedBody / confirmSkipped）', () => {
  test('基线建立前：任何 body 都不命中（不误挡首次上传/失败重传）', () => {
    const s = createState();
    expect(s.isConfirmedBody(1, body('a.png'))).toBe(false);
  });

  test('基线命中：相同 workflowId + 相同 body 才跳过', () => {
    const s = createState();
    s.setConfirmedBody(1, body('a.png'));
    expect(s.isConfirmedBody(1, body('a.png'))).toBe(true);
  });

  test('内容变化必须放行：url 差一个字符、多余空白、ratio 变化都不命中', () => {
    const s = createState();
    s.setConfirmedBody(1, body('a.png'));
    expect(s.isConfirmedBody(1, body('b.png'))).toBe(false);
    expect(s.isConfirmedBody(1, body('a.png') + ' ')).toBe(false);
    expect(s.isConfirmedBody(1, body('a.png').replace('16:9', '9:16'))).toBe(false);
  });

  test('跨工作流隔离：A 的基线不挡 B 的上传（workflowId 参与匹配）', () => {
    const s = createState();
    s.setConfirmedBody(1611, body('a.png'));
    expect(s.isConfirmedBody(1614, body('a.png'))).toBe(false);
    // 数字/字符串 id 等价（URL 参数解析出的 id 是字符串）
    expect(s.isConfirmedBody('1611', body('a.png'))).toBe(true);
  });

  test('非字符串 body 不记录基线（防御：undefined/对象不产生假基线）', () => {
    const s = createState();
    s.setConfirmedBody(1, undefined);
    s.setConfirmedBody(1, null);
    s.setConfirmedBody(1, { not: 'string' });
    expect(s.isConfirmedBody(1, body('a.png'))).toBe(false);
  });

  test('新基线覆盖旧基线（loadWorkflow 重建 / 手动保存更新）', () => {
    const s = createState();
    s.setConfirmedBody(1, body('a.png'));
    s.setConfirmedBody(1, body('b.png'));
    expect(s.isConfirmedBody(1, body('a.png'))).toBe(false);
    expect(s.isConfirmedBody(1, body('b.png'))).toBe(true);
  });
});

describe('跳过后的状态机推进（防关页补发绕门）', () => {
  test('confirmSkipped 推进 confirmedVersion，isDirty 归零', () => {
    const s = createState();
    s.setConfirmedBody(1, body('a.png'));
    s.markDirty();            // 轮询触发 autoSaveWorkflow 内部的 markDirty
    expect(s.isDirty()).toBe(true);
    s.confirmSkipped();       // 门命中跳过上传
    expect(s.isDirty()).toBe(false);
  });

  test('confirmSkipped 不回退已确认版本', () => {
    const s = createState();
    s.markDirty();            // version 1
    s.beginSend(null, false);
    s.endSend(1, true);       // confirmedVersion → 1
    s.markDirty();            // version 2（内容实际未变，如重复赋相同 url）
    s.confirmSkipped();       // confirmedVersion → 2
    expect(s.state.confirmedVersion).toBe(2);
    s.confirmSkipped();       // 幂等，不回退不越界
    expect(s.state.confirmedVersion).toBe(2);
    expect(s.state.version).toBe(2);
  });

  test('门命中后关页决策：内容未变 → planUnloadSend 不再补发', () => {
    const s = createState();
    s.setConfirmedBody(1, body('a.png'));
    s.markDirty();
    s.confirmSkipped();
    expect(s.planUnloadSend(body('a.png').length)).toEqual({ action: 'none' });
  });

  test('门未命中（内容真实变化）→ 关页照常补发，不受门影响', () => {
    const s = createState();
    s.setConfirmedBody(1, body('a.png'));
    s.markDirty();            // 用户真实修改
    const plan = s.planUnloadSend(body('b.png').length);
    expect(plan.action).toBe('send');
  });
});

describe('dispatchBeforeUnloadSave 与门共存（关页 keepalive 补发路径）', () => {
  test('内容=基线时（isDirty 已被 confirmSkipped 归零）不产生补发请求', async () => {
    const s = createState();
    s.setConfirmedBody(1, body('a.png'));
    s.markDirty();
    s.confirmSkipped();

    let sendCalled = false;
    const plan = WorkflowRecovery_dispatch({
      saveState: s,
      serializeBody: () => body('a.png'),
      send: () => { sendCalled = true; }
    });
    expect(plan).toEqual({ action: 'none' });
    expect(sendCalled).toBe(false);
  });

  test('内容真实变化时关页补发正常发起（门不阻碍丢失保护）', async () => {
    const s = createState();
    s.setConfirmedBody(1, body('a.png'));
    s.markDirty();            // 真实修改：version 领先基线

    let sendArg = null;
    const plan = WorkflowRecovery_dispatch({
      saveState: s,
      serializeBody: () => body('b.png'),
      send: (opts) => { sendArg = opts; }
    });
    expect(plan.action).toBe('send');
    expect(sendArg).not.toBe(null);
    expect(sendArg.serializedBody).toBe(body('b.png'));
  });
});

describe('reset 清理基线', () => {
  test('reset 后基线失效，isDirty 复位', () => {
    const s = createState();
    s.setConfirmedBody(1, body('a.png'));
    s.markDirty();
    s.reset();
    expect(s.isConfirmedBody(1, body('a.png'))).toBe(false);
    expect(s.isDirty()).toBe(false);
  });

  test('reset 同时清除已知服务端哈希', () => {
    const s = createState();
    s.setConfirmedBody(1, body('a.png'), 'h1');
    s.noteServerHash(1, 'h1');
    s.reset();
    expect(s.getConfirmedHash(1)).toBe(null);
    // 哈希记录已清，门退化为纯 body 比较也不会命中（基线已清）
    expect(s.isConfirmedBody(1, body('a.png'))).toBe(false);
  });
});

describe('服务端权威哈希双条件（noteServerHash / getConfirmedHash）', () => {
  test('哈希一致时门正常命中', () => {
    const s = createState();
    s.setConfirmedBody(1, body('a.png'), 'h1');
    s.noteServerHash(1, 'h1');
    expect(s.isConfirmedBody(1, body('a.png'))).toBe(true);
    expect(s.getConfirmedHash(1)).toBe('h1');
  });

  test('哈希漂移（服务端被其他会话/迟到请求改写）→ 门失效，重传收敛', () => {
    const s = createState();
    s.setConfirmedBody(1, body('a.png'), 'h1');
    s.noteServerHash(1, 'h1');
    expect(s.isConfirmedBody(1, body('a.png'))).toBe(true);
    // 下轮 poll 看到新哈希：即使 body 与基线逐字节一致也必须放行
    s.noteServerHash(1, 'h2');
    expect(s.isConfirmedBody(1, body('a.png'))).toBe(false);
  });

  test('其他工作流的哈希漂移不影响本工作流的门', () => {
    const s = createState();
    s.setConfirmedBody(1, body('a.png'), 'h1');
    s.noteServerHash(1, 'h1');
    s.noteServerHash(2, 'h-other'); // 另一个工作流的 poll 结果
    expect(s.isConfirmedBody(1, body('a.png'))).toBe(true);
  });

  test('哈希未知时退化为纯 body 比较（旧服务端/滚动发布兼容）', () => {
    // 基线无哈希（旧 PUT 响应）+ poll 无哈希 → 维持 24a4fc18 行为
    const s = createState();
    s.setConfirmedBody(1, body('a.png'));
    expect(s.isConfirmedBody(1, body('a.png'))).toBe(true);
    expect(s.getConfirmedHash(1)).toBe(null);

    // 基线有哈希但尚未收到任何 poll 哈希 → 不误挡
    const s2 = createState();
    s2.setConfirmedBody(1, body('a.png'), 'h1');
    expect(s2.isConfirmedBody(1, body('a.png'))).toBe(true);
  });

  test('noteServerHash 忽略空值，getConfirmedHash 对其他工作流返回 null', () => {
    const s = createState();
    s.setConfirmedBody(1, body('a.png'), 'h1');
    s.noteServerHash(1, null);
    s.noteServerHash(1, undefined);
    s.noteServerHash(1, '');
    expect(s.isConfirmedBody(1, body('a.png'))).toBe(true); // 未被空值污染
    expect(s.getConfirmedHash(2)).toBe(null);
  });

  test('新基线覆盖旧哈希：PUT 成功后 CAS 基值随响应滚动', () => {
    const s = createState();
    s.setConfirmedBody(1, body('a.png'), 'h1');
    s.noteServerHash(1, 'h1');
    // 真实修改后保存成功，服务端返回新哈希
    s.setConfirmedBody(1, body('b.png'), 'h2');
    expect(s.getConfirmedHash(1)).toBe('h2');
    // 旧 body/旧哈希组合不再命中
    expect(s.isConfirmedBody(1, body('a.png'))).toBe(false);
    // 新 body 在 poll 追上（h2）后命中
    expect(s.isConfirmedBody(1, body('b.png'))).toBe(false); // lastSeen 仍是 h1
    s.noteServerHash(1, 'h2');
    expect(s.isConfirmedBody(1, body('b.png'))).toBe(true);
  });
});

describe('CAS 409 冲突熔断（noteConflict / isConflictBlocked）', () => {
  test('冲突后熔断，成功保存解除', () => {
    const s = createState();
    s.setConfirmedBody(1, body('a.png'), 'h1');
    expect(s.isConflictBlocked(1)).toBe(false);
    s.noteConflict(1);
    expect(s.isConflictBlocked(1)).toBe(true);
    // 熔断期间保持 dirty（本地修改有恢复快照兜底，等用户刷新）
    s.markDirty();
    expect(s.isDirty()).toBe(true);
    // 用户刷新后以服务端最新内容为基保存成功 → 解除熔断
    s.setConfirmedBody(1, body('c.png'), 'h3');
    expect(s.isConflictBlocked(1)).toBe(false);
  });

  test('跨工作流隔离与 reset 清理', () => {
    const s = createState();
    s.noteConflict(1);
    expect(s.isConflictBlocked(2)).toBe(false);
    s.reset();
    expect(s.isConflictBlocked(1)).toBe(false);
  });

  test('409 后 getLastSeenServerHash 推进、getConfirmedHash 基线保持过期值', () => {
    // 回归：熔断期间本地修改写入恢复快照，快照 baseHash 必须保留过期的
    // 确认基线（getConfirmedHash），使刷新重放 CAS 必然 409 放弃、以服务端
    // 数据为准；绝不能取 getLastSeenServerHash（409 下发的最新服务端哈希），
    // 否则重放 CAS 通过会把本地旧内容覆盖到他人已保存的新内容上。
    const s = createState();
    s.setConfirmedBody(1, body('a.png'), 'h-baseline');
    // lastSeen 只由 GET/poll/409 的 noteServerHash 通道推进；仅建基线时为 null
    expect(s.getLastSeenServerHash(1)).toBe(null);
    // GET/poll 感知到基线哈希 → 已知
    s.noteServerHash(1, 'h-baseline');
    expect(s.getLastSeenServerHash(1)).toBe('h-baseline');
    // PUT 409：响应携带服务端当前哈希
    s.noteServerHash(1, 'h-server-latest');
    s.noteConflict(1);
    expect(s.isConflictBlocked(1)).toBe(true);
    expect(s.getConfirmedHash(1)).toBe('h-baseline');          // 过期基线：熔断快照 baseHash 取此值
    expect(s.getLastSeenServerHash(1)).toBe('h-server-latest'); // 仅用于去重门失效判断，不作快照 baseHash
    // 跨工作流隔离与未知时返回 null
    expect(s.getLastSeenServerHash(2)).toBe(null);
    s.reset();
    expect(s.getLastSeenServerHash(1)).toBe(null);
  });
});

// dispatchBeforeUnloadSave 的薄封装：从模块取 WorkflowRecovery
const { WorkflowRecovery } = require('../js/auto_save_state.js');
function WorkflowRecovery_dispatch(opts){
  return WorkflowRecovery.dispatchBeforeUnloadSave(opts);
}
