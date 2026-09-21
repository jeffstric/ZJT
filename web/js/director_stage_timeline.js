// ============================
// director_stage_timeline.js - 导演台时间轴
// 多轨道关键帧调度：相机轨 + 每个人偶独立轨道，各自记录/拖动互不影响；
// 相机键支持 cut（硬切镜头）：到达该键瞬间跳变，段内保持上一键配置；
// 播放时逐轨插值驱动角色走位与运镜 + 行走摆动。
// 由 director_stage_editor.js 在 IIFE 内调用 window.DirectorStageTimelineModule
// .attach(DirectorEditor, helpers) 挂载原型方法，编辑器负责在生命周期中调用：
//   restoreFromData → restoreTimeline(d)   （兼容旧版全局快照 keys 格式，自动迁移）
//   serializeData   → serializeTimeline()
//   open            → setupTimeline()
//   startLoop frame → tickTimeline(tNow)
//   close           → stopTimelineForClose()
// ============================
(function () {
  'use strict';

  var DEFAULT_DURATION = 6;   // 默认时长（秒）
  var MIN_DURATION = 1;
  var MAX_DURATION = 60;
  var KEY_MERGE_WINDOW = 0.08; // 同时刻关键帧覆盖阈值（秒）
  var KEY_DELETE_RADIUS = 0.2; // 「删除关键帧」吸附阈值（秒）
  var WALK_MIN_SPEED = 0.22;   // 低于该速度（m/s）不做行走摆动
  var WALK_MAX_SPEED = 1.25;   // 摆幅饱和速度

  function lerp(a, b, u) { return a + (b - a) * u; }

  // 角度最短路径插值（处理 350°→10° 应走 20° 而非 -340°），
  // 结果归一到 (-180, 180]，避免 360/720 等等价角写进关键帧数据
  function lerpAngle(a, b, u) {
    var d = (b - a) % 360;
    if (d > 180) d -= 360;
    if (d < -180) d += 360;
    var r = a + d * u;
    r = ((r % 360) + 540) % 360 - 180;
    return r;
  }

  function num(v) { return (typeof v === 'number' && isFinite(v)) ? v : 0; }

  function escHtml(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function sortKeys(keys) { keys.sort(function (a, b) { return a.t - b.t; }); }

  function attach(DirectorEditor, helpers) {
    var clamp = helpers.clamp;
    var round2 = helpers.round2;
    var deg2rad = helpers.deg2rad;

    // ---------- 轨道模型 ----------
    // tl.tracks = [
    //   { kind: 'camera', id: '<camId>', keys: [{ t, pos, target, fov, cut, camId }] },  // 每个机位一条（多机位）
    //   { kind: 'puppet', id: '<puppetId>', keys: [{ t, x, z, rotY }] }
    // ]
    // 轨道引用串：'camera:<camId>' | 'puppet:<id>'
    // 切镜头语义：任一相机轨的键 = 「该时刻起画面归该机位」——跨轨接管是隐式硬切；
    // 同轨相邻键默认平滑运镜，cut=true 表示同轨内也硬切（跳切）。

    function getCameraTrack(tl, camId) {
      for (var i = 0; i < tl.tracks.length; i++) {
        if (tl.tracks[i].kind === 'camera' && tl.tracks[i].id === camId) return tl.tracks[i];
      }
      return null;
    }

    function getOrCreateCameraTrack(tl, camId) {
      var tr = getCameraTrack(tl, camId);
      if (!tr) {
        tr = { kind: 'camera', id: camId, keys: [] };
        tl.tracks.unshift(tr);
      }
      return tr;
    }

    function cameraTrackIds(tl) {
      var ids = [];
      for (var i = 0; i < tl.tracks.length; i++) {
        if (tl.tracks[i].kind === 'camera') ids.push(tl.tracks[i].id);
      }
      return ids;
    }

    function getPuppetTrack(tl, pid) {
      for (var i = 0; i < tl.tracks.length; i++) {
        if (tl.tracks[i].kind === 'puppet' && tl.tracks[i].id === pid) return tl.tracks[i];
      }
      return null;
    }

    function getOrCreatePuppetTrack(tl, pid) {
      var tr = getPuppetTrack(tl, pid);
      if (!tr) {
        tr = { kind: 'puppet', id: pid, keys: [] };
        tl.tracks.push(tr);
      }
      return tr;
    }

    function resolveTrack(tl, ref) {
      if (ref && ref.indexOf('camera:') === 0) return getCameraTrack(tl, ref.slice(7));
      if (ref && ref.indexOf('puppet:') === 0) return getPuppetTrack(tl, ref.slice(7));
      // 兼容裸 'camera'（旧引用）：指向第一条相机轨
      if (ref === 'camera') {
        for (var i = 0; i < tl.tracks.length; i++) {
          if (tl.tracks[i].kind === 'camera') return tl.tracks[i];
        }
      }
      return null;
    }

    function trackRefOf(tr) {
      return tr.kind === 'camera' ? 'camera:' + tr.id : 'puppet:' + tr.id;
    }

    function sanitizeCameraKey(k, duration) {
      var cam = (k && k.camera) || k || {};   // 兼容旧全局快照 {camera:{...}} 与裸键两种传入
      return {
        t: clamp(num(k && k.t), 0, duration),
        pos: [num(cam.pos && cam.pos[0]), num(cam.pos && cam.pos[1]), num(cam.pos && cam.pos[2])],
        target: [num(cam.target && cam.target[0]), num(cam.target && cam.target[1]), num(cam.target && cam.target[2])],
        fov: clamp(num(cam.fov) || 35, 10, 120),
        cut: !!(k && k.cut),
        camId: (k && k.camId) ? String(k.camId) : null   // 记录时所属的机位（多机位管理用，求值仍以配置快照为准）
      };
    }

    function sanitizePuppetKey(k, duration) {
      var v = (k && k.puppets) ? null : k;    // 旧全局快照的 puppets[pid] 值直接传入
      return {
        t: clamp(num(k && k.t), 0, duration),
        x: num(v && v.x), z: num(v && v.z), rotY: num(v && v.rotY)
      };
    }

    // 旧版全局快照（tl.keys：每键含所有人偶 + 相机）→ 逐实体轨道
    function migrateLegacyKeys(srcKeys, duration) {
      var camKeys = [];
      var pupMap = {};
      (srcKeys || []).forEach(function (k) {
        if (!k || typeof k.t !== 'number' || !isFinite(k.t)) return;
        camKeys.push(sanitizeCameraKey({ t: k.t, camera: k.camera }, duration));
        if (k.puppets && typeof k.puppets === 'object') {
          Object.keys(k.puppets).forEach(function (pid) {
            var v = k.puppets[pid];
            if (!v || typeof v !== 'object') return;
            (pupMap[pid] = pupMap[pid] || []).push(sanitizePuppetKey({ t: k.t, x: v.x, z: v.z, rotY: v.rotY }, duration));
          });
        }
      });
      return { camKeys: camKeys, pupMap: pupMap };
    }

    // 同轨近时刻合并：后者覆盖前者（cut 标志/camId 随新键）
    function mergeKeyInto(last, k, kind) {
      if (kind === 'camera') {
        last.pos = k.pos; last.target = k.target; last.fov = k.fov; last.cut = k.cut; last.camId = k.camId;
      } else {
        last.x = k.x; last.z = k.z; last.rotY = k.rotY;
      }
    }

    // ---------- 数据恢复 / 序列化 ----------

    DirectorEditor.prototype.restoreTimeline = function (d) {
      if (!this.tl) this.tl = {};
      var src = (d && d.timeline) || null;
      this.tl.duration = DEFAULT_DURATION;
      this.tl.tracks = [];
      this.tl.playhead = 0;
      this.tl.playing = false;
      this.tl.scrubbing = false;
      this.tl.keyDrag = null;   // {track, index, moved}
      this.tl.lastFrameAt = 0;
      if (!src) return;
      if (typeof src.duration === 'number' && isFinite(src.duration)) {
        this.tl.duration = clamp(src.duration, MIN_DURATION, MAX_DURATION);
      }
      // 旧数据迁移的统一落轨机位：优先当前激活机位（编辑器 restore 时机位已就位）
      var legacyCamId = this.activeCameraId || 'cam1';
      if (Array.isArray(src.tracks)) {
        // tracks 格式：相机轨按 id 分轨（多机位）；无 id 的相机轨（v3）整体并入激活机位轨
        var self = this;
        src.tracks.forEach(function (tr) {
          if (!tr || !Array.isArray(tr.keys)) return;
          if (tr.kind === 'camera') {
            var camId = tr.id ? String(tr.id) : legacyCamId;
            var camKeys = tr.keys
              .filter(function (k) { return k && typeof k.t === 'number' && isFinite(k.t); })
              .map(function (k) { return sanitizeCameraKey(k, self.tl.duration); });
            var lane = getOrCreateCameraTrack(self.tl, camId);
            lane.keys = lane.keys.concat(camKeys);
            sortKeys(lane.keys);
          } else if (tr.kind === 'puppet' && tr.id !== undefined && tr.id !== null) {
            var pKeys = tr.keys
              .filter(function (k) { return k && typeof k.t === 'number' && isFinite(k.t); })
              .map(function (k) { return sanitizePuppetKey(k, self.tl.duration); });
            sortKeys(pKeys);
            if (pKeys.length) getOrCreatePuppetTrack(self.tl, tr.id).keys = pKeys;
          }
        });
      } else if (Array.isArray(src.keys)) {
        // v2 旧格式迁移：全局快照 → 相机全部并入激活机位轨 + 各人偶轨
        var migrated = migrateLegacyKeys(src.keys, this.tl.duration);
        sortKeys(migrated.camKeys);
        if (migrated.camKeys.length) getOrCreateCameraTrack(this.tl, legacyCamId).keys = migrated.camKeys;
        var tlRef = this.tl;
        Object.keys(migrated.pupMap).forEach(function (pid) {
          sortKeys(migrated.pupMap[pid]);
          getOrCreatePuppetTrack(tlRef, pid).keys = migrated.pupMap[pid];
        });
      }
    };

    DirectorEditor.prototype.serializeTimeline = function () {
      var liveIds = {};
      this.puppets.forEach(function (p) { liveIds[p.id] = true; });
      // 已删除机位的相机轨同样剔除（求值时也不参与，避免幽灵机位劫持画面）
      var liveCamIds = {};
      if (Array.isArray(this.cameras)) {
        this.cameras.forEach(function (c) { if (c && c.id) liveCamIds[c.id] = true; });
      }
      var tracks = [];
      this.tl.tracks.forEach(function (tr) {
        if (tr.kind === 'camera') {
          if (!tr.keys.length) return;
          if (Object.keys(liveCamIds).length && !liveCamIds[tr.id]) return;
          tracks.push({
            kind: 'camera',
            id: tr.id,
            keys: tr.keys.map(function (k) {
              return {
                t: round2(k.t),
                pos: [round2(k.pos[0]), round2(k.pos[1]), round2(k.pos[2])],
                target: [round2(k.target[0]), round2(k.target[1]), round2(k.target[2])],
                fov: Math.round(k.fov),
                cut: !!k.cut,
                camId: k.camId || null
              };
            })
          });
        } else if (tr.kind === 'puppet' && liveIds[tr.id]) {
          // 已删除人偶的轨道整体丢弃，避免幽灵数据反复落盘
          if (!tr.keys.length) return;
          tracks.push({
            kind: 'puppet',
            id: tr.id,
            keys: tr.keys.map(function (k) {
              return { t: round2(k.t), x: round2(k.x), z: round2(k.z), rotY: round2(k.rotY) };
            })
          });
        }
      });
      return { duration: round2(this.tl.duration), tracks: tracks };
    };

    // ---------- UI ----------

    DirectorEditor.prototype.setupTimeline = function () {
      var host = this.$('dsTimeline');
      if (!host) return;
      host.innerHTML =
        '<div class="ds-tl-controls">' +
          '<button type="button" class="ds-mini-btn ds-tl-play" id="dsTlPlayBtn" title="播放/暂停（空格）">▶ 播放</button>' +
          '<button type="button" class="ds-mini-btn" id="dsTlStopBtn" title="停止并回到 0s">⏹ 停止</button>' +
          '<span class="ds-tl-time" id="dsTlTime">0.0s / ' + this.tl.duration.toFixed(1) + 's</span>' +
          '<label class="ds-tl-dur" title="时间轴总时长（秒）">时长 ' +
            '<input type="number" id="dsTlDuration" min="' + MIN_DURATION + '" max="' + MAX_DURATION + '" step="0.5" value="' + this.tl.duration + '"> s' +
          '</label>' +
          '<button type="button" class="ds-mini-btn" id="dsTlKeyBtn" title="在当前时间记录所有角色位置与相机状态">◆ 记录关键帧</button>' +
          '<button type="button" class="ds-mini-btn" id="dsTlDelKeyBtn" title="删除当前时间附近的所有轨道关键帧（取最近一个）">✕ 删除关键帧</button>' +
          '<span class="ds-tl-hint">每条轨道独立：轨道左侧 ◆ 记录单个角色/相机，✕ 删本轨最近键；相机轨「切」= 硬切镜头；顶栏 ◆ 记录全部</span>' +
        '</div>' +
        '<div class="ds-tl-lanes">' +
          '<div class="ds-tl-labels" id="dsTlLabels"></div>' +
          '<div class="ds-tl-area" id="dsTlArea">' +
            '<div class="ds-tl-ruler" id="dsTlRuler"></div>' +
            '<div class="ds-tl-lane-rows" id="dsTlLaneRows"></div>' +
            '<div class="ds-tl-playhead" id="dsTlPlayhead"><div class="ds-tl-playhead-cap"></div></div>' +
          '</div>' +
        '</div>';

      var self = this;
      var area = this.$('dsTlArea');

      this.on(this.$('dsTlPlayBtn'), 'click', function () { self.togglePlay(); });
      this.on(this.$('dsTlStopBtn'), 'click', function () { self.stopTimeline(); });
      this.on(this.$('dsTlKeyBtn'), 'click', function () { self.recordTimelineKey(); });
      this.on(this.$('dsTlDelKeyBtn'), 'click', function () { self.deleteTimelineKeyAtPlayhead(); });

      // 空格 = 播放/暂停（输入框聚焦时不抢占）
      this.on(document, 'keydown', function (e) {
        if (!self.overlay || !self.overlay.classList.contains('show')) return;
        if (e.key !== ' ' && e.key !== 'Spacebar') return;
        var tag = document.activeElement && document.activeElement.tagName;
        if (tag === 'INPUT' || tag === 'TEXTAREA') return;
        e.preventDefault();
        self.togglePlay();
      });

      this.on(this.$('dsTlDuration'), 'change', function () {
        var v = parseFloat(this.value);
        if (!isFinite(v)) v = DEFAULT_DURATION;
        v = clamp(v, MIN_DURATION, MAX_DURATION);
        this.value = v;
        self.tl.duration = v;
        // 超出新时长的关键帧吸附到末端（逐轨、轨内近似时刻合并）
        self.tl.tracks.forEach(function (tr) {
          var merged = [];
          sortKeys(tr.keys);
          tr.keys.forEach(function (k) {
            k.t = Math.min(k.t, v);
            var last = merged[merged.length - 1];
            if (last && Math.abs(last.t - k.t) <= KEY_MERGE_WINDOW) {
              mergeKeyInto(last, k, tr.kind);
            } else {
              merged.push(k);
            }
          });
          tr.keys = merged;
        });
        self.setPlayhead(Math.min(self.tl.playhead, v));
        self.markDirty();
        self.renderTimeline();
      });

      // 轨道区交互（事件委托，lane 内容随 renderTimeline 重建，父节点常驻）：
      // 空白按下=拖播放头（scrub）；关键帧按下=拖动改时刻（原位点击=跳转）
      function trackTimeFromEvent(e) {
        var rect = area.getBoundingClientRect();
        var u = clamp((e.clientX - rect.left) / Math.max(rect.width, 1), 0, 1);
        return u * self.tl.duration;
      }

      this.on(area, 'mousedown', function (e) {
        if (e.button !== 0) return;
        e.preventDefault();
        var keyEl = e.target.classList && e.target.classList.contains('ds-tl-key')
          ? e.target
          : (e.target.closest ? e.target.closest('.ds-tl-key') : null);
        if (keyEl) {
          var tr = resolveTrack(self.tl, keyEl.dataset.track);
          var idx = parseInt(keyEl.dataset.index, 10);
          if (tr && isFinite(idx) && tr.keys[idx]) {
            self.pauseTimeline();
            self.tl.keyDrag = { track: tr, index: idx, moved: false };
          }
        } else {
          self.pauseTimeline();
          self.tl.scrubbing = true;
          self.setPlayhead(trackTimeFromEvent(e));
        }
      });

      // 标签列按钮（◆ 记录本轨 / ✕ 删本轨最近键 / 切 相机硬切开关），委托到常驻父节点
      this.on(this.$('dsTlLabels'), 'click', function (e) {
        var btn = e.target.closest ? e.target.closest('[data-act]') : null;
        if (!btn) return;
        var ref = btn.dataset.track;
        if (btn.dataset.act === 'rec') self.recordTimelineKeyOnTrack(ref);
        else if (btn.dataset.act === 'del') self.deleteTimelineKeyOnTrack(ref);
        else if (btn.dataset.act === 'cut') self.toggleCameraCutAtPlayhead();
      });

      this.on(window, 'mousemove', function (e) {
        if (self.tl.scrubbing) {
          self.setPlayhead(trackTimeFromEvent(e));
        } else if (self.tl.keyDrag) {
          var drag = self.tl.keyDrag;
          var k = drag.track.keys[drag.index];
          if (!k) { self.tl.keyDrag = null; return; }
          var t = trackTimeFromEvent(e);
          if (!drag.moved) {
            // 移动超过 3px 才视为拖动，否则当作点击跳转
            if (Math.abs(t - k.t) * (area.getBoundingClientRect().width / Math.max(self.tl.duration, 0.01)) < 3) return;
            drag.moved = true;
          }
          k.t = round2(clamp(t, 0, self.tl.duration));
          self.setPlayhead(k.t);
          self.renderTimeline();
        }
      });

      this.on(window, 'mouseup', function () {
        if (self.tl.scrubbing) {
          self.tl.scrubbing = false;
          return;
        }
        if (self.tl.keyDrag) {
          var drag = self.tl.keyDrag;
          self.tl.keyDrag = null;
          var k = drag.track.keys[drag.index];
          if (drag.moved && k) {
            // 拖动后按新时刻重排序；与本轨相近关键帧合并（不影响其他轨）
            sortKeys(drag.track.keys);
            var merged = [];
            drag.track.keys.forEach(function (item) {
              var last = merged[merged.length - 1];
              if (last && last !== item && Math.abs(last.t - item.t) <= KEY_MERGE_WINDOW) {
                mergeKeyInto(last, item, drag.track.kind);
              } else {
                merged.push(item);
              }
            });
            drag.track.keys = merged;
            self.markDirty();
            self.renderTimeline();
          } else if (k) {
            // 原位点击：跳转到该关键帧时刻
            self.setPlayhead(k.t);
          }
        }
      });

      this.renderTimeline();
    };

    // 当前应显示的轨道列表：每机位一条相机轨 + 按人偶顺序的人偶轨
    // （无轨的机位/人偶显示空 lane，便于记录；机位删除后 lane 消失）
    function displayTracks(self) {
      var list = [];
      if (Array.isArray(self.cameras) && self.cameras.length) {
        self.cameras.forEach(function (c) {
          var tr = c && c.id ? getCameraTrack(self.tl, c.id) : null;
          list.push({ kind: 'camera', id: c.id, name: c.name, keys: tr ? tr.keys : [] });
        });
      } else {
        // 兼容无 cameras 的宿主（单测等）：直接按已有相机轨显示
        cameraTrackIds(self.tl).forEach(function (camId) {
          list.push({ kind: 'camera', id: camId, name: null, keys: getCameraTrack(self.tl, camId).keys });
        });
      }
      self.puppets.forEach(function (p) {
        var tr = getPuppetTrack(self.tl, p.id);
        list.push({ kind: 'puppet', id: p.id, name: p.name, keys: tr ? tr.keys : [] });
      });
      return list;
    }

    // 完整重绘（时长/关键帧/人偶变化时）
    DirectorEditor.prototype.renderTimeline = function () {
      if (!this.tl) return;
      var ruler = this.$('dsTlRuler');
      var rowsEl = this.$('dsTlLaneRows');
      var labelsEl = this.$('dsTlLabels');
      if (!ruler || !rowsEl || !labelsEl) return;
      var dur = this.tl.duration || DEFAULT_DURATION;

      // 标尺：每秒一刻度
      var html = '';
      var step = dur > 24 ? 5 : 1;
      for (var s = 0; s <= dur + 1e-6; s += step) {
        html += '<div class="ds-tl-tick" style="left:' + (s / dur * 100) + '%"><span>' + s + 's</span></div>';
      }
      ruler.innerHTML = html;

      var self = this;
      function camNameOf(camId) {
        if (!camId || !self.cameras) return '';
        for (var ci = 0; ci < self.cameras.length; ci++) {
          if (self.cameras[ci].id === camId) return self.cameras[ci].name;
        }
        return '';
      }
      var labelHtml = '<div class="ds-tl-corner"></div>';
      var rowsHtml = '';
      displayTracks(this).forEach(function (tr) {
        var ref = trackRefOf(tr);
        var name = tr.kind === 'camera'
          ? ('🎥 ' + (tr.name || tr.id))
          : ('🧍 ' + (tr.name || tr.id));
        // 「切」= 同轨跳切（跨机位接管本身就是硬切，无需开关）
        var cutBtn = tr.kind === 'camera'
          ? '<button type="button" class="ds-tl-lane-btn" data-act="cut" data-track="' + ref + '" title="切换本轨最近相机键：硬切（跳切）/ 平滑运镜">切</button>'
          : '';
        labelHtml +=
          '<div class="ds-tl-lane-label">' +
            '<span class="ds-tl-lane-name" title="' + escHtml(tr.kind === 'camera' ? '相机' : (tr.name || tr.id)) + '">' + escHtml(name) + '</span>' +
            '<button type="button" class="ds-tl-lane-btn" data-act="rec" data-track="' + ref + '" title="在播放头时刻记录' + (tr.kind === 'camera' ? '相机' : '该角色') + '">◆</button>' +
            '<button type="button" class="ds-tl-lane-btn" data-act="del" data-track="' + ref + '" title="删除该轨道播放头附近的最近关键帧">✕</button>' +
            cutBtn +
          '</div>';
        rowsHtml += '<div class="ds-tl-lane-keys" data-track="' + ref + '">' +
          tr.keys.map(function (k, i) {
            var isCut = tr.kind === 'camera' && k.cut;
            var tip = tr.kind === 'camera'
              ? (k.cut ? '硬切镜头' : '平滑运镜')
              : '关键帧';
            var camName = tr.kind === 'camera' ? camNameOf(k.camId) : '';
            if (camName) tip += '（' + camName + '）';
            return '<div class="ds-tl-key' + (isCut ? ' cut' : '') + '" data-track="' + ref + '" data-index="' + i + '"' +
              ' title="' + k.t.toFixed(1) + 's ' + tip + '（拖动改时刻）" style="left:' + (k.t / dur * 100) + '%"></div>';
          }).join('') +
        '</div>';
      });
      labelsEl.innerHTML = labelHtml;
      rowsEl.innerHTML = rowsHtml;

      this.renderTimelineTime();
    };

    // 轻量刷新（播放/scrub 每帧）：播放头位置 + 时间文本 + 播放按钮态
    DirectorEditor.prototype.renderTimelineTime = function () {
      if (!this.tl) return;
      var ph = this.$('dsTlPlayhead');
      if (ph) ph.style.left = (this.tl.playhead / (this.tl.duration || 1) * 100) + '%';
      var timeEl = this.$('dsTlTime');
      if (timeEl) {
        timeEl.textContent = this.tl.playhead.toFixed(1) + 's / ' + this.tl.duration.toFixed(1) + 's';
      }
      var playBtn = this.$('dsTlPlayBtn');
      if (playBtn) {
        playBtn.textContent = this.tl.playing ? '⏸ 暂停' : '▶ 播放';
        playBtn.classList.toggle('active', !!this.tl.playing);
      }
    };

    // ---------- 关键帧编辑 ----------

    function upsertKey(track, key) {
      for (var i = 0; i < track.keys.length; i++) {
        if (Math.abs(track.keys[i].t - key.t) <= KEY_MERGE_WINDOW) {
          key.t = track.keys[i].t;
          mergeKeyInto(track.keys[i], key, track.kind);
          // t 相同属同键，无需重排
          return track.keys[i];
        }
      }
      track.keys.push(key);
      sortKeys(track.keys);
      return key;
    }

    function snapshotCameraKey(editor, t) {
      return {
        t: round2(t),
        pos: [round2(editor.virtualCamCfg.pos.x), round2(editor.virtualCamCfg.pos.y), round2(editor.virtualCamCfg.pos.z)],
        target: [round2(editor.virtualCamCfg.target.x), round2(editor.virtualCamCfg.target.y), round2(editor.virtualCamCfg.target.z)],
        fov: Math.round(editor.virtualCamCfg.fov),
        cut: false,
        camId: editor.activeCameraId || null
      };
    }

    // 顶栏：记录所有角色 + 相机（相机记到当前激活机位轨）
    DirectorEditor.prototype.recordTimelineKey = function () {
      var t = clamp(this.tl.playhead, 0, this.tl.duration);
      var self = this;
      var count = 0;
      this.puppets.forEach(function (p) {
        upsertKey(getOrCreatePuppetTrack(self.tl, p.id), {
          t: round2(t), x: round2(p.x), z: round2(p.z), rotY: round2(p.rotY)
        });
        count++;
      });
      upsertKey(getOrCreateCameraTrack(this.tl, this.activeCameraId || 'cam1'), snapshotCameraKey(this, t));
      this.markDirty();
      this.renderTimeline();
      this.setStatus('已记录 ' + t.toFixed(1) + 's 关键帧（' + count + ' 个角色 + 相机）');
    };

    // 单轨记录（轨道左侧 ◆ 按钮）；相机轨按键=把当前画面记到该机位轨
    DirectorEditor.prototype.recordTimelineKeyOnTrack = function (ref) {
      var tr = resolveTrack(this.tl, ref);
      if (!tr) {
        if (ref && ref.indexOf('puppet:') === 0) {
          tr = getOrCreatePuppetTrack(this.tl, ref.slice(7));
        } else if (ref && ref.indexOf('camera:') === 0) {
          tr = getOrCreateCameraTrack(this.tl, ref.slice(7));
        } else {
          tr = getOrCreateCameraTrack(this.tl, this.activeCameraId || 'cam1');
        }
      }
      var t = clamp(this.tl.playhead, 0, this.tl.duration);
      if (tr.kind === 'camera') {
        var camKey = snapshotCameraKey(this, t);
        camKey.camId = tr.id;   // 记到所在机位轨
        upsertKey(tr, camKey);
        this.setStatus('已记录 ' + t.toFixed(1) + 's 机位关键帧');
      } else {
        var self = this;
        var pup = null;
        this.puppets.forEach(function (p) { if (p.id === tr.id) pup = p; });
        if (!pup) { this.setStatus('人偶不存在，无法记录'); return; }
        upsertKey(tr, { t: round2(t), x: round2(pup.x), z: round2(pup.z), rotY: round2(pup.rotY) });
        this.setStatus('已记录 ' + t.toFixed(1) + 's 「' + (pup.name || pup.id) + '」关键帧');
      }
      this.markDirty();
      this.renderTimeline();
    };

    // 顶栏：删除所有轨里离播放头最近的一个关键帧
    DirectorEditor.prototype.deleteTimelineKeyAtPlayhead = function () {
      var t = this.tl.playhead;
      var bestTrack = null, bestIdx = -1, best = KEY_DELETE_RADIUS;
      this.tl.tracks.forEach(function (tr) {
        for (var i = 0; i < tr.keys.length; i++) {
          var d = Math.abs(tr.keys[i].t - t);
          if (d <= best) { best = d; bestTrack = tr; bestIdx = i; }
        }
      });
      if (!bestTrack) {
        this.setStatus('当前时间附近没有关键帧');
        return;
      }
      bestTrack.keys.splice(bestIdx, 1);
      this.markDirty();
      this.renderTimeline();
      this.setStatus('已删除关键帧');
    };

    // 单轨删除（轨道左侧 ✕ 按钮）：只删本轨播放头附近的最近键
    DirectorEditor.prototype.deleteTimelineKeyOnTrack = function (ref) {
      var tr = resolveTrack(this.tl, ref);
      if (!tr || !tr.keys.length) {
        this.setStatus('该轨道没有关键帧');
        return;
      }
      var t = this.tl.playhead;
      var idx = -1, best = KEY_DELETE_RADIUS;
      for (var i = 0; i < tr.keys.length; i++) {
        var d = Math.abs(tr.keys[i].t - t);
        if (d <= best) { best = d; idx = i; }
      }
      if (idx < 0) {
        this.setStatus('该轨道当前时间附近没有关键帧');
        return;
      }
      tr.keys.splice(idx, 1);
      this.markDirty();
      this.renderTimeline();
      this.setStatus('已删除该轨道关键帧');
    };

    // 同轨跳切开关：跨机位接管本身就是硬切，这里只切换本轨最近相机键的 cut（跳切）
    DirectorEditor.prototype.toggleCameraCutAtPlayhead = function () {
      var lanes = [];
      for (var i = 0; i < this.tl.tracks.length; i++) {
        if (this.tl.tracks[i].kind === 'camera' && this.tl.tracks[i].keys.length) lanes.push(this.tl.tracks[i]);
      }
      if (!lanes.length) {
        this.setStatus('相机轨没有关键帧，请先记录机位');
        return;
      }
      var t = this.tl.playhead;
      var lane = null, idx = -1, best = KEY_DELETE_RADIUS;
      lanes.forEach(function (tr) {
        for (var i = 0; i < tr.keys.length; i++) {
          var d = Math.abs(tr.keys[i].t - t);
          if (d <= best) { best = d; lane = tr; idx = i; }
        }
      });
      if (!lane) {
        this.setStatus('播放头附近没有机位关键帧（吸附半径 ' + KEY_DELETE_RADIUS + 's）');
        return;
      }
      var k = lane.keys[idx];
      k.cut = !k.cut;
      this.markDirty();
      this.renderTimeline();
      this.setStatus(k.cut
        ? (k.t.toFixed(1) + 's 已设为硬切：到达该键瞬间跳变')
        : (k.t.toFixed(1) + 's 已改为平滑运镜'));
    };

    // ---------- 播放 ----------

    DirectorEditor.prototype.togglePlay = function () {
      if (this.tl.playing) {
        this.pauseTimeline();
        return;
      }
      if (!this.tl.tracks.length || !this.tl.tracks.some(function (tr) { return tr.keys.length; })) {
        this.setStatus('请先记录关键帧，再播放');
        return;
      }
      if (this.tl.playhead >= this.tl.duration - 1e-3) this.tl.playhead = 0;
      this.tl.playing = true;
      this.tl.lastFrameAt = 0;
      this.renderTimelineTime();
      this.setStatus('播放中：角色走位 + 运镜预览');
    };

    DirectorEditor.prototype.pauseTimeline = function () {
      if (!this.tl || !this.tl.playing) return;
      this.tl.playing = false;
      this.restorePoses();
      this.renderTimelineTime();
      this.setStatus('已暂停，可继续调整并记录关键帧');
    };

    DirectorEditor.prototype.stopTimeline = function () {
      if (!this.tl) return;
      this.tl.playing = false;
      this.restorePoses();
      this.tl.playhead = 0;
      // 回到 0 时刻位形（若有）
      this.applyTimelineAt(0);
      this.renderTimelineTime();
      this.setStatus('已停止');
      // 录制中按停止：同时结束录制（上传已录部分）
      if (typeof this.stopRecording === 'function') this.stopRecording();
    };

    // 关闭编辑器前收尾（close 调用）：停播并恢复关节姿态，避免摆动残留在序列化外的 rig 上
    DirectorEditor.prototype.stopTimelineForClose = function () {
      if (!this.tl) return;
      this.tl.playing = false;
      this.restorePoses();
    };

    // 恢复所有关节到 jointDeg 姿态（去掉行走摆动的临时偏移）
    DirectorEditor.prototype.restorePoses = function () {
      var self = this;
      this.puppets.forEach(function (p) {
        if (typeof self.applyJointDeg === 'function') self.applyJointDeg(p);
        if (typeof self.applyPuppetTransform === 'function') self.applyPuppetTransform(p);
      });
    };

    DirectorEditor.prototype.setPlayhead = function (t) {
      if (!this.tl) return;
      this.tl.playhead = clamp(t, 0, this.tl.duration);
      this.applyTimelineAt(this.tl.playhead);
      this.renderTimelineTime();
    };

    // 每帧驱动（startLoop 调用，tNow 为秒）
    DirectorEditor.prototype.tickTimeline = function (tNow) {
      if (!this.tl) return;
      if (!this.tl.playing || this.tl.scrubbing || this.tl.keyDrag) {
        this.tl.lastFrameAt = tNow;
        return;
      }
      // 用户拖拽人偶/相机时自动暂停播放，避免插值覆盖手动调整
      if (this.dragging) {
        this.pauseTimeline();
        return;
      }
      var dt = this.tl.lastFrameAt ? Math.min(0.1, Math.max(0, tNow - this.tl.lastFrameAt)) : 0;
      this.tl.lastFrameAt = tNow;
      this.tl.playhead += dt;
      var ended = false;
      if (this.tl.playhead >= this.tl.duration) {
        this.tl.playhead = this.tl.duration;
        ended = true;
      }
      this.applyTimelineAt(this.tl.playhead, dt);
      this.renderTimelineTime();
      if (ended) {
        this.tl.playing = false;
        this.restorePoses();
        this.renderTimelineTime();
        this.setStatus('播放结束（停在末帧位形）');
        // 录制中播完：自动结束录制并上传
        if (typeof this.stopRecording === 'function') this.stopRecording();
      }
    };

    // 找到包住 t 的相邻关键帧
    function bracketKeys(keys, t) {
      var k0 = null, k1 = null;
      for (var i = 0; i < keys.length; i++) {
        if (keys[i].t <= t + 1e-6) k0 = keys[i];
        else { k1 = keys[i]; break; }
      }
      if (!k0) { k0 = keys[0]; k1 = keys.length > 1 ? keys[1] : null; }
      return [k0, k1];
    }

    // 存活机位轨：机位已删除的轨不参与求值（与序列化剔除同语义，避免幽灵机位劫持画面）
    function liveCameraLanes(editor) {
      var lanes = [];
      var camIds = null;
      if (Array.isArray(editor.cameras) && editor.cameras.length) {
        camIds = {};
        editor.cameras.forEach(function (c) { if (c && c.id) camIds[c.id] = true; });
      }
      for (var i = 0; i < editor.tl.tracks.length; i++) {
        var tr = editor.tl.tracks[i];
        if (tr.kind !== 'camera' || !tr.keys.length) continue;
        if (camIds && !camIds[tr.id]) continue;
        lanes.push(tr);
      }
      return lanes;
    }

    // 应用 t 时刻插值位形：逐人偶在自己轨内插值（缺轨保持当前编辑位形）；
    // 多机位：接管轨内插值（同轨平滑/跳切，跨轨接管=隐式硬切）+ 行走摆动
    DirectorEditor.prototype.applyTimelineAt = function (t, dt) {
      var self = this;
      var swingOn = !!(this.tl.playing && dt); // 仅真实播放时叠加步态摆动；scrub/停止只做静态插值

      this.puppets.forEach(function (p) {
        var tr = getPuppetTrack(self.tl, p.id);
        if (!tr || !tr.keys.length) return; // 该人偶无轨道：保持当前编辑位形
        var pair = bracketKeys(tr.keys, t);
        var k0 = pair[0], k1 = pair[1];
        var span = k1 ? Math.max(k1.t - k0.t, 1e-3) : 1;
        var u = k1 ? clamp((t - k0.t) / span, 0, 1) : 0;
        p.x = lerp(k0.x, k1 ? k1.x : k0.x, u);
        p.z = lerp(k0.z, k1 ? k1.z : k0.z, u);
        p.rotY = lerpAngle(k0.rotY, k1 ? k1.rotY : k0.rotY, u);
        self.applyPuppetTransform(p);

        // 行走摆动（播放动作）：位移速度超阈值时叠加步态关节摆动；
        // 非播放态或静止时恢复 jointDeg 姿态
        if (swingOn && k1) {
          var speed = Math.hypot(k1.x - k0.x, k1.z - k0.z) / span;
          applyWalkSwing(p, speed, dt) || restoreSwing(self, p);
        } else {
          restoreSwing(self, p);
        }
      });

      // 多机位求值：任一相机轨的键 = 「该时刻起画面归该机位」。
      // ≤t 的最后一个键所在轨为接管轨，在接管轨内按自己的键插值；
      // 同轨相邻键默认平滑运镜、cut 键跳切；跨轨接管本身就是硬切（到点瞬间跳变）。
      var camLanes = liveCameraLanes(this);
      if (camLanes.length) {
        var takeover = null;   // {lane, k} ≤t 的最后一个键（跨轨；同刻取后遍历到的）
        var firstKey = null;   // t 早于首键时，用最早键所在轨保持其首键位形
        camLanes.forEach(function (lane) {
          for (var i = 0; i < lane.keys.length; i++) {
            var k = lane.keys[i];
            if (k.t <= t + 1e-6 && (!takeover || k.t >= takeover.k.t - 1e-6)) takeover = { lane: lane, k: k };
            if (!firstKey || k.t < firstKey.k.t) firstKey = { lane: lane, k: k };
          }
        });
        var activeLane = takeover ? takeover.lane : (firstKey ? firstKey.lane : null);
        if (activeLane) {
          var cpair = bracketKeys(activeLane.keys, t);
          var ca = cpair[0], cb = cpair[1];
          var cspan = cb ? Math.max(cb.t - ca.t, 1e-3) : 1;
          var cu;
          if (!cb) {
            cu = 0; // 轨内末键之后保持末帧机位
          } else if (cb.cut) {
            // 同轨跳切：到达 cut 键时刻前保持轨内上一键配置，到点瞬间跳变
            cu = (t >= cb.t) ? 1 : 0;
          } else {
            cu = clamp((t - ca.t) / cspan, 0, 1);
          }
          this.virtualCamCfg.pos.set(
            lerp(ca.pos[0], cb ? cb.pos[0] : ca.pos[0], cu),
            lerp(ca.pos[1], cb ? cb.pos[1] : ca.pos[1], cu),
            lerp(ca.pos[2], cb ? cb.pos[2] : ca.pos[2], cu)
          );
          this.virtualCamCfg.target.set(
            lerp(ca.target[0], cb ? cb.target[0] : ca.target[0], cu),
            lerp(ca.target[1], cb ? cb.target[1] : ca.target[1], cu),
            lerp(ca.target[2], cb ? cb.target[2] : ca.target[2], cu)
          );
          this.virtualCamCfg.fov = lerp(ca.fov, cb ? cb.fov : ca.fov, cu);
        }
      }
      this.updateCamHelper();
    };

    // 步态摆动：直接改 rig 关节旋转（jointDeg 不动），停止/暂停时 restorePoses 复原
    // 返回 true=本次有摆动；false=静止（调用方负责恢复姿态）
    function applyWalkSwing(p, speed, dt) {
      var amp = clamp((speed - WALK_MIN_SPEED) / (WALK_MAX_SPEED - WALK_MIN_SPEED), 0, 1);
      var rig = p.rig;
      if (!rig || amp <= 0) return false;
      if (typeof p._walkPhase !== 'number' || !isFinite(p._walkPhase)) p._walkPhase = 0;
      // 步频随速度：约 1.8 步/秒（1.2m/s 时）
      p._walkPhase += dt * (1.6 + 2.6 * amp);
      var ph = p._walkPhase;

      var hipAmp = 22 * amp;     // 髋前后摆
      var kneeAmp = 34 * amp;    // 膝盖弯曲（后摆时最大）
      var armAmp = 13 * amp;     // 手臂反相摆
      var bobAmp = 0.025 * amp;  // 重心起伏

      var sinp = Math.sin(ph);
      var base = p.jointDeg || {};

      function swing(jointKey, addDeg) {
        var g = rig.joints[jointKey];
        if (!g) return;
        var deg = base[jointKey] || [0, 0, 0];
        g.rotation.set(deg2rad(deg[0] + addDeg), deg2rad(deg[1]), deg2rad(deg[2]));
      }

      swing('hipL', hipAmp * sinp);
      swing('hipR', -hipAmp * sinp);
      swing('kneeL', kneeAmp * Math.max(0, (1 - Math.sin(ph)) / 2));
      swing('kneeR', kneeAmp * Math.max(0, (1 + Math.sin(ph)) / 2));
      swing('shoulderL', -armAmp * sinp);
      swing('shoulderR', armAmp * sinp);
      // 重心轻微起伏：applyPuppetTransform 刚重置过基础值，这里直接叠加
      if (rig.hipsY) {
        rig.hipsY.position.y += bobAmp * Math.abs(Math.cos(ph));
      }
      p._walkSwung = true;
      return true;
    }

    // 静止但此前摆过：恢复 jointDeg 姿态
    function restoreSwing(editor, p) {
      if (!p._walkSwung) return;
      p._walkSwung = false;
      p._walkPhase = 0;
      editor.applyJointDeg(p);
    }
  }

  window.DirectorStageTimelineModule = { attach: attach };

})();
