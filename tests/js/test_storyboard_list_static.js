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
const listPageJs = fs.readFileSync(path.join(root, 'web/js/pages/list_page.js'), 'utf8');
const scriptWriterJs = fs.readFileSync(path.join(root, 'web/js/script_writer.js'), 'utf8');
const serverPy = fs.readFileSync(path.join(root, 'server.py'), 'utf8');

assert.match(html, /id="storyboardFolderContainer"/);
assert.match(html, /id="storyboardOwnerScope"/);
assert.match(html, /只看自己/);
assert.match(html, /查看全部/);
assert.match(html, /查看指定用户/);
assert.match(html, /id="storyboardOwnerInput"/);
assert.match(jsSource, /escapeHtml\(ownerName\)/);
assert.match(jsSource, /query\.set\('scope', ownerScope\)/);
assert.match(fs.readFileSync(cssPath, 'utf8'), /\.folder-owner/);
assert.match(fs.readFileSync(cssPath, 'utf8'), /\.owner-scope\[hidden\]/);
assert.match(html, /\/js\/storyboard_list\.js/);
assert.match(listPageJs, /handleStoryboardListClick/);
assert.match(scriptWriterJs, /openStoryboardFromScript/);
assert.match(serverPy, /@app\.get\("\/storyboard-list"\)/);

const source = jsSource
  .replace(/export\s+function\s+/g, 'function ')
  .replace(/export\s+const\s+/g, 'const ');

global.window = {
  escapeHtml(value) {
    return String(value ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  },
};
global.localStorage = {
  getItem() {
    return '';
  },
};

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
