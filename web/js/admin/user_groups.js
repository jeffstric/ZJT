/**
 * 管理后台「用户分组」页面（mixin，挂载到 admin 根应用）。
 *
 * 分组由管理员创建（单组制：一个用户最多属于一个组），仅用于后台管理
 * 与月度算力报表统计，不影响用户登录与权限。所有请求复用 admin 根应用
 * 中的 Bearer 凭据（this.authToken）。
 */
(function () {
    'use strict';

    const API_ROOT = '/api/admin';

    function unwrapData(response) {
        const body = response && response.data;
        if (body && Object.prototype.hasOwnProperty.call(body, 'code') && body.code !== 0) {
            throw new Error(body.detail || body.error || 'Operation failed');
        }
        return body && Object.prototype.hasOwnProperty.call(body, 'data') ? body.data : body;
    }

    function apiError(error) {
        return error?.response?.data?.detail
            || error?.response?.data?.error
            || error?.message
            || String(error);
    }

    window.UserGroupsAdminMixin = {
        data() {
            return {
                userGroups: {
                    list: [],
                    loading: false,
                    loaded: false,
                    error: '',
                },
                userGroupModal: {
                    show: false,
                    mode: 'create', // create | edit
                    groupId: null,
                    name: '',
                    remark: '',
                    loading: false,
                },
                userGroupMembersModal: {
                    show: false,
                    groupId: null,
                    groupName: '',
                    members: [],
                    total: 0,
                    page: 1,
                    pageSize: 20,
                    loading: false,
                },
                // 用户管理页「设组」弹窗
                userGroupSetModal: {
                    show: false,
                    userId: null,
                    userName: '',
                    currentGroupId: null,
                    selectedGroupId: '', // '' = 未分组
                    loading: false,
                },
            };
        },

        methods: {
            // ---------- 分组列表 ----------
            async loadUserGroups(force) {
                const state = this.userGroups;
                if (state.loading) return;
                if (state.loaded && !force) return;
                state.loading = true;
                state.error = '';
                try {
                    const data = unwrapData(await axios.get(`${API_ROOT}/user-groups`, {
                        headers: { 'Authorization': `Bearer ${this.authToken}` }
                    }));
                    state.list = Array.isArray(data) ? data : [];
                    state.loaded = true;
                } catch (error) {
                    state.error = apiError(error);
                } finally {
                    state.loading = false;
                }
            },

            // ---------- 创建/编辑分组 ----------
            openUserGroupCreateModal() {
                this.userGroupModal = {
                    show: true,
                    mode: 'create',
                    groupId: null,
                    name: '',
                    remark: '',
                    loading: false,
                };
            },

            openUserGroupEditModal(group) {
                this.userGroupModal = {
                    show: true,
                    mode: 'edit',
                    groupId: group.id,
                    name: group.name || '',
                    remark: group.remark || '',
                    loading: false,
                };
            },

            closeUserGroupModal() {
                this.userGroupModal.show = false;
            },

            async submitUserGroupModal() {
                const modal = this.userGroupModal;
                const name = (modal.name || '').trim();
                if (!name) {
                    alert(this.t('user_group_name_required'));
                    return;
                }
                const isEdit = modal.mode === 'edit';
                if (!confirm(this.t(isEdit ? 'confirm_user_group_update' : 'confirm_user_group_create', { name }))) {
                    return;
                }
                modal.loading = true;
                try {
                    if (isEdit) {
                        await axios.put(`${API_ROOT}/user-groups/${modal.groupId}`, {
                            name,
                            remark: (modal.remark || '').trim() || null,
                        }, { headers: { 'Authorization': `Bearer ${this.authToken}` } });
                    } else {
                        await axios.post(`${API_ROOT}/user-groups`, {
                            name,
                            remark: (modal.remark || '').trim() || null,
                        }, { headers: { 'Authorization': `Bearer ${this.authToken}` } });
                    }
                    this.closeUserGroupModal();
                    await this.loadUserGroups(true);
                } catch (error) {
                    alert(apiError(error));
                } finally {
                    modal.loading = false;
                }
            },

            // ---------- 删除分组（组内用户自动回到未分组） ----------
            async deleteUserGroup(group) {
                const message = group.member_count > 0
                    ? this.t('confirm_user_group_delete_with_members', { name: group.name, count: group.member_count })
                    : this.t('confirm_user_group_delete', { name: group.name });
                if (!confirm(message)) return;

                try {
                    await axios.delete(`${API_ROOT}/user-groups/${group.id}`, {
                        headers: { 'Authorization': `Bearer ${this.authToken}` }
                    });
                    await this.loadUserGroups(true);
                } catch (error) {
                    alert(apiError(error));
                }
            },

            // ---------- 分组成员 ----------
            openUserGroupMembersModal(group) {
                this.userGroupMembersModal.show = true;
                this.userGroupMembersModal.groupId = group.id;
                this.userGroupMembersModal.groupName = group.name || '';
                this.userGroupMembersModal.members = [];
                this.userGroupMembersModal.total = 0;
                this.userGroupMembersModal.page = 1;
                this.loadUserGroupMembers();
            },

            closeUserGroupMembersModal() {
                this.userGroupMembersModal.show = false;
                this.userGroupMembersModal.groupId = null;
                this.userGroupMembersModal.members = [];
            },

            async loadUserGroupMembers() {
                const state = this.userGroupMembersModal;
                if (!state.groupId) return;
                state.loading = true;
                try {
                    const data = unwrapData(await axios.get(
                        `${API_ROOT}/user-groups/${state.groupId}/members`,
                        {
                            params: { page: state.page, page_size: state.pageSize },
                            headers: { 'Authorization': `Bearer ${this.authToken}` }
                        }
                    ));
                    state.members = Array.isArray(data.members) ? data.members : [];
                    state.total = data.total || 0;
                } catch (error) {
                    alert(apiError(error));
                } finally {
                    state.loading = false;
                }
            },

            userGroupMembersTotalPages() {
                const state = this.userGroupMembersModal;
                return Math.max(1, Math.ceil(state.total / state.pageSize));
            },

            prevGroupMembersPage() {
                const state = this.userGroupMembersModal;
                if (state.page > 1) {
                    state.page -= 1;
                    this.loadUserGroupMembers();
                }
            },

            nextGroupMembersPage() {
                const state = this.userGroupMembersModal;
                if (state.page < this.userGroupMembersTotalPages()) {
                    state.page += 1;
                    this.loadUserGroupMembers();
                }
            },

            // ---------- 用户管理页「设组」 ----------
            async openSetUserGroupModal(user) {
                // 分组下拉需要分组列表；未加载过则先拉取
                if (!this.userGroups.loaded) {
                    await this.loadUserGroups();
                }
                this.userGroupSetModal = {
                    show: true,
                    userId: user.user_id,
                    userName: user.display_name || this.t('user_fallback_label', { id: user.user_id }),
                    currentGroupId: user.group_id || null,
                    selectedGroupId: user.group_id != null ? String(user.group_id) : '',
                    loading: false,
                };
            },

            closeSetUserGroupModal() {
                this.userGroupSetModal.show = false;
            },

            async submitSetUserGroup() {
                const modal = this.userGroupSetModal;
                const groupId = modal.selectedGroupId === '' ? null : parseInt(modal.selectedGroupId, 10);
                modal.loading = true;
                try {
                    await axios.put(`${API_ROOT}/users/${modal.userId}/group`, {
                        group_id: groupId,
                    }, { headers: { 'Authorization': `Bearer ${this.authToken}` } });
                    this.closeSetUserGroupModal();
                    await this.loadUsers();
                } catch (error) {
                    alert(apiError(error));
                } finally {
                    modal.loading = false;
                }
            },

            userGroupNameById(groupId) {
                if (groupId == null) return '';
                const group = this.userGroups.list.find(g => g.id === groupId);
                return group ? group.name : '';
            },
        },
    };
})();
