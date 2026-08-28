/**
 * 涂鸦编辑器核心纯逻辑：输出画布尺寸 / contain 布局 / 命中检测 / 命令栈撤销重做。
 * 这些函数不依赖 DOM 与运行态（image_doodle_editor.js 加载期无副作用）。
 */

const {
  computeOutSize,
  containFit,
  pointToSegmentDistance,
  measureApproxText,
  elementBBox,
  hitTestElement,
  handlePointsForBbox,
  hitHandleIndex,
  normalizeRect,
  distFactor,
  dragBbox,
  applyRecord,
} = require('../js/image_doodle_editor.js');

describe('computeOutSize 输出画布尺寸', () => {
  test('original 等于底图原尺寸', () => {
    expect(computeOutSize(1920, 1080, 'original')).toEqual({ w: 1920, h: 1080 });
    expect(computeOutSize(1920, 1080, null)).toEqual({ w: 1920, h: 1080 });
  });

  test('横图切 16:9 保持长边为宽', () => {
    expect(computeOutSize(1920, 1080, '16:9')).toEqual({ w: 1920, h: 1080 });
  });

  test('横图切 9:16 以长边为高（画布扩展不裁剪）', () => {
    const out = computeOutSize(1920, 1080, '9:16');
    expect(out.h).toBe(1920);
    expect(out.w).toBe(Math.round((1920 * 9) / 16));
  });

  test('竖图切 16:9 以长边为宽', () => {
    const out = computeOutSize(1080, 1920, '16:9');
    expect(out.w).toBe(1920);
    expect(out.h).toBe(Math.round((1920 * 9) / 16));
  });

  test('1:1 正方形输出', () => {
    expect(computeOutSize(800, 600, '1:1')).toEqual({ w: 800, h: 800 });
  });
});

describe('containFit', () => {
  test('宽图在竖框内上下留白居中', () => {
    const fit = containFit(100, 200, 100, 100);
    expect(fit.scale).toBe(1);
    expect(fit.x).toBe(0);
    expect(fit.y).toBeCloseTo(50);
  });

  test('等比缩放优先取较小系数', () => {
    const fit = containFit(200, 100, 100, 100);
    expect(fit.scale).toBe(1);
    expect(fit.x).toBeCloseTo(50);
    expect(fit.y).toBe(0);
  });
});

describe('pointToSegmentDistance', () => {
  test('点到水平线段的垂直距离', () => {
    expect(pointToSegmentDistance(5, 3, 0, 0, 10, 0)).toBe(3);
  });

  test('投影在线段外时取端点距离', () => {
    expect(pointToSegmentDistance(15, 0, 0, 0, 10, 0)).toBe(5);
  });

  test('零长度线段退化为点距离', () => {
    expect(pointToSegmentDistance(3, 4, 0, 0, 0, 0)).toBe(5);
  });
});

describe('measureApproxText / elementBBox', () => {
  test('中文按全宽、西文按窄宽估算', () => {
    const zh = measureApproxText('涂鸦', 20);
    const en = measureApproxText('ab', 20);
    expect(zh.w).toBeCloseTo(40);
    expect(en.w).toBeCloseTo(20 * 0.56 * 2, 5);
  });

  test('多行高度按行数累计', () => {
    const m = measureApproxText('a\nb', 20);
    expect(m.lines).toBe(2);
    expect(m.h).toBeCloseTo(2 * 20 * 1.25);
  });

  test('stroke 包围盒含线宽外扩', () => {
    const b = elementBBox({ type: 'stroke', points: [{ x: 10, y: 10 }, { x: 30, y: 20 }], color: '#000', width: 4 });
    expect(b.x).toBe(8);
    expect(b.y).toBe(8);
    expect(b.w).toBe(24);
    expect(b.h).toBe(14);
  });

  test('rect 包围盒含线宽外扩', () => {
    const b = elementBBox({ type: 'rect', x: 0, y: 0, w: 100, h: 50, color: '#000', width: 6 });
    expect(b).toEqual({ x: -3, y: -3, w: 106, h: 56 });
  });

  test('text 包围盒基于近似测量', () => {
    const b = elementBBox({ type: 'text', x: 5, y: 6, text: '涂', color: '#000', fontSize: 20 });
    expect(b.x).toBe(5);
    expect(b.y).toBe(6);
    expect(b.w).toBeCloseTo(20);
    expect(b.h).toBeCloseTo(25);
  });
});

describe('hitTestElement 命中检测', () => {
  const stroke = { id: 1, type: 'stroke', points: [{ x: 0, y: 0 }, { x: 100, y: 0 }], color: '#000', width: 6 };
  const rect = { id: 2, type: 'rect', x: 10, y: 10, w: 100, h: 50, color: '#000', width: 4 };
  const text = { id: 3, type: 'text', x: 0, y: 0, text: '涂鸦', color: '#000', fontSize: 20 };

  test('stroke 线上命中（含半线宽容差）', () => {
    expect(hitTestElement(stroke, 50, 0, 0)).toBe(true);
    expect(hitTestElement(stroke, 50, 2.9, 0)).toBe(true);  // width/2 = 3
    expect(hitTestElement(stroke, 50, 4, 0)).toBe(false);
  });

  test('stroke 单点命中退化为圆', () => {
    const dot = { id: 9, type: 'stroke', points: [{ x: 10, y: 10 }], color: '#000', width: 6 };
    expect(hitTestElement(dot, 12, 12, 0)).toBe(true);
    expect(hitTestElement(dot, 20, 20, 0)).toBe(false);
  });

  test('rect 边线命中、内部不命中（空心矩形语义）', () => {
    expect(hitTestElement(rect, 60, 10, 0)).toBe(true);   // 上边
    expect(hitTestElement(rect, 60, 35, 0)).toBe(false);  // 中心空白
    expect(hitTestElement(rect, 60, 60, 0)).toBe(true);   // 下边
  });

  test('text 包围盒内命中', () => {
    expect(hitTestElement(text, 5, 5, 0)).toBe(true);
    expect(hitTestElement(text, 100, 100, 0)).toBe(false);
  });

  test('eraser 擦除轨迹不可命中、无包围盒（不参与选中/移动）', () => {
    const eraser = { id: 8, type: 'eraser', points: [{ x: 0, y: 0 }, { x: 50, y: 0 }], color: '#000', width: 6 };
    expect(hitTestElement(eraser, 25, 0, 10)).toBe(false);
    expect(elementBBox(eraser)).toBe(null);
  });
});

