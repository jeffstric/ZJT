// 自动保存关页补发状态机 + IndexedDB 恢复记录测试（正式套件：npm test / vitest run）
//
// 覆盖：
//  - 关页三分支（planUnloadSend）：定时器待触发 / 请求正在发送 / 请求体超限
//  - 确认规则：过期 ack 不推进、confirmed 不回退、被取代请求的 ack 失效
//  - endSend 返回契约（并发乱序）：仅"最新发送且成功"返回 true——调用方据此
//    决定是否清除恢复记录，防止旧请求成功清掉新请求的恢复快照
//  - 恢复记录 IndexedDB 写入/读取/清除轮转（fake indexedDB），记录携带 workflowId/userId
//  - 跨工作流/跨用户重放门控（matchesReplayContext）：A 的未确认快照不能恢复进 B
//  - 无 indexedDB 环境静默降级（vi.resetModules + 移除全局后重新加载模块）

// vitest globals（describe/test/expect/beforeAll/vi）由 vitest.config.js 的
// globals: true 注入，不能 require('vitest')（CJS 下被禁用）
const { createAutoSaveState, WorkflowRecovery, KEEPALIVE_BODY_MAX_BYTES } =
  require('../js/auto_save_state.js');

const SMALL_BODY = 1000; // 模拟小工作流 JSON 字节数
const LARGE_BODY = KEEPALIVE_BODY_MAX_BYTES + 1; // 超过 keepalive 安全余量

// ========== fake indexedDB（最小实现，仅覆盖模块用到的 API 面） ==========
// 模块用到：open(req.onupgradeneeded/onsuccess/result)、db.createObjectStore、
// db.objectStoreNames.contains、db.transaction().objectStore().put/get/delete、
// 请求的 onsuccess/result、事务的 oncomplete/onerror/onabort。

function createFakeIndexedDB() {
  const dbs = {};

  function makeRequest() {
    return { result: undefined, onsuccess: null, onerror: null, onabort: null };
  }

  function getDb(name) {
    if (dbs[name]) return dbs[name];
    const data = {}; // storeName → Map
    const db = {
      objectStoreNames: {
        contains: (s) => Object.prototype.hasOwnProperty.call(data, s),
      },
      createObjectStore: (s) => {
        data[s] = new Map();
        return data[s];
      },
      transaction: (s) => {
        const store = data[s];
        const api = {
          put: (value, key) => {
            const req = makeRequest();
            store.set(key, value);
            req.result = key;
            queueMicrotask(() => {
              if (req.onsuccess) req.onsuccess({ target: req });
              queueMicrotask(() => {
                if (tx.oncomplete) tx.oncomplete({ target: tx });
              });
            });
            return req;
          },
          get: (key) => {
            const req = makeRequest();
            req.result = store.has(key) ? store.get(key) : undefined;
            queueMicrotask(() => {
              if (req.onsuccess) req.onsuccess({ target: req });
            });
            return req;
          },
          delete: (key) => {
            const req = makeRequest();
            store.delete(key);
            queueMicrotask(() => {
              if (req.onsuccess) req.onsuccess({ target: req });
              queueMicrotask(() => {
                if (tx.oncomplete) tx.oncomplete({ target: tx });
              });
            });
            return req;
          },
        };
        const tx = { oncomplete: null, onerror: null, onabort: null, objectStore: () => api };
        return tx;
      },
      onversionchange: null,
      close: () => {},
    };
    dbs[name] = db;
    return db;
  }

  return {
    open: (name) => {
      const req = makeRequest();
      const db = getDb(name);
      queueMicrotask(() => {
        req.result = db;
        if (req.onupgradeneeded) req.onupgradeneeded({ target: req });
        if (req.onsuccess) req.onsuccess({ target: req });
      });
      return req;
    },
  };
}

beforeAll(() => {
  // 模块惰性打开 IDB 连接（首次 save/load/clear 时），在此之前打桩即可
  vi.stubGlobal('indexedDB', createFakeIndexedDB());
});

// ========== 基础：markDirty / isDirty / endSend 契约 ==========

