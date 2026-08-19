const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const html = [
  fs.readFileSync(path.join(__dirname, '../../web/marketing_agent.html'), 'utf8'),
  fs.readFileSync(path.join(__dirname, '../../web/js/marketing_agent.js'), 'utf8'),
].join('\n');

assert.equal(
  html.includes('function restorePendingVerificationFromHistory'),
  true,
  'switching back to a session should restore an unanswered verification_id from loaded history'
);

assert.equal(
  html.includes("item.verification_status && item.verification_status !== 'pending'"),
  true,
  'timed out or cancelled verification history must not be restored as pending'
);

assert.equal(
  html.includes('verificationStatus: vData.status || h.verification_status || null'),
  true,
  'restored verification messages should keep backend verification status for disabled rendering'
);

assert.equal(
  html.includes('restorePendingVerificationFromHistory(history);'),
  true,
  'selectSession should restore pending verification state after loading session history'
);

assert.equal(
  html.includes('function isActiveVerificationMessage(msg)'),
  true,
  'verification option buttons should only be enabled for the active pending verification message'
);

assert.equal(
  html.includes(':disabled="!isActiveVerificationMessage(msg)"'),
  true,
  'verification option buttons must not rely on a global pending flag only'
);

assert.equal(
  html.includes('@click="selectVerificationOption(opt, msg.verificationId)"'),
  true,
  'verification option clicks should submit the verification id belonging to that message'
);

assert.equal(
  html.includes('if (!text || (isLoading.value && !pendingVerificationId.value)) return;'),
  true,
  'custom verification answers typed in the main input should be allowed while the agent task is waiting_human'
);

assert.equal(
  html.includes(':disabled="!inputText.trim() || (isLoading && !pendingVerificationId) || hasPendingAgentImages"'),
  true,
  'send button should stay usable for pending verification answers even when isLoading is true'
);

console.log('marketing_agent verification session restore tests passed');
