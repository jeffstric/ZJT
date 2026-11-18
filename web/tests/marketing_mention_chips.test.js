/**
 * 营销智能体输入框 @ 资产 token 胶囊镜像层（web/js/marketing_mention_chips.js）。
 *
 * 契约：
 * - scanAssetMentionTokens：按出现序扫描 `@资产:{id}`，中文相邻/多位数字不误截
 * - register/briefById：资产池注入与查询；sync 对池外 token 退化纯文本（镜像层清空）
 * - sync 渲染：chip-anchor 隐藏占位 + 胶囊（缩略图/名称/悬停大图），名称转义，
 *   data-start/end 对齐 token 区间；无 token 时镜像层清空
 * - 原子编辑：删除触及 token 整枚删除；token 中间插入被阻止
 * - 兜底：池外 id 经 AssetLibrary.api 详情拉取入池后重渲染；失败保留纯文本不抛错
 * - marketing_agent.js 接线：insertMention 注册资产池 + inputText watcher 同步
 */
import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it, beforeEach } from 'vitest';

const root = path.resolve(import.meta.dirname, '../..');
const readSource = (relativePath) => fs.readFileSync(path.join(root, relativePath), 'utf8');

// IIFE 普通脚本：new Function 在全局作用域执行后取 window 挂载（jsdom 环境）
function loadPlainScript(relativePath) {
    const factory = new Function(readSource(relativePath));
    factory();
}

beforeEach(() => {
    // 用真实 escape.js（权威实现，非本地副本）+ 重挂载模块，避免用例间资产池泄漏
    loadPlainScript('web/js/escape.js');
    loadPlainScript('web/js/marketing_mention_chips.js');
    delete window.AssetLibrary;
});

const chips = () => window.MAMentionChips;

function makeTextarea(value) {
    const ta = document.createElement('textarea');
    ta.value = value;
    document.body.appendChild(ta);
    return ta;
}

function makeMirror() {
    const mirror = document.createElement('div');
    document.body.appendChild(mirror);
    return mirror;
}

describe('scanAssetMentionTokens', () => {
    it('按出现序扫描 token 并给出偏移', () => {
        expect(chips().scanAssetMentionTokens('看 @资产:12 和 @资产:7 结束')).toEqual([
            { assetId: 12, token: '@资产:12', start: 2, end: 8 },
            { assetId: 7, token: '@资产:7', start: 11, end: 16 },
        ]);
    });

    it('多位数字不误截、相邻中文不误匹配', () => {
        expect(chips().scanAssetMentionTokens('@资产:123456')).toEqual([
            { assetId: 123456, token: '@资产:123456', start: 0, end: 10 },
        ]);
        expect(chips().scanAssetMentionTokens('@资产:12x')).toEqual([
            { assetId: 12, token: '@资产:12', start: 0, end: 6 },
        ]);
        expect(chips().scanAssetMentionTokens('没有标记')).toEqual([]);
        expect(chips().scanAssetMentionTokens('')).toEqual([]);
    });
});

describe('register / briefById', () => {
    it('注册后可查，非法 id 忽略', () => {
        chips().register(3, '夏日海景', '/upload/a.png');
        expect(chips().briefById(3)).toEqual({ name: '夏日海景', thumb: '/upload/a.png' });
        expect(chips().briefById(99)).toBe(null);
        chips().register(0, '无效', '');
        expect(chips().briefById(0)).toBe(null);
    });

    it('同名重复注册覆盖旧值', () => {
        chips().register(5, '旧名', '/upload/old.png');
        chips().register(5, '新名', '/upload/new.png');
        expect(chips().briefById(5)).toEqual({ name: '新名', thumb: '/upload/new.png' });
    });
});

describe('sync 渲染', () => {
    it('有 token 时渲染胶囊，data-start/end 对齐、名称转义、悬停地址正确', () => {
        chips().register(12, '夏日<海>景', '/upload/sea.png');
        const ta = makeTextarea('开头 @资产:12 结尾');
        const mirror = makeMirror();
        chips().sync(ta, mirror);

        const chip = mirror.querySelector('.ma-mention-chip');
        expect(chip).not.toBe(null);
        expect(chip.dataset.start).toBe('3');
        expect(chip.dataset.end).toBe('9');
        expect(chip.dataset.hoverPreview).toBe('/upload/sea.png');
        const name = chip.querySelector('.ma-mention-chip-name');
        expect(name.textContent).toBe('夏日<海>景');
        expect(name.innerHTML).not.toContain('<海>');
        expect(mirror.querySelector('.ma-chip-anchor img').getAttribute('src')).toBe('/upload/sea.png');
        // 镜像层文本转义后与原文等价可见结构（token 前后文本保留）
        expect(mirror.textContent).toContain('开头 ');
        expect(mirror.textContent).toContain(' 结尾');
    });

    it('池外 token 退化纯文本：镜像层清空、不生成胶囊', () => {
        const ta = makeTextarea('只有 @资产:777 未知资产');
        const mirror = makeMirror();
        chips().sync(ta, mirror);
        expect(mirror.querySelector('.ma-mention-chip')).toBe(null);
    });

    it('无 token 时镜像层清空', () => {
        chips().register(1, 'a', '/x.png');
        const ta = makeTextarea('普通文本 @名称');
        const mirror = makeMirror();
        mirror.innerHTML = '<span>旧内容</span>';
        chips().sync(ta, mirror);
        expect(mirror.innerHTML).toBe('');
    });

    it('textarea/mirror 缺失时静默返回', () => {
        expect(() => chips().sync(null, null)).not.toThrow();
    });
});

