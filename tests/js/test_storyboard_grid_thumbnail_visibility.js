const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const cssPath = path.join(__dirname, '../../web/css/storyboard.css');
const css = fs.readFileSync(cssPath, 'utf8');
const gridPreviewRule = css.match(/\.storyboard-thumb \.preview-media\s*\{([^}]*)\}/);

assert.ok(gridPreviewRule, '应定义 Grid 分镜缩略图的 preview-media 样式');
assert.match(
    gridPreviewRule[1],
    /opacity:\s*1\s*;/,
    'Grid 分镜缩略图必须直接可见，不能继承主预览区的 opacity: 0'
);
assert.match(
    gridPreviewRule[1],
    /transition:\s*none\s*;/,
    'Grid 分镜缩略图不应复用主预览区的淡入过渡'
);

console.log('storyboard grid thumbnail visibility tests passed');
