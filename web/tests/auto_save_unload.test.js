// 自动保存关页补发状态机 + IndexedDB 恢复记录测试（正式套件：npm test / vitest run）
//
// 覆盖：
//  - 关页三分支（planUnloadSend）：定时器待触发 / 请求正在发送 / 请求体超限
//  - 确认规则：过期 ack 不推进、confirmed 不回退、被取代请求的 ack 失效
//  - endSend 返回契约（并发乱序）：仅"最新发送且成功"返回 true——调用方据此
//    决定是否清除恢复记录，防止旧请求成功清掉新请求的恢复快照
//  - 卸载发送在任何异步 IDB 等待前同步调用真实 fetch 入口
//  - 恢复记录按 userId/workflowId 分区，snapshotId/version 条件清理
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
  const dbs = new Map();

  function makeRequest() {
    return { result: undefined, error: null, onsuccess: null, onerror: null, onabort: null };
  }

  function getEntry(name) {
    if (dbs.has(name)) return dbs.get(name);
    const data = {}; // storeName → Map
    const db = {
      version: 0,
      objectStoreNames: {
        contains: (s) => Object.prototype.hasOwnProperty.call(data, s),
      },
      createObjectStore: (s) => {
        if (!Object.prototype.hasOwnProperty.call(data, s)) data[s] = new Map();
        return data[s];
      },
      onversionchange: null,
      close: () => {},
    };
    const entry = { db, data };
    db.transaction = (s) => makeTransaction(entry, s);
    dbs.set(name, entry);
    return entry;
  }

  // 按 pending request 数模拟真实事务：onsuccess 内可继续发起 delete，
  // 所有请求完成后才触发 oncomplete。这是条件 get → delete 测试的关键。
  function makeTransaction(entry, storeName) {
    let pending = 0;
    let completionQueued = false;
    let finished = false;
    const tx = {
      oncomplete: null,
      onerror: null,
      onabort: null,
      objectStore: (s) => makeStoreApi(entry, s || storeName, tx),
      _queueCompletion: queueCompletion,
    };

    function queueCompletion() {
      if (finished || completionQueued || pending !== 0) return;
      completionQueued = true;
      queueMicrotask(() => {
        completionQueued = false;
        if (finished || pending !== 0 || !tx.oncomplete) return;
        finished = true;
        tx.oncomplete({ target: tx });
      });
    }

    function request(work) {
      const req = makeRequest();
      pending += 1;
      queueMicrotask(() => {
        try {
          req.result = work();
          if (req.onsuccess) req.onsuccess({ target: req });
        } catch (error) {
          req.error = error;
          finished = true;
          if (req.onerror) req.onerror({ target: req });
          if (tx.onerror) tx.onerror({ target: tx });
        } finally {
          pending -= 1;
          queueCompletion();
        }
      });
      return req;
    }

    tx._request = request;
    return tx;
  }

  function makeStoreApi(entry, storeName, tx) {
    const store = entry.data[storeName];
    if (!store) throw new Error(`object store not found: ${storeName}`);
    return {
      put: (value, key) => tx._request(() => {
        store.set(key, value);
        return key;
      }),
      get: (key) => tx._request(() => (store.has(key) ? store.get(key) : undefined)),
      delete: (key) => tx._request(() => {
        store.delete(key);
        return undefined;
      }),
    };
  }

  const api = {
    open: (name, requestedVersion) => {
      const req = makeRequest();
      const entry = getEntry(name);
      queueMicrotask(() => {
        const oldVersion = entry.db.version;
        const newVersion = requestedVersion || oldVersion || 1;
        req.result = entry.db;
        if (newVersion < oldVersion) {
          req.error = new Error('VersionError');
          if (req.onerror) req.onerror({ target: req });
          return;
        }
        if (newVersion === oldVersion) {
          if (req.onsuccess) req.onsuccess({ target: req });
          return;
        }

        const tx = makeTransaction(entry, 'snapshots');
        req.transaction = tx;
        entry.db.version = newVersion;
        if (req.onupgradeneeded) {
          req.onupgradeneeded({ target: req, oldVersion, newVersion });
        }
        tx.oncomplete = () => {
          if (req.onsuccess) req.onsuccess({ target: req });
        };
        tx._queueCompletion();
      });
      return req;
    },
    seed: (name, version, storeName, key, value) => {
      const entry = getEntry(name);
      entry.db.version = version;
      if (!entry.data[storeName]) entry.data[storeName] = new Map();
      entry.data[storeName].set(key, value);
    },
    has: (name, storeName, key) => {
      const entry = getEntry(name);
      const store = entry.data[storeName];
      return !!store && store.has(key);
    },
  };
  return api;
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
    const sentVersion = m.beginSend(null, true);
    m.markRequestStarted(sentVersion);
    expect(m.planUnloadSend(SMALL_BODY)).toEqual({ action: 'none' });
  });

  test('分支2 请求正在发送：在途最新普通 fetch + 小 body → 中止并升级 keepalive', () => {
    const m = createAutoSaveState();
    m.markDirty();
    const sentVersion = m.beginSend({ abort() {} }, false);
    m.markRequestStarted(sentVersion);
    expect(m.planUnloadSend(SMALL_BODY)).toEqual({ action: 'send', keepalive: true, abort: true });
  });

  test('分支2 请求正在发送：在途已过期 → 中止后用最新 payload 重发', () => {
    const m = createAutoSaveState();
    m.markDirty(); // v1 发送中
    const sentVersion = m.beginSend({ abort() {} }, false);
    m.markRequestStarted(sentVersion);
    m.markDirty(); // v2 新修改
    expect(m.planUnloadSend(SMALL_BODY)).toEqual({ action: 'send', keepalive: true, abort: true });
  });

  test('分支2 请求正在发送：在途最新 + 大 body → none（尽力发送 + IndexedDB 恢复兜底）', () => {
    const m = createAutoSaveState();
    m.markDirty();
    const sentVersion = m.beginSend(null, false);
    m.markRequestStarted(sentVersion);
    expect(m.planUnloadSend(LARGE_BODY)).toEqual({ action: 'none' });
  });

  test('普通保存仍在等待 IDB 落盘：大 body 也必须关页补发', () => {
    const m = createAutoSaveState();
    m.markDirty();
    const sentVersion = m.beginSend({ abort() {} }, false);
    expect(m.state.inFlight.requestStarted).toBe(false);
    expect(m.planUnloadSend(LARGE_BODY)).toEqual({ action: 'send', keepalive: false, abort: true });

    expect(m.markRequestStarted(sentVersion)).toBe(true);
    expect(m.planUnloadSend(LARGE_BODY)).toEqual({ action: 'none' });
  });

  test('分支2 请求正在发送：在途过期 + 大 body → 中止重发普通 fetch', () => {
    const m = createAutoSaveState();
    m.markDirty();
    const sentVersion = m.beginSend(null, false);
    m.markRequestStarted(sentVersion);
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
    const sentVersion = m.beginSend({ abort() { aborted = true; } }, false);
    m.markRequestStarted(sentVersion);
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

// ========== 卸载路径：fetch 必须同步启动 ==========

describe('卸载发送时序', () => {
  test('生产卸载 dispatcher 传递 unload/预序列化 body，并在返回前启动 fetch', () => {
    const saveState = createAutoSaveState();
    saveState.markDirty();
    const body = '{"workflow_data":"dispatcher-body"}';
    const serializeBody = vi.fn(() => body);
    const cancelPending = vi.fn();
    const fetchImpl = vi.fn(() => new Promise(() => {}));
    const recovery = Object.create(WorkflowRecovery);
    recovery.saveSnapshotSync = vi.fn(() => false);
    recovery.saveSnapshot = vi.fn(() => new Promise(() => {}));
    const send = vi.fn((saveOptions) => {
      expect(saveOptions).toEqual({
        skipHistory: true,
        keepalive: true,
        unload: true,
        serializedBody: body,
      });
      return WorkflowRecovery.startUnloadSend.call(
        recovery,
        saveOptions.serializedBody,
        { version: 1, workflowId: 'wf-dispatch', userId: 'u-dispatch', snapshotId: 'snap-dispatch' },
        '/api/video-workflow/wf-dispatch',
        { method: 'PUT', keepalive: saveOptions.keepalive, body: saveOptions.serializedBody },
        fetchImpl
      );
    });

    const plan = WorkflowRecovery.dispatchBeforeUnloadSave({
      saveState,
      serializeBody,
      measureBodyBytes: (value) => new Blob([value]).size,
      cancelPending,
      send,
    });

    // 不 await：dispatcher → unload send → fetch 的整条同步接线已执行。
    expect(plan).toEqual({ action: 'send', keepalive: true, abort: false });
    expect(serializeBody).toHaveBeenCalledTimes(1);
    expect(cancelPending).toHaveBeenCalledTimes(1);
    expect(send).toHaveBeenCalledTimes(1);
    expect(fetchImpl).toHaveBeenCalledWith(
      '/api/video-workflow/wf-dispatch',
      { method: 'PUT', keepalive: true, body }
    );
  });

  test('IDB 未就绪时，不等 saveSnapshot 就在当前调用栈执行 fetch', async () => {
    const order = [];
    const pendingSnapshot = new Promise(() => {});
    const recovery = Object.create(WorkflowRecovery);
    recovery.saveSnapshotSync = vi.fn(() => {
      order.push('sync-put');
      return false;
    });
    recovery.saveSnapshot = vi.fn(() => {
      order.push('async-put');
      return pendingSnapshot;
    });
    const fetchImpl = vi.fn((url, options) => {
      order.push('fetch');
      return Promise.resolve({ url, options });
    });
    const body = '{"workflow_data":"pre-serialized"}';
    const requestOptions = { method: 'PUT', keepalive: true, body };

    const started = WorkflowRecovery.startUnloadSend.call(
      recovery,
      body,
      { version: 1, workflowId: 'wf-unload', userId: 'u-unload', snapshotId: 'snap-unload' },
      '/api/video-workflow/wf-unload',
      requestOptions,
      fetchImpl
    );

    // 不 await、不 flush microtasks：直接证明 fetch 在卸载同步调用栈内已启动。
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    expect(fetchImpl).toHaveBeenCalledWith('/api/video-workflow/wf-unload', requestOptions);
    expect(fetchImpl.mock.calls[0][1].keepalive).toBe(true);
    expect(fetchImpl.mock.calls[0][1].body).toBe(body);
    expect(order).toEqual(['sync-put', 'fetch', 'async-put']);
    expect(started.syncQueued).toBe(false);
    await expect(started.sendPromise).resolves.toMatchObject({ url: '/api/video-workflow/wf-unload' });
  });

  test('IDB 同步 put 已入队时，仍立即 fetch 且不重复异步写入', async () => {
    const recovery = Object.create(WorkflowRecovery);
    recovery.saveSnapshotSync = vi.fn(() => true);
    recovery.saveSnapshot = vi.fn(() => Promise.resolve(true));
    const fetchImpl = vi.fn(() => Promise.resolve('sent'));

    const started = WorkflowRecovery.startUnloadSend.call(
      recovery,
      '{}',
      { version: 1, workflowId: 'wf-sync', userId: 'u-sync', snapshotId: 'snap-sync' },
      '/api/video-workflow/wf-sync',
      { method: 'PUT', keepalive: true, body: '{}' },
      fetchImpl
    );

    expect(fetchImpl).toHaveBeenCalledTimes(1);
    expect(recovery.saveSnapshot).not.toHaveBeenCalled();
    expect(started.syncQueued).toBe(true);
    await expect(started.snapshotPromise).resolves.toBe(true);
  });
});

// ========== 恢复记录：IndexedDB 分区与条件清理（fake indexedDB） ==========

describe('恢复记录 IndexedDB 分区与轮转', () => {
  test('saveSnapshot 写入后只能从对应用户/工作流 key 读回', async () => {
    const meta = {
      version: 7,
      workflowId: 'wf-1',
      userId: 'user-1',
      snapshotId: 'snap-1',
    };
    const ok = await WorkflowRecovery.saveSnapshot('{"workflow_data":{}}', meta);
    expect(ok).toBe(true);

    const record = await WorkflowRecovery.loadSnapshot(meta);
    expect(record).not.toBeNull();
    expect(record.payload).toBe('{"workflow_data":{}}');
    expect(record.version).toBe(7);
    expect(record.workflowId).toBe('wf-1');
    expect(record.userId).toBe('user-1');
    expect(record.snapshotId).toBe('snap-1');
    expect(await WorkflowRecovery.loadSnapshot({ workflowId: 'wf-other', userId: 'user-1' })).toBeNull();
    expect(await WorkflowRecovery.clearSnapshot(meta)).toBe(true);
  });

  test('同一用户的两个工作流同时存在，清理 A 不影响 B', async () => {
    const a = { version: 1, workflowId: 'wf-A', userId: 'user-shared', snapshotId: 'snap-A' };
    const b = { version: 1, workflowId: 'wf-B', userId: 'user-shared', snapshotId: 'snap-B' };
    await WorkflowRecovery.saveSnapshot('payload-A', a);
    await WorkflowRecovery.saveSnapshot('payload-B', b);

    expect((await WorkflowRecovery.loadSnapshot(a)).payload).toBe('payload-A');
    expect((await WorkflowRecovery.loadSnapshot(b)).payload).toBe('payload-B');
    expect(await WorkflowRecovery.clearSnapshot(a)).toBe(true);
    expect(await WorkflowRecovery.loadSnapshot(a)).toBeNull();
    expect((await WorkflowRecovery.loadSnapshot(b)).payload).toBe('payload-B');
    expect(await WorkflowRecovery.clearSnapshot(b)).toBe(true);
  });

  test('同一工作流的两个用户互相隔离', async () => {
    const a = { version: 1, workflowId: 'wf-shared', userId: 'user-A', snapshotId: 'snap-user-A' };
    const b = { version: 1, workflowId: 'wf-shared', userId: 'user-B', snapshotId: 'snap-user-B' };
    await WorkflowRecovery.saveSnapshot('payload-user-A', a);
    await WorkflowRecovery.saveSnapshot('payload-user-B', b);

    expect((await WorkflowRecovery.loadSnapshot(a)).payload).toBe('payload-user-A');
    expect((await WorkflowRecovery.loadSnapshot(b)).payload).toBe('payload-user-B');
    expect(await WorkflowRecovery.clearSnapshot(a)).toBe(true);
    expect((await WorkflowRecovery.loadSnapshot(b)).payload).toBe('payload-user-B');
    expect(await WorkflowRecovery.clearSnapshot(b)).toBe(true);
  });

  test('同 key/同 version 的标签页 B 覆盖 A 后，A 的迟到 ack 不能删除 B', async () => {
    const tabA = { version: 1, workflowId: 'wf-tabs', userId: 'user-tabs', snapshotId: 'tab-A' };
    const tabB = { version: 1, workflowId: 'wf-tabs', userId: 'user-tabs', snapshotId: 'tab-B' };
    await WorkflowRecovery.saveSnapshot('payload-tab-A', tabA);
    await WorkflowRecovery.saveSnapshot('payload-tab-B', tabB);

    expect(await WorkflowRecovery.clearSnapshot(tabA)).toBe(false);
    const current = await WorkflowRecovery.loadSnapshot(tabB);
    expect(current.payload).toBe('payload-tab-B');
    expect(current.snapshotId).toBe('tab-B');
    expect(await WorkflowRecovery.clearSnapshot(tabB)).toBe(true);
  });

  test('snapshotId 相同但 version 不同时也不删除', async () => {
    const saved = { version: 4, workflowId: 'wf-version', userId: 'user-version', snapshotId: 'same-id' };
    await WorkflowRecovery.saveSnapshot('payload-version', saved);

    expect(await WorkflowRecovery.clearSnapshot({ ...saved, version: 5 })).toBe(false);
    expect((await WorkflowRecovery.loadSnapshot(saved)).payload).toBe('payload-version');
    expect(await WorkflowRecovery.clearSnapshot(saved)).toBe(true);
  });

  test('新 PUT 成功但新快照未写入时，可清理本 writer 序号更早的残留快照', async () => {
    const oldRecord = {
      version: 1,
      workflowId: 'wf-confirmed',
      userId: 'user-confirmed',
      snapshotId: 'snap-old',
      writerId: 'writer-A',
      writerSequence: 1,
      createdAt: 100,
    };
    const confirmedSave = {
      ...oldRecord,
      version: 2,
      snapshotId: 'snap-confirmed',
      writerSequence: 2,
      createdAt: 200,
    };
    await WorkflowRecovery.saveSnapshot('old-payload', oldRecord);

    expect(await WorkflowRecovery.clearConfirmedSnapshot(confirmedSave)).toBe(true);
    expect(await WorkflowRecovery.loadSnapshot(oldRecord)).toBeNull();
  });

  test('迟到确认不会清理本 writer 序号更新或相同但 token 不同的快照', async () => {
    const ack = {
      version: 1,
      workflowId: 'wf-created-at',
      userId: 'user-created-at',
      snapshotId: 'snap-ack',
      writerId: 'writer-A',
      writerSequence: 2,
      createdAt: 200,
    };
    const sameTime = { ...ack, snapshotId: 'snap-same-time' };
    await WorkflowRecovery.saveSnapshot('same-time-payload', sameTime);
    expect(await WorkflowRecovery.clearConfirmedSnapshot(ack)).toBe(false);
    expect((await WorkflowRecovery.loadSnapshot(ack)).snapshotId).toBe('snap-same-time');

    const newer = { ...ack, snapshotId: 'snap-newer', writerSequence: 3, createdAt: 300 };
    await WorkflowRecovery.saveSnapshot('newer-payload', newer);
    expect(await WorkflowRecovery.clearConfirmedSnapshot(ack)).toBe(false);
    expect((await WorkflowRecovery.loadSnapshot(ack)).snapshotId).toBe('snap-newer');
    expect(await WorkflowRecovery.clearSnapshot(newer)).toBe(true);
  });

  test('不同 writer 的快照即使创建更早，也不能被本页成功 PUT 清理', async () => {
    const otherTab = {
      version: 1,
      workflowId: 'wf-cross-writer',
      userId: 'user-cross-writer',
      snapshotId: 'snap-other-tab',
      writerId: 'writer-B',
      writerSequence: 1,
      createdAt: 100,
    };
    const thisTabAck = {
      ...otherTab,
      version: 2,
      snapshotId: 'snap-this-tab',
      writerId: 'writer-A',
      writerSequence: 2,
      createdAt: 200,
    };
    await WorkflowRecovery.saveSnapshot('other-tab-payload', otherTab);

    expect(await WorkflowRecovery.clearConfirmedSnapshot(thisTabAck)).toBe(false);
    expect((await WorkflowRecovery.loadSnapshot(otherTab)).snapshotId).toBe('snap-other-tab');
    expect(await WorkflowRecovery.clearSnapshot(otherTab)).toBe(true);
  });

  test('createWriteIdentity 在本页 writer 内生成单调序号和唯一 token', () => {
    const first = WorkflowRecovery.createWriteIdentity();
    const second = WorkflowRecovery.createWriteIdentity();
    expect(second.writerId).toBe(first.writerId);
    expect(second.writerSequence).toBe(first.writerSequence + 1);
    expect(second.snapshotId).not.toBe(first.snapshotId);
  });

  test('saveSnapshotSync：连接已打开时同步写入成功并可读回', async () => {
    // 用例内显式预热，不依赖其他测试的执行顺序。
    await WorkflowRecovery.prepare();
    const meta = { version: 9, workflowId: 'wf-3', userId: 'user-3', snapshotId: 'snap-sync-idb' };
    expect(WorkflowRecovery.saveSnapshotSync('{"workflow_data":"sync"}', meta)).toBe(true);
    const record = await WorkflowRecovery.loadSnapshot(meta);
    expect(record.payload).toBe('{"workflow_data":"sync"}');
    expect(record.workflowId).toBe('wf-3');
    expect(await WorkflowRecovery.clearSnapshot(meta)).toBe(true);
  });

  test('缺少 workflowId 或 userId 时写入/读取/清理全部 fail-closed', async () => {
    expect(await WorkflowRecovery.saveSnapshot('payload', { version: 1, userId: 'u' })).toBeNull();
    expect(await WorkflowRecovery.saveSnapshot('payload', { version: 1, workflowId: 'wf' })).toBeNull();
    expect(WorkflowRecovery.saveSnapshotSync('payload', { workflowId: 'wf' })).toBe(false);
    expect(await WorkflowRecovery.loadSnapshot({ workflowId: 'wf' })).toBeNull();
    expect(await WorkflowRecovery.clearSnapshot({
      workflowId: 'wf', snapshotId: 'snap', version: 1,
    })).toBe(false);
    expect(await WorkflowRecovery.saveSnapshot('payload', {
      version: 1, workflowId: 'wf', userId: 'u',
    })).toBeNull();
  });
});

// ========== 跨工作流/跨用户重放门控 ==========

describe('跨工作流/跨用户重放门控（matchesReplayContext）', () => {
  test('完全匹配 → 允许重放', () => {
    expect(
      WorkflowRecovery.matchesReplayContext(
        { payload: 'p', workflowId: 'wf-1', userId: 'u-1', snapshotId: 'snap-1' },
        { workflowId: 'wf-1', userId: 'u-1' }
      )
    ).toBe(true);
  });

  test('工作流 A 的快照恢复进工作流 B → 禁止（防跨工作流覆盖）', () => {
    expect(
      WorkflowRecovery.matchesReplayContext(
        { payload: 'p', workflowId: 'wf-1', userId: 'u-1', snapshotId: 'snap-1' },
        { workflowId: 'wf-2', userId: 'u-1' }
      )
    ).toBe(false);
  });

  test('账号切换（同一工作流）→ 禁止（防跨用户覆盖）', () => {
    expect(
      WorkflowRecovery.matchesReplayContext(
        { payload: 'p', workflowId: 'wf-1', userId: 'u-1', snapshotId: 'snap-1' },
        { workflowId: 'wf-1', userId: 'u-2' }
      )
    ).toBe(false);
  });

  test('workflowId 数字/字符串归一化后匹配', () => {
    expect(
      WorkflowRecovery.matchesReplayContext(
        { payload: 'p', workflowId: '12', userId: 'u-1', snapshotId: 'snap-1' },
        { workflowId: 12, userId: 'u-1' }
      )
    ).toBe(true);
  });

  test('旧版或上下文身份缺失 → fail-closed 拒绝', () => {
    expect(
      WorkflowRecovery.matchesReplayContext(
        { payload: 'p', workflowId: null, userId: null, snapshotId: 'snap-1' },
        { workflowId: 'wf-1', userId: 'u-1' }
      )
    ).toBe(false);
    expect(
      WorkflowRecovery.matchesReplayContext(
        { payload: 'p', workflowId: 'wf-1', userId: null, snapshotId: 'snap-1' },
        { workflowId: 'wf-1', userId: 'u-1' }
      )
    ).toBe(false);
    expect(
      WorkflowRecovery.matchesReplayContext(
        { payload: 'p', workflowId: 'wf-1', userId: 'u-1', snapshotId: 'snap-1' },
        { workflowId: 'wf-1' }
      )
    ).toBe(false);
  });

  test('无记录 / 无 payload → 禁止', () => {
    expect(WorkflowRecovery.matchesReplayContext(null, { workflowId: 'wf-1', userId: 'u-1' })).toBe(false);
    expect(
      WorkflowRecovery.matchesReplayContext({ version: 1 }, { workflowId: 'wf-1', userId: 'u-1' })
    ).toBe(false);
  });
});

// ========== v1 全局 latest 记录迁移 ==========
// 放在常规用例之后：vi.resetModules 会重建模块级 IDB 连接缓存。

describe('IndexedDB v1 记录迁移', () => {
  test('带完整身份的 latest 迁移到分区 key 并生成 snapshotId', async () => {
    const migratingIdb = createFakeIndexedDB();
    migratingIdb.seed(
      'video_workflow_recovery',
      1,
      'snapshots',
      'latest',
      {
        payload: 'legacy-payload',
        version: 3,
        workflowId: 'wf-legacy',
        userId: 'user-legacy',
      }
    );
    vi.stubGlobal('indexedDB', migratingIdb);
    try {
      vi.resetModules();
      const fresh = await import('../js/auto_save_state.js');
      const mod = fresh.default || fresh;
      const context = { workflowId: 'wf-legacy', userId: 'user-legacy' };
      const record = await mod.WorkflowRecovery.loadSnapshot(context);

      expect(record.payload).toBe('legacy-payload');
      expect(record.version).toBe(3);
      expect(typeof record.snapshotId).toBe('string');
      expect(record.snapshotId.length).toBeGreaterThan(0);
      expect(migratingIdb.has('video_workflow_recovery', 'snapshots', 'latest')).toBe(false);
      expect(await mod.WorkflowRecovery.clearSnapshot(record)).toBe(true);
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test('缺少身份的 latest 在升级时删除，不做不安全重放', async () => {
    const migratingIdb = createFakeIndexedDB();
    migratingIdb.seed(
      'video_workflow_recovery',
      1,
      'snapshots',
      'latest',
      { payload: 'unsafe-legacy-payload', version: 4 }
    );
    vi.stubGlobal('indexedDB', migratingIdb);
    try {
      vi.resetModules();
      const fresh = await import('../js/auto_save_state.js');
      const mod = fresh.default || fresh;
      await expect(
        mod.WorkflowRecovery.loadSnapshot({ workflowId: 'wf-any', userId: 'user-any' })
      ).resolves.toBeNull();
      expect(migratingIdb.has('video_workflow_recovery', 'snapshots', 'latest')).toBe(false);
    } finally {
      vi.unstubAllGlobals();
    }
  });
});

describe('IndexedDB 打开降级与重试', () => {
  test('version upgrade 被 blocked 时不悬挂保存，后续读写可重试', async () => {
    const retryTarget = createFakeIndexedDB();
    let openAttempts = 0;
    const blockedThenReady = {
      open: (...args) => {
        openAttempts += 1;
        if (openAttempts === 1) {
          const req = { result: undefined, onsuccess: null, onerror: null, onabort: null, onblocked: null };
          queueMicrotask(() => {
            if (req.onblocked) req.onblocked({ target: req });
          });
          return req;
        }
        return retryTarget.open(...args);
      },
    };
    vi.stubGlobal('indexedDB', blockedThenReady);
    try {
      vi.resetModules();
      const fresh = await import('../js/auto_save_state.js');
      const mod = fresh.default || fresh;
      await expect(mod.WorkflowRecovery.prepare()).resolves.toBeNull();

      const meta = {
        version: 1,
        workflowId: 'wf-retry',
        userId: 'user-retry',
        snapshotId: 'snap-retry',
      };
      await expect(mod.WorkflowRecovery.saveSnapshot('retry-payload', meta)).resolves.toBe(true);
      expect((await mod.WorkflowRecovery.loadSnapshot(meta)).payload).toBe('retry-payload');
      expect(openAttempts).toBe(2);
    } finally {
      vi.unstubAllGlobals();
    }
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
        mod.WorkflowRecovery.saveSnapshot('{"a":1}', {
          version: 1, workflowId: '1', userId: 'u1', snapshotId: 'snap-1',
        })
      ).resolves.toBe(null);
      await expect(mod.WorkflowRecovery.loadSnapshot({ workflowId: '1', userId: 'u1' })).resolves.toBe(null);
      await expect(mod.WorkflowRecovery.clearSnapshot({
        version: 1, workflowId: '1', userId: 'u1', snapshotId: 'snap-1',
      })).resolves.toBe(false);
      await expect(mod.WorkflowRecovery.prepare()).resolves.toBe(null);
      expect(mod.WorkflowRecovery.saveSnapshotSync('{"a":1}', {
        workflowId: '1', userId: 'u1', snapshotId: 'snap-1',
      })).toBe(false);

      // 状态机在无 IDB 环境下同样可用
      const m = mod.createAutoSaveState();
      m.markDirty();
      expect(m.planUnloadSend(SMALL_BODY)).toEqual({ action: 'send', keepalive: true, abort: false });
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
