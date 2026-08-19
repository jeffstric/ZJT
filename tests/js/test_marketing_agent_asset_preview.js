const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const js = fs.readFileSync(
  path.join(__dirname, '../../web/js/marketing_agent.js'),
  'utf8'
);
const css = fs.readFileSync(
  path.join(__dirname, '../../web/css/marketing_agent.css'),
  'utf8'
);
const html = fs.readFileSync(
  path.join(__dirname, '../../web/marketing_agent.html'),
  'utf8'
);

assert.match(
  js,
  /aspectRatio: `\$\{parts\.w\} \/ \$\{parts\.h\}`/,
  'portrait asset cards must use CSS aspect-ratio 9 / 16, not 9:16'
);
assert.match(
  js,
  /preview\.style\.aspectRatio = `\$\{video\.videoWidth\} \/ \$\{video\.videoHeight\}`/,
  'missing ratio should fall back to video metadata'
);
assert.match(
  html,
  /@loadedmetadata="applyAssetVideoAspect"/,
  'asset videos should measure real dimensions after metadata loads'
);
assert.match(
  css,
  /\.asset-preview video \{[\s\S]*?width:\s*auto;[\s\S]*?max-height:\s*100%/,
  'asset videos must use auto width and height-cap so portrait frames are not cropped'
);
