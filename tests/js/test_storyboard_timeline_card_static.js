const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const repoRoot = path.join(__dirname, '../..');
const renderSource = fs.readFileSync(path.join(repoRoot, 'web/js/storyboard/render.js'), 'utf8');
const cssSource = fs.readFileSync(path.join(repoRoot, 'web/css/storyboard.css'), 'utf8');
const htmlSource = fs.readFileSync(path.join(repoRoot, 'web/storyboard.html'), 'utf8');

assert.match(
  htmlSource,
  /\/css\/storyboard\.css\?v=__VERSION__/,
  'storyboard page should cache-bust storyboard.css'
);

assert.match(
  renderSource,
  /<div class="scene-timeline-meta">[\s\S]*icon\('play',\s*14\)[\s\S]*<b>\$\{escapeHtml\(scene\.durationLabel\)\}<\/b>[\s\S]*<\/div>/,
  'timeline cards should render duration with a play icon inside the thumbnail'
);

assert.match(
  renderSource,
  /function renderTimelineThumbInner\(scene\)[\s\S]*class="scene-timeline-id-badge\$\{statusClass\}"[\s\S]*分镜\$\{escapeHtml\(scene\.id\)\}/,
  'timeline cards should render the real scene id as a thumbnail badge'
);

assert.match(
  renderSource,
  /class="scene-timeline-thumb[^\n]*[\s\S]*\$\{renderTimelineThumbInner\(scene\)\}[\s\S]*<\/button>/,
  'initial timeline rendering should reuse the same thumbnail renderer as partial refreshes'
);

assert.match(
  renderSource,
  /function renderTimelineMediaFrame\(scene\)[\s\S]*class="scene-timeline-media-frame first-frame-\$\{status\}"[\s\S]*<img src="\$\{escapeHtml\(scene\.firstFrameUrl\)\}"/,
  'timeline thumbnails should wrap media in a dedicated contain frame'
);

assert.match(
  renderSource,
  /<div class="scene-timeline-item"[^>]*>[\s\S]*<button class="scene-timeline-thumb[\s\S]*<\/button>\s*<div class="scene-timeline-actions">[\s\S]*data-action="duplicate-scene"[\s\S]*data-action="delete-scene"[\s\S]*<\/div>[\s\S]*<\/div>/,
  'timeline duplicate/delete actions should remain valid sibling buttons within each timeline card'
);

assert.match(
  cssSource,
  /\.scene-timeline-thumb\s*\{[\s\S]*width:\s*var\(--timeline-thumb-width\);[\s\S]*height:\s*var\(--timeline-thumb-height\);/,
  'timeline cards should use a stable landscape card size'
);

assert.match(
  cssSource,
  /--timeline-thumb-width:\s*180px;[\s\S]*--timeline-thumb-height:\s*101\.25px;/,
  'timeline cards should be compact but remain 16:9 landscape'
);

assert.match(
  cssSource,
  /\.scene-timeline-media-frame img\s*\{[\s\S]*width:\s*100%;[\s\S]*height:\s*100%;[\s\S]*object-fit:\s*contain\s*!important;[\s\S]*background:\s*#000;/,
  'timeline thumbnails should fill the frame height and contain portrait images with black side bars'
);

assert.match(
  cssSource,
  /\.scene-timeline-thumb > img\s*\{[\s\S]*width:\s*100%;[\s\S]*height:\s*100%;[\s\S]*object-fit:\s*contain\s*!important;[\s\S]*background:\s*#000;/,
  'timeline thumbnails should keep old direct image markup uncropped after cached JS loads'
);

assert.match(
  cssSource,
  /\.scene-timeline-item\s*\{[\s\S]*position:\s*relative;/,
  'timeline cards should provide the positioning context for overlays'
);

assert.match(
  cssSource,
  /\.scene-timeline-actions\s*\{[\s\S]*position:\s*absolute;[\s\S]*right:\s*8px;[\s\S]*bottom:\s*8px;/,
  'timeline actions should sit on the bottom-right overlay'
);

assert.match(
  cssSource,
  /\.scene-timeline-id-badge\s*\{[\s\S]*position:\s*absolute;[\s\S]*top:\s*8px;[\s\S]*left:\s*8px;/,
  'timeline scene id badge should sit on the top-left overlay'
);

assert.match(
  cssSource,
  /\.scene-timeline-id-badge\.has-first-frame-status\s*\{[\s\S]*top:\s*32px;/,
  'timeline scene id badge should move below the first-frame status badge'
);

assert.match(cssSource, /\.scene-timeline-insert-slot::before/);
assert.match(cssSource, /\.scene-timeline-insert-slot::after/);

console.log('storyboard timeline card static tests passed');
