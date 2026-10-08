/**
 * Ctrl+滚轮：按住修饰键时一律平移。
 * 浏览器页面缩放 110% 会把鼠标一格变成非整数 deltaY，不能因此误判成触控板捏合。
 */
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { describe, expect, it } from 'vitest';

function loadCtrlWheelAction(){
  const source = fs.readFileSync(path.resolve(import.meta.dirname, '../js/events.js'), 'utf8');
  const start = source.indexOf('function ctrlWheelAction(');
  if(start < 0) throw new Error('ctrlWheelAction 未找到');
  let depth = 0;
  let end = -1;
  for(let i = source.indexOf('{', start); i < source.length; i++){
    if(source[i] === '{') depth++;
    else if(source[i] === '}'){
      depth--;
      if(depth === 0){
        end = i + 1;
        break;
      }
    }
  }
  const context = {};
  vm.createContext(context);
  vm.runInContext(source.slice(start, end) + '\nthis.ctrlWheelAction = ctrlWheelAction;', context);
  return context.ctrlWheelAction;
}

const ctrlWheelAction = loadCtrlWheelAction();

describe('ctrlWheelAction', () => {
  it('按住 Ctrl 时，110% 页面缩放下的小数滚轮仍平移', () => {
    expect(ctrlWheelAction({ deltaMode: 0, deltaY: -120 / 1.1 }, true)).toBe('pan');
    expect(ctrlWheelAction({ deltaMode: 0, deltaY: 120 / 1.1 }, true)).toBe('pan');
  });

  it('按住 Ctrl 时，整数滚轮平移', () => {
    expect(ctrlWheelAction({ deltaMode: 0, deltaY: -120 }, true)).toBe('pan');
    expect(ctrlWheelAction({ deltaMode: 0, deltaY: 100 }, true)).toBe('pan');
  });

  it('没按 Ctrl/Cmd 的小数滚轮视为触控板捏合，仍然缩放', () => {
    expect(ctrlWheelAction({ deltaMode: 0, deltaY: -4.5 }, false)).toBe('pinch-zoom');
    expect(ctrlWheelAction({ deltaMode: 0, deltaY: 6.25 }, false)).toBe('pinch-zoom');
  });

  it('没按键但 deltaY 是整数，或不是像素模式，不判成捏合', () => {
    expect(ctrlWheelAction({ deltaMode: 0, deltaY: -120 }, false)).toBe('pan');
    expect(ctrlWheelAction({ deltaMode: 1, deltaY: -1.5 }, false)).toBe('pan');
  });
});
