/**
 * video_workflow 剧本拆分请求体：与故事板 sequence_mode / 质检参数对齐。
 */
require('../js/script_split_task.js');

const { buildSplitRequestBody, normalizeSequenceMode } = window.ScriptSplitTask;

describe('ScriptSplitTask.normalizeSequenceMode', () => {
  test('合法模式原样返回', () => {
    expect(normalizeSequenceMode('speed')).toBe('speed');
    expect(normalizeSequenceMode('balanced')).toBe('balanced');
    expect(normalizeSequenceMode('quality')).toBe('quality');
  });

  test('非法或空值回落 balanced', () => {
    expect(normalizeSequenceMode('')).toBe('balanced');
    expect(normalizeSequenceMode(null)).toBe('balanced');
    expect(normalizeSequenceMode('cinema')).toBe('balanced');
  });
});

describe('ScriptSplitTask.buildSplitRequestBody', () => {
  test('透传 sequence_mode 与质检参数', () => {
    const body = buildSplitRequestBody(
      {
        scriptContent: 'hello',
        maxGroupDuration: 15,
        forceMediumShot: true,
        noBgMusic: true,
        splitMultiDialogue: false,
        sequenceMode: 'quality',
        enableScriptSplitQc: true,
        scriptSplitQcMaxRounds: 3,
        splitModel: 'gemini-3-flash-preview',
        splitModelId: '1',
        splitModelVendorId: '2',
        enableThinking: false,
        thinkingEffort: 'medium',
      },
      99
    );
    expect(body.sequence_mode).toBe('quality');
    expect(body.enable_script_split_qc).toBe(true);
    expect(body.script_split_qc_max_rounds).toBe(3);
    expect(body.world_id).toBe(99);
  });

  test('缺省时使用 balanced 且关闭质检', () => {
    const body = buildSplitRequestBody({ scriptContent: 'x' }, null);
    expect(body.sequence_mode).toBe('balanced');
    expect(body.enable_script_split_qc).toBe(false);
    expect(body.script_split_qc_max_rounds).toBe(2);
  });
});
