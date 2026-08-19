const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const html = fs.readFileSync(
  path.join(__dirname, '../../web/marketing_agent.html'),
  'utf8'
);
const js = fs.readFileSync(
  path.join(__dirname, '../../web/js/marketing_agent.js'),
  'utf8'
);
const source = html + '\n' + js;

assert.match(
  source,
  /function getLLMModelSelectionKey\(model\)/,
  'LLM selection should use a composite key helper'
);

assert.match(
  html,
  /:key="getLLMModelSelectionKey\(model\)"/,
  'LLM dropdown rows should be keyed by model and vendor'
);

assert.match(
  html,
  /selectedLLMModelKey === getLLMModelSelectionKey\(model\)/,
  'LLM selected styles should compare model and vendor'
);

assert.match(
  source,
  /marketing_selected_llm_vendor_id/,
  'LLM preference persistence should include vendor_id'
);

assert.match(
  source,
  /vendorName === 'volcengine'[\s\S]*vendorName === 'zjt_api'/,
  'duplicate model names should prefer volcengine before zjt_api'
);

assert.match(
  source,
  /scene=llm\.marketing/,
  'marketing LLM list should request marketing scene catalog'
);
assert.match(
  html,
  /selectLLMTrack\('value'\)/,
  'marketing LLM picker should expose value track'
);
assert.match(
  html,
  /selectLLMTrack\('quality'\)/,
  'marketing LLM picker should expose quality track'
);

console.log('marketing_agent LLM vendor selection tests passed');
