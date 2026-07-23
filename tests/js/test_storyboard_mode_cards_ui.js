const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const renderSource = fs.readFileSync(
  path.join(__dirname, '../../web/js/storyboard/render.js'),
  'utf8'
);
const cssSource = fs.readFileSync(
  path.join(__dirname, '../../web/css/storyboard.css'),
  'utf8'
);

assert.match(renderSource, /sequence-mode-intro-meta/);
assert.match(renderSource, /sequence-mode-benefit/);
assert.doesNotMatch(renderSource, /sequence-mode-intro-crown/);
assert.doesNotMatch(
  cssSource,
  /\.sequence-mode-intro-head span\s*\{/,
  'mode-card styles should target semantic classes instead of every nested span'
);
assert.doesNotMatch(cssSource, /animation:\s*cinema-(?:glow|shimmer)/);
assert.match(
  cssSource,
  /\.sequence-mode-intro-card--cinema\s*\{[\s\S]{0,600}background:\s*#fff8e7/,
  'quality mode should use the approved soft-gold surface'
);
assert.match(cssSource, /@media\s*\(max-width:\s*540px\)/);

console.log('storyboard mode cards UI tests passed');