describe('详情接口兜底', () => {
    it('池外 id 经 AssetLibrary.api 拉取入池后重渲染', async () => {
        let apiCalls = [];
        window.AssetLibrary = {
            api: (url) => {
                apiCalls.push(url);
                return Promise.resolve({ data: { id: 42, name: '兜底资产', file_url: '/upload/42.png' } });
            },
        };
        const ta = makeTextarea('@资产:42');
        const mirror = makeMirror();
        chips().sync(ta, mirror);
        expect(mirror.querySelector('.ma-mention-chip')).toBe(null); // 首轮无数据退化纯文本

        await Promise.resolve();
        await new Promise(r => setTimeout(r, 0)); // 等 .then 入池 + syncActive 重渲染
        expect(apiCalls).toEqual(['/assets/42']);
        const chip = mirror.querySelector('.ma-mention-chip');
        expect(chip).not.toBe(null);
        expect(chip.querySelector('.ma-mention-chip-name').textContent).toBe('兜底资产');
    });

    it('详情拉取失败保留纯文本且每 id 只尝试一次', async () => {
        let calls = 0;
        window.AssetLibrary = {
            api: () => {
                calls += 1;
                return Promise.reject(new Error('无权限'));
            },
        };
        const ta = makeTextarea('@资产:9');
        const mirror = makeMirror();
        chips().sync(ta, mirror);
        chips().sync(ta, mirror); // 第二次 sync 不重复请求
        await new Promise(r => setTimeout(r, 0));
        expect(calls).toBe(1);
        expect(mirror.querySelector('.ma-mention-chip')).toBe(null);
        expect(() => chips().sync(ta, mirror)).not.toThrow();
    });

    it('无 AssetLibrary 时直接退化，不抛错', () => {
        const ta = makeTextarea('@资产:1');
        const mirror = makeMirror();
        expect(() => chips().sync(ta, mirror)).not.toThrow();
        expect(mirror.querySelector('.ma-mention-chip')).toBe(null);
    });
});

describe('原子编辑（beforeinput）', () => {
    it('退格触及 token：整枚删除', () => {
        chips().register(8, '资产8', '/8.png');
        const ta = makeTextarea('前 @资产:8 后');
        const mirror = makeMirror();
        chips().sync(ta, mirror);
        // token '@资产:8' 区间 [2,7)，光标紧贴 token 尾部（' ' 之前）
        ta.setSelectionRange(7, 7);
        const event = new Event('beforeinput', { bubbles: true, cancelable: true });
        event.inputType = 'deleteContentBackward';
        ta.dispatchEvent(event);
        expect(ta.value).toBe('前  后');
        expect(event.defaultPrevented).toBe(true);
    });

    it('光标落 token 中间插入字符：被阻止', () => {
        chips().register(8, '资产8', '/8.png');
        const ta = makeTextarea('@资产:8');
        const mirror = makeMirror();
        chips().sync(ta, mirror);
        ta.setSelectionRange(4, 4); // token 中间
        const event = new Event('beforeinput', { bubbles: true, cancelable: true });
        event.inputType = 'insertText';
        event.data = 'x';
        ta.dispatchEvent(event);
        expect(event.defaultPrevented).toBe(true);
        expect(ta.value).toBe('@资产:8');
    });

    it('token 外正常编辑不受影响', () => {
        chips().register(8, '资产8', '/8.png');
        const ta = makeTextarea('@资产:8 尾部');
        const mirror = makeMirror();
        chips().sync(ta, mirror);
        ta.setSelectionRange(9, 9);
        const event = new Event('beforeinput', { bubbles: true, cancelable: true });
        event.inputType = 'insertText';
        ta.dispatchEvent(event);
        expect(event.defaultPrevented).toBe(false);
    });
});

describe('marketing_agent.js 接线契约', () => {
    const maSource = readSource('web/js/marketing_agent.js');

    it('insertMention 选中资产时注册资产池（胶囊免请求渲染）', () => {
        expect(maSource).toMatch(/item\.isAsset[\s\S]{0,200}MAMentionChips\.register\(item\.assetId, item\.displayName, item\.thumbnailUrl\)/);
    });

    it('inputText watcher 同步胶囊镜像层', () => {
        expect(maSource).toMatch(/Vue\.watch\(inputText, syncMentionChips\)/);
        expect(maSource).toMatch(/MAMentionChips\.sync\(inputTextarea\.value, mentionMirror\.value\)/);
    });

    it('onMounted 挂悬停大图委托并做初始渲染', () => {
        expect(maSource).toMatch(/MAMentionChips\.setupHoverPreview\(\)/);
    });

    it('模板含镜像层挂载点与脚本引入', () => {
        const html = readSource('web/marketing_agent.html');
        expect(html).toMatch(/ref="mentionMirror"/);
        expect(html).toMatch(/\/js\/marketing_mention_chips\.js/);
    });
});
