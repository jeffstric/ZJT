const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const eventsPath = path.join(__dirname, '../../web/js/storyboard/events.js');
const renderPath = path.join(__dirname, '../../web/js/storyboard/render.js');
const statePath = path.join(__dirname, '../../web/js/storyboard/state.js');

const events = fs.readFileSync(eventsPath, 'utf8');
const render = fs.readFileSync(renderPath, 'utf8');
const state = fs.readFileSync(statePath, 'utf8');

assert.match(render, /data-auto-image-sequence-mode="quality"/, 'quality button should remain visible');
assert.match(events, /效果模式仅商业版支持，请购买商业版后使用/, 'community quality click should show commercial-only message');
assert.match(events, /state\.editionInfo\?\.mode !== 'enterprise'/, 'quality click should check enterprise mode');
assert.match(events, /return;/, 'community quality click should not fall through to state mutation');
assert.match(state, /editionInfo:\s*\{\s*mode:\s*'community'/, 'storyboard state should track edition info');
assert.match(state, /config\.autoImageSequenceMode === 'quality'[\s\S]*state\.editionInfo\?\.mode === 'enterprise'/, 'community restore should not keep persisted quality mode');

console.log('storyboard quality enterprise gate tests passed');
