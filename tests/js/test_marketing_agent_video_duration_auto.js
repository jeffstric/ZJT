const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const html = fs.readFileSync(
  path.join(__dirname, '../../web/marketing_agent.html'),
  'utf8'
);
const marketingAgentJs = fs.readFileSync(
  path.join(__dirname, '../../web/js/marketing_agent.js'),
  'utf8'
);
const zh = fs.readFileSync(
  path.join(__dirname, '../../web/i18n/locales/zh-CN/marketing_agent.json'),
  'utf8'
);
const en = fs.readFileSync(
  path.join(__dirname, '../../web/i18n/locales/en/marketing_agent.json'),
  'utf8'
);

assert.match(
  marketingAgentJs,
  /const selectedDuration = ref\('auto'\)/,
  'marketing agent should default video duration to auto'
);

assert.match(
  marketingAgentJs,
  /return \['auto', \.\.\.config\.durations\]/,
  'duration options should prepend auto before model-supported durations'
);

assert.match(
  marketingAgentJs,
  /function formatDurationOption\(duration\)/,
  'duration labels should format auto separately from seconds'
);

assert.match(
  marketingAgentJs,
  /function resolveSelectedDurationForSubmission\(\)/,
  'direct video submission should resolve auto to a concrete supported duration'
);

assert.match(
  marketingAgentJs,
  /form\.append\('duration_seconds', String\(resolveSelectedDurationForSubmission\(\)\)\)/,
  'direct video API calls should not submit the literal auto string as duration_seconds'
);

assert.match(
  html,
  /formatDurationOption\(selectedDuration\)/,
  'marketing agent duration bar should render auto duration label'
);

assert.match(
  zh,
  /"duration_auto"\s*:\s*"自动"/,
  'Chinese locale should include an auto duration label'
);

assert.match(
  en,
  /"duration_auto"\s*:\s*"Auto"/,
  'English locale should include an auto duration label'
);

console.log('marketing_agent video duration auto tests passed');