describe('控制点几何', () => {
  test('8 控制点顺序与位置', () => {
    const pts = handlePointsForBbox({ x: 0, y: 0, w: 100, h: 50 });
    expect(pts[0]).toEqual({ x: 0, y: 0 });       // nw
    expect(pts[4]).toEqual({ x: 100, y: 50 });    // se
    expect(pts[1]).toEqual({ x: 50, y: 0 });      // n
  });

  test('hitHandleIndex 命中与未命中', () => {
    const pts = handlePointsForBbox({ x: 0, y: 0, w: 100, h: 50 });
    expect(hitHandleIndex(pts, 100, 50, 10)).toBe(4);
    expect(hitHandleIndex(pts, 99, 44, 8)).toBe(4);
    expect(hitHandleIndex(pts, 50, 25, 10)).toBe(-1);
  });

  test('对角锚点 = (handleIdx + 4) % 8', () => {
    const pts = handlePointsForBbox({ x: 0, y: 0, w: 10, h: 10 });
    // nw(0) 的对角是 se(4)
    expect(pts[(0 + 4) % 8]).toEqual(pts[4]);
    expect(pts[(1 + 4) % 8]).toEqual(pts[5]);
  });
});

describe('normalizeRect / distFactor / dragBbox', () => {
  test('反向拖拽归一化', () => {
    expect(normalizeRect(30, 40, 10, 20)).toEqual({ x: 10, y: 20, w: 20, h: 20 });
  });

  test('等比缩放因子基于到锚点距离', () => {
    const anchor = { x: 0, y: 0 };
    expect(distFactor(anchor, { x: 10, y: 0 }, { x: 30, y: 0 })).toBeCloseTo(3);
    // 极近锚点被钳制，不产生 Infinity
    expect(Number.isFinite(distFactor(anchor, { x: 10, y: 0 }, { x: 0, y: 0 }))).toBe(true);
  });

  test('se handle 拖拽扩展 bbox 且有最小尺寸兜底', () => {
    const b = dragBbox({ x: 0, y: 0, w: 100, h: 50 }, 4, { x: 150, y: 80 }, 4);
    expect(b).toEqual({ x: 0, y: 0, w: 150, h: 80 });
    const clamped = dragBbox({ x: 0, y: 0, w: 100, h: 50 }, 4, { x: -50, y: -50 }, 4);
    expect(clamped.w).toBe(4);
    expect(clamped.h).toBe(4);
  });

  test('nw handle 拖拽同时移动原点', () => {
    const b = dragBbox({ x: 0, y: 0, w: 100, h: 50 }, 0, { x: -20, y: -10 }, 4);
    expect(b.x).toBe(-20);
    expect(b.y).toBe(-10);
    expect(b.w).toBe(120);
    expect(b.h).toBe(60);
  });
});

describe('applyRecord 命令栈', () => {
  const el = (id) => ({ id, type: 'rect', x: id, y: 0, w: 10, h: 10, color: '#000', width: 2 });

  test('add：undo 移除 / redo 恢复', () => {
    const rec = { action: 'add', element: el(1) };
    let elements = [];
    elements = applyRecord(rec, elements, false); // do
    expect(elements.map((e) => e.id)).toEqual([1]);
    elements = applyRecord(rec, elements, true);  // undo
    expect(elements).toEqual([]);
    elements = applyRecord(rec, elements, false); // redo
    expect(elements.map((e) => e.id)).toEqual([1]);
  });

  test('update：快照替换不 mutate 原数组', () => {
    const before = el(1);
    const after = Object.assign({}, before, { x: 99 });
    const rec = { action: 'update', id: 1, before, after };
    const src = [before];
    const undone = applyRecord(rec, src, false);
    expect(undone[0].x).toBe(99);
    expect(src[0].x).toBe(1); // 原数组未被修改
  });

  test('delete：按原索引插回恢复顺序', () => {
    const a = el(1), b = el(2), c = el(3);
    const rec = { action: 'delete', items: [{ index: 0, element: a }, { index: 2, element: c }] };
    let elements = [a, b, c];
    elements = applyRecord(rec, elements, false); // do: 删 a、c
    expect(elements.map((e) => e.id)).toEqual([2]);
    elements = applyRecord(rec, elements, true);  // undo: 插回原位
    expect(elements.map((e) => e.id)).toEqual([1, 2, 3]);
  });

  test('clear：undo 全量恢复 / redo 清空', () => {
    const a = el(1), b = el(2);
    const rec = { action: 'clear', items: [a, b] };
    let elements = [a, b];
    elements = applyRecord(rec, elements, false);
    expect(elements).toEqual([]);
    elements = applyRecord(rec, elements, true);
    expect(elements.map((e) => e.id)).toEqual([1, 2]);
  });

  test('未知 action 原样返回', () => {
    const elements = [el(1)];
    expect(applyRecord({ action: 'noop' }, elements, true)).toBe(elements);
  });
});
