const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

// 剧本节点拆分模型 data-model-id 必须是数值库 ID：
// 本地服务模型（ollama/vllm）在 /api/models 下发的 id 是 "vendor:模型名" 路由串，
// 历史版本把它当作 model_id 提交导致后端 int() 500
// （事故见 docs/backend/incidents/2026-09-06-script-split-composite-model-id.md）。

const repoRoot = path.join(__dirname, '../..');
const scriptNodeJs = fs.readFileSync(path.join(repoRoot, 'web/js/script_node.js'), 'utf8');
const splitTaskJs = fs.readFileSync(path.join(repoRoot, 'web/js/script_split_task.js'), 'utf8');

assert.match(
  scriptNodeJs,
  /const\s+rawModelId\s*=\s*model\.model_id\s*\?\?\s*model\.id\s*\?\?\s*'';/,
  'appendSplitOption should prefer the numeric db model_id over the routing composite id'
);

assert.match(
  scriptNodeJs,
  /String\(rawModelId\)\.includes\(':'\)\s*\?\s*''\s*:\s*rawModelId/,
  'composite "vendor:model" ids must not be written into data-model-id'
);

assert.doesNotMatch(
  scriptNodeJs,
  /const\s+modelId\s*=\s*model\.id\s*\?\?\s*model\.model_id/,
  'the old composite-id-first lookup must stay removed'
);

assert.match(
  splitTaskJs,
  /model_id:\s*scriptNodeData\.splitModelId\s*\|\|\s*''/,
  'split task client should submit node.data.splitModelId as model_id'
);

console.log('script node split model id wiring tests passed');
