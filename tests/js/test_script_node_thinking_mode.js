const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const repoRoot = path.join(__dirname, '../..');
const scriptNodeJs = fs.readFileSync(path.join(repoRoot, 'web/js/script_node.js'), 'utf8');
const workflowJs = fs.readFileSync(path.join(repoRoot, 'web/js/workflow.js'), 'utf8');

const enableThinkingPayloads = scriptNodeJs.match(/enable_thinking:\s*node\.data\.enableThinking\s*===\s*true/g) || [];
assert.equal(
  enableThinkingPayloads.length,
  2,
  'both script parse entry points should submit node.data.enableThinking as enable_thinking'
);

const thinkingEffortPayloads = scriptNodeJs.match(/thinking_effort:\s*node\.data\.thinkingEffort\s*\|\|\s*['"]medium['"]/g) || [];
assert.equal(
  thinkingEffortPayloads.length,
  2,
  'both script parse entry points should submit node.data.thinkingEffort as thinking_effort'
);

assert.match(
  scriptNodeJs,
  /function\s+isThinkingModelOption\([^)]*\)[\s\S]*vendorName[\s\S]*deepseek/i,
  'script node should detect DeepSeek thinking-capable models for default enablement'
);

assert.match(
  scriptNodeJs,
  /function\s+syncThinkingModeFromSelectedModel\([^)]*\)[\s\S]*node\.data\.enableThinking\s*=\s*true/,
  'script node should default-enable thinking for DeepSeek models unless the user disabled it'
);

assert.match(
  scriptNodeJs,
  /enableThinkingEl\.addEventListener\(['"]change['"][\s\S]*node\.data\.enableThinking\s*=\s*enableThinkingEl\.checked/,
  'script node should persist thinking toggle changes to node.data'
);

assert.match(
  scriptNodeJs,
  /thinkingEffortEl\.addEventListener\(['"]change['"][\s\S]*node\.data\.thinkingEffort\s*=\s*thinkingEffortEl\.value/,
  'script node should persist thinking effort changes to node.data'
);

assert.match(
  scriptNodeJs,
  /splitModelSelect\.addEventListener\(['"]change['"][\s\S]*syncThinkingModeFromSelectedModel\(/,
  'switching the split model should refresh thinking mode visibility and defaults'
);

assert.match(
  workflowJs,
  /node\.data\.enableThinking\s*=\s*nodeData\.data\.enableThinking\s*!==\s*undefined\s*\?\s*nodeData\.data\.enableThinking\s*:\s*false/,
  'workflow reload should restore script-node enableThinking'
);

assert.match(
  workflowJs,
  /node\.data\.thinkingEffort\s*=\s*nodeData\.data\.thinkingEffort\s*\|\|\s*['"]medium['"]/,
  'workflow reload should restore script-node thinkingEffort'
);

assert.match(
  workflowJs,
  /splitModelEl\.dispatchEvent\(new Event\(['"]change['"],\s*\{\s*bubbles:\s*true\s*\}\)\)/,
  'workflow reload should trigger script-node split model change handling after restoring thinking fields'
);

console.log('script node thinking mode wiring tests passed');
