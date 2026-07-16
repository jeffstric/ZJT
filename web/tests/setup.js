// Shared Vitest setup for browser-oriented frontend modules.
// 避免用例间 localStorage 污染（jsdom 在同一文件内会复用 storage）
import { beforeEach } from 'vitest';

beforeEach(() => {
  try {
    localStorage.clear();
  } catch (_) {
    // 部分用例会替换 localStorage mock，可能没有 clear
  }
  try {
    sessionStorage.clear();
  } catch (_) {
    /* ignore */
  }
});
