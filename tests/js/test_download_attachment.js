const assert = require('node:assert/strict');
const path = require('node:path');

global.location = {
    origin: 'http://app.local',
    pathname: '/video-workflow',
    search: '',
    assign(url) { global.__assigned = url; },
};
global.localStorage = {
    getItem() { return 'valid-token'; },
};

const api = require(path.join(__dirname, '../../web/js/download_attachment.js'));

assert.equal(
    api.unwrapMediaUrl('http://app.local/api/proxy-image?url=' + encodeURIComponent('https://cdn.example/a.png?e=1')),
    'https://cdn.example/a.png?e=1'
);
assert.equal(api.unwrapMediaUrl('/upload/cache/a.mp4'), '/upload/cache/a.mp4');

(async () => {
    global.__assigned = '';
    let seen = null;
    global.fetch = async (url, opts) => {
        seen = { url, opts };
        return {
            ok: true,
            status: 200,
            headers: { get: () => 'application/json' },
            json: async () => ({ success: true, redirect_url: 'https://cdn.example/a.mp4?attname=clip.mp4' }),
        };
    };
    await api.downloadWithAuth('https://cdn.example/a.mp4?e=1&token=cdn', 'clip.mp4');
    assert.equal(seen.opts.headers.Authorization, 'Bearer valid-token');
    assert.equal(seen.url.includes('format=json'), true);
    assert.equal(seen.url.includes('auth_token='), false);
    assert.equal(seen.url.includes('valid-token'), false);
    assert.equal(global.__assigned, 'https://cdn.example/a.mp4?attname=clip.mp4');

    let unauthorized = false;
    global.fetch = async () => ({
        ok: false,
        status: 401,
        headers: { get: () => 'application/json' },
        json: async () => ({ success: false, error_code: 'invalid_auth_token', error: 'Authorization is invalid or expired' }),
    });
    await assert.rejects(
        () => api.downloadWithAuth('https://cdn.example/a.mp4', 'clip.mp4', {
            onUnauthorized() { unauthorized = true; },
        }),
        (err) => err.status === 401
    );
    assert.equal(unauthorized, true);
})().catch((err) => {
    console.error(err);
    process.exit(1);
});
