const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const imageToVideoNodeJs = fs.readFileSync(path.join(__dirname, '../../web/js/image_to_video_node.js'), 'utf8');
const eventsJs = fs.readFileSync(path.join(__dirname, '../../web/js/events.js'), 'utf8');

const imageToVideoStart = imageToVideoNodeJs.indexOf('function createImageToVideoNode(opts)');
assert.notEqual(imageToVideoStart, -1, 'image_to_video node factory should exist');
const imageToVideoHeaderEnd = imageToVideoNodeJs.indexOf('const headerEl = el.querySelector', imageToVideoStart);
assert.notEqual(imageToVideoHeaderEnd, -1, 'image_to_video node DOM query block should exist');
const imageToVideoMarkup = imageToVideoNodeJs.slice(imageToVideoStart, imageToVideoHeaderEnd);

assert.match(
  imageToVideoMarkup,
  /node-title[\s\S]*data-i18n="image_to_video"/,
  'image_to_video title should be translatable after async i18n init'
);
assert.match(
  imageToVideoMarkup,
  /class="label"[^>]*data-i18n="image_mode_label"/,
  'image mode label should be translatable after async i18n init'
);
assert.match(
  imageToVideoMarkup,
  /option value="first_last_frame"[^>]*data-i18n="image_mode_first_last"/,
  'first/last image mode option should be translatable'
);
assert.match(
  imageToVideoMarkup,
  /option value="multi_reference"[^>]*data-i18n="image_mode_multi_ref"/,
  'multi-reference image mode option should be translatable'
);
assert.match(
  imageToVideoMarkup,
  /option value="text_to_video"[^>]*data-i18n="image_mode_text_to_video"/,
  'text-to-video image mode option should be translatable'
);

const mouseupStart = eventsJs.indexOf("window.addEventListener('mouseup'");
assert.notEqual(mouseupStart, -1, 'global mouseup handler should exist');
const videoConnectStart = eventsJs.indexOf("if(fromNode && fromNode.type === 'video')", mouseupStart);
assert.notEqual(videoConnectStart, -1, 'video node connection branch should exist in mouseup handler');
const audioConnectStart = eventsJs.indexOf("if(fromNode && fromNode.type === 'audio')", videoConnectStart);
assert.notEqual(audioConnectStart, -1, 'audio node connection branch should follow video branch');
const videoConnectBlock = eventsJs.slice(videoConnectStart, audioConnectStart);

assert.equal(
  videoConnectBlock.includes('data-node-id='),
  true,
  'video connection branch should query target node DOM by data-node-id'
);
assert.equal(
  videoConnectBlock.includes('data-node-id=鈥'),
  false,
  'video connection branch must not contain mojibake quotes in data-node-id selectors'
);
assert.match(
  videoConnectBlock,
  /canvasEl\.querySelector\(`\.node\[data-node-id="\$\{node\.id\}"\]`\)/,
  'video connection branch should use a valid data-node-id selector'
);

console.log('image_to_video node UI tests passed');
