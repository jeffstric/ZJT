const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const adaptersPath = path.join(__dirname, '../../web/js/storyboard/adapters.js');
const apiPath = path.join(__dirname, '../../web/js/storyboard/api.js');
const renderPath = path.join(__dirname, '../../web/js/storyboard/render.js');
const serverPath = path.join(__dirname, '../../server.py');
const constantPath = path.join(__dirname, '../../config/constant.py');

const adaptersSource = fs.readFileSync(adaptersPath, 'utf8')
  .replace(/export\s+function\s+/g, 'function ');

const adaptersFactory = new Function(
  adaptersSource + '\nreturn { assetFromApi, mapAssetAvatar, normalizePagedList };'
);

const { assetFromApi, mapAssetAvatar, normalizePagedList } = adaptersFactory();

const renderSource = fs.readFileSync(renderPath, 'utf8')
  .replace(/^import[\s\S]*?from\s+['"][^'"]+['"];\r?\n/gm, '')
  .replace(/export\s+function\s+/g, 'function ');

const renderFactory = new Function(
  'mapAssetAvatar',
  'characterReferenceSelectionKey',
  renderSource + '\nreturn { renderPromptWithInlineRoles };'
);

function escapeHtml(value) {
  return String(value || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

class FakeTextNode {
  constructor(text) {
    this.text = String(text || '');
  }

  get outerHTML() {
    return escapeHtml(this.text);
  }
}

class FakeElement {
  constructor(tagName) {
    this.tagName = tagName.toLowerCase();
    this.children = [];
    this.className = '';
    this.title = '';
    this.src = '';
    this.alt = '';
    this.dataset = {};
    this.style = { cssText: '' };
    this._textContent = '';
    this.classList = {
      add: (...classes) => {
        const existing = this.className ? this.className.split(/\s+/) : [];
        for (const cls of classes) {
          if (cls && !existing.includes(cls)) existing.push(cls);
        }
        this.className = existing.join(' ');
      },
    };
  }

  appendChild(child) {
    this.children.push(child);
    return child;
  }

  set textContent(value) {
    this._textContent = String(value || '');
    this.children = [];
  }

  get textContent() {
    return this._textContent || this.children.map(child => child.text || child.textContent || '').join('');
  }

  set innerHTML(value) {
    this.textContent = String(value || '').replace(/<[^>]*>/g, '');
  }

  get innerHTML() {
    if (this.children.length) return this.children.map(child => child.outerHTML).join('');
    return escapeHtml(this._textContent);
  }

  get outerHTML() {
    const attrs = [];
    if (this.className) attrs.push(`class="${escapeHtml(this.className)}"`);
    if (this.title) attrs.push(`title="${escapeHtml(this.title)}"`);
    if (this.src) attrs.push(`src="${escapeHtml(this.src)}"`);
    if (this.alt) attrs.push(`alt="${escapeHtml(this.alt)}"`);
    if (this.style.cssText) attrs.push(`style="${escapeHtml(this.style.cssText)}"`);
    const attrText = attrs.length ? ` ${attrs.join(' ')}` : '';
    if (this.tagName === 'img') return `<img${attrText}>`;
    return `<${this.tagName}${attrText}>${this.innerHTML}</${this.tagName}>`;
  }
}

global.document = {
  createElement: tagName => new FakeElement(tagName),
  createTextNode: text => new FakeTextNode(text),
};
function characterReferenceSelectionKey(character) {
  const id = character?.id ?? character?.character_id ?? character?.characterId ?? character?.db_id;
  if (id !== null && id !== undefined && id !== '') return String(id);
  return character?.name ? `name:${String(character.name).trim().toLowerCase()}` : '';
}
const { renderPromptWithInlineRoles } = renderFactory(mapAssetAvatar, characterReferenceSelectionKey);

const prop = assetFromApi({
  id: 18,
  name: '扩音器',
  reference_image: 'upload/props/pic/speaker.png',
});

assert.equal(prop.avatar, 'upload/props/pic/speaker.png');
assert.equal(prop.reference_image, 'upload/props/pic/speaker.png');
assert.equal(prop.raw.reference_image, 'upload/props/pic/speaker.png');
assert.equal(mapAssetAvatar({ reference_images: [{ file_url: 'upload/props/pic/speaker-side.png' }] }), 'upload/props/pic/speaker-side.png');
assert.equal(
  mapAssetAvatar({ reference_images: '[{"url":"upload/props/pic/speaker-front.png"}]' }),
  'upload/props/pic/speaker-front.png'
);

const character = assetFromApi({
  id: 22,
  name: '裁判',
  reference_images: '[{"file_url":"upload/character/pic/referee.png"}]',
});

assert.equal(character.avatar, 'upload/character/pic/referee.png');
assert.deepEqual(character.reference_images, [{ file_url: 'upload/character/pic/referee.png' }]);
assert.equal(mapAssetAvatar({ file_url: 'upload/character/pic/file.png' }), 'upload/character/pic/file.png');
assert.equal(mapAssetAvatar({ url: 'upload/character/pic/url.png' }), 'upload/character/pic/url.png');

assert.deepEqual(normalizePagedList({ success: true, characters: [{ name: '裁判' }] }).map(item => item.name), ['裁判']);
assert.deepEqual(normalizePagedList({ success: true, props: [{ name: '扩音器' }] }).map(item => item.name), ['扩音器']);
assert.deepEqual(normalizePagedList({ success: true, items: [{ name: '公文包' }] }).map(item => item.name), ['公文包']);

const nestedRolePropHtml = renderPromptWithInlineRoles(
  '【【裁判】】满脸严肃，嘴里含着〖〖【【裁判】】哨子〗〗。',
  [{ name: '裁判', reference_image: 'upload/character/pic/referee.png' }],
  [{ name: '裁判哨子', reference_image: 'upload/props/pic/whistle.png' }]
);
assert.match(
  nestedRolePropHtml,
  /class="prop-chip"[\s\S]*\/api\/thumbnail\?url=upload%2Fprops%2Fpic%2Fwhistle\.png&amp;size=16/,
  'prop chip should resolve image when prop marker contains nested role marker'
);
assert.doesNotMatch(
  nestedRolePropHtml,
  /【【裁判】】哨子/,
  'prop chip display name should not leak nested role marker text'
);

const plainPropHtml = renderPromptWithInlineRoles(
  '嘴里含着〖〖裁判哨子〗〗。',
  [{ name: '裁判', reference_image: 'upload/character/pic/referee.png' }],
  [{ name: '裁判哨子', reference_image: 'upload/props/pic/whistle.png' }]
);
assert.match(
  plainPropHtml,
  /class="prop-chip"[\s\S]*\/api\/thumbnail\?url=upload%2Fprops%2Fpic%2Fwhistle\.png&amp;size=16/,
  'plain prop marker that contains a role name should not be polluted by role pre-tagging'
);
assert.doesNotMatch(
  plainPropHtml,
  /【【裁判】】哨子/,
  'role pre-tagging should skip text inside prop markers'
);

const unmatchedPropHtml = renderPromptWithInlineRoles(
  '\u53ea\u5269\u4e0b\u4e00\u4e2a\u534a\u762a\u7684\u3016\u3016\u8db3\u7403\u3017\u3017\u9759\u9759\u8eba\u5728\u539f\u5730\u3002',
  [{ name: '\u5927\u529b\u795e\u676f', reference_image: 'upload/character/pic/trophy.png' }],
  [{ name: '\u516c\u6587\u5305', reference_image: 'upload/props/pic/briefcase.png' }]
);
assert.doesNotMatch(
  unmatchedPropHtml,
  /class="prop-chip"/,
  'unmatched prop marker should not render as a prop chip'
);
assert.match(unmatchedPropHtml, /\u8db3\u7403/, 'unmatched prop marker should fall back to plain text');
assert.doesNotMatch(
  unmatchedPropHtml,
  /\u3016\u3016\u8db3\u7403\u3017\u3017/,
  'unmatched prop marker delimiters should not leak into display text'
);

const apiSource = fs.readFileSync(apiPath, 'utf8');
assert.match(
  apiSource,
  /fetchProps\(worldId\)[\s\S]*page_size=1000/,
  'storyboard should load enough props for prompt chips to resolve reference images'
);
assert.match(
  apiSource,
  /fetchCharacters\(worldId\)[\s\S]*page_size=1000/,
  'storyboard should load enough characters for prompt chips to resolve reference images'
);

const serverSource = fs.readFileSync(serverPath, 'utf8');
const constantSource = fs.readFileSync(constantPath, 'utf8');
assert.match(
  constantSource,
  /ASSET_LIST_MAX_PAGE_SIZE\s*=\s*1000/,
  'shared asset list page-size limit should be defined in config.constant'
);
assert.match(
  serverSource,
  /async def get_characters\([\s\S]*page_size: int = Query\(100, ge=1, le=ASSET_LIST_MAX_PAGE_SIZE/,
  'characters API must accept storyboard page_size=1000 instead of returning 422'
);
assert.match(
  serverSource,
  /async def get_locations\([\s\S]*page_size: int = Query\(100, ge=1, le=ASSET_LIST_MAX_PAGE_SIZE/,
  'locations API must accept storyboard page_size=1000 instead of returning 422'
);
assert.match(
  serverSource,
  /async def get_props\([\s\S]*page_size: int = Query\(100, ge=1, le=ASSET_LIST_MAX_PAGE_SIZE/,
  'props API must accept storyboard page_size=1000 instead of returning 422'
);

console.log('storyboard prop reference chip tests passed');
