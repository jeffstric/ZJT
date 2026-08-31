/**
 * 剧本创作页「已入库」资产库。
 * 依赖 script_writer.js 中的全局变量/函数（USER_ID, WORLD_ID, AUTH_TOKEN, loadFiles 等）。
 */
(function () {
    var SOURCE_STAGING = 'staging';
    var SOURCE_DATABASE = 'database';
    var assetSource = SOURCE_STAGING;
    var libraryKeyword = '';
    var librarySearchTimer = null;
    var pendingDelete = null;
    var libraryCache = {};
    var TYPE_LABELS = {
        worlds: '世界',
        characters: '角色',
        scripts: '剧本',
        locations: '场景',
        props: '道具'
    };

    function t(key, fallback, params) {
        if (window.t) {
            var out = params ? window.t(key, params) : window.t(key);
            if (out && out !== key) return out;
        }
        return fallback;
    }

    function authHeaders() {
        return {
            'Authorization': AUTH_TOKEN || '',
            'X-User-Id': String(USER_ID || '')
        };
    }

    function formatCreatorTag(userId) {
        var s = userId == null ? '' : String(userId);
        if (!s) return '';
        return '·' + (s.length <= 4 ? s : s.slice(-4));
    }

    function isOwnAsset(userId) {
        return String(userId) === String(USER_ID);
    }

    function currentType() {
        return typeof currentFileType === 'string' ? currentFileType : 'worlds';
    }

    function applySourceChrome() {
        var sidebar = document.getElementById('file-sidebar');
        var title = document.getElementById('file-sidebar-title');
        var searchBox = document.getElementById('library-search-box');
        var isLib = assetSource === SOURCE_DATABASE;
        if (sidebar) sidebar.classList.toggle('is-library', isLib);
        if (title) {
            title.textContent = isLib
                ? t('library_management', '世界资产')
                : t('file_management', '📁 暂存文件管理');
        }
        document.querySelectorAll('.asset-source-btn').forEach(function (btn) {
            btn.classList.toggle('active', btn.getAttribute('data-source') === assetSource);
        });
        if (searchBox) {
            if (isLib) searchBox.removeAttribute('hidden');
            else searchBox.setAttribute('hidden', '');
        }
        var addBtn = document.getElementById('add-file-btn');
        if (addBtn && isLib) addBtn.style.display = 'none';
        if (typeof updateStyleRecognizeVisibility === 'function') {
            updateStyleRecognizeVisibility(currentType());
        }
    }

    function setLibraryCount(n) {
        var el = document.getElementById('library-count');
        if (!el) return;
        el.textContent = n == null ? '' : String(n);
    }

    async function apiJson(url, options) {
        var opts = options || {};
        var headers = Object.assign({}, authHeaders(), opts.headers || {});
        var resp = await fetch(url, Object.assign({}, opts, { headers: headers }));
        var data = {};
        try {
            data = await resp.json();
        } catch (e) {
            data = {};
        }
        if (typeof checkTokenExpired === 'function' && checkTokenExpired(data, resp)) {
            throw new Error('token_expired');
        }
        return { resp: resp, data: data };
    }

    function listPageSize(fileType) {
        // /api/scripts 历史校验 le=100；角色/场景/道具允许到 1000
        return fileType === 'scripts' ? 100 : 1000;
    }

    function listUrl(fileType, keyword, page, pageSize) {
        var q = new URLSearchParams({
            world_id: String(WORLD_ID || ''),
            page: String(page || 1),
            page_size: String(pageSize || listPageSize(fileType))
        });
        if (keyword) q.set('keyword', keyword);
        if (fileType === 'scripts') {
            q.set('order_by', 'episode_number');
            q.set('order_direction', 'ASC');
            return '/api/scripts?' + q.toString();
        }
        if (fileType === 'characters') return '/api/characters?' + q.toString();
        if (fileType === 'locations') return '/api/locations?' + q.toString();
        if (fileType === 'props') return '/api/props?' + q.toString();
        return null;
    }

    function extractListRows(body) {
        if (!body) return [];
        if (Array.isArray(body)) return body;
        var payload = body.data;
        if (Array.isArray(payload)) return payload;
        if (payload && Array.isArray(payload.data)) return payload.data;
        return [];
    }

    function listErrorMessage(listed) {
        var body = listed && listed.data ? listed.data : {};
        if (listed && listed.resp && !listed.resp.ok) {
            if (Array.isArray(body.detail) && body.detail.length) {
                return body.detail[0].msg || ('HTTP ' + listed.resp.status);
            }
            return body.message || body.detail || ('HTTP ' + listed.resp.status);
        }
        if (body && body.code != null && body.code !== 0) {
            return body.message || t('error_load_failed', '加载失败');
        }
        return null;
    }

    async function fetchAllLibraryRows(fileType, keyword) {
        var pageSize = listPageSize(fileType);
        var page = 1;
        var all = [];
        var total = null;
        while (page <= 50) {
            var url = listUrl(fileType, keyword, page, pageSize);
            var listed = await apiJson(url);
            var err = listErrorMessage(listed);
            if (err) throw new Error(err);
            var payload = listed.data && listed.data.data;
            var rows = extractListRows(listed.data);
            if (payload && typeof payload.total === 'number') total = payload.total;
            all = all.concat(rows);
            if (total != null && all.length >= total) break;
            if (rows.length < pageSize) break;
            page += 1;
        }
        return all;
    }

    function displayName(fileType, item) {
        if (fileType === 'scripts') {
            var ep = item.episode_number;
            var title = item.title || '';
            return ep != null ? ('第' + ep + '集：' + title) : (title || ('剧本 #' + item.id));
        }
        return item.name || ('#' + item.id);
    }

    function escapeHtmlLocal(s) {
        if (typeof escapeHtml === 'function') return escapeHtml(s);
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function escapeAttr(s) {
        if (typeof escapeHtmlAttr === 'function') return escapeHtmlAttr(s);
        return escapeHtmlLocal(s);
    }

    function renderLibraryItems(fileType, items) {
        var container = document.getElementById('file-items-container');
        if (!container) return;
        if (!items || !items.length) {
            container.innerHTML = '<div class="file-empty">' + t('library_empty', '暂无已入库资产') + '</div>';
            setLibraryCount(0);
            return;
        }
        setLibraryCount(items.length);
        container.innerHTML = '';
        items.forEach(function (item) {
            var own = isOwnAsset(item.user_id);
            var creator = formatCreatorTag(item.user_id);
            var name = displayName(fileType, item);
            var canMutate = own && fileType !== 'worlds';
            var thumb = item.reference_image || '';
            var imageHtml = '';
            if (['characters', 'locations', 'props'].indexOf(fileType) >= 0) {
                var hasImg = thumb && String(thumb).trim();
                imageHtml =
                    '<button class="file-btn image-preview-btn ' + (hasImg ? 'has-image' : 'no-image') + '"' +
                    ' data-action="library-preview" data-id="' + escapeAttr(item.id) + '" title="' +
                    (hasImg ? t('title_preview_image', '预览图片') : t('title_no_image', '暂无参考图')) + '">' +
                    '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">' +
                    '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/>' +
                    '<polyline points="21 15 16 10 5 21"/></svg></button>';
            }
            var storyboardHtml = '';
            if (fileType === 'scripts') {
                storyboardHtml =
                    '<button class="file-btn storyboard-btn" data-action="open-storyboard"' +
                    ' data-script-id="' + escapeAttr(item.id) + '"' +
                    ' data-episode-number="' + escapeAttr(item.episode_number || '') + '"' +
                    ' title="' + t('title_open_storyboard', '打开故事板') + '">' +
                    '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">' +
                    '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M8 4v16M3 9h18M3 15h18"/></svg></button>';
            }
            var deleteTitle = canMutate
                ? t('title_delete', '删除')
                : t('library_delete_owner_only', '由用户 ' + creator + ' 创建，仅创建者可删除');
            var editTitle = canMutate || (fileType === 'worlds' && own)
                ? t('title_edit', '编辑')
                : t('library_edit_owner_only', '由用户 ' + creator + ' 创建，仅创建者可编辑');
            var canEdit = fileType === 'worlds' ? own : canMutate;
            var itemEl = document.createElement('div');
            itemEl.className = 'file-item';
            itemEl.innerHTML =
                '<div class="file-item-meta">' +
                    '<div class="file-name">' + escapeHtmlLocal(name) + '</div>' +
                    '<div class="file-item-sub">#' + escapeHtmlLocal(item.id) +
                    (creator ? ' ' + escapeHtmlLocal(creator) : '') + '</div>' +
                '</div>' +
                '<div class="file-actions">' +
                    imageHtml + storyboardHtml +
                    (fileType === 'worlds' ? '' :
                        '<button class="file-btn delete-btn' + (canMutate ? '' : ' is-disabled') + '"' +
                        (canMutate ? ' data-action="library-delete"' : ' disabled') +
                        ' data-id="' + escapeAttr(item.id) + '" title="' + escapeAttr(deleteTitle) + '">' +
                        '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">' +
                        '<polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>' +
                        '<line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/></svg></button>') +
                    '<button class="file-btn view-btn" data-action="library-view" data-id="' + escapeAttr(item.id) +
                    '" title="' + t('title_view', '查看') + '">' +
                    '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">' +
                    '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg></button>' +
                    '<button class="file-btn edit-btn' + (canEdit ? '' : ' is-disabled') + '"' +
                    (canEdit ? ' data-action="library-edit"' : ' disabled') +
                    ' data-id="' + escapeAttr(item.id) + '" title="' + escapeAttr(editTitle) + '">' +
                    '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">' +
                    '<path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>' +
                    '<path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg></button>' +
                '</div>';
            container.appendChild(itemEl);
        });
        if (!container._libraryDelegationBound) {
            container._libraryDelegationBound = true;
            container.addEventListener('click', onLibraryClick);
        }
    }

    function onLibraryClick(e) {
        if (assetSource !== SOURCE_DATABASE) return;
        var btn = e.target.closest('[data-action]');
        if (!btn || btn.disabled) return;
        var action = btn.dataset.action;
        var id = btn.dataset.id;
        if (action === 'library-view') viewLibraryItem(currentType(), id);
        else if (action === 'library-edit') editLibraryItem(currentType(), id);
        else if (action === 'library-delete') openLibraryDeleteModal(currentType(), id);
        else if (action === 'library-preview') previewLibraryImage(currentType(), id);
        else if (action === 'open-storyboard' && typeof openStoryboardFromScript === 'function') {
            openStoryboardFromScript(btn.dataset.scriptId, btn.dataset.episodeNumber);
        }
    }

    function detailUrl(fileType, id) {
        if (fileType === 'worlds') return '/api/worlds/' + id;
        if (fileType === 'characters') return '/api/characters/' + id;
        if (fileType === 'scripts') return '/api/scripts/' + id;
        if (fileType === 'locations') return '/api/locations/' + id;
        if (fileType === 'props') return '/api/props/' + id;
        return null;
    }

    function rememberLibraryRows(fileType, rows) {
        libraryCache[fileType] = rows || [];
    }

    function cachedRecord(fileType, id) {
        var sid = String(id);
        var rows = libraryCache[fileType] || [];
        for (var i = 0; i < rows.length; i++) {
            if (String(rows[i].id) === sid) return rows[i];
        }
        return null;
    }

    async function fetchWorldFromList(id) {
        var sid = String(id || WORLD_ID || '');
        if (typeof cachedWorlds !== 'undefined' && cachedWorlds && cachedWorlds.length) {
            for (var i = 0; i < cachedWorlds.length; i++) {
                if (String(cachedWorlds[i].id) === sid) return cachedWorlds[i];
            }
        }
        var wr = await apiJson('/api/worlds?page=1&page_size=100');
        var err = listErrorMessage(wr);
        if (err) throw new Error(err);
        var worlds = extractListRows(wr.data);
        for (var j = 0; j < worlds.length; j++) {
            if (String(worlds[j].id) === sid) return worlds[j];
        }
        return null;
    }

    function toViewerData(fileType, rec) {
        if (fileType === 'props') {
            return {
                name: rec.name,
                type: rec.other_info || '',
                description: rec.content || '',
                reference_image: rec.reference_image
            };
        }
        if (fileType === 'locations') {
            return {
                name: rec.name,
                parent_name: rec.parent_name || '',
                parent_id: rec.parent_id,
                description: rec.description,
                reference_image: rec.reference_image,
                reference_images: rec.reference_images
            };
        }
        return rec;
    }

    async function fetchDetail(fileType, id) {
        var cached = cachedRecord(fileType, id);
        if (fileType === 'worlds') {
            if (cached) return cached;
            var world = await fetchWorldFromList(id);
            if (world) return world;
            throw new Error(t('error_world_not_found', '世界不存在或无权访问'));
        }
        if (cached) return cached;
        var url = detailUrl(fileType, id);
        if (url) {
            var result = await apiJson(url);
            if (result.resp && result.resp.ok && result.data && result.data.code === 0 && result.data.data) {
                return result.data.data;
            }
        }
        var rows = await fetchAllLibraryRows(fileType, '');
        rememberLibraryRows(fileType, rows);
        cached = cachedRecord(fileType, id);
        if (cached) return cached;
        throw new Error(t('error_unknown', '记录不存在'));
    }

    async function loadLibraryFiles(fileType) {
        var container = document.getElementById('file-items-container');
        if (!container) return;
        if (!WORLD_ID) {
            container.innerHTML = '<div class="file-empty">' + t('error_select_world_first', '请先选择世界') + '</div>';
            setLibraryCount(0);
            return;
        }
        container.innerHTML = '<div class="file-empty">' + t('loading', '加载中...') + '</div>';
        try {
            if (fileType === 'worlds') {
                var world = await fetchWorldFromList(WORLD_ID);
                var worldRows = world ? [world] : [];
                rememberLibraryRows('worlds', worldRows);
                renderLibraryItems('worlds', worldRows);
                return;
            }
            var rows = await fetchAllLibraryRows(fileType, libraryKeyword);
            rememberLibraryRows(fileType, rows);
            renderLibraryItems(fileType, rows);
        } catch (err) {
            if (err && err.message === 'token_expired') return;
            container.innerHTML = '<div class="file-empty">' + t('error_load_failed', '加载失败') + '</div>';
            setLibraryCount(0);
        }
    }

    async function viewLibraryItem(fileType, id) {
        try {
            var rec = await fetchDetail(fileType, id);
            document.querySelectorAll('.view-form').forEach(function (form) { form.style.display = 'none'; });
            var data = toViewerData(fileType, rec);
            var name = displayName(fileType, rec);
            if (fileType === 'worlds' && typeof showWorldViewer === 'function') showWorldViewer(name, rec);
            else if (fileType === 'characters' && typeof showCharacterViewer === 'function') showCharacterViewer(name, rec);
            else if (fileType === 'locations' && typeof showLocationViewer === 'function') showLocationViewer(name, data);
            else if (fileType === 'props' && typeof showPropViewer === 'function') showPropViewer(name, data);
            else if (fileType === 'scripts' && typeof showScriptViewer === 'function') showScriptViewer(name, rec);
            document.getElementById('view-modal').classList.add('show');
        } catch (err) {
            if (typeof showError === 'function') showError(t('error_view_file_failed', { error: err.message }) || ('查看失败: ' + err.message));
        }
    }

    async function editLibraryItem(fileType, id) {
        try {
            var rec = await fetchDetail(fileType, id);
            if (!isOwnAsset(rec.user_id)) {
                if (typeof showError === 'function') {
                    showError(t('library_edit_owner_only', '仅创建者可编辑，创建者 ' + formatCreatorTag(rec.user_id)));
                }
                return;
            }
            currentEditFile = {
                fileType: fileType,
                fileName: displayName(fileType, rec),
                id: rec.id,
                source: SOURCE_DATABASE,
                userId: rec.user_id
            };
            document.querySelectorAll('.edit-form').forEach(function (form) { form.style.display = 'none'; });
            var data = toViewerData(fileType, rec);
            if (fileType === 'worlds' && typeof showWorldEditor === 'function') showWorldEditor(currentEditFile.fileName, rec);
            else if (fileType === 'characters' && typeof showCharacterEditor === 'function') showCharacterEditor(currentEditFile.fileName, rec);
            else if (fileType === 'locations' && typeof showLocationEditor === 'function') await showLocationEditor(currentEditFile.fileName, data);
            else if (fileType === 'props' && typeof showPropEditor === 'function') showPropEditor(currentEditFile.fileName, data);
            else if (fileType === 'scripts' && typeof showScriptEditor === 'function') showScriptEditor(currentEditFile.fileName, rec);
            document.getElementById('edit-modal').classList.add('show');
        } catch (err) {
            if (typeof showError === 'function') showError(t('error_edit_failed', { error: err.message }) || ('打开编辑失败: ' + err.message));
        }
    }

    async function previewLibraryImage(fileType, id) {
        try {
            var rec = await fetchDetail(fileType, id);
            var url = rec.reference_image;
            if (!url && typeof showInfo === 'function') {
                showInfo(t('title_no_image', '暂无参考图'));
                return;
            }
            if (typeof previewItemImage === 'function') {
                // 回退：直接打开图片预览弹窗
            }
            var img = document.getElementById('preview-image');
            var modal = document.getElementById('image-preview-modal');
            var title = document.getElementById('image-preview-title');
            if (img && modal) {
                img.src = url;
                if (title) title.textContent = displayName(fileType, rec);
                modal.classList.add('show');
            }
        } catch (err) {
            if (typeof showError === 'function') showError(err.message);
        }
    }

    function collectParsed(fileType) {
        var raw = '';
        if (fileType === 'worlds' && typeof collectWorldData === 'function') raw = collectWorldData();
        else if (fileType === 'characters' && typeof collectCharacterData === 'function') raw = collectCharacterData();
        else if (fileType === 'locations' && typeof collectLocationData === 'function') raw = collectLocationData();
        else if (fileType === 'props' && typeof collectPropData === 'function') raw = collectPropData();
        else if (fileType === 'scripts' && typeof collectScriptData === 'function') raw = collectScriptData();
        if (!raw) return null;
        try { return JSON.parse(raw); } catch (e) { return null; }
    }

    async function saveLibraryAsset() {
        var edit = currentEditFile || {};
        if (edit.source !== SOURCE_DATABASE || !edit.id) return false;
        var fileType = edit.fileType;
        var parsed = collectParsed(fileType);
        if (!parsed) {
            if (typeof showError === 'function') showError(t('error_file_content_empty', '文件内容不能为空'));
            return true;
        }
        var method = 'PUT';
        var url = detailUrl(fileType, edit.id);
        var body = parsed;
        if (fileType === 'locations') {
            method = 'PATCH';
            body = {
                name: parsed.name,
                parent_name: parsed.parent_name || '',
                description: parsed.description,
                reference_image: parsed.reference_image,
                reference_images: parsed.reference_images
            };
        } else if (fileType === 'props') {
            method = 'PATCH';
            body = {
                name: parsed.name,
                content: parsed.description,
                other_info: parsed.type,
                reference_image: parsed.reference_image
            };
        } else if (fileType === 'scripts') {
            body = {
                title: parsed.title,
                episode_number: parsed.episode_number,
                content: parsed.content
            };
        } else if (fileType === 'characters') {
            body = {
                name: parsed.name,
                age: parsed.age,
                identity: parsed.identity,
                appearance: parsed.appearance,
                personality: parsed.personality,
                behavior: parsed.behavior,
                other_info: parsed.other_info,
                default_voice: parsed.default_voice,
                reference_image: parsed.reference_image,
                reference_images: parsed.reference_images
            };
        } else if (fileType === 'worlds') {
            body = {
                name: parsed.name,
                description: parsed.description,
                story_type: parsed.story_type,
                story_outline: parsed.story_outline,
                visual_style: parsed.visual_style,
                era_environment: parsed.era_environment,
                color_language: parsed.color_language,
                composition_preference: parsed.composition_preference
            };
        }
        try {
            var result = await apiJson(url, {
                method: method,
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body)
            });
            if (result.data.code !== 0) {
                if (typeof showError === 'function') {
                    showError(result.data.message || t('error_save_failed', '保存失败'));
                }
                return true;
            }
            if (typeof showSuccess === 'function') {
                showSuccess(t('success_file_updated', { name: edit.fileName }) || ('✓ 已更新: ' + edit.fileName));
            }
            if (typeof closeEditModal === 'function') closeEditModal();
            await loadLibraryFiles(fileType);
            await syncStagingAfterLibrarySave(fileType, parsed);
            var typeName = TYPE_LABELS[fileType] || fileType;
            if (typeof notifyAgentAssetUpdated === 'function') {
                await notifyAgentAssetUpdated('系统通知：' + typeName + ' "' + edit.fileName + '" 已在数据库中更新，请重新读取最新内容。');
            }
        } catch (err) {
            if (typeof showError === 'function') showError(err.message);
        }
        return true;
    }

    async function syncStagingAfterLibrarySave(fileType, parsed) {
        var apiMap = {
            worlds: '/api/world-files',
            characters: '/api/characters-files',
            scripts: '/api/scripts-files',
            locations: '/api/locations-files',
            props: '/api/props-files'
        };
        var fileName = parsed.name;
        if (fileType === 'scripts') {
            fileName = parsed.episode_number != null ? String(parsed.episode_number) : parsed.title;
        }
        if (fileType === 'worlds') fileName = 'world_' + WORLD_ID + '.json';
        if (!fileName || !apiMap[fileType]) return;
        try {
            await fetch(apiMap[fileType] + '/' + encodeURIComponent(fileName) +
                '?user_id=' + USER_ID + '&world_id=' + WORLD_ID + '&auth_token=' + encodeURIComponent(AUTH_TOKEN), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    content: JSON.stringify(parsed, null, 2),
                    user_id: USER_ID,
                    world_id: WORLD_ID,
                    auth_token: AUTH_TOKEN
                })
            });
        } catch (e) {
            console.warn('sync staging after library save failed', e);
        }
    }

    async function openLibraryDeleteModal(fileType, id) {
        try {
            var rec = await fetchDetail(fileType, id);
            if (!isOwnAsset(rec.user_id)) {
                if (typeof showError === 'function') {
                    showError(t('library_delete_owner_only', '仅创建者可删除，创建者 ' + formatCreatorTag(rec.user_id)));
                }
                return;
            }
            pendingDelete = { fileType: fileType, id: rec.id, record: rec };
            var name = displayName(fileType, rec);
            var creator = formatCreatorTag(rec.user_id);
            var summary = document.getElementById('library-delete-summary');
            if (summary) {
                summary.textContent = '确定删除已入库' + (TYPE_LABELS[fileType] || '') +
                    '「' + name + '」（id=' + rec.id + '，创建者 ' + creator + '）？此操作不可撤销。';
            }
            var warnings = [];
            var usage = rec.usage || {};
            if (fileType === 'scripts' && usage.storyboard_count > 0) {
                warnings.push('有 ' + usage.storyboard_count + ' 个分镜关联此剧本，删除后会解除关联，分镜不会被删除。');
            }
            if (fileType === 'locations' && usage.child_location_count > 0) {
                warnings.push('有 ' + usage.child_location_count + ' 个子场景，删除后它们会变为顶级场景。');
            }
            if (fileType === 'characters' && usage.dialogue_count > 0) {
                warnings.push('对白中有 ' + usage.dialogue_count + ' 处引用此角色，删除后引用会失效，分镜不会被删除。');
            }
            var ul = document.getElementById('library-delete-warnings');
            if (ul) {
                ul.innerHTML = warnings.map(function (w) { return '<li>' + escapeHtmlLocal(w) + '</li>'; }).join('');
            }
            var cb = document.getElementById('library-delete-staging');
            if (cb) cb.checked = true;
            document.getElementById('library-delete-modal').classList.add('show');
        } catch (err) {
            if (typeof showError === 'function') showError(err.message);
        }
    }

    function closeLibraryDeleteModal() {
        pendingDelete = null;
        var modal = document.getElementById('library-delete-modal');
        if (modal) modal.classList.remove('show');
    }

    async function confirmLibraryDelete() {
        if (!pendingDelete) return;
        var fileType = pendingDelete.fileType;
        var id = pendingDelete.id;
        var alsoStaging = !!(document.getElementById('library-delete-staging') || {}).checked;
        var url = detailUrl(fileType, id) + (alsoStaging ? '?also_delete_staging=true' : '');
        try {
            if (typeof showInfo === 'function') showInfo(t('status_deleting', '正在删除...'));
            var result = await apiJson(url, { method: 'DELETE' });
            if (result.data.code !== 0) {
                if (typeof showError === 'function') showError(result.data.message || t('error_delete_failed', '删除失败'));
                return;
            }
            closeLibraryDeleteModal();
            if (typeof showSuccess === 'function') showSuccess(t('success_deleted', '删除成功'));
            await loadLibraryFiles(fileType);
            var typeName = TYPE_LABELS[fileType] || fileType;
            if (typeof notifyAgentAssetUpdated === 'function') {
                await notifyAgentAssetUpdated('系统通知：已入库' + typeName + '已被用户删除，请勿继续引用。');
            }
        } catch (err) {
            if (typeof showError === 'function') showError(err.message);
        }
    }

    function switchAssetSource(source) {
        assetSource = source === SOURCE_DATABASE ? SOURCE_DATABASE : SOURCE_STAGING;
        applySourceChrome();
        if (assetSource === SOURCE_DATABASE) loadLibraryFiles(currentType());
        else if (typeof loadFiles === 'function') loadFiles(currentType());
    }

    function onLibrarySearchInput() {
        var input = document.getElementById('library-search-input');
        libraryKeyword = input ? input.value.trim() : '';
        if (librarySearchTimer) clearTimeout(librarySearchTimer);
        librarySearchTimer = setTimeout(function () {
            if (assetSource === SOURCE_DATABASE) loadLibraryFiles(currentType());
        }, 250);
    }

    function initLibraryUi() {
        applySourceChrome();
        var input = document.getElementById('library-search-input');
        if (input && !input._bound) {
            input._bound = true;
            input.addEventListener('input', onLibrarySearchInput);
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initLibraryUi);
    } else {
        initLibraryUi();
    }

    window.switchAssetSource = switchAssetSource;
    window.closeLibraryDeleteModal = closeLibraryDeleteModal;
    window.confirmLibraryDelete = confirmLibraryDelete;
    window.ScriptWriterLibrary = {
        SOURCE_STAGING: SOURCE_STAGING,
        SOURCE_DATABASE: SOURCE_DATABASE,
        getSource: function () { return assetSource; },
        isLibrary: function () { return assetSource === SOURCE_DATABASE; },
        loadLibraryFiles: loadLibraryFiles,
        saveLibraryAsset: saveLibraryAsset,
        formatCreatorTag: formatCreatorTag,
        applySourceChrome: applySourceChrome
    };
})();
