const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const adaptersPath = path.join(__dirname, '../../web/js/storyboard/adapters.js');
const apiPath = path.join(__dirname, '../../web/js/storyboard/api.js');

const adaptersSource = fs.readFileSync(adaptersPath, 'utf8')
  .replace(/export\s+function\s+/g, 'function ');

const adaptersFactory = new Function(
  adaptersSource + '\nreturn { assetFromApi, mapAssetAvatar };'
);

const { assetFromApi, mapAssetAvatar } = adaptersFactory();

const prop = assetFromApi({
  id: 18,
  name: '扩音器',
  reference_image: 'upload/props/pic/speaker.png',
});

assert.equal(prop.avatar, 'upload/props/pic/speaker.png');
assert.equal(prop.reference_image, 'upload/props/pic/speaker.png');
assert.equal(prop.raw.reference_image, 'upload/props/pic/speaker.png');
assert.equal(mapAssetAvatar({ reference_images: [{ file_url: 'upload/props/pic/speaker-side.png' }] }), 'upload/props/pic/speaker-side.png');

const apiSource = fs.readFileSync(apiPath, 'utf8');
assert.match(
  apiSource,
  /fetchProps\(worldId\)[\s\S]*page_size=1000/,
  'storyboard should load enough props for prompt chips to resolve reference images'
);

console.log('storyboard prop reference chip tests passed');
