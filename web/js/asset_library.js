/**
 * asset_library.js — 资产库公共模块（marketing_agent / video_workflow / storyboard 三页共用）。
 *
 * 依赖（页面需先加载）：web/js/escape.js（HTML 转义，XSS 红线：所有用户内容必须转义）、
 * web/css/asset_library.css。
 *
 * 能力：
 *  - AssetLibrary.promptAdd({sourceUrl, name})      加入资产库弹窗（分组/权限设置）
 *  - AssetLibrary.openModal({onPick})               资产库浏览弹窗（分组筛选/搜索/分页；onPick 时为选择器模式）
 *  - AssetLibrary.fetchMentionItems(keyword)         @ 提及数据源（返回 [{id,name,thumb}])
 *  - AssetLibrary.MENTION_PREFIX                     提及 token 前缀 '@资产:'
 *  - AssetLibrary.buildMentionToken(asset)           生成 `@资产:{id}` token
 *  - AssetLibrary.resolveMentionTokens(text)         提交前把 token 解析为 ![名称](绝对URL)
 *  - AssetLibrary.toast(message, isError)            轻提示
 *
 * 后端接口见 api/asset_library.py（/api/asset-library/*）与 docs/backend/asset_library.md。
 */
(function () {
    'use strict';

    var MENTION_PREFIX = '@资产:';
    var TOKEN_RE = /@资产:(\d+)(?![\d])/g;

    // id -> asset 详情缓存（提及解析用；页面级生命周期足够）
    var assetCache = {};

    // ============ 基础工具 ============

    function esc(value) {
        return window.escapeHtml ? window.escapeHtml(value) : String(value == null ? '' : value)
            .replace(/[&<>"']/g, function (c) {
                return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
            });
    }

    function getAuthToken() {
        try { return localStorage.getItem('auth_token') || ''; } catch (e) { return ''; }
    }

    function toast(message, isError) {
        var el = document.createElement('div');
        el.className = 'al-toast' + (isError ? ' al-toast--error' : '');
        el.textContent = message;
        document.body.appendChild(el);
        setTimeout(function () { el.remove(); }, isError ? 3500 : 2200);
    }

    function apiError(result, fallback) {
        if (result && result.detail) return result.detail;
        if (result && result.message) return result.message;
        return fallback || '操作失败，请稍后重试';
    }

    function api(path, options) {
        options = options || {};
        var headers = { 'Authorization': 'Bearer ' + getAuthToken() };
        if (options.body && !(options.body instanceof FormData)) {
            headers['Content-Type'] = 'application/json';
            options.body = JSON.stringify(options.body);
        }
        options.headers = headers;
        return fetch('/api/asset-library' + path, options).then(function (res) {
            return res.json().catch(function () { return {}; }).then(function (data) {
                if (!res.ok) {
                    var err = new Error(apiError(data, 'HTTP ' + res.status));
                    err.status = res.status;
                    err.payload = data;
                    throw err;
                }
                return data;
            });
        });
    }

    function formatSize(bytes) {
        var n = Number(bytes) || 0;
        if (n >= 1024 * 1024 * 1024) return (n / (1024 * 1024 * 1024)).toFixed(2) + ' GB';
        if (n >= 1024 * 1024) return (n / (1024 * 1024)).toFixed(1) + ' MB';
        if (n >= 1024) return (n / 1024).toFixed(0) + ' KB';
        return n + ' B';
    }

    function absoluteUrl(url) {
        if (!url) return '';
        if (/^https?:\/\//i.test(url)) return url;
        if (url.indexOf('data:') === 0) return url;
        return location.origin + (url.charAt(0) === '/' ? url : '/' + url);
    }

    // ============ 弹窗骨架 ============

    function buildModal(className, title, bodyHtml, footerHtml) {
        var overlay = document.createElement('div');
        overlay.className = 'al-overlay';
        overlay.innerHTML =
            '<div class="al-modal ' + (className || '') + '" role="dialog" aria-label="' + esc(title) + '">' +
            '<div class="al-header"><h3 class="al-title">' + esc(title) + '</h3>' +
            '<button type="button" class="al-close" data-al-close title="关闭">×</button></div>' +
            '<div class="al-body">' + bodyHtml + '</div>' +
            (footerHtml ? '<div class="al-footer">' + footerHtml + '</div>' : '') +
            '</div>';
        overlay.addEventListener('click', function (ev) {
            if (ev.target === overlay || ev.target.closest('[data-al-close]')) overlay.remove();
        });
        document.body.appendChild(overlay);
        return overlay;
    }

    // ============ 权限设置组件（加入/编辑共用） ============

    var PERM_OPTIONS = [
        { value: 'private', label: '仅自己' },
        { value: 'specified', label: '指定成员' },
        { value: 'public', label: '所有人' }
    ];

    /**
     * 渲染一套权限设置（radio 式按钮 + 成员选择器）。
     * state: { view: {permission, members:[]}, edit: {...} }
     */
    function renderPermSection(container, kind, state, labels) {
        var section = container.querySelector('[data-al-perm="' + kind + '"]');
        if (!section) return;
        var conf = state[kind];
        var html = '<div class="al-perm-row" role="group">';
        PERM_OPTIONS.forEach(function (opt) {
            html += '<button type="button" class="al-perm-opt' + (conf.permission === opt.value ? ' is-active' : '') +
                '" data-al-perm-opt="' + kind + '" data-value="' + opt.value + '">' + esc(opt.label) + '</button>';
        });
        html += '</div>';
        if (conf.permission === 'specified') {
            html += renderMemberBox(kind, conf.members, labels.hint);
        }
        section.innerHTML = html;
        section.querySelectorAll('[data-al-perm-opt]').forEach(function (btn) {
            btn.addEventListener('click', function () {
                conf.permission = btn.getAttribute('data-value');
                renderPermSection(container, kind, state, labels);
            });
        });
        bindMemberBox(section, kind, conf);
    }

    function renderMemberBox(kind, members, hint) {
        var html = '<div class="al-member-box" data-al-memberbox="' + kind + '">';
        html += '<input type="text" class="al-input al-member-search" placeholder="搜索昵称 / 手机号 / 邮箱添加成员" data-al-member-search>';
        html += '<div class="al-member-candidates" data-al-member-candidates hidden></div>';
        html += '<div class="al-member-tags" data-al-member-tags></div>';
        html += '<div class="al-hint">' + esc(hint) + '</div>';
        html += '</div>';
        return html;
    }

    function renderMemberTags(section, conf) {
        var tagBox = section.querySelector('[data-al-member-tags]');
        if (!tagBox) return;
        if (!conf.members.length) { tagBox.innerHTML = ''; return; }
        var html = '';
        conf.members.forEach(function (m) {
            html += '<span class="al-member-tag">' + esc(m.name) +
                '<button type="button" data-al-member-remove="' + esc(String(m.user_id)) + '" title="移除">×</button></span>';
        });
        tagBox.innerHTML = html;
        tagBox.querySelectorAll('[data-al-member-remove]').forEach(function (btn) {
            btn.addEventListener('click', function () {
                var uid = Number(btn.getAttribute('data-al-member-remove'));
                conf.members = conf.members.filter(function (m) { return m.user_id !== uid; });
                renderMemberTags(section, conf);
            });
        });
    }

    var memberSearchTimer = null;

    function bindMemberBox(section, kind, conf) {
        var box = section.querySelector('[data-al-memberbox="' + kind + '"]');
        if (!box) return;
        renderMemberTags(section, conf);
        var input = box.querySelector('[data-al-member-search]');
        var candidates = box.querySelector('[data-al-member-candidates]');
        if (!input || !candidates) return;
        input.addEventListener('input', function () {
            if (memberSearchTimer) clearTimeout(memberSearchTimer);
            var kw = input.value.trim();
            if (!kw) { candidates.hidden = true; candidates.innerHTML = ''; return; }
            memberSearchTimer = setTimeout(function () {
                api('/users?keyword=' + encodeURIComponent(kw)).then(function (res) {
                    var items = (res.data && res.data.items) || [];
                    var existing = conf.members.map(function (m) { return m.user_id; });
                    items = items.filter(function (u) { return existing.indexOf(u.user_id) < 0; });
                    if (!items.length) {
                        candidates.hidden = true;
                        candidates.innerHTML = '';
                        return;
                    }
                    var html = '';
                    items.forEach(function (u) {
                        html += '<button type="button" class="al-member-candidate" data-uid="' + esc(String(u.user_id)) +
                            '" data-uname="' + esc(u.display_name) + '">' + esc(u.display_name) +
                            ' <span class="al-hint">#' + esc(String(u.user_id)) + '</span></button>';
                    });
                    candidates.innerHTML = html;
                    candidates.hidden = false;
                    candidates.querySelectorAll('[data-uid]').forEach(function (btn) {
                        btn.addEventListener('click', function () {
                            conf.members.push({
                                user_id: Number(btn.getAttribute('data-uid')),
                                name: btn.getAttribute('data-uname')
                            });
                            input.value = '';
                            candidates.hidden = true;
                            candidates.innerHTML = '';
                            renderMemberTags(section, conf);
                        });
                    });
                }).catch(function () {
                    candidates.hidden = true;
                    candidates.innerHTML = '';
                });
            }, 250);
        });
    }

    // ============ 加入资产库弹窗 ============

    /**
     * 打开「加入资产库」弹窗。
     * @param opts {sourceUrl, name?, assetType?, onAdded?}
     */
    function promptAdd(opts) {
        opts = opts || {};
        var sourceUrl = opts.sourceUrl || '';
        if (!sourceUrl) { toast('缺少源文件地址', true); return; }
        var state = {
            view: { permission: 'private', members: [] },
            edit: { permission: 'private', members: [] }
        };
        var body =
            '<div class="al-add-preview"><img src="' + esc(absoluteUrl(sourceUrl)) + '" alt="预览" onerror="this.style.display=\'none\'"></div>' +
            '<div class="al-field"><label class="al-label">资产名称</label>' +
            '<input type="text" class="al-input" data-al-name maxlength="200" value="' + esc(opts.name || '') + '" placeholder="给资产起个名字"></div>' +
            '<div class="al-field"><label class="al-label">分组（共享目录，所有人可见）</label><div class="al-perm-row" data-al-group-row></div></div>' +
            '<div class="al-field" data-al-perm="view"><label class="al-label">谁可以看</label></div>' +
            '<div class="al-field" data-al-perm="edit"><label class="al-label">谁可以编辑</label></div>' +
            '<div class="al-error" data-al-error></div>';
        var footer =
            '<button type="button" class="al-btn" data-al-close>取消</button>' +
            '<button type="button" class="al-btn al-btn--primary" data-al-submit>加入资产库</button>';
        var overlay = buildModal('al-modal--compact', '加入资产库', body, footer);

        // 分组下拉（异步填充）
        var groupRow = overlay.querySelector('[data-al-group-row]');
        var groups = [];
        api('/groups').then(function (res) {
            groups = (res.data && res.data.groups) || [];
            var html = '<select class="al-select" data-al-group style="max-width:100%">' +
                '<option value="">未分组</option>';
            groups.forEach(function (g) {
                html += '<option value="' + esc(String(g.id)) + '">' + esc(g.name) + '</option>';
            });
            html += '</select>';
            groupRow.innerHTML = html;
        }).catch(function () {
            groupRow.innerHTML = '<span class="al-hint">分组加载失败，将保存为未分组</span>';
        });

        renderPermSection(overlay, 'view', state, { hint: '被指定的成员可以查看该资产' });
        renderPermSection(overlay, 'edit', state, { hint: '被指定的成员可以编辑该资产的名称/分组/权限' });

        var submitBtn = overlay.querySelector('[data-al-submit]');
        var errBox = overlay.querySelector('[data-al-error]');
        submitBtn.addEventListener('click', function () {
            var name = (overlay.querySelector('[data-al-name]').value || '').trim() || '未命名资产';
            var groupSel = overlay.querySelector('[data-al-group]');
            var groupId = groupSel && groupSel.value ? Number(groupSel.value) : null;
            submitBtn.disabled = true;
            submitBtn.textContent = '加入中…';
            errBox.textContent = '';
            api('/assets', {
                method: 'POST',
                body: {
                    source_url: sourceUrl,
                    name: name,
                    group_id: groupId,
                    asset_type: opts.assetType || 'image',
                    view_permission: state.view.permission,
                    edit_permission: state.edit.permission,
                    view_members: state.view.members.map(function (m) { return m.user_id; }),
                    edit_members: state.edit.members.map(function (m) { return m.user_id; })
                }
            }).then(function (res) {
                overlay.remove();
                toast('已加入资产库');
                if (res.data) assetCache[res.data.id] = res.data;
                if (typeof opts.onAdded === 'function') opts.onAdded(res.data);
            }).catch(function (e) {
                submitBtn.disabled = false;
                submitBtn.textContent = '加入资产库';
                errBox.textContent = e.message || '加入失败';
            });
        });
    }

    // ============ 编辑资产弹窗 ============

    function promptEdit(asset, onChanged) {
        var state = {
            view: { permission: asset.view_permission, members: [] },
            edit: { permission: asset.edit_permission, members: [] }
        };
        // 已保存成员展示名以「用户{id}」兜底（搜索接口不支持批量 id 反查）
        function fillMembers(kind) {
            (asset[kind + '_members'] || []).forEach(function (uid) {
                state[kind].members.push({ user_id: uid, name: '用户' + uid });
            });
        }

        var body =
            '<div class="al-field"><label class="al-label">资产名称</label>' +
            '<input type="text" class="al-input" data-al-name maxlength="200" value="' + esc(asset.name || '') + '"></div>' +
            '<div class="al-field"><label class="al-label">分组</label><div class="al-perm-row" data-al-group-row></div></div>' +
            '<div class="al-field" data-al-perm="view"><label class="al-label">谁可以看</label></div>' +
            '<div class="al-field" data-al-perm="edit"><label class="al-label">谁可以编辑</label></div>' +
            '<div class="al-error" data-al-error></div>';
        var footer =
            '<button type="button" class="al-btn" data-al-close>取消</button>' +
            '<button type="button" class="al-btn al-btn--primary" data-al-submit>保存</button>';
        var overlay = buildModal('al-modal--compact', '编辑资产', body, footer);

        api('/groups').then(function (res) {
            var groups = (res.data && res.data.groups) || [];
            var html = '<select class="al-select" data-al-group>' + '<option value="">未分组</option>';
            groups.forEach(function (g) {
                html += '<option value="' + esc(String(g.id)) + '"' + (g.id === asset.group_id ? ' selected' : '') + '>' + esc(g.name) + '</option>';
            });
            html += '</select>';
            overlay.querySelector('[data-al-group-row]').innerHTML = html;
        }).catch(function () {
            overlay.querySelector('[data-al-group-row]').innerHTML = '<span class="al-hint">分组加载失败</span>';
        });

        // 成员名兜底：借助搜索接口不可批量，直接用「用户{id}」占位
        fillMembers('view');
        fillMembers('edit');
        renderPermSection(overlay, 'view', state, { hint: '被指定的成员可以查看该资产' });
        renderPermSection(overlay, 'edit', state, { hint: '被指定的成员可以编辑该资产的名称/分组/权限' });

        overlay.querySelector('[data-al-submit]').addEventListener('click', function () {
            var btn = overlay.querySelector('[data-al-submit]');
            var errBox = overlay.querySelector('[data-al-error]');
            var groupSel = overlay.querySelector('[data-al-group]');
            var payload = {
                name: overlay.querySelector('[data-al-name]').value.trim(),
                group_id: groupSel && groupSel.value ? Number(groupSel.value) : null,
                view_permission: state.view.permission,
                edit_permission: state.edit.permission,
                view_members: state.view.members.map(function (m) { return m.user_id; }),
                edit_members: state.edit.members.map(function (m) { return m.user_id; })
            };
            btn.disabled = true;
            errBox.textContent = '';
            api('/assets/' + asset.id, { method: 'PUT', body: payload }).then(function () {
                overlay.remove();
                toast('已保存');
                if (typeof onChanged === 'function') onChanged();
            }).catch(function (e) {
                btn.disabled = false;
                errBox.textContent = e.message || '保存失败';
            });
        });
    }

    // ============ 浏览弹窗 ============

    /**
     * 打开资产库浏览弹窗。
     * @param opts {mode?: 'browse', onPick?(asset), ownerUserId?}
     *  onPick 提供时卡片显示「引用」按钮，点击后回调并关窗。
     */
    function openModal(opts) {
        opts = opts || {};
        var view = {
            groupId: null,          // null=全部; 'ungrouped'=未分组; number=分组
            scope: 'all',
            keyword: '',
            page: 1,
            pageSize: 24,
            total: 0,
            groups: []
        };

        var body =
            '<div class="al-browse">' +
            '<aside class="al-browse-side" data-al-side></aside>' +
            '<div class="al-browse-main">' +
            '<div class="al-toolbar">' +
            '<div class="al-scope-tabs">' +
            '<button type="button" class="al-scope-tab is-active" data-scope="all">全部</button>' +
            '<button type="button" class="al-scope-tab" data-scope="mine">我的</button>' +
            '<button type="button" class="al-scope-tab" data-scope="shared">共享给我</button>' +
            '</div>' +
            '<input type="text" class="al-input" placeholder="搜索资产名称" data-al-keyword>' +
            '<span class="al-quota" data-al-quota></span>' +
            '</div>' +
            '<div class="al-grid-wrap"><div class="al-grid" data-al-grid></div></div>' +
            '<div class="al-pager" data-al-pager></div>' +
            '</div></div>';
        var overlay = buildModal('al-modal--wide', opts.title || '资产库', body, '');

        var els = {
            side: overlay.querySelector('[data-al-side]'),
            grid: overlay.querySelector('[data-al-grid]'),
            pager: overlay.querySelector('[data-al-pager]'),
            quota: overlay.querySelector('[data-al-quota]'),
            keyword: overlay.querySelector('[data-al-keyword]')
        };

        // ---- 数据加载 ----
        function loadGroups() {
            api('/groups').then(function (res) {
                view.groups = (res.data && res.data.groups) || [];
                view.ungroupedCount = (res.data && res.data.ungrouped_count) || 0;
                renderSide();
            }).catch(function () { renderSide(); });
            api('/quota').then(function (res) {
                var q = res.data || {};
                els.quota.textContent = q.quota_bytes
                    ? '容量：' + formatSize(q.used_bytes) + ' / ' + formatSize(q.quota_bytes)
                    : '容量：' + formatSize(q.used_bytes) + '（不限）';
            }).catch(function () { els.quota.textContent = ''; });
        }

        function renderSide() {
            var html = '<button type="button" class="al-group-item' + (view.groupId === null ? ' is-active' : '') +
                '" data-al-g="">全部资产</button>';
            html += '<button type="button" class="al-group-item' + (view.groupId === 'ungrouped' ? ' is-active' : '') +
                '" data-al-g="ungrouped">未分组<span class="al-group-count">' + esc(String(view.ungroupedCount || 0)) + '</span></button>';
            view.groups.forEach(function (g) {
                html += '<button type="button" class="al-group-item' + (view.groupId === g.id ? ' is-active' : '') +
                    '" data-al-g="' + esc(String(g.id)) + '"><span class="al-group-name" style="overflow:hidden;text-overflow:ellipsis">' +
                    esc(g.name) + '</span><span class="al-group-count">' + esc(String(g.asset_count || 0)) + '</span>';
                if (g.can_manage) {
                    html += '<span class="al-group-ops">' +
                        '<button type="button" data-al-g-rename="' + esc(String(g.id)) + '" title="重命名">✎</button>' +
                        '<button type="button" data-al-g-del="' + esc(String(g.id)) + '" title="删除">🗑</button></span>';
                }
                html += '</button>';
            });
            html += '<button type="button" class="al-new-group" data-al-new-group>＋ 新建分组</button>';
            els.side.innerHTML = html;

            els.side.querySelectorAll('[data-al-g]').forEach(function (btn) {
                btn.addEventListener('click', function (ev) {
                    if (ev.target.closest('[data-al-g-rename]') || ev.target.closest('[data-al-g-del]')) return;
                    var raw = btn.getAttribute('data-al-g');
                    view.groupId = raw === '' ? null : (raw === 'ungrouped' ? 'ungrouped' : Number(raw));
                    view.page = 1;
                    renderSide();
                    loadAssets();
                });
            });
            els.side.querySelectorAll('[data-al-g-rename]').forEach(function (btn) {
                btn.addEventListener('click', function (ev) {
                    ev.stopPropagation();
                    var gid = Number(btn.getAttribute('data-al-g-rename'));
                    var g = view.groups.filter(function (x) { return x.id === gid; })[0];
                    var name = prompt('新的分组名称', g ? g.name : '');
                    if (!name || !name.trim()) return;
                    api('/groups/' + gid, { method: 'PUT', body: { name: name.trim() } })
                        .then(function () { loadGroups(); })
                        .catch(function (e) { toast(e.message || '重命名失败', true); });
                });
            });
            els.side.querySelectorAll('[data-al-g-del]').forEach(function (btn) {
                btn.addEventListener('click', function (ev) {
                    ev.stopPropagation();
                    var gid = Number(btn.getAttribute('data-al-g-del'));
                    if (!confirm('确认删除该分组？（组内仍有资产时无法删除）')) return;
                    api('/groups/' + gid, { method: 'DELETE' })
                        .then(function () {
                            if (view.groupId === gid) { view.groupId = null; loadAssets(); }
                            loadGroups();
                        })
                        .catch(function (e) { toast(e.message || '删除失败', true); });
                });
            });
            var newBtn = els.side.querySelector('[data-al-new-group]');
            if (newBtn) newBtn.addEventListener('click', function () {
                var name = prompt('分组名称（全局共享，所有人可见）');
                if (!name || !name.trim()) return;
                api('/groups', { method: 'POST', body: { name: name.trim() } })
                    .then(function () { loadGroups(); })
                    .catch(function (e) { toast(e.message || '创建失败', true); });
            });
        }

        function loadAssets() {
            els.grid.innerHTML = '<div class="al-empty">加载中…</div>';
            var params = '?page=' + view.page + '&page_size=' + view.pageSize +
                '&scope=' + view.scope + '&asset_type=image';
            if (view.groupId === 'ungrouped') params += '&group_scope=ungrouped';
            else if (view.groupId !== null) params += '&group_id=' + view.groupId;
            if (view.keyword) params += '&keyword=' + encodeURIComponent(view.keyword);
            api('/assets' + params).then(function (res) {
                var data = res.data || {};
                view.total = data.total || 0;
                var items = data.items || [];
                renderGrid(items);
                renderPager();
            }).catch(function (e) {
                els.grid.innerHTML = '<div class="al-empty">' + esc(e.message || '加载失败') + '</div>';
            });
        }

        function renderGrid(items) {
            if (!items.length) {
                els.grid.innerHTML = '<div class="al-empty">暂无资产：在各页面生成图片后点击「加入资产库」</div>';
                return;
            }
            var html = '';
            items.forEach(function (a) {
                html += '<div class="al-card" data-al-asset="' + esc(String(a.id)) + '">' +
                    '<div class="al-card-thumb" data-al-thumb="' + esc(String(a.id)) + '" data-al-url="' + esc(absoluteUrl(a.file_url)) + '">' +
                    '<img src="' + esc(absoluteUrl(a.file_url)) + '" alt="' + esc(a.name) + '" loading="lazy">' +
                    (a.user_id !== currentUserId() ? '<span class="al-card-badge">' + esc(a.owner_name || '') + '</span>' : '') +
                    '</div>' +
                    '<div class="al-card-info"><div class="al-card-name" title="' + esc(a.name) + '">' + esc(a.name) + '</div>' +
                    '<div class="al-card-meta">' + formatSize(a.file_size) + '</div></div>' +
                    '<div class="al-card-actions">' +
                    (typeof opts.onPick === 'function'
                        ? '<button type="button" class="al-btn al-btn--small al-btn--primary" data-al-pick="' + esc(String(a.id)) + '">引用</button>'
                        : '') +
                    (a.can_edit
                        ? '<button type="button" class="al-btn al-btn--small" data-al-edit="' + esc(String(a.id)) + '">编辑</button>'
                        : '') +
                    '</div></div>';
                assetCache[a.id] = a;
            });
            els.grid.innerHTML = html;

            els.grid.querySelectorAll('[data-al-thumb]').forEach(function (el) {
                el.addEventListener('click', function () {
                    window.open(el.getAttribute('data-al-url'), '_blank');
                });
            });
            els.grid.querySelectorAll('[data-al-pick]').forEach(function (btn) {
                btn.addEventListener('click', function () {
                    var id = Number(btn.getAttribute('data-al-pick'));
                    var asset = assetCache[id];
                    overlay.remove();
                    if (asset && typeof opts.onPick === 'function') opts.onPick(asset);
                });
            });
            els.grid.querySelectorAll('[data-al-edit]').forEach(function (btn) {
                btn.addEventListener('click', function () {
                    var id = Number(btn.getAttribute('data-al-edit'));
                    promptEdit(assetCache[id], function () { loadAssets(); loadGroups(); });
                });
            });
        }

        function renderPager() {
            var pages = Math.max(1, Math.ceil(view.total / view.pageSize));
            if (pages <= 1) { els.pager.innerHTML = '共 ' + view.total + ' 项'; return; }
            els.pager.innerHTML =
                '<button type="button" class="al-btn al-btn--small" data-al-prev' + (view.page <= 1 ? ' disabled' : '') + '>上一页</button>' +
                '<span>' + view.page + ' / ' + pages + '（共 ' + view.total + ' 项）</span>' +
                '<button type="button" class="al-btn al-btn--small" data-al-next' + (view.page >= pages ? ' disabled' : '') + '>下一页</button>';
            var prev = els.pager.querySelector('[data-al-prev]');
            var next = els.pager.querySelector('[data-al-next]');
            if (prev && view.page > 1) prev.addEventListener('click', function () { view.page--; loadAssets(); });
            if (next && view.page < pages) next.addEventListener('click', function () { view.page++; loadAssets(); });
        }

        // ---- 工具条事件 ----
        overlay.querySelectorAll('[data-scope]').forEach(function (btn) {
            btn.addEventListener('click', function () {
                overlay.querySelectorAll('[data-scope]').forEach(function (b) { b.classList.remove('is-active'); });
                btn.classList.add('is-active');
                view.scope = btn.getAttribute('data-scope');
                view.page = 1;
                loadAssets();
            });
        });
        var kwTimer = null;
        els.keyword.addEventListener('input', function () {
            if (kwTimer) clearTimeout(kwTimer);
            kwTimer = setTimeout(function () {
                view.keyword = els.keyword.value.trim();
                view.page = 1;
                loadAssets();
            }, 300);
        });

        loadGroups();
        loadAssets();
        return overlay;
    }

    function currentUserId() {
        var uid = null;
        try { uid = Number(localStorage.getItem('user_id')); } catch (e) { uid = null; }
        return uid;
    }

    // ============ @ 提及 ============

    /**
     * @ 提及数据源：返回 [{id, name, thumb}]（Promise）。
     * 各页提及菜单调用，选择后用 buildMentionToken 生成插入文本。
     */
    function fetchMentionItems(keyword) {
        var params = '?page=1&page_size=50&scope=all&asset_type=image';
        if (keyword) params += '&keyword=' + encodeURIComponent(keyword);
        return api('/assets' + params).then(function (res) {
            var items = (res.data && res.data.items) || [];
            items.forEach(function (a) { assetCache[a.id] = a; });
            return items.map(function (a) {
                return { id: a.id, name: a.name, thumb: absoluteUrl(a.file_url), url: absoluteUrl(a.file_url) };
            });
        }).catch(function () { return []; });
    }

    function buildMentionToken(asset) {
        return MENTION_PREFIX + asset.id;
    }

    /**
     * 提交前解析文本中的 `@资产:{id}` token：
     * 已缓存的资产直接替换为 ![名称](绝对URL)；未缓存的拉取详情后替换；
     * 拉取失败的 token 保留原文（不阻断提交）。
     */
    function resolveMentionTokens(text) {
        if (!text || text.indexOf(MENTION_PREFIX) < 0) return Promise.resolve(text);
        var ids = [];
        var m;
        TOKEN_RE.lastIndex = 0;
        while ((m = TOKEN_RE.exec(text)) !== null) {
            var id = Number(m[1]);
            if (ids.indexOf(id) < 0) ids.push(id);
        }
        if (!ids.length) return Promise.resolve(text);

        var missing = ids.filter(function (id) { return !assetCache[id]; });
        var ready = missing.length
            ? Promise.all(missing.map(function (id) {
                return api('/assets/' + id).then(function (res) {
                    if (res.data) assetCache[id] = res.data;
                }).catch(function () { /* 无权访问或已清除：保留原文 */ });
            }))
            : Promise.resolve();

        return ready.then(function () {
            return text.replace(new RegExp(MENTION_PREFIX + '(\\d+)(?![\\d])', 'g'), function (all, idStr) {
                var asset = assetCache[Number(idStr)];
                if (!asset || !asset.file_url) return all;
                return '![' + String(asset.name || '资产').replace(/[\[\]]/g, '') + '](' + absoluteUrl(asset.file_url) + ')';
            });
        });
    }

    // ============ 导出 ============

    window.AssetLibrary = {
        MENTION_PREFIX: MENTION_PREFIX,
        TOKEN_RE_SOURCE: '@资产:(\\d+)',
        api: api,
        toast: toast,
        promptAdd: promptAdd,
        promptEdit: promptEdit,
        openModal: openModal,
        fetchMentionItems: fetchMentionItems,
        buildMentionToken: buildMentionToken,
        resolveMentionTokens: resolveMentionTokens,
        absoluteUrl: absoluteUrl
    };
})();
