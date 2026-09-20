// ============================
// director_stage_timeline.js - 导演台时间轴
// 关键帧调度：记录/拖动关键帧控制角色与相机移动；播放时插值驱动 + 行走摆动
// 由 director_stage_editor.js 在 IIFE 内调用 window.DirectorStageTimelineModule
// .attach(DirectorEditor, helpers) 挂载原型方法，编辑器负责在生命周期中调用：
//   restoreFromData → restoreTimeline(d)
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

  function attach(DirectorEditor, helpers) {
    var clamp = helpers.clamp;
    var round2 = helpers.round2;
    var deg2rad = helpers.deg2rad;

    // ---------- 数据恢复 / 序列化 ----------

    DirectorEditor.prototype.restoreTimeline = function (d) {
      if (!this.tl) this.tl = {};
      var src = (d && d.timeline) || null;
      this.tl.duration = DEFAULT_DURATION;
      this.tl.keys = [];
      this.tl.playhead = 0;
      this.tl.playing = false;
      this.tl.scrubbing = false;
      this.tl.keyDrag = null;   // {index, moved}
      this.tl.lastFrameAt = 0;
      if (!src) return;
      if (typeof src.duration === 'number' && isFinite(src.duration)) {
        this.tl.duration = clamp(src.duration, MIN_DURATION, MAX_DURATION);
      }
      if (Array.isArray(src.keys)) {
        var self = this;
        this.tl.keys = src.keys
          .filter(function (k) { return k && typeof k.t === 'number' && isFinite(k.t); })
          .map(function (k) { return sanitizeKey(k, self.tl.duration); })
          .sort(function (a, b) { return a.t - b.t; });
      }
    };

    function sanitizeKey(k, duration) {
      var puppets = {};
      if (k.puppets && typeof k.puppets === 'object') {
        Object.keys(k.puppets).forEach(function (pid) {
          var v = k.puppets[pid];
          if (!v || typeof v !== 'object') return;
          puppets[pid] = {
            x: num(v.x), z: num(v.z), rotY: num(v.rotY)
          };
        });
      }
      var cam = k.camera || {};
      return {
        t: clamp(num(k.t), 0, duration),
        puppets: puppets,
        camera: {
          pos: [num(cam.pos && cam.pos[0]), num(cam.pos && cam.pos[1]), num(cam.pos && cam.pos[2])],
          target: [num(cam.target && cam.target[0]), num(cam.target && cam.target[1]), num(cam.target && cam.target[2])],
          fov: clamp(num(cam.fov) || 35, 10, 120)
        }
      };
    }

    function num(v) { return (typeof v === 'number' && isFinite(v)) ? v : 0; }

    DirectorEditor.prototype.serializeTimeline = function () {
      var liveIds = {};
      this.puppets.forEach(function (p) { liveIds[p.id] = true; });
      var keys = this.tl.keys.map(function (k) {
        var puppets = {};
        // 已删除人偶的关键帧数据丢弃，避免幽灵数据反复落盘
        Object.keys(k.puppets).forEach(function (pid) {
          if (!liveIds[pid]) return;
          var v = k.puppets[pid];
          puppets[pid] = { x: round2(v.x), z: round2(v.z), rotY: round2(v.rotY) };
        });
        var c = k.camera;
        return {
          t: round2(k.t),
          puppets: puppets,
          camera: {
            pos: [round2(c.pos[0]), round2(c.pos[1]), round2(c.pos[2])],
            target: [round2(c.target[0]), round2(c.target[1]), round2(c.target[2])],
            fov: Math.round(c.fov)
          }
        };
      });
      return { duration: round2(this.tl.duration), keys: keys };
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
          '<button type="button" class="ds-mini-btn" id="dsTlDelKeyBtn" title="删除当前时间附近的关键帧">✕ 删除关键帧</button>' +
          '<span class="ds-tl-hint">摆位形 → 记录关键帧 → 拖动时间轴换位形 → 再记录；播放预览角色走位与运镜</span>' +
        '</div>' +
        '<div class="ds-tl-track" id="dsTlTrack">' +
          '<div class="ds-tl-ruler" id="dsTlRuler"></div>' +
          '<div class="ds-tl-keys" id="dsTlKeys"></div>' +
          '<div class="ds-tl-playhead" id="dsTlPlayhead"><div class="ds-tl-playhead-cap"></div></div>' +
        '</div>';

      var self = this;
      var track = this.$('dsTlTrack');

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
        // 超出新时长的关键帧吸附到末端（近似时刻合并）
        var merged = [];
        self.tl.keys.sort(function (a, b) { return a.t - b.t; }).forEach(function (k) {
          k.t = Math.min(k.t, v);
          var last = merged[merged.length - 1];
          if (last && Math.abs(last.t - k.t) <= KEY_MERGE_WINDOW) {
            last.puppets = k.puppets; last.camera = k.camera;
          } else {
            merged.push(k);
          }
        });
        self.tl.keys = merged;
        self.setPlayhead(Math.min(self.tl.playhead, v));
        self.markDirty();
        self.renderTimeline();
      });

      // 轨道交互：空白按下=拖播放头（scrub）；关键帧按下=拖动改时刻（原位点击=跳转）
      function trackTimeFromEvent(e) {
        var rect = track.getBoundingClientRect();
        var u = clamp((e.clientX - rect.left) / Math.max(rect.width, 1), 0, 1);
        return u * self.tl.duration;
      }

      this.on(track, 'mousedown', function (e) {
        if (e.button !== 0) return;
        e.preventDefault();
        var isKey = e.target.classList && e.target.classList.contains('ds-tl-key');
        if (isKey) {
          var idx = parseInt(e.target.dataset.index, 10);
          if (isFinite(idx) && self.tl.keys[idx]) {
            self.pauseTimeline();
            self.tl.keyDrag = { index: idx, moved: false };
          }
        } else {
          self.pauseTimeline();
          self.tl.scrubbing = true;
          self.setPlayhead(trackTimeFromEvent(e));
        }
      });

      this.on(window, 'mousemove', function (e) {
        if (self.tl.scrubbing) {
          self.setPlayhead(trackTimeFromEvent(e));
        } else if (self.tl.keyDrag) {
          var t = trackTimeFromEvent(e);
          var k = self.tl.keys[self.tl.keyDrag.index];
          if (!k) { self.tl.keyDrag = null; return; }
          if (!self.tl.keyDrag.moved) {
            // 移动超过 3px 才视为拖动，否则当作点击跳转
            if (Math.abs(t - k.t) * (track.getBoundingClientRect().width / Math.max(self.tl.duration, 0.01)) < 3) return;
            self.tl.keyDrag.moved = true;
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
          var k = self.tl.keys[drag.index];
          if (drag.moved && k) {
            // 拖动后按新时刻重排序；与相近关键帧合并
            self.tl.keys.sort(function (a, b) { return a.t - b.t; });
            var merged = [];
            self.tl.keys.forEach(function (item) {
              var last = merged[merged.length - 1];
              if (last && last !== item && Math.abs(last.t - item.t) <= KEY_MERGE_WINDOW) {
                last.puppets = item.puppets; last.camera = item.camera;
              } else {
                merged.push(item);
              }
            });
            self.tl.keys = merged;
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

    // 完整重绘（时长/关键帧变化时）
    DirectorEditor.prototype.renderTimeline = function () {
      if (!this.tl) return;
      var ruler = this.$('dsTlRuler');
      var keysEl = this.$('dsTlKeys');
      if (!ruler || !keysEl) return;
      var dur = this.tl.duration || DEFAULT_DURATION;

      // 标尺：每秒一刻度
      var html = '';
      var step = dur > 24 ? 5 : 1;
      for (var s = 0; s <= dur + 1e-6; s += step) {
        html += '<div class="ds-tl-tick" style="left:' + (s / dur * 100) + '%"><span>' + s + 's</span></div>';
      }
      ruler.innerHTML = html;

      var self = this;
      keysEl.innerHTML = this.tl.keys.map(function (k, i) {
        return '<div class="ds-tl-key" data-index="' + i + '" title="' + k.t.toFixed(1) + 's 关键帧（拖动改时刻）" style="left:' + (k.t / dur * 100) + '%"></div>';
      }).join('');

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

    DirectorEditor.prototype.recordTimelineKey = function () {
      var t = clamp(this.tl.playhead, 0, this.tl.duration);
      var key = {
        t: round2(t),
        puppets: {},
        camera: {
          pos: [round2(this.virtualCamCfg.pos.x), round2(this.virtualCamCfg.pos.y), round2(this.virtualCamCfg.pos.z)],
          target: [round2(this.virtualCamCfg.target.x), round2(this.virtualCamCfg.target.y), round2(this.virtualCamCfg.target.z)],
          fov: Math.round(this.virtualCamCfg.fov)
        }
      };
      this.puppets.forEach(function (p) {
        key.puppets[p.id] = { x: round2(p.x), z: round2(p.z), rotY: round2(p.rotY) };
      });

      // 相近时刻覆盖旧关键帧（沿用旧时刻，避免标记漂移）
      var replaced = false;
      for (var i = 0; i < this.tl.keys.length; i++) {
        if (Math.abs(this.tl.keys[i].t - key.t) <= KEY_MERGE_WINDOW) {
          key.t = this.tl.keys[i].t;
          this.tl.keys[i] = key;
          replaced = true;
          break;
        }
      }
      if (!replaced) {
        this.tl.keys.push(key);
        this.tl.keys.sort(function (a, b) { return a.t - b.t; });
      }
      this.markDirty();
      this.renderTimeline();
      this.setStatus('已记录 ' + key.t.toFixed(1) + 's 关键帧（共 ' + this.tl.keys.length + ' 个）');
    };

    DirectorEditor.prototype.deleteTimelineKeyAtPlayhead = function () {
      var t = this.tl.playhead;
      var idx = -1;
      var best = KEY_DELETE_RADIUS;
      for (var i = 0; i < this.tl.keys.length; i++) {
        var d = Math.abs(this.tl.keys[i].t - t);
        if (d <= best) { best = d; idx = i; }
      }
      if (idx < 0) {
        this.setStatus('当前时间附近没有关键帧');
        return;
      }
      this.tl.keys.splice(idx, 1);
      this.markDirty();
      this.renderTimeline();
      this.setStatus('已删除关键帧');
    };

    // ---------- 播放 ----------

    DirectorEditor.prototype.togglePlay = function () {
      if (this.tl.playing) {
        this.pauseTimeline();
        return;
      }
      if (!this.tl.keys.length) {
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
      // 回到首个关键帧位形（若有）
      this.applyTimelineAt(0);
      this.renderTimelineTime();
      this.setStatus('已停止');
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

    // 应用 t 时刻插值位形：puppet x/z/rotY + 相机 pos/target/fov + 行走摆动
    DirectorEditor.prototype.applyTimelineAt = function (t, dt) {
      var keys = this.tl.keys;
      if (!keys.length) return;
      var pair = bracketKeys(keys, t);
      var k0 = pair[0], k1 = pair[1];
      var span = k1 ? Math.max(k1.t - k0.t, 1e-3) : 1;
      var u = k1 ? clamp((t - k0.t) / span, 0, 1) : 0;

      var self = this;
      var swingOn = !!(this.tl.playing && dt); // 仅真实播放时叠加步态摆动；scrub/停止只做静态插值
      this.puppets.forEach(function (p) {
        var a = k0.puppets[p.id];
        if (!a) return; // 该关键帧未含此人偶：保持当前编辑位形
        var b = k1 ? k1.puppets[p.id] : null;
        if (!b) {
          p.x = a.x; p.z = a.z; p.rotY = a.rotY;
        } else {
          p.x = lerp(a.x, b.x, u);
          p.z = lerp(a.z, b.z, u);
          p.rotY = lerpAngle(a.rotY, b.rotY, u);
        }
        self.applyPuppetTransform(p);

        // 行走摆动（播放动作）：位移速度超阈值时叠加步态关节摆动；
        // 非播放态或静止时恢复 jointDeg 姿态
        if (swingOn && b) {
          var speed = Math.hypot(b.x - a.x, b.z - a.z) / span;
          applyWalkSwing(p, speed, dt) || restoreSwing(self, p);
        } else {
          restoreSwing(self, p);
        }
      });

      var ca = k0.camera, cb = k1 ? k1.camera : null;
      this.virtualCamCfg.pos.set(
        lerp(ca.pos[0], cb ? cb.pos[0] : ca.pos[0], u),
        lerp(ca.pos[1], cb ? cb.pos[1] : ca.pos[1], u),
        lerp(ca.pos[2], cb ? cb.pos[2] : ca.pos[2], u)
      );
      this.virtualCamCfg.target.set(
        lerp(ca.target[0], cb ? cb.target[0] : ca.target[0], u),
        lerp(ca.target[1], cb ? cb.target[1] : ca.target[1], u),
        lerp(ca.target[2], cb ? cb.target[2] : ca.target[2], u)
      );
      this.virtualCamCfg.fov = lerp(ca.fov, cb ? cb.fov : ca.fov, u);
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
