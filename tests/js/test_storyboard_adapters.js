const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const adapterPath = path.join(__dirname, '../../web/js/storyboard/adapters.js');
assert.equal(fs.existsSync(adapterPath), true, 'storyboard adapters.js should exist');

const source = fs.readFileSync(adapterPath, 'utf8')
  .replace(/export\s+function\s+/g, 'function ')
  .replace(/export\s+const\s+/g, 'const ');

const factory = new Function(
  source + '\nreturn { normalizePagedList, sceneFromApi, sceneToPromptPayload, formatDuration };'
);
const adapters = factory();

const pagedResponse = {
  code: 0,
  data: {
    total: 2,
    page: 1,
    page_size: 100,
    data: [{ id: 1, name: '角色A' }, { id: 2, name: '角色B' }],
  },
};
assert.deepEqual(
  adapters.normalizePagedList(pagedResponse).map((item) => item.name),
  ['角色A', '角色B'],
  'paged API response should unwrap data.data arrays'
);

const scene = adapters.sceneFromApi({
  id: 11,
  sort_order: 2,
  title: '分镜2',
  duration: 8,
  preview_image_url: '/preview.png',
  prompt_json: {
    perspective: '中景',
    style: '写实',
    scene_desc: '办公室冲突',
    character_desc: '主角紧张',
  },
  voiceover_text: '旁白',
  image_status: 2,
  video_status: 1,
});

assert.equal(scene.id, 11);
assert.equal(scene.durationLabel, '00:08');
assert.equal(scene.thumbnail, '/preview.png');
assert.equal(scene.sceneInfo.sceneDesc, '办公室冲突');
assert.equal(scene.status.image, 2);

assert.deepEqual(
  adapters.sceneToPromptPayload({
    sceneInfo: {
      perspective: '近景',
      style: '赛博朋克',
      sceneDesc: '雨夜街道',
      charDesc: '女孩回头',
    },
  }),
  {
    perspective: '近景',
    style: '赛博朋克',
    scene_desc: '雨夜街道',
    character_desc: '女孩回头',
  },
  'UI scene info should serialize to storyboard_scene.prompt_json'
);

console.log('storyboard adapter tests passed');
