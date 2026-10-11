// 同页自动保存单飞与写 id 自愈（正式套件：npm test / vitest run）
//
// 覆盖：
//  - 请求已发出时，后来的保存不 abort，只记补发
//  - 请求还停在写 IndexedDB 时，新保存 abort 旧 controller
//  - 超时只释放槽位，不 abort；原写 id 仍算本页
//  - 释放之后才回来的成功 / 409 都是 ignore，不得记冲突
//  - 当前 409：本页写 id 自愈一次；别人的、空的、或第二次都是冲突
//  - setConfirmedHash 不解除自愈闩；setConfirmedBody 才解除

const { createAutoSaveState } = require('../js/auto_save_state.js');

function startSend(state){
  const controller = new AbortController();
  state.markDirty();
  const decision = state.beginOrCoalesce(controller);
  return { controller: controller, decision: decision };
}

describe('自动保存单飞', () => {
  test('请求已发出时后来的保存不 abort，只记补发', () => {
    const state = createAutoSaveState();
    const first = startSend(state);
    expect(first.decision.action).toBe('send');
    state.markRequestStarted(first.decision.sentVersion);

    const secondController = new AbortController();
    state.markDirty();
    const second = state.beginOrCoalesce(secondController);
    expect(second.action).toBe('coalesce');
    expect(first.controller.signal.aborted).toBe(false);
    expect(secondController.signal.aborted).toBe(false);
    expect(state.hasStartedInFlight()).toBe(true);
  });

  test('请求尚未发出时，新保存 abort 旧 controller', () => {
    const state = createAutoSaveState();
    const first = startSend(state);
    expect(state.hasStartedInFlight()).toBe(false);

    const second = startSend(state);
    expect(second.decision.action).toBe('send');
    expect(first.controller.signal.aborted).toBe(true);
    expect(second.controller.signal.aborted).toBe(false);
    expect(second.decision.writeId).not.toBe(first.decision.writeId);
  });

  test('超时释放槽位但不 abort，写 id 仍属于本页', () => {
    const state = createAutoSaveState();
    const first = startSend(state);
    expect(state.releaseForTimeout(first.decision.sentVersion)).toBeNull();

    state.markRequestStarted(first.decision.sentVersion);
    const released = state.releaseForTimeout(first.decision.sentVersion);
    expect(released).toEqual({ writeId: first.decision.writeId, resave: true });
    expect(first.controller.signal.aborted).toBe(false);
    expect(state.hasStartedInFlight()).toBe(false);
    expect(state.isCurrentSend(first.decision.sentVersion)).toBe(false);
    expect(state.ownsWriteId(first.decision.writeId)).toBe(true);

    const next = startSend(state);
    expect(next.decision.action).toBe('send');
  });
});

describe('保存响应判定', () => {
  test('迟到的成功与 409 都忽略，且不记冲突', () => {
    const state = createAutoSaveState();
    const first = startSend(state);
    state.markRequestStarted(first.decision.sentVersion);
    state.releaseForTimeout(first.decision.sentVersion);

    expect(state.interpretSaveResponse(
      first.decision.sentVersion, 0, 'hash-a', first.decision.writeId
    ).action).toBe('ignore');
    const lateConflict = state.interpretSaveResponse(
      first.decision.sentVersion, 409, 'hash-a', first.decision.writeId
    );
    expect(lateConflict.action).toBe('ignore');
    if(lateConflict.action === 'conflict') state.noteConflict(1);
    expect(state.isConflictBlocked(1)).toBe(false);
  });

  test('本页写 id 的 409 只自愈一次；空 id 与别人的 id 直接冲突', () => {
    const state = createAutoSaveState();
    const first = startSend(state);
    state.markRequestStarted(first.decision.sentVersion);

    expect(state.interpretSaveResponse(
      first.decision.sentVersion, 409, 'hash-server', null
    ).action).toBe('conflict');
    expect(state.interpretSaveResponse(
      first.decision.sentVersion, 409, 'hash-server', 'foreign-write-id'
    ).action).toBe('conflict');

    const owned = state.interpretSaveResponse(
      first.decision.sentVersion, 409, 'hash-server', first.decision.writeId
    );
    expect(owned.action).toBe('self-heal');
    state.setConfirmedHash(7, 'hash-server');
    expect(state.getConfirmedHash(7)).toBe('hash-server');
    state.endSend(first.decision.sentVersion, false);

    const again = startSend(state);
    state.markRequestStarted(again.decision.sentVersion);
    expect(state.interpretSaveResponse(
      again.decision.sentVersion, 409, 'hash-next', first.decision.writeId
    ).action).toBe('conflict');
  });

  test('成功确认后解除自愈闩，下一次本页 409 仍可自愈', () => {
    const state = createAutoSaveState();
    const first = startSend(state);
    state.markRequestStarted(first.decision.sentVersion);
    expect(state.interpretSaveResponse(
      first.decision.sentVersion, 409, 'hash-1', first.decision.writeId
    ).action).toBe('self-heal');
    state.endSend(first.decision.sentVersion, false);
    state.setConfirmedBody(7, '{"same":true}', 'hash-1');

    const second = startSend(state);
    state.markRequestStarted(second.decision.sentVersion);
    expect(state.interpretSaveResponse(
      second.decision.sentVersion, 409, 'hash-2', second.decision.writeId
    ).action).toBe('self-heal');
  });

  test('缺内容哈希的 409 不消耗自愈次数', () => {
    const state = createAutoSaveState();
    const first = startSend(state);
    state.markRequestStarted(first.decision.sentVersion);
    expect(state.interpretSaveResponse(
      first.decision.sentVersion, 409, '', first.decision.writeId
    ).action).toBe('conflict');
    expect(state.interpretSaveResponse(
      first.decision.sentVersion, 409, 'hash-1', first.decision.writeId
    ).action).toBe('self-heal');
  });

  test('当前笔成功后，期间积下的修改还要再发一笔', () => {
    const state = createAutoSaveState();
    const first = startSend(state);
    state.markRequestStarted(first.decision.sentVersion);
    state.markDirty();
    state.noteResaveNeeded();
    expect(state.interpretSaveResponse(
      first.decision.sentVersion, 0, 'hash-1', first.decision.writeId
    ).action).toBe('confirm');
    expect(state.endSend(first.decision.sentVersion, true)).toBe(false);
    expect(state.takeFollowUp(first.decision.sentVersion)).toBe(true);
    expect(state.takeFollowUp(first.decision.sentVersion)).toBe(false);
  });
});
