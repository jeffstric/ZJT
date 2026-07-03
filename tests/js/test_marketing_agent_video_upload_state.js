const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const marketingAgentJs = fs.readFileSync(
  path.join(__dirname, '../../web/js/marketing_agent.js'),
  'utf8'
);

const videoBranchStarts = [...marketingAgentJs.matchAll(/if \(file\.type\.startsWith\('video\/'\)\) \{/g)]
  .map(match => match.index);
assert.notEqual(videoBranchStarts.length, 0, 'video upload branch should exist');

videoBranchStarts.forEach((videoBranchStart, index) => {
  const audioBranchStart = marketingAgentJs.indexOf("if (file.type.startsWith('audio/')) {", videoBranchStart);
  assert.notEqual(audioBranchStart, -1, `audio upload branch should follow video branch ${index + 1}`);

  const videoBranch = marketingAgentJs.slice(videoBranchStart, audioBranchStart);

  assert.equal(
    videoBranch.includes('hasUploadedImage.value = true'),
    false,
    `uploading a video must not mark image state as uploaded in branch ${index + 1}`
  );

  assert.equal(
    videoBranch.includes('processVideoFile(file, fileDuration);'),
    true,
    `video upload branch ${index + 1} should still process the selected video file`
  );
});

console.log('marketing_agent video upload state tests passed');
