import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const root = path.resolve(import.meta.dirname, '../..');
const readSource = (relativePath) => fs.readFileSync(path.join(root, relativePath), 'utf8');

describe('index implementation lock UI', () => {
  it('renders lock checkbox only when a vendor is selected', () => {
    const htmlSource = readSource('web/index.html');
    const cssSource = readSource('web/css/index.css');
    const appSource = readSource('web/js/index_app.js');

    expect(htmlSource).toContain('固定此供应商（失败后不自动切换）');
    expect(htmlSource).toContain('v-if="userPreferences[taskKey]"');
    expect(htmlSource).toContain('handleLockChange(taskKey, $event.target.checked)');
    expect(htmlSource).toContain('userPreferenceLocks[taskKey]');
    expect(htmlSource).toContain('勾选「固定此供应商」后');

    expect(cssSource).toContain('.settings-lock');
    expect(cssSource).toContain('.settings-lock-hint');

    expect(appSource).toContain('userPreferenceLocks: {}');
    expect(appSource).toContain('async handleLockChange(taskKey, locked)');
    expect(appSource).toContain('locked: !!locked');
  });
});
