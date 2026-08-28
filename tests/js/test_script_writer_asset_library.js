const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const repoRoot = path.join(__dirname, '../..');
const htmlSource = fs.readFileSync(path.join(repoRoot, 'web/script_writer.html'), 'utf8');
const jsSource = fs.readFileSync(path.join(repoRoot, 'web/js/script_writer.js'), 'utf8');
const libSource = fs.readFileSync(path.join(repoRoot, 'web/js/script_writer_library.js'), 'utf8');
const cssSource = fs.readFileSync(path.join(repoRoot, 'web/css/script_writer_library.css'), 'utf8');
const zhIndex = JSON.parse(fs.readFileSync(path.join(repoRoot, 'web/i18n/locales/zh-CN/index.json'), 'utf8'));
const enIndex = JSON.parse(fs.readFileSync(path.join(repoRoot, 'web/i18n/locales/en/index.json'), 'utf8'));

const I18N_KEYS = [
  'library_management',
  'asset_source_staging',
  'asset_source_database',
  'library_search_placeholder',
  'library_empty',
  'library_delete_title',
  'library_delete_also_staging',
  'library_delete_resurrect_hint',
  'library_delete_confirm',
  'library_delete_owner_only',
  'library_edit_owner_only',
];

for (const key of I18N_KEYS) {
  assert.ok(zhIndex[key], `zh-CN missing i18n key ${key}`);
  assert.ok(enIndex[key], `en missing i18n key ${key}`);
}

assert.match(htmlSource, /asset-source-switch/, 'sidebar should have source switch');
assert.match(htmlSource, /switchAssetSource\('staging'\)/, 'staging source button');
assert.match(htmlSource, /switchAssetSource\('database'\)/, 'database source button');
assert.match(htmlSource, /script_writer_library\.js/, 'library js should be included');
assert.match(htmlSource, /script_writer_library\.css/, 'library css should be included');
assert.match(htmlSource, /library-delete-modal/, 'delete confirm modal');
assert.match(htmlSource, /id="library-delete-staging"/, 'also-delete-staging checkbox');
assert.match(htmlSource, /checked/, 'also-delete-staging should default checked');

assert.match(jsSource, /ScriptWriterLibrary\.isLibrary\(\)/, 'loadFiles should branch on library mode');
assert.match(jsSource, /saveLibraryAsset\(\)/, 'saveEditedFile should delegate library saves');
assert.match(
  jsSource,
  /updateStyleRecognizeVisibility[\s\S]*isLibrary\(\)/,
  'style recognition should hide in library mode'
);

assert.match(libSource, /formatCreatorTag/, 'creator tag helper');
assert.match(libSource, /slice\(-4\)/, 'creator tag uses last 4 chars of user_id');
assert.match(libSource, /also_delete_staging=true/, 'delete should pass also_delete_staging');
assert.match(libSource, /仅创建者可删除/, 'non-owner cannot delete');
assert.match(
  libSource,
  /fileType === 'scripts' \? 100 : 1000/,
  'scripts list must use page_size=100 (API historically rejects 1000)'
);
assert.match(libSource, /fetchAllLibraryRows/, 'library list should paginate');
assert.match(libSource, /listErrorMessage/, 'API errors must not be shown as empty list');
assert.match(libSource, /fetchWorldFromList/, 'world tab must use GET /api/worlds list, not GET /api/worlds/{id}');
assert.match(libSource, /rememberLibraryRows/, 'library list should cache rows for view/edit');
assert.doesNotMatch(
  libSource,
  /apiJson\('\/api\/worlds\/' \+ WORLD_ID\)/,
  'do not fetch world detail exclusively from GET /api/worlds/{id}'
);
assert.doesNotMatch(
  libSource,
  /page_size': '1000'/,
  'do not hardcode page_size=1000 for all asset types'
);
assert.match(cssSource, /\.asset-source-switch/, 'source switch styles');
assert.match(cssSource, /\.file-sidebar\.is-library/, 'library mode hides staging actions');
