/**
 * 公告中心（用户端铃铛 + 通知面板 + 详情弹窗）
 *
 * 以 Vue mixin 形式并入 index.html 主应用（index_app.js 的 App 对象）：
 * - index.html 内联启动脚本中 `app.mixin(window.AnnouncementCenterMixin)` 注册
 * - 依赖主应用的 isLoggedIn computed（authToken/userPhone）判断登录态
 * - 数据源：/api/announcements/*（本站公告，per-user 已读）
 *          /api/notifications/poll（远程拉取的系统公告，全局已读）
 */
(function () {
  'use strict';

  const POLL_INTERVAL_MS = 60 * 1000;      // 未读数轮询间隔
  const ANN_LIST_LIMIT = 50;               // 面板单次拉取公告条数

  window.AnnouncementCenterMixin = {
    data() {
      return {
        // 铃铛与通知面板
        annBell: {
          count: 0,            // 本站公告未读数（徽标）
          panelOpen: false,
          loading: false,
          items: [],           // 本站公告列表（含 is_read）
          systemNotifications: [],  // 远程系统公告（全局已读）
          systemUnreadCount: 0,
          loadedOnce: false
        },
        // 公告详情弹窗
        annDetail: {
          show: false,
          item: null,          // { source: 'announcement'|'system', ... }
          imageZoom: null      // 当前放大的图片 URL
        },
        annPollTimer: null
      };
    },

    watch: {
      // 登录态变化时启停未读数轮询（含 URL 带 token 进入 / 登录成功 / 退出）
      isLoggedIn: {
        handler(v) {
          if (v) {
            this.startAnnouncementPolling();
          } else {
            this.stopAnnouncementPolling();
            this.annBell.count = 0;
            this.annBell.panelOpen = false;
          }
        }
      }
    },

    mounted() {
      // 主应用 mounted 晚于 mixin mounted 执行；登录态就绪由上方 watcher 兜底触发
      document.addEventListener('click', this._annOutsideClickHandler = (e) => {
        if (!this.annBell.panelOpen) return;
        const panel = document.querySelector('.ann-panel');
        const bell = document.querySelector('.ann-bell-btn');
        if (panel && !panel.contains(e.target) && bell && !bell.contains(e.target)) {
          this.annBell.panelOpen = false;
        }
      });
    },

    beforeUnmount() {
      this.stopAnnouncementPolling();
      if (this._annOutsideClickHandler) {
        document.removeEventListener('click', this._annOutsideClickHandler);
        this._annOutsideClickHandler = null;
      }
    },

    methods: {
      // ============ 轮询 ============

      startAnnouncementPolling() {
        this.stopAnnouncementPolling();
        this.pollAnnouncementUnread();
        this.annPollTimer = setInterval(() => this.pollAnnouncementUnread(), POLL_INTERVAL_MS);
      },

      stopAnnouncementPolling() {
        if (this.annPollTimer) {
          clearInterval(this.annPollTimer);
          this.annPollTimer = null;
        }
      },

      async pollAnnouncementUnread() {
        if (!this.authToken) return;
        try {
          const response = await axios.get('/api/announcements/unread-count', {
            headers: { 'Authorization': `Bearer ${this.authToken}` }
          });
          if (response.data.code === 0) {
            this.annBell.count = response.data.data.count || 0;
          } else if (response.data.message === '未登录') {
            this.stopAnnouncementPolling();
          }
        } catch (error) {
          // 静默失败，等待下一轮
        }
      },

      // ============ 面板 ============

      toggleAnnouncementPanel() {
        if (this.annBell.panelOpen) {
          this.annBell.panelOpen = false;
        } else {
          this.openAnnouncementPanel();
        }
      },

      async openAnnouncementPanel() {
        this.annBell.panelOpen = true;
        if (this.annBell.loadedOnce && !this._annListDirty) return;
        await this.refreshAnnouncementPanel();
      },

      async refreshAnnouncementPanel() {
        this.annBell.loading = true;
        try {
          // 本站公告（per-user 已读）
          const annRes = await axios.get('/api/announcements', {
            params: { limit: ANN_LIST_LIMIT },
            headers: { 'Authorization': `Bearer ${this.authToken}` }
          });
          if (annRes.data.code === 0) {
            this.annBell.items = annRes.data.data.items || [];
            this.annBell.loadedOnce = true;
            this._annListDirty = false;
          }

          // 远程系统公告（复用现有全局公告轮询接口）
          try {
            const sysRes = await axios.get('/api/notifications/poll');
            if (sysRes.data.code === 0) {
              const data = sysRes.data.data || {};
              this.annBell.systemNotifications = data.notifications || [];
              this.annBell.systemUnreadCount = data.unread_count || 0;
            }
          } catch (error) { /* 系统公告失败不影响本站公告展示 */ }
        } catch (error) {
          // 静默失败
        } finally {
          this.annBell.loading = false;
        }
      },

      // ============ 已读与详情 ============

      async openAnnouncementDetail(item, source) {
        this.annDetail.item = { ...item, source };
        this.annDetail.show = true;
        this.annDetail.imageZoom = null;

        if (source === 'announcement' && !item.is_read) {
          try {
            const response = await axios.post(`/api/announcements/${item.id}/read`, {}, {
              headers: { 'Authorization': `Bearer ${this.authToken}` }
            });
            if (response.data.code === 0) {
              item.is_read = true;
              this.annBell.count = Math.max(0, this.annBell.count - 1);
              this._annListDirty = true;
            }
          } catch (error) { /* 已读失败不阻断浏览 */ }
        } else if (source === 'system' && !item.is_read) {
          try {
            await axios.post(`/api/notifications/${item.id}/read`);
            item.is_read = true;
            this.annBell.systemUnreadCount = Math.max(0, this.annBell.systemUnreadCount - 1);
          } catch (error) { /* 已读失败不阻断浏览 */ }
        }
      },

      closeAnnouncementDetail() {
        this.annDetail.show = false;
        this.annDetail.item = null;
        this.annDetail.imageZoom = null;
      },

      async markAllAnnouncementsRead() {
        try {
          const response = await axios.post('/api/announcements/read-all', {}, {
            headers: { 'Authorization': `Bearer ${this.authToken}` }
          });
          if (response.data.code === 0) {
            this.annBell.items.forEach(n => { n.is_read = true; });
            this.annBell.count = 0;
            this._annListDirty = true;
          }
        } catch (error) { /* 静默失败 */ }
      },

      async markAllSystemNotificationsRead() {
        try {
          await axios.post('/api/notifications/read-all');
          this.annBell.systemNotifications.forEach(n => { n.is_read = true; });
          this.annBell.systemUnreadCount = 0;
        } catch (error) { /* 静默失败 */ }
      },

      // ============ 展示辅助 ============

      annLevelText(level) {
        const key = 'ann_level_' + (level || 'info');
        const text = this.$t ? this.$t(key) : '';
        // index 语言包未包含该键时 $t 原样返回 key，做兜底
        return text === key ? { info: '信息', success: '成功', warning: '警告', error: '错误' }[level] : text;
      },

      annFormatTime(dateStr) {
        if (!dateStr) return '';
        const date = new Date(dateStr);
        if (isNaN(date.getTime())) return dateStr;
        const locale = (localStorage.getItem('zjt_locale') === 'en') ? 'en-US' : 'zh-CN';
        return date.toLocaleString(locale, {
          year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit'
        });
      },

      annTruncate(text, max) {
        if (!text) return '';
        return text.length > max ? text.slice(0, max) + '…' : text;
      }
    }
  };
})();