describe('自动保存状态机基础', () => {
  test('初始不 dirty，markDirty 后 dirty 且 version 自增', () => {
    const m = createAutoSaveState();
    expect(m.isDirty()).toBe(false);
    m.markDirty();
    expect(m.isDirty()).toBe(true);
    expect(m.state.version).toBe(1);
  });

  test('endSend 返回契约：仅"最新发送且成功"为 true（并发乱序门控）', () => {
    // 1) 最新且成功 → true
    const m1 = createAutoSaveState();
    m1.markDirty(); // v1
    const v1 = m1.beginSend(null, true);
    expect(m1.endSend(v1, true)).toBe(true);
    expect(m1.state.confirmedVersion).toBe(1);

    // 2) 被新 beginSend 取代 → 旧请求的成功 ack 返回 false 且不推进
    //    （对应 autoSaveWorkflow 中"新请求前 abort 旧请求"之外的双保险：
    //    若旧请求已到达服务端，其 ack 也不得清掉新请求的恢复快照）
    const m2 = createAutoSaveState();
    m2.markDirty(); // v1
    const oldV = m2.beginSend(null, false);
    m2.markDirty(); // v2
    m2.beginSend(null, false); // 取代 v1
    expect(m2.endSend(oldV, true)).toBe(false);
    expect(m2.state.confirmedVersion).toBe(0);
    expect(m2.state.inFlight).not.toBeNull();

    // 3) 失败 → false
    const m3 = createAutoSaveState();
    m3.markDirty();
    const v3 = m3.beginSend(null, true);
    expect(m3.endSend(v3, false)).toBe(false);
    expect(m3.isDirty()).toBe(true);

    // 4) 成功但发送后有新修改（过期成功）→ false，不推进
    const m4 = createAutoSaveState();
    m4.markDirty(); // v1
    const v4 = m4.beginSend(null, false);
    m4.markDirty(); // v2
    expect(m4.endSend(v4, true)).toBe(false);
    expect(m4.state.confirmedVersion).toBe(0);
    expect(m4.isDirty()).toBe(true);

    // 5) confirmed 不回退
    const m5 = createAutoSaveState();
    m5.markDirty(); // v1
    const va = m5.beginSend(null, true);
    m5.endSend(va, true); // confirmed=1
    m5.markDirty(); // v2
    const vb = m5.beginSend(null, true);
    m5.endSend(vb, false); // v2 失败
    expect(m5.state.confirmedVersion).toBe(1);
  });
});

// ========== 关页三分支（planUnloadSend） ==========

