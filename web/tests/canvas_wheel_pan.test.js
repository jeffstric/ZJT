/**
 * 画布滚轮：
 * - 默认 pan：普通滚轮上下平移，真正按住 Ctrl/Cmd 时缩放。
 * - 用户点选 zoom 后：普通滚轮缩放，真正按住 Ctrl/Cmd 时上下平移。
 * - 触控板捏合始终缩放。
 * - 浏览器页面缩放 110% 会把鼠标一格变成非整数 deltaY，不能因此误判成捏合。
 */
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { describe, expect, it } from 'vitest';

function extractFunction(source, name){
  const start = source.indexOf('function ' + name + '(');
  if(start < 0) throw new Error(name + ' 未找到');
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
  if(end < 0) throw new Error(name + ' 未能截取');
  return source.slice(start, end);
}

function loadWheelFns(){
  const source = fs.readFileSync(path.resolve(import.meta.dirname, '../js/events.js'), 'utf8');
  const context = {};
  vm.createContext(context);
  vm.runInContext(
    extractFunction(source, 'ctrlWheelAction') + '\n' +
    extractFunction(source, 'canvasWheelGesture') + '\n' +
    'this.ctrlWheelAction = ctrlWheelAction;\nthis.canvasWheelGesture = canvasWheelGesture;',
    context
  );
  return context;
}

const { ctrlWheelAction, canvasWheelGesture } = loadWheelFns();

function wheel(extra){
  return Object.assign({ ctrlKey: false, metaKey: false, shiftKey: false, deltaMode: 0, deltaX: 0, deltaY: 0 }, extra);
}

describe('ctrlWheelAction', () => {
  it('按住 Ctrl 时，110% 页面缩放下的小数滚轮不判成捏合', () => {
    expect(ctrlWheelAction({ deltaMode: 0, deltaY: -120 / 1.1 }, true)).toBe('modifier');
    expect(ctrlWheelAction({ deltaMode: 0, deltaY: 120 / 1.1 }, true)).toBe('modifier');
  });

  it('按住 Ctrl 时，整数滚轮是修饰键动作', () => {
    expect(ctrlWheelAction({ deltaMode: 0, deltaY: -120 }, true)).toBe('modifier');
    expect(ctrlWheelAction({ deltaMode: 0, deltaY: 100 }, true)).toBe('modifier');
  });

  it('没按 Ctrl/Cmd 的小数滚轮视为触控板捏合', () => {
    expect(ctrlWheelAction({ deltaMode: 0, deltaY: -4.5 }, false)).toBe('pinch-zoom');
    expect(ctrlWheelAction({ deltaMode: 0, deltaY: 6.25 }, false)).toBe('pinch-zoom');
  });

  it('没按键但 deltaY 是整数，或不是像素模式，不判成捏合', () => {
    expect(ctrlWheelAction({ deltaMode: 0, deltaY: -120 }, false)).toBe('modifier');
    expect(ctrlWheelAction({ deltaMode: 1, deltaY: -1.5 }, false)).toBe('modifier');
  });
});

describe('canvasWheelGesture', () => {
  it('默认和平移模式：普通滚轮上下平移，Ctrl+滚轮缩放', () => {
    expect(canvasWheelGesture(wheel({ deltaY: 120 }), false, 'pan')).toBe('pan-y');
    expect(canvasWheelGesture(wheel({ deltaY: -120 }), false, undefined)).toBe('pan-y');
    expect(canvasWheelGesture(wheel({ ctrlKey: true, deltaY: -120 / 1.1 }), true, 'pan')).toBe('zoom');
    expect(canvasWheelGesture(wheel({ metaKey: true, deltaY: 120 }), true, 'pan')).toBe('zoom');
  });

  it('点选缩放模式后：普通滚轮缩放，真正按住 Ctrl 的 110% 滚轮仍上下平移', () => {
    expect(canvasWheelGesture(wheel({ deltaY: -120 }), false, 'zoom')).toBe('zoom');
    expect(canvasWheelGesture(wheel({ ctrlKey: true, deltaY: -120 / 1.1 }), true, 'zoom')).toBe('pan-y');
    expect(canvasWheelGesture(wheel({ ctrlKey: true, deltaY: 120 }), true, 'zoom')).toBe('pan-y');
  });

  it('两种模式下捏合都缩放，Shift+滚轮都左右平移', () => {
    const pinch = wheel({ ctrlKey: true, deltaY: -4.5 });
    expect(canvasWheelGesture(pinch, false, 'pan')).toBe('zoom');
    expect(canvasWheelGesture(pinch, false, 'zoom')).toBe('zoom');
    const shift = wheel({ shiftKey: true, deltaY: 120 });
    expect(canvasWheelGesture(shift, false, 'pan')).toBe('pan-x');
    expect(canvasWheelGesture(shift, false, 'zoom')).toBe('pan-x');
  });
});

describe('滚轮模式记忆', () => {
  function loadShortcuts(storage){
    const source = fs.readFileSync(path.resolve(import.meta.dirname, '../js/canvas_shortcuts.js'), 'utf8');
    const context = { localStorage: storage };
    vm.createContext(context);
    vm.runInContext(source, context);
    return context;
  }

  it('未选择时是上下平移，只有写入 zoom 后才变成滚轮缩放', () => {
    const storage = {
      getItem(){ return null; },
      setItem(){},
    };
    const api = loadShortcuts(storage);
    expect(api.getCanvasWheelMode()).toBe('pan');
    let saved = null;
    storage.setItem = function(key, value){ saved = key + '=' + value; };
    storage.getItem = function(){ return saved === 'canvasWheelMode=zoom' ? 'zoom' : null; };
    expect(api.setCanvasWheelMode('zoom')).toBe('zoom');
    expect(saved).toBe('canvasWheelMode=zoom');
    expect(api.getCanvasWheelMode()).toBe('zoom');
    storage.getItem = function(){ return 'pan'; };
    expect(api.setCanvasWheelMode('pan')).toBe('pan');
    expect(api.getCanvasWheelMode()).toBe('pan');
    storage.getItem = function(){ return 'nope'; };
    expect(api.getCanvasWheelMode()).toBe('pan');
  });
});
