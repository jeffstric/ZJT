const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const repoRoot = path.join(__dirname, '../..');
const taskConfigSource = fs.readFileSync(path.join(repoRoot, 'web/js/task_config.js'), 'utf8');

const mockConfig = {
  code: 0,
  data: {
    tasks: [
      {
        id: 99,
        key: 'happy_horse_image_to_video',
        short_key: 'happy_horse',
        category: 'image_to_video',
        supported_durations: [5],
        computing_power: { 5: 115 },
        power_modifiers: [
          {
            attribute: 'resolution',
            values: { '720P': 1.0, '1080P': 1.5 },
            default: 1.0,
          },
        ],
        implementations: [
          {
            name: 'happy_horse_dashscope_v1',
            supported_video_resolutions: [
              { value: '720P', label: '720P' },
              { value: '1080P', label: '1080P' },
            ],
            default_video_resolution: '720P',
          },
        ],
      },
    ],
    categories: {},
    providers: {},
  },
};

const context = {
  console,
  localStorage: { getItem: () => null },
  fetch: async () => ({
    ok: true,
    json: async () => mockConfig,
  }),
};
context.window = context;

vm.runInNewContext(taskConfigSource, context, { filename: 'task_config.js' });

function plain(value) {
  return JSON.parse(JSON.stringify(value));
}

(async () => {
  await context.TaskConfig.load();

  assert.deepEqual(
    plain(context.TaskConfig.getVideoResolutionOptions('happy_horse')),
    [
      { value: '720P', label: '720P' },
      { value: '1080P', label: '1080P' },
    ],
    'should expose structured video resolution options'
  );
  assert.equal(
    context.TaskConfig.getDefaultVideoResolution('happy_horse'),
    '720P',
    'should expose implementation default video resolution'
  );
  assert.equal(
    context.TaskConfig.getComputingPower('happy_horse', 5, { resolution: '1080P' }),
    173,
    '1080P should apply resolution power modifier'
  );

  const modelConfigs = context.TaskConfig.getModelConfigs();
  assert.deepEqual(
    plain(modelConfigs.happy_horse.video_resolutions),
    [
      { value: '720P', label: '720P' },
      { value: '1080P', label: '1080P' },
    ],
    'legacy model config should include video_resolutions'
  );
  assert.equal(modelConfigs.happy_horse.default_video_resolution, '720P');

  console.log('task config video resolution tests passed');
})().catch(error => {
  console.error(error);
  process.exit(1);
});
