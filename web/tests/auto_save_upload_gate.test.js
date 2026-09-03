// 自动保存上传去重门测试（正式套件：npm test / vitest run）
//
// 背景：poll-status 对失败/CDN PENDING 节点每轮重复返回相同 updated_nodes，
// 前端内容实际未变却全量 PUT（大工作流十余 MB，经 frp 转发周期性打满 ECS
// 公网出带宽）。去重门按"body 与服务端最近确认基线逐字节一致"跳过上传。
//
// 覆盖：
//  - 基线命中/不命中：内容相同跳过，内容变化（哪怕一个字符）放行
//  - 跨工作流隔离：A 工作流的基线不能挡 B 工作流的上传
//  - 跳过后状态机推进：confirmSkipped 使 isDirty() 归零——关页补发
//    （dispatchBeforeUnloadSave）不会误判"有未确认修改"而绕过门重发
//  - 基线只在确认后建立：setConfirmedBody 之前门不命中（失败不挡重传）
//  - reset() 清理基线（切工作流/重置场景）
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
});

// dispatchBeforeUnloadSave 的薄封装：从模块取 WorkflowRecovery
const { WorkflowRecovery } = require('../js/auto_save_state.js');
function WorkflowRecovery_dispatch(opts){
  return WorkflowRecovery.dispatchBeforeUnloadSave(opts);
}
