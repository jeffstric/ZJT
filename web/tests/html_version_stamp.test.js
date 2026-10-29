/**
 * 静态资源 __VERSION__ 缓存戳一致性守卫（e73286c1a / 4cfff3edc）。
 *
 * 契约：所有本地 /js/、/css/ 引用统一带 ?v=__VERSION__（服务端渲染时替换为
 * 实际版本号），浏览器端长缓存才能随版本失效。不允许硬编码历史版本戳回归。
 */
import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const root = path.resolve(import.meta.dirname, '../..');
const webDir = path.join(root, 'web');

const HTML_FILES = [
    'index.html',
    'marketing_agent.html',
    'marketing_inspiration.html',
    'script_writer.html',
    'storyboard.html',
    'video_workflow.html',
    'video_workflow_list.html',
    'admin.html',
];

const read = (name) => fs.readFileSync(path.join(webDir, name), 'utf8');

const stamp = '?v=__VERSION__';
// 允许无版本戳的例外：由 fetch 动态加载/被测试工具直接引用等场景按需登记
const STAMP_WHITELIST = ['/js/task_config.js'];

describe('静态资源 __VERSION__ 缓存戳', () => {
    it('缓存戳机制在用（至少一个页面出现 ?v=__VERSION__）', () => {
        const using = HTML_FILES.filter((f) => fs.existsSync(path.join(webDir, f)) && read(f).includes(stamp));
        expect(using.length, '没有任何页面使用 __VERSION__ 缓存戳，机制已失效').toBeGreaterThan(0);
    });

    it.each(HTML_FILES.filter((f) => fs.existsSync(path.join(webDir, f))))(
        '%s 不再出现硬编码历史版本戳',
        (file) => {
            const html = read(file);
            const hardcoded = html.match(/\?v=20\d{6,}/g) || [];
            expect(
                hardcoded,
                `${file} 存在硬编码版本戳: ${hardcoded.join(', ')}，请改为 ${stamp}（硬编码戳发布后不随版本失效）`
            ).toEqual([]);
        },
    );
});
