const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.join(__dirname, '../..');
const htmlPath = path.join(root, 'web/storyboard_list.html');
const jsPath = path.join(root, 'web/js/storyboard_list.js');
const cssPath = path.join(root, 'web/css/storyboard_list.css');

assert.equal(fs.existsSync(htmlPath), true, 'storyboard list html should exist');
assert.equal(fs.existsSync(jsPath), true, 'storyboard list js should exist');
assert.equal(fs.existsSync(cssPath), true, 'storyboard list css should exist');

const html = fs.readFileSync(htmlPath, 'utf8');
const jsSource = fs.readFileSync(jsPath, 'utf8');
const indexHtml = fs.readFileSync(path.join(root, 'web/index.html'), 'utf8');
const scriptWriterHtml = fs.readFileSync(path.join(root, 'web/script_writer.html'), 'utf8');
const serverPy = fs.readFileSync(path.join(root, 'server.py'), 'utf8');

assert.match(html, /id="storyboardFolderContainer"/);
assert.match(html, /\/js\/storyboard_list\.js/);
assert.match(indexHtml, /handleStoryboardListClick/);
assert.match(scriptWriterHtml, /openStoryboardFromScript/);
assert.match(serverPy, /@app\.get\("\/storyboard-list"\)/);

const source = jsSource
  .replace(/export\s+function\s+/g, 'function ')
  .replace(/export\s+const\s+/g, 'const ');

const factory = new Function(
  source + '\nreturn { buildStoryboardUrl, normalizeFoldersResponse };'
);
const helpers = factory();

assert.equal(
  helpers.buildStoryboardUrl({
    world_id: 7,
    episode_number: 2,
    script_id: 11,
    storyboard_id: 31,
  }),
  '/storyboard?id=31&world_id=7&episode_number=2&script_id=11'
);

assert.deepEqual(
  helpers.normalizeFoldersResponse({ success: true, folders: [{ folder_key: '7:1' }] }),
  [{ folder_key: '7:1' }]
);

console.log('storyboard list static tests passed');
