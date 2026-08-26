/**
 * 自动保存状态机 + 关页/重载恢复快照（IndexedDB）。
 *
 * 背景（为什么不能只检查防抖定时器）：
 * - 定时器触发后 / flushAutoSave 已启动普通 fetch 时，定时器为 null 但请求仍在途；
 *   普通 fetch 在页面卸载时可能被浏览器取消 → 必须跟踪"是否有未确认的修改"，
 *   关页时只要最新版本未被服务器确认就补发（keepalive）。
 * - keepalive 请求体有 64KiB 硬上限（MDN RequestInit.keepalive），大工作流无法
 *   靠 keepalive 保证送达 → 发送前先把 payload 写入 IndexedDB 恢复记录，
 *   下次加载时重放（re-PUT）未确认记录，保证大工作流最后修改不丢。
 *
 * 状态：
 *   version          —— 每次修改（safeAutoSave/flushAutoSave）自增
 *   confirmedVersion —— 服务器已确认的最高版本
 *   inFlight         —— { controller, sentVersion, keepalive }，当前在途 PUT
 *
 * 确认规则：只有"发送后没有新修改"（sentVersion === version）的成功响应才推进
 * confirmedVersion，避免过期响应的确认造成"旧确认覆盖新状态"的错觉。
 *
 * 恢复记录安全不变式：记录始终保存"最后一次已发送的 payload"——新的 PUT 在
 * 发送前覆盖它，确认成功的 PUT 清除它。因此加载时重放未确认记录永远不会用旧
 * 数据覆盖更新的服务端状态：更新的服务端状态只能来自更新的 PUT 成功，而那次
 * PUT 要么已覆盖记录（重放的就是新 payload）、要么已清除记录（无记录可重放）。
 *
 * 记录带 { workflowId, userId } 门控：单条 'latest' 槽位是全局的，工作流 A 留下
 * 未确认快照后打开 B，绝不能把 A 的内容重放进 B（跨工作流/跨账号覆盖）。重放前
 * 必须经 matchesReplayContext 校验当前 URL 工作流与当前用户与记录一致。
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
        keepalive: !!keepalive
      };
      return saveState.version;
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
     *   - 普通请求且 body 超限 → 无法升级，让它尽力发送（恢复记录已在发送前写入）
     * - 在途请求已过期（发送后有新修改）→ 中止并用 keepalive（或超限时普通）重发最新
     * - 无在途但有未确认修改 → 发送（可 keepalive 时 keepalive）
     */
    function planUnloadSend(bodyBytes){
      const keepaliveOk = bodyBytes <= KEEPALIVE_BODY_MAX_BYTES;
      const entry = saveState.inFlight;

      if(entry){
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
      endSend: endSend,
      abortInFlight: abortInFlight,
      planUnloadSend: planUnloadSend,
      reset: reset
    };
  }

  // ========== 恢复快照（IndexedDB，best-effort） ==========
  //
  // 每次自动保存 PUT 发送【前】写入 payload（防抖的 1.5s 余量保证页面卸载前已落盘），
  // 确认成功后清除。无 indexedDB 环境（老浏览器/隐私模式）静默降级为 no-op，
  // 关页 keepalive 路径不受影响。
  //
  // 记录形状：{ payload, version, workflowId, userId }——
  // - payload 为 PUT body 原文（重放时原样发送，不重新序列化）；
  // - workflowId/userId 用于重放门控（matchesReplayContext），防止"工作流 A 的
  //   未确认快照被重放到工作流 B"的跨工作流/跨账号覆盖；
  // - 单条 'latest' 槽位：新保存的 PUT 发送前覆盖，恒为"最后一次已发送 payload"。

  const RECOVERY_DB_NAME = 'video_workflow_recovery';
  const RECOVERY_STORE = 'snapshots';
  const RECOVERY_KEY = 'latest';

  function openRecoveryDb(){
    return new Promise(function(resolve){
      if(typeof indexedDB === 'undefined'){
        resolve(null);
        return;
      }
      let req;
      try {
        req = indexedDB.open(RECOVERY_DB_NAME, 1);
      } catch(e){
        resolve(null);
        return;
      }
      req.onupgradeneeded = function(){
        try {
          const db = req.result;
          if(!db.objectStoreNames.contains(RECOVERY_STORE)){
            db.createObjectStore(RECOVERY_STORE);
          }
        } catch(e){}
      };
      req.onsuccess = function(){
        const db = req.result;
        db.onversionchange = function(){ try { db.close(); } catch(e){} };
        resolve(db);
      };
      req.onerror = function(){ resolve(null); };
      req.onabort = function(){ resolve(null); };
    });
  }

  let _recoveryDb = null;
  let _recoveryDbPromise = null;

  function ensureRecoveryDb(){
    if(_recoveryDb) return Promise.resolve(_recoveryDb);
    if(!_recoveryDbPromise){
      _recoveryDbPromise = openRecoveryDb().then(function(db){
        _recoveryDb = db;
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

  // 归一化 meta：workflowId/userId 缺失时存 null（旧版记录语义，best-effort 重放）
  function buildRecoveryRecord(payload, meta){
    const m = meta || {};
    return {
      payload: payload,
      version: m.version || 0,
      workflowId: (m.workflowId === undefined || m.workflowId === null || m.workflowId === '')
        ? null : String(m.workflowId),
      userId: (m.userId === undefined || m.userId === null || m.userId === '')
        ? null : String(m.userId)
    };
  }

  const WorkflowRecovery = {
    /**
     * 写入待恢复记录。
     * @param {string} payload PUT body 原文
     * @param {{version?: number, workflowId?: (string|number), userId?: (string|number)}} meta
     * 返回 Promise<boolean>（是否写入成功）；所有异常内部吞掉。
     * 注意：调用方（autoSaveWorkflow）必须 await 后再发 fetch，"发送前写入"才成立。
     */
    saveSnapshot: function(payload, meta){
      return runRecoveryStore('readwrite', function(store){
        store.put(buildRecoveryRecord(payload, meta), RECOVERY_KEY);
        return true;
      });
    },

    /**
     * 同步尽力写入（best-effort，可安全用于 beforeunload 同步上下文）：
     * 连接已打开时立即发出 put（put 调用本身是同步的），保证页面销毁前写入已
     * 提交到 IDB 队列；连接未打开（页面刚加载尚未发生过保存）或任何异常时
     * 静默返回 false，不抛不阻塞。关页路径先调它，随后 autoSaveWorkflow 的
     * 异步 saveSnapshot 会以相同 payload 覆写，无副作用。
     */
    saveSnapshotSync: function(payload, meta){
      if(!_recoveryDb) return false;
      try {
        _recoveryDb
          .transaction(RECOVERY_STORE, 'readwrite')
          .objectStore(RECOVERY_STORE)
          .put(buildRecoveryRecord(payload, meta), RECOVERY_KEY);
        return true;
      } catch(e){
        return false;
      }
    },

    /**
     * 重放门控：记录必须属于当前工作流 + 当前用户才允许重放，
     * 防止跨工作流/跨账号覆盖（A 留下未确认快照 → 打开 B 不能把 A 内容恢复进 B）。
     * 记录的 workflowId/userId 为 null（旧版记录）或上下文缺失时视为匹配（best effort）。
     */
    matchesReplayContext: function(record, context){
      if(!record || !record.payload) return false;
      const c = context || {};
      if(record.workflowId !== null && record.workflowId !== undefined
        && c.workflowId !== null && c.workflowId !== undefined
        && String(record.workflowId) !== String(c.workflowId)) return false;
      if(record.userId !== null && record.userId !== undefined
        && c.userId !== null && c.userId !== undefined
        && String(record.userId) !== String(c.userId)) return false;
      return true;
    },

    /**
     * 读取待恢复记录 {payload, version} | null。
     */
    loadSnapshot: function(){
      return ensureRecoveryDb().then(function(db){
        if(!db) return null;
        return new Promise(function(resolve){
          try {
            const tx = db.transaction(RECOVERY_STORE, 'readonly');
            const req = tx.objectStore(RECOVERY_STORE).get(RECOVERY_KEY);
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
     * 清除待恢复记录（自动保存确认成功后 / 恢复重放成功后调用）。
     */
    clearSnapshot: function(){
      return runRecoveryStore('readwrite', function(store){
        store.delete(RECOVERY_KEY);
        return true;
      });
    }
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
