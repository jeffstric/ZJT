import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const root = path.resolve(import.meta.dirname, '../..');
const readSource = (relativePath) => fs.readFileSync(path.join(root, relativePath), 'utf8');

// 回归背景（fix 53a8f69c）：营销智能体「直连生成」轮询 /api/get-status 出现
// 3 连错（瞬时 401/网络抖动）后旧逻辑直接 clearDirectGenerationTask 判死，
// 气泡永久停在失败/生成中，而服务端其实仍在生成——用户误以为失败。
// 修复契约（不判死、降频续探）：
//   1. 连错达到 MAX_CONSECUTIVE_TASK_ERRORS(3) 后不再 clearDirectGenerationTask
//   2. 气泡转中性占位文案 generating_placeholder（非失败文案）
//   3. 高频 interval 重建为 TASK_ERROR_BACKOFF_INTERVAL(30s) 低频探测
//   4. 成功响应到达时 resetTaskErrorCount 清零错误计数（恢复后正常收尾）
//   5. 旧图片路径（无 projectIds）分流到直连：带 projectIds 的
//      checkImageStatus 调用直接委托 checkDirectGenerationStatus
describe('marketing_agent 直连生成轮询 3 连错降频不判死', () => {
    const source = readSource('web/js/marketing_agent.js');

    const fnBody = (name, nextAnchor) => {
        const start = source.indexOf(`function ${name}`);
        expect(start, `未找到函数 ${name}`).toBeGreaterThan(-1);
        const end = source.indexOf(nextAnchor, start);
        return source.slice(start, end > start ? end : undefined);
    };

    it('错误阈值与降频间隔常量保持 3 次 / 30 秒', () => {
        expect(source).toMatch(/MAX_CONSECUTIVE_TASK_ERRORS\s*=\s*3\b/);
        expect(source).toMatch(/TASK_ERROR_BACKOFF_INTERVAL\s*=\s*30000\b/);
    });

    it('直连轮询 catch 兜底不判死：不再 clearDirectGenerationTask', () => {
        const body = fnBody('checkDirectGenerationStatus', 'async function checkImageStatus');
        const catchIdx = body.indexOf('catch (err)');
        expect(catchIdx).toBeGreaterThan(-1);
        const catchBlock = body.slice(catchIdx);
        expect(catchBlock).toContain('recordTaskError(errorKey)');
        expect(catchBlock).toContain('MAX_CONSECUTIVE_TASK_ERRORS');
        expect(
            catchBlock,
            '3 连错兜底不得判死任务（53a8f69c 修复点：clearDirectGenerationTask 会让气泡永久停死）'
        ).not.toContain('clearDirectGenerationTask');
    });

    it('兜底气泡转中性占位文案而非失败文案', () => {
        const body = fnBody('checkDirectGenerationStatus', 'async function checkImageStatus');
        const catchBlock = body.slice(body.indexOf('catch (err)'));
        expect(catchBlock).toContain(`window.t('generating_placeholder')`);
    });

    it('兜底后重建 30s 降频 interval 继续探测', () => {
        const body = fnBody('checkDirectGenerationStatus', 'async function checkImageStatus');
        const catchBlock = body.slice(body.indexOf('catch (err)'));
        expect(catchBlock).toContain('trackedClearInterval(task.intervalId)');
        expect(catchBlock).toContain('trackedSetInterval(() => checkFn(task), TASK_ERROR_BACKOFF_INTERVAL)');
        // 降频前清空错误计数：下一次 3 连错才会再次触发兜底，避免每 5s 反复重建
        expect(catchBlock).toContain('resetTaskErrorCount(errorKey)');
    });

    it('成功响应到达时清零错误计数，恢复后照常收尾', () => {
        const body = fnBody('checkDirectGenerationStatus', 'async function checkImageStatus');
        const okBlock = body.slice(0, body.indexOf('catch (err)'));
        expect(okBlock).toMatch(/resetTaskErrorCount\(errorKey\)/);
    });

    it('带 projectIds 的图片轮询委托直连路径（享受同款不判死兜底）', () => {
        const body = fnBody('checkImageStatus', 'function startImageStatusCheck');
        const delegate = body.slice(
            body.indexOf('async function checkImageStatus') >= 0 ? 0 : body.indexOf('if (msgUid && msgUid.projectIds)'),
            body.indexOf('if (!imageProjectIds.value)')
        );
        expect(delegate).toContain('return checkDirectGenerationStatus(task)');
    });

    it('任务清理路径统一清错误计数（clearDirectGenerationTask 内）', () => {
        const body = fnBody('clearDirectGenerationTask', 'function clearDirectGenerationTasksByType');
        expect(body).toContain('resetTaskErrorCount(');
    });
});
