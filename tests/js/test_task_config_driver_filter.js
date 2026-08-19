const assert = require('assert');
global.window = global;
const TaskConfig = require('../../web/js/task_config.js');

assert.strictEqual(TaskConfig.isDriverAvailable(20, null), true);
assert.strictEqual(TaskConfig.isDriverAvailable(20, {}), true);
assert.strictEqual(TaskConfig.isDriverAvailable(20, { 20: { available: false } }), false);
assert.strictEqual(TaskConfig.isDriverAvailable(22, { 20: { available: false } }), true);
assert.strictEqual(TaskConfig.isDriverAvailable(22, { 22: { available: true } }), true);

const options = [
  { value: 'minimax_h3', taskType: 20 },
  { value: 'seedance_2_0', taskType: 22 },
];
const filtered = TaskConfig.filterAvailableModelOptions(options, { 20: { available: false } });
assert.strictEqual(filtered.length, 1);
assert.strictEqual(filtered[0].value, 'seedance_2_0');

console.log('test_task_config_driver_filter.js ok');