describe('关页三分支', () => {
  test('分支1 定时器待触发：dirty 无在途，小 body → keepalive 补发', () => {
    const m = createAutoSaveState();
    m.markDirty();
    expect(m.planUnloadSend(SMALL_BODY)).toEqual({ action: 'send', keepalive: true, abort: false });
  });

  test('分支1 无修改 / 全部已确认 → none', () => {
    const m1 = createAutoSaveState();
    expect(m1.planUnloadSend(SMALL_BODY)).toEqual({ action: 'none' });

    const m2 = createAutoSaveState();
    m2.markDirty();
    const v = m2.beginSend(null, true);
    m2.endSend(v, true);
    expect(m2.planUnloadSend(SMALL_BODY)).toEqual({ action: 'none' });
  });

  test('分支2 请求正在发送：在途最新 keepalive → none（卸载后浏览器继续发送）', () => {
    const m = createAutoSaveState();
    m.markDirty();
    m.beginSend(null, true);
    expect(m.planUnloadSend(SMALL_BODY)).toEqual({ action: 'none' });
  });

  test('分支2 请求正在发送：在途最新普通 fetch + 小 body → 中止并升级 keepalive', () => {
    const m = createAutoSaveState();
    m.markDirty();
    m.beginSend({ abort() {} }, false);
    expect(m.planUnloadSend(SMALL_BODY)).toEqual({ action: 'send', keepalive: true, abort: true });
  });

  test('分支2 请求正在发送：在途已过期 → 中止后用最新 payload 重发', () => {
    const m = createAutoSaveState();
    m.markDirty(); // v1 发送中
    m.beginSend({ abort() {} }, false);
    m.markDirty(); // v2 新修改
    expect(m.planUnloadSend(SMALL_BODY)).toEqual({ action: 'send', keepalive: true, abort: true });
  });

  test('分支2 请求正在发送：在途最新 + 大 body → none（尽力发送 + IndexedDB 恢复兜底）', () => {
    const m = createAutoSaveState();
    m.markDirty();
    m.beginSend(null, false);
    expect(m.planUnloadSend(LARGE_BODY)).toEqual({ action: 'none' });
  });

  test('分支2 请求正在发送：在途过期 + 大 body → 中止重发普通 fetch', () => {
    const m = createAutoSaveState();
    m.markDirty();
    m.beginSend(null, false);
    m.markDirty();
    expect(m.planUnloadSend(LARGE_BODY)).toEqual({ action: 'send', keepalive: false, abort: true });
  });

  test('分支3 请求体超限：dirty 无在途 > 59KB → 补发但 keepalive 不可用', () => {
    const m = createAutoSaveState();
    m.markDirty();
    expect(m.planUnloadSend(LARGE_BODY)).toEqual({ action: 'send', keepalive: false, abort: false });
  });

  test('abortInFlight 调用在途 controller 且不清空 inFlight', () => {
    const m = createAutoSaveState();
    m.markDirty();
    let aborted = false;
    m.beginSend({ abort() { aborted = true; } }, false);
    m.abortInFlight();
    expect(aborted).toBe(true);
    expect(m.state.inFlight).not.toBeNull();

    // 无 controller 时不抛异常
    const m2 = createAutoSaveState();
    m2.markDirty();
    m2.beginSend(null, false);
    expect(() => m2.abortInFlight()).not.toThrow();
  });
});

// ========== 恢复记录：IndexedDB 轮转（fake indexedDB） ==========

describe('恢复记录 IndexedDB 轮转', () => {
  test('saveSnapshot 写入后 loadSnapshot 读回，且记录携带 workflowId/userId', async () => {
    const ok = await WorkflowRecovery.saveSnapshot('{"workflow_data":{}}', {
      version: 7,
      workflowId: 'wf-1',
      userId: 'user-1',
    });
    expect(ok).toBe(true);

    const record = await WorkflowRecovery.loadSnapshot();
    expect(record).not.toBeNull();
    expect(record.payload).toBe('{"workflow_data":{}}');
    expect(record.version).toBe(7);
    expect(record.workflowId).toBe('wf-1');
    expect(record.userId).toBe('user-1');
  });

  test('单槽位覆盖：新保存的 payload 覆盖旧记录', async () => {
    await WorkflowRecovery.saveSnapshot('{"workflow_data":"second"}', {
      version: 8,
      workflowId: 'wf-2',
      userId: 'user-2',
    });
    const record = await WorkflowRecovery.loadSnapshot();
    expect(record.payload).toBe('{"workflow_data":"second"}');
    expect(record.workflowId).toBe('wf-2');
  });

  test('clearSnapshot 清除后 loadSnapshot 返回 null', async () => {
    const ok = await WorkflowRecovery.clearSnapshot();
    expect(ok).toBe(true);
    expect(await WorkflowRecovery.loadSnapshot()).toBeNull();
  });

  test('saveSnapshotSync：连接已打开时同步写入成功并可读回', async () => {
    // 前面用例已让模块打开（并缓存）IDB 连接 → 同步 put 可用
    expect(
      WorkflowRecovery.saveSnapshotSync('{"workflow_data":"sync"}', {
        version: 9,
        workflowId: 'wf-3',
        userId: 'user-3',
      })
    ).toBe(true);
    const record = await WorkflowRecovery.loadSnapshot();
    expect(record.payload).toBe('{"workflow_data":"sync"}');
    expect(record.workflowId).toBe('wf-3');
    await WorkflowRecovery.clearSnapshot();
  });

  test('meta 归一化：workflowId/userId 缺失时存 null（旧版记录语义）', async () => {
    await WorkflowRecovery.saveSnapshot('{"workflow_data":"legacy"}', { version: 10 });
    const record = await WorkflowRecovery.loadSnapshot();
    expect(record.workflowId).toBeNull();
    expect(record.userId).toBeNull();
    await WorkflowRecovery.clearSnapshot();
  });
});

