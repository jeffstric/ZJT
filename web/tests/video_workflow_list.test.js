// state.js 的函数在浏览器中通过 <script> 标签加载成为全局函数
// 在测试环境中需要手动挂载到 globalThis
const stateModule = require('../js/state.js');
globalThis.getAuthToken = stateModule.getAuthToken;
globalThis.getUserId = stateModule.getUserId;
globalThis.showToast = stateModule.showToast;
globalThis.state = stateModule.state;

const {
  ensureLoggedIn,
  buildWorkflowListQuery,
  ownerHintText,
  canManageWorkflow,
  workflowOwnerMarkup,
  loadWorkflows,
  bindOwnerScope,
  setListBrowseState,
} = require('../js/video_workflow_list.js');

describe('video_workflow_list - ensureLoggedIn', () => {
  beforeEach(() => {
    localStorage.clear();
    // mock toast DOM
    const toast = document.createElement('div');
    toast.id = 'toast';
    document.body.appendChild(toast);
    vi.useFakeTimers();
  });

  afterEach(() => {
    document.body.innerHTML = '';
    localStorage.clear();
    vi.useRealTimers();
  });

  test('有 user_id 时返回 true', () => {
    localStorage.setItem('user_id', 'user_123');
    expect(ensureLoggedIn()).toBe(true);
  });

  test('无 user_id 时返回 false 并显示 toast', () => {
    expect(ensureLoggedIn()).toBe(false);
    const toast = document.getElementById('toast');
    expect(toast.textContent).toBeTruthy();
    expect(toast.classList.contains('show')).toBe(true);
  });
});

describe('video_workflow_list - 作者范围', () => {
  beforeEach(() => {
    globalThis.escapeHtml = (value) => String(value ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  });

  test('普通用户不带 scope', () => {
    const query = buildWorkflowListQuery({
      page: 1,
      pageSize: 10,
      status: '',
      keyword: '',
      isAdmin: false,
      scope: 'all',
      owner: '远方',
    });
    expect(query).toBe('page=1&page_size=10');
    expect(query).not.toContain('scope=');
  });

  test('管理员只看自己也会带上 scope=mine', () => {
    const query = buildWorkflowListQuery({
      page: 2,
      pageSize: 10,
      status: '1',
      keyword: '夜',
      isAdmin: true,
      scope: 'mine',
      owner: '',
    });
    const params = new URLSearchParams(query);
    expect(params.get('scope')).toBe('mine');
    expect(params.get('status')).toBe('1');
    expect(params.get('keyword')).toBe('夜');
    expect(params.has('owner')).toBe(false);
  });

  test('管理员查看指定用户带上 owner', () => {
    const query = buildWorkflowListQuery({
      page: 1,
      pageSize: 10,
      isAdmin: true,
      scope: 'user',
      owner: 'user@example.com',
    });
    const params = new URLSearchParams(query);
    expect(params.get('scope')).toBe('user');
    expect(params.get('owner')).toBe('user@example.com');
  });

  test('作者昵称经过转义', () => {
    expect(workflowOwnerMarkup('')).toBe('');
    expect(workflowOwnerMarkup('  <b>远方</b>  ')).toBe(
      '<div class="workflow-owner">&lt;b&gt;远方&lt;/b&gt;</div>'
    );
  });

  test('他人工作流不显示编辑删除', () => {
    expect(canManageWorkflow({ user_id: 14 }, '14')).toBe(true);
    expect(canManageWorkflow({ user_id: 33 }, '14')).toBe(false);
    expect(canManageWorkflow({}, '14')).toBe(true);
  });

  test('范围提示映射到文案键', () => {
    expect(ownerHintText('success')).toBe('');
    expect(ownerHintText('请输入昵称或账号')).toBe('owner_query_required');
    expect(ownerHintText('未找到该用户')).toBe('owner_not_found');
  });
});

function mountWorkflowList() {
  document.body.innerHTML = `
    <div id="toast"></div>
    <select id="statusFilter"><option value=""></option></select>
    <section id="workflowOwnerScope">
      <button type="button" class="owner-scope-btn" data-scope="mine">只看自己</button>
      <button type="button" class="owner-scope-btn" data-scope="all">查看全部</button>
      <button type="button" class="owner-scope-btn" data-scope="user">查看指定用户</button>
      <form id="workflowOwnerForm">
        <input id="workflowOwnerInput" />
        <button type="submit">查看</button>
      </form>
      <p id="workflowOwnerHint" hidden></p>
    </section>
    <div id="workflowContainer"></div>
    <div id="pagination"><span id="pageInfo"></span><button id="prevBtn"></button><button id="nextBtn"></button></div>
  `;
  globalThis.escapeHtml = (value) => String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
  localStorage.setItem('user_id', '14');
  localStorage.setItem('auth_token', 'preview');
  bindOwnerScope();
}

function workflowPayload(name, id) {
  return {
    ok: true,
    json: async () => ({
      code: 0,
      message: 'success',
      data: {
        total: 1,
        data: [{ id, name, description: '', user_id: 14, status: 1, owner_nickname: '远方' }],
      },
    }),
  };
}

describe('video_workflow_list - 范围切换', () => {
  afterEach(() => {
    document.body.innerHTML = '';
    localStorage.clear();
    setListBrowseState({ isAdmin: false, scope: 'mine', owner: '' });
    vi.unstubAllGlobals();
  });

  test('迟到的列表响应不会盖掉后一次范围', async () => {
    mountWorkflowList();
    setListBrowseState({ isAdmin: true, scope: 'all', owner: '' });
    let resolveFirst;
    let resolveSecond;
    const first = new Promise((resolve) => { resolveFirst = resolve; });
    const second = new Promise((resolve) => { resolveSecond = resolve; });
    const queue = [first, second];
    vi.stubGlobal('fetch', vi.fn(() => queue.shift()));

    const older = loadWorkflows();
    const newer = loadWorkflows();
    resolveSecond(workflowPayload('新的', 2));
    await newer;
    resolveFirst(workflowPayload('旧的', 1));
    await older;

    expect(document.body.textContent).toContain('新的');
    expect(document.body.textContent).not.toContain('旧的');
  });

  test('查看指定用户按输入框当前内容查询', async () => {
    mountWorkflowList();
    setListBrowseState({ isAdmin: true, scope: 'all', owner: '小明' });
    document.getElementById('workflowOwnerInput').value = '小红';
    vi.stubGlobal('fetch', vi.fn(async () => workflowPayload('小红的戏', 3)));

    document.querySelector('[data-scope="user"]').click();
    await vi.waitFor(() => {
      expect(document.body.textContent).toContain('小红的戏');
    });

    const url = vi.mocked(fetch).mock.calls.at(-1)[0];
    const params = new URLSearchParams(String(url).split('?')[1]);
    expect(params.get('scope')).toBe('user');
    expect(params.get('owner')).toBe('小红');
  });

  test('指定用户输入为空时不发请求', () => {
    mountWorkflowList();
    setListBrowseState({ isAdmin: true, scope: 'mine', owner: '小明' });
    document.getElementById('workflowOwnerInput').value = '   ';
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);

    document.querySelector('[data-scope="user"]').click();

    expect(fetchMock).not.toHaveBeenCalled();
    expect(document.getElementById('workflowOwnerHint').textContent).toBe('owner_query_required');
    expect(document.getElementById('workflowOwnerHint').hidden).toBe(false);
  });
});
