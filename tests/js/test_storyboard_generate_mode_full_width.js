const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const repoRoot = path.join(__dirname, '../..');
const renderSource = fs.readFileSync(path.join(repoRoot, 'web/js/storyboard/render.js'), 'utf8');
const styleSource = fs.readFileSync(path.join(repoRoot, 'web/css/storyboard.css'), 'utf8');

assert.match(
  renderSource,
  /<div class="gfs-mode-section">\s*<div class="generate-from-script-model">/,
  'the storyboard generation mode section should have its own full-width layout wrapper'
);

assert.match(
  styleSource,
  /\.generate-from-script-dialog \.gfs-mode-section\s*\{[^}]*grid-column:\s*1\s*\/\s*-1;/s,
  'the storyboard generation mode section should span both dialog columns'
);

console.log('storyboard full-width generation mode layout tests passed');
