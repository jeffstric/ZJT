/**
 * 自动保存状态机 + 关页/重载恢复快照（IndexedDB）。
 *
 * 背景（为什么不能只检查防抖定时器）：
 * - 定时器触发后 / flushAutoSave 已启动普通 fetch 时，定时器为 null 但请求仍在途；
 *   普通 fetch 在页面卸载时可能被浏览器取消 → 必须跟踪"是否有未确认的修改"，
 *   关页时只要最新版本未被服务器确认就补发（keepalive）。
 * - keepalive 请求体有 64KiB 硬上限（MDN RequestInit.keepalive），大工作流无法
 *   靠 keepalive 保证送达 → 发送前先把 payload 写入 IndexedDB 恢复记录，
 *   下次加载时重放（re-PUT）未确认记录，作为降低丢失风险的
 *   best-effort 恢复机制（卸载时 IDB 事务仍不保证已持久化）。
 *
 * 状态：
 *   version          —— 每次修改（safeAutoSave/flushAutoSave）自增
 *   confirmedVersion —— 服务器已确认的最高版本
 *   inFlight         —— { controller, sentVersion, keepalive, requestStarted }，当前保存
 *
 * 确认规则：只有"发送后没有新修改"（sentVersion === version）的成功响应才推进
 * confirmedVersion，避免过期响应的确认造成"旧确认覆盖新状态"的错觉。
 *
 * 恢复记录的本地安全不变式：同一用户/工作流 key 保留最后一次 IDB 写入，
 * 成功 PUT 只能清理本次 snapshotId/version，或同 writerId 下序号更早的记录。
 * 这能防止迟到 ack 误清更新恢复快照，但不解决已到达服务端的
 * 跨标签页 PUT 乱序；后者需后端 revision/CAS 才能严格保证。
 *
 * 恢复记录按 { userId, workflowId } 使用独立 key，避免不同用户/工作流互相
 * 覆盖或误清。同一工作流的多标签页仍共享 key（最后一次写入胜出）；每次写入
 * 另带全局唯一 snapshotId，清理时同时匹配 snapshotId 和 version，防止
 * 迟到响应删除另一标签页的新快照。
 *
 * endSend 返回布尔（仅"该请求是最新发送且成功"为 true），调用方据此决定是否
 * 清除恢复记录：被新请求取代的旧请求的成功 ack 不得清掉新请求的恢复快照。
 */