// ========== 跨工作流/跨用户重放门控 ==========

describe('跨工作流/跨用户重放门控（matchesReplayContext）', () => {
  test('完全匹配 → 允许重放', () => {
    expect(
      WorkflowRecovery.matchesReplayContext(
        { payload: 'p', workflowId: 'wf-1', userId: 'u-1' },
        { workflowId: 'wf-1', userId: 'u-1' }
      )
    ).toBe(true);
  });

  test('工作流 A 的快照恢复进工作流 B → 禁止（防跨工作流覆盖）', () => {
    expect(
      WorkflowRecovery.matchesReplayContext(
        { payload: 'p', workflowId: 'wf-1', userId: 'u-1' },
        { workflowId: 'wf-2', userId: 'u-1' }
      )
    ).toBe(false);
  });

  test('账号切换（同一工作流）→ 禁止（防跨用户覆盖）', () => {
    expect(
      WorkflowRecovery.matchesReplayContext(
        { payload: 'p', workflowId: 'wf-1', userId: 'u-1' },
        { workflowId: 'wf-1', userId: 'u-2' }
      )
    ).toBe(false);
  });

  test('workflowId 数字/字符串归一化后匹配', () => {
    expect(
      WorkflowRecovery.matchesReplayContext(
        { payload: 'p', workflowId: '12', userId: 'u-1' },
        { workflowId: 12, userId: 'u-1' }
      )
    ).toBe(true);
  });

  test('旧版记录（workflowId/userId 为 null）→ best-effort 允许', () => {
    expect(
      WorkflowRecovery.matchesReplayContext(
        { payload: 'p', workflowId: null, userId: null },
        { workflowId: 'wf-1', userId: 'u-1' }
      )
    ).toBe(true);
    expect(
      WorkflowRecovery.matchesReplayContext(
        { payload: 'p', workflowId: 'wf-1', userId: null },
        { workflowId: 'wf-1', userId: 'u-1' }
      )
    ).toBe(true);
  });

  test('无记录 / 无 payload → 禁止', () => {
    expect(WorkflowRecovery.matchesReplayContext(null, { workflowId: 'wf-1', userId: 'u-1' })).toBe(false);
    expect(
      WorkflowRecovery.matchesReplayContext({ version: 1 }, { workflowId: 'wf-1', userId: 'u-1' })
    ).toBe(false);
  });
});

// ========== 无 indexedDB 环境静默降级 ==========
// 注意：放在最后——需要 vi.resetModules + 移除 indexedDB 全局后重新加载模块，
// 影响模块级连接缓存，不能与上面的轮转用例共享实例。

describe('无 indexedDB 环境静默降级', () => {
  test('save/load/clear 全部 resolve 且吞异常，saveSnapshotSync 返回 false', async () => {
    vi.stubGlobal('indexedDB', undefined);
    try {
      vi.resetModules();
      const fresh = await import('../js/auto_save_state.js');
      const mod = fresh.default || fresh;

      await expect(
        mod.WorkflowRecovery.saveSnapshot('{"a":1}', { version: 1, workflowId: '1', userId: 'u1' })
      ).resolves.toBe(null);
      await expect(mod.WorkflowRecovery.loadSnapshot()).resolves.toBe(null);
      await expect(mod.WorkflowRecovery.clearSnapshot()).resolves.toBe(null);
      expect(mod.WorkflowRecovery.saveSnapshotSync('{"a":1}', {})).toBe(false);

      // 状态机在无 IDB 环境下同样可用
      const m = mod.createAutoSaveState();
      m.markDirty();
      expect(m.planUnloadSend(SMALL_BODY)).toEqual({ action: 'send', keepalive: true, abort: false });
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