(function(root){
  'use strict';

  // 64KiB 以下留安全余量（与 node_base.js 关页保存逻辑共用）
  const KEEPALIVE_BODY_MAX_BYTES = 59000;

  /**
   * 创建自动保存状态机实例（页面用单例；测试可独立实例）。
   */
  function createAutoSaveState(){
    const saveState = {
      version: 0,
      confirmedVersion: 0,
      inFlight: null
    };

    // 一次用户操作/状态变更 → 一个待确认版本
    function markDirty(){
      saveState.version += 1;
    }

    function isDirty(){
      return saveState.version > saveState.confirmedVersion;
    }

    /**
     * 记录一次 PUT 开始，返回 sentVersion（调用方需保存并在 endSend 时回传）。
     * 新的 beginSend 覆盖 inFlight：旧请求的 endSend 因 sentVersion 不匹配自动失效，
     * 调用方在发新请求前 abort 旧 controller 防止过期 payload 晚到覆盖新状态。
     */
    function beginSend(controller, keepalive){
      saveState.inFlight = {
        controller: controller || null,
        sentVersion: saveState.version,
        keepalive: !!keepalive,
        // beginSend 在常规路径中早于 await saveSnapshot；此时网络请求
        // 尚未创建，关页决策不能把它误判为“已在途”。
        requestStarted: false
      };
      return saveState.version;
    }

    // fetch 创建后立即标记；被更新 beginSend 取代的旧保存不得改写新状态。
    function markRequestStarted(sentVersion){
      const entry = saveState.inFlight;
      if(!entry || entry.sentVersion !== sentVersion) return false;
      entry.requestStarted = true;
      return true;
    }

    /**
     * PUT 结束（成功/失败）。
     * - 被更新的发送取代（inFlight.sentVersion 已变）→ 无操作
     * - 成功且发送后无新修改 → 推进 confirmedVersion（不回退）
     * - 失败 / 发送后有新修改 → 保持 dirty，等待下一次保存确认
     *
     * 返回 true 仅当"该请求是最新发送且成功"（确认成立）。调用方（autoSaveWorkflow）
     * 据此决定是否清除恢复记录：被取代的旧请求的成功 ack 必须返回 false，
     * 否则旧请求成功时会清掉新请求的恢复快照，而新请求可能随后失败。
     */
    function endSend(sentVersion, success){
      const entry = saveState.inFlight;
      if(!entry || entry.sentVersion !== sentVersion) return false;
      saveState.inFlight = null;
      if(success && sentVersion === saveState.version){
        if(sentVersion > saveState.confirmedVersion){
          saveState.confirmedVersion = sentVersion;
        }
        return true;
      }
      return false;
    }

    // 中止在途请求（关页补发前调用，防止过期 payload 晚到覆盖新状态）
    function abortInFlight(){
      const entry = saveState.inFlight;
      if(entry && entry.controller && typeof entry.controller.abort === 'function'){
        try { entry.controller.abort(); } catch(e) {}
      }
      // 不清空 inFlight：新 beginSend 会覆盖；旧的 endSend 因 sentVersion 不匹配失效
    }

    /**
     * 关页（beforeunload）补发决策：
     *   { action: 'none' }                —— 无需补发
     *   { action: 'send', keepalive, abort } —— (必要时中止在途) 后重新发送最新 PUT
     *
     * 分支：
     * - 在途请求已是最新版本：
     *   - keepalive 请求 → 会随卸载继续发送，无需补发
     *   - 普通请求且 body 可 keepalive → 中止并升级为 keepalive 重发（严格更优）
     *   - 普通请求且 body 超限 → 无法升级，让它尽力发送（恢复记录已请求写入）
     * - 在途请求已过期（发送后有新修改）→ 中止并用 keepalive（或超限时普通）重发最新
     * - 无在途但有未确认修改 → 发送（可 keepalive 时 keepalive）
     */
    function planUnloadSend(bodyBytes){
      const keepaliveOk = bodyBytes <= KEEPALIVE_BODY_MAX_BYTES;
      const entry = saveState.inFlight;

      if(entry){
        // 常规保存可能仍在 await IndexedDB，网络 PUT 并未启动。
        // 卸载时必须中止它的 controller（防止后续补发旧 body），
        // 并用当前最新 payload 立即启动新请求，大 body 也不能跳过。
        if(!entry.requestStarted){
          return { action: 'send', keepalive: keepaliveOk, abort: true };
        }
        if(entry.sentVersion === saveState.version){
          if(entry.keepalive || !keepaliveOk){
            return { action: 'none' };
          }
          // 最新的普通 fetch 可能随卸载被取消 → 中止后升级为 keepalive
          return { action: 'send', keepalive: true, abort: true };
        }
        return { action: 'send', keepalive: keepaliveOk, abort: true };
      }

      if(!isDirty()){
        return { action: 'none' };
      }
      return { action: 'send', keepalive: keepaliveOk, abort: false };
    }

    function reset(){
      saveState.version = 0;
      saveState.confirmedVersion = 0;
      saveState.inFlight = null;
    }

    return {
      state: saveState,
      markDirty: markDirty,
      isDirty: isDirty,
      beginSend: beginSend,
      markRequestStarted: markRequestStarted,
      endSend: endSend,
      abortInFlight: abortInFlight,
      planUnloadSend: planUnloadSend,
      reset: reset
    };
  }

  // ========== 恢复快照（IndexedDB，best-effort） ==========
  //
  // 常规自动保存 PUT 发送【前】写入 payload，确认成功后按 snapshotId/version
  // 条件清除。beforeunload 不能等待异步事务：该路径先启动 keepalive fetch，
  // IndexedDB 只做 best-effort 兜底。无 indexedDB 环境静默降级为 no-op。
  //
  // 记录形状：
  // { payload, version, workflowId, userId, snapshotId, writerId, writerSequence, createdAt }——
  // - payload 为 PUT body 原文（重放时原样发送，不重新序列化）；
  // - workflowId/userId 共同组成 IndexedDB key，不同工作流互不覆盖；
  // - snapshotId/version 用于精确 compare-and-delete；writerId/writerSequence 只在
  //   同一标签页内判断先后，禁止用时间戳跨标签页删除快照。

  const RECOVERY_DB_NAME = 'video_workflow_recovery';
  const RECOVERY_STORE = 'snapshots';
  const RECOVERY_DB_VERSION = 2;
  const LEGACY_RECOVERY_KEY = 'latest';
  const RECOVERY_KEY_PREFIX = 'workflow:';
  let _snapshotSequence = 0;

  function normalizeRecoveryIdentity(value){
    return (value === undefined || value === null || value === '') ? null : String(value);
  }

  function normalizeFiniteNumber(value){
    if(value === undefined || value === null || value === '') return null;
    const numberValue = Number(value);
    return Number.isFinite(numberValue) ? numberValue : null;
  }

  function buildRecoveryKey(meta){
    const m = meta || {};
    const workflowId = normalizeRecoveryIdentity(m.workflowId);
    const userId = normalizeRecoveryIdentity(m.userId);
    if(!workflowId || !userId) return null;
    // JSON 数组编码避免简单分隔符在 ID 本身包含特殊字符时产生碰撞。
    return RECOVERY_KEY_PREFIX + JSON.stringify([userId, workflowId]);
  }

  function createSnapshotId(){
    try {
      if(typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'){
        return crypto.randomUUID();
      }
    } catch(e) {}
    _snapshotSequence += 1;
    return Date.now().toString(36) + '-' + _snapshotSequence.toString(36) + '-' +
      Math.random().toString(36).slice(2);
  }

  // 每个页面/标签页独立 writer；只有同 writer 的单调序号才可比较先后。
  // 不能用 createdAt 跨标签页排序：较早创建的另一标签页快照仍可能未送达。
  const RECOVERY_WRITER_ID = createSnapshotId();
  let _writerSequence = 0;

  function createWriteIdentity(){
    _writerSequence += 1;
    return {
      snapshotId: createSnapshotId(),
      writerId: RECOVERY_WRITER_ID,
      writerSequence: _writerSequence,
      createdAt: Date.now()
    };
  }

  function openRecoveryDb(){
    return new Promise(function(resolve){
      let settled = false;
      function finish(db){
        if(settled){
          // 升级被其他标签页阻塞后，open 请求可能在稍后才成功。
          // 本次调用已降级返回 null，迟到的连接必须关闭，避免泄漏。
          if(db){ try { db.close(); } catch(e){} }
          return;
        }
        settled = true;
        resolve(db || null);
      }
      if(typeof indexedDB === 'undefined'){
        finish(null);
        return;
      }
      let req;
      try {
        req = indexedDB.open(RECOVERY_DB_NAME, RECOVERY_DB_VERSION);
      } catch(e){
        finish(null);
        return;
      }
      req.onupgradeneeded = function(event){
        try {
          const db = req.result;
          if(!db.objectStoreNames.contains(RECOVERY_STORE)){
            db.createObjectStore(RECOVERY_STORE);
          } else if(event && event.oldVersion < 2 && req.transaction){
            // v1 使用全局 latest。只迁移带完整上下文的记录；缺少用户/工作流身份的
            // 旧记录不能安全恢复，直接删除，避免跨工作流覆盖。
            const store = req.transaction.objectStore(RECOVERY_STORE);
            const legacyReq = store.get(LEGACY_RECOVERY_KEY);
            legacyReq.onsuccess = function(){
              const legacy = legacyReq.result;
              const scopedKey = buildRecoveryKey(legacy);
              if(legacy && legacy.payload && scopedKey){
                legacy.snapshotId = legacy.snapshotId || createSnapshotId();
                legacy.writerId = legacy.writerId || 'legacy-v1';
                legacy.writerSequence = Number.isFinite(Number(legacy.writerSequence))
                  ? Number(legacy.writerSequence)
                  : 0;
                legacy.createdAt = Number.isFinite(Number(legacy.createdAt))
                  ? Number(legacy.createdAt)
                  : 0;
                store.put(legacy, scopedKey);
              }
              store.delete(LEGACY_RECOVERY_KEY);
            };
          }
        } catch(e){}
      };
      req.onsuccess = function(){
        const db = req.result;
        db.onversionchange = function(){
          try { db.close(); } catch(e){}
          // 连接已因其他页面升级而关闭；清掉缓存，后续读写重新 open。
          if(_recoveryDb === db){
            _recoveryDb = null;
            _recoveryDbPromise = null;
          }
        };
        finish(db);
      };
      req.onerror = function(){ finish(null); };
      req.onabort = function(){ finish(null); };
      // 不让被旧标签页阻塞的版本升级卡住常规自动保存。
      // 本次快照静默降级，后续保存会重试打开 IDB。
      req.onblocked = function(){ finish(null); };
    });
  }

  let _recoveryDb = null;
  let _recoveryDbPromise = null;

  function ensureRecoveryDb(){
    if(_recoveryDb) return Promise.resolve(_recoveryDb);
    if(!_recoveryDbPromise){
      _recoveryDbPromise = openRecoveryDb().then(function(db){
        _recoveryDb = db;
        if(!db) _recoveryDbPromise = null;
        return db;
      });
    }
    return _recoveryDbPromise;
  }

  function runRecoveryStore(mode, storeFn){
    return ensureRecoveryDb().then(function(db){
      if(!db) return null;
      return new Promise(function(resolve){
        try {
          const tx = db.transaction(RECOVERY_STORE, mode);
          const store = tx.objectStore(RECOVERY_STORE);
          const out = storeFn(store);
          tx.oncomplete = function(){ resolve(out); };
          tx.onerror = function(){ resolve(null); };
          tx.onabort = function(){ resolve(null); };
        } catch(e){
          resolve(null);
        }
      });
    });
  }

  // 归一化 meta。workflowId/userId 缺失时记录不可安全分区，调用方会拒绝写入。
  function buildRecoveryRecord(payload, meta){
    const m = meta || {};
    return {
      payload: payload,
      version: m.version || 0,
      workflowId: normalizeRecoveryIdentity(m.workflowId),
      userId: normalizeRecoveryIdentity(m.userId),
      snapshotId: m.snapshotId ? String(m.snapshotId) : null,
      writerId: m.writerId ? String(m.writerId) : null,
      writerSequence: normalizeFiniteNumber(m.writerSequence),
      createdAt: normalizeFiniteNumber(m.createdAt)
    };
  }

  const WorkflowRecovery = {
    /**
     * 写入待恢复记录。
     * @param {string} payload PUT body 原文
     * @param {{version?: number, workflowId: (string|number), userId: (string|number), snapshotId: string, writerId?: string, writerSequence?: number, createdAt?: number}} meta
     * 返回 Promise<boolean>（是否写入成功）；所有异常内部吞掉。
     * 注意：调用方（autoSaveWorkflow）必须 await 后再发 fetch，"发送前写入"才成立。
     * snapshotId 必填：若内部生成却不返回，调用方将无法安全条件清理。
     */
    saveSnapshot: function(payload, meta){
      const record = buildRecoveryRecord(payload, meta);
      const key = buildRecoveryKey(record);
      if(!key || !record.snapshotId) return Promise.resolve(null);
      return runRecoveryStore('readwrite', function(store){
        store.put(record, key);
        return true;
      });
    },

    /**
     * 同步尽力排队（best-effort，可用于 beforeunload 同步上下文）：
     * 连接已打开时立即调用 put；这只表示请求已进入 IDB 事务队列，不代表事务已
     * 持久化。连接未打开或任何异常时返回 false，由 startUnloadSend 在网络请求
     * 已同步启动后再异步补写。
     */
    saveSnapshotSync: function(payload, meta){
      if(!_recoveryDb) return false;
      try {
        const record = buildRecoveryRecord(payload, meta);
        const key = buildRecoveryKey(record);
        if(!key || !record.snapshotId) return false;
        _recoveryDb
          .transaction(RECOVERY_STORE, 'readwrite')
          .objectStore(RECOVERY_STORE)
          .put(record, key);
        return true;
      } catch(e){
        return false;
      }
    },

    /**
     * 卸载发送启动器：直接同步调用 fetch，而不是接收可能内部 await 的
     * 异步回调。因此可严格保证 fetch(..., {keepalive:true}) 在 beforeunload
     * 事件回调返回前已创建。IndexedDB 连接未就绪时，网络请求启动后再
     * 异步补写恢复记录。fetchImpl 仅用于测试注入。
     */
    startUnloadSend: function(payload, meta, requestUrl, requestOptions, fetchImpl){
      const syncQueued = this.saveSnapshotSync(payload, meta);
      let sendPromise;
      try {
        const transport = fetchImpl || root.fetch;
        if(typeof transport !== 'function') throw new Error('fetch is unavailable');
        sendPromise = Promise.resolve(transport(requestUrl, requestOptions));
      } catch(error){
        sendPromise = Promise.reject(error);
      }
      const snapshotPromise = syncQueued
        ? Promise.resolve(true)
        : this.saveSnapshot(payload, meta);
      return { sendPromise: sendPromise, snapshotPromise: snapshotPromise, syncQueued: syncQueued };
    },

    /**
     * beforeunload 决策与调度的可测试入口。send 在函数返回前同步调用，
     * 生产环境传入 autoSaveWorkflow；它收到 unload=true 后会进入上面的
     * startUnloadSend，从而在首个 await 前直接启动 fetch。
     */
    dispatchBeforeUnloadSave: function(options){
      const opts = options || {};
      const saveState = opts.saveState;
      if(!saveState || typeof saveState.isDirty !== 'function' || !saveState.isDirty()){
        return { action: 'none' };
      }
      if(typeof opts.serializeBody !== 'function' || typeof opts.send !== 'function'){
        return { action: 'none' };
      }

      const body = opts.serializeBody();
      const bodyBytes = typeof opts.measureBodyBytes === 'function'
        ? opts.measureBodyBytes(body)
        : body.length;
      const plan = saveState.planUnloadSend(bodyBytes);
      if(plan.action !== 'send') return plan;

      if(plan.abort) saveState.abortInFlight();
      if(typeof opts.cancelPending === 'function') opts.cancelPending();
      if(!plan.keepalive && typeof opts.warnLargeBody === 'function') opts.warnLargeBody();

      opts.send({
        skipHistory: true,
        keepalive: plan.keepalive,
        unload: true,
        serializedBody: body
      });
      return plan;
    },

    /**
     * 重放门控：记录必须属于当前工作流 + 当前用户才允许重放，
     * 防止跨工作流/跨账号覆盖（A 留下未确认快照 → 打开 B 不能把 A 内容恢复进 B）。
     * 任一身份缺失都拒绝重放，采用 fail-closed，避免不确定上下文造成跨账号覆盖。
     */
    matchesReplayContext: function(record, context){
      if(!record || !record.payload || !record.snapshotId) return false;
      const recordKey = buildRecoveryKey(record);
      const contextKey = buildRecoveryKey(context);
      return !!recordKey && !!contextKey && recordKey === contextKey;
    },

    /**
     * 读取当前用户 + 工作流的待恢复记录。
     */
    loadSnapshot: function(context){
      const key = buildRecoveryKey(context);
      if(!key) return Promise.resolve(null);
      return ensureRecoveryDb().then(function(db){
        if(!db) return null;
        return new Promise(function(resolve){
          try {
            const tx = db.transaction(RECOVERY_STORE, 'readonly');
            const req = tx.objectStore(RECOVERY_STORE).get(key);
            req.onsuccess = function(){
              const value = req.result || null;
              resolve(value && value.payload ? value : null);
            };
            req.onerror = function(){ resolve(null); };
            tx.onabort = function(){ resolve(null); };
          } catch(e){
            resolve(null);
          }
        });
      });
    },

    /**
     * 条件清除待恢复记录。只有 key、snapshotId、version 都仍匹配时才删除，
     * 防止另一标签页写入新快照后被迟到的成功响应误清。
     */
    clearSnapshot: function(meta){
      const expected = meta || {};
      const key = buildRecoveryKey(expected);
      if(!key || !expected.snapshotId) return Promise.resolve(false);
      return ensureRecoveryDb().then(function(db){
        if(!db) return false;
        return new Promise(function(resolve){
          let cleared = false;
          try {
            const tx = db.transaction(RECOVERY_STORE, 'readwrite');
            const store = tx.objectStore(RECOVERY_STORE);
            const req = store.get(key);
            req.onsuccess = function(){
              const current = req.result;
              if(!current) return;
              const sameSnapshot = String(current.snapshotId || '') === String(expected.snapshotId);
              const sameVersion = Number(current.version || 0) === Number(expected.version || 0);
              if(sameSnapshot && sameVersion){
                store.delete(key);
                cleared = true;
              }
            };
            req.onerror = function(){ resolve(false); };
            tx.oncomplete = function(){ resolve(cleared); };
            tx.onerror = function(){ resolve(false); };
            tx.onabort = function(){ resolve(false); };
          } catch(e){
            resolve(false);
          }
        });
      });
    },

    /**
     * 最新的手动/自动保存已获服务器确认时清理恢复记录。
     * 除精确匹配本次 snapshotId/version 外，也可删除“同 writerId 且
     * writerSequence 更小”的旧记录。这处理“本页新快照写入临时失败，
     * 但新 PUT 成功”时的旧快照残留；不同 writer 永远不做先后比较。
     */
    clearConfirmedSnapshot: function(meta){
      const expected = meta || {};
      const key = buildRecoveryKey(expected);
      const expectedSequence = normalizeFiniteNumber(expected.writerSequence);
      if(!key || !expected.snapshotId){
        return Promise.resolve(false);
      }
      return ensureRecoveryDb().then(function(db){
        if(!db) return false;
        return new Promise(function(resolve){
          let cleared = false;
          try {
            const tx = db.transaction(RECOVERY_STORE, 'readwrite');
            const store = tx.objectStore(RECOVERY_STORE);
            const req = store.get(key);
            req.onsuccess = function(){
              const current = req.result;
              if(!current) return;
              const sameSnapshot = String(current.snapshotId || '') === String(expected.snapshotId);
              const sameVersion = Number(current.version || 0) === Number(expected.version || 0);
              const currentSequence = normalizeFiniteNumber(current.writerSequence);
              const sameWriter = !!expected.writerId &&
                String(current.writerId || '') === String(expected.writerId);
              const strictlyOlder = sameWriter && expectedSequence !== null &&
                currentSequence !== null && currentSequence < expectedSequence;
              if((sameSnapshot && sameVersion) || strictlyOlder){
                store.delete(key);
                cleared = true;
              }
            };
            req.onerror = function(){ resolve(false); };
            tx.oncomplete = function(){ resolve(cleared); };
            tx.onerror = function(){ resolve(false); };
            tx.onabort = function(){ resolve(false); };
          } catch(e){
            resolve(false);
          }
        });
      });
    },

    // 页面初始化时预热 IDB 连接，提高 beforeunload 同步 put 能入队的概率。
    // 这仍然是 best-effort，调用方不需要等待。
    prepare: function(){
      return ensureRecoveryDb();
    },

    createWriteIdentity: createWriteIdentity,
    createSnapshotId: createSnapshotId,
    buildRecoveryKey: buildRecoveryKey
  };

  // 页面级单例（workflow.js / node_base.js 引用）；测试用 createAutoSaveState()
  // 建独立实例，避免互相污染
  root.autoSaveState = createAutoSaveState();

  root.createAutoSaveState = createAutoSaveState;
  root.WorkflowRecovery = WorkflowRecovery;
  root.KEEPALIVE_BODY_MAX_BYTES = KEEPALIVE_BODY_MAX_BYTES;
})(typeof window !== 'undefined' ? window : globalThis);

// Node.js 环境（Vitest）：导出供测试使用，不影响浏览器全局变量
if (typeof module !== 'undefined') {
  module.exports = { createAutoSaveState, WorkflowRecovery, KEEPALIVE_BODY_MAX_BYTES };
}
