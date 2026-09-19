    /**
     * 画布文件拖放：从文件夹拖入图片/视频文件，直接在落点创建对应节点。
     *
     * 实现方式：drop 后调用现有 createImageNode / createVideoNode 建节点，
     * 再把 File 通过 DataTransfer 注入节点的 <input type="file"> 并派发
     * change 事件，完整复用既有的上传/预览/连线同步/自动保存逻辑。
     */
    (function () {
      const container = document.getElementById('canvasContainer');
      if (!container) return;

      // 与后端 utils/media_upload.py 白名单保持一致
      const IMAGE_EXTS = ['jpg', 'jpeg', 'png', 'webp', 'gif', 'bmp'];
      const VIDEO_EXTS = ['mp4', 'mov', 'webm', 'avi', 'mkv'];

      function translate(key, fallback, params) {
        const v = window.t ? window.t(key, params || {}) : null;
        return v && v !== key ? v : fallback;
      }

      function fileExt(name) {
        const idx = typeof name === 'string' ? name.lastIndexOf('.') : -1;
        return idx >= 0 ? name.slice(idx + 1).toLowerCase() : '';
      }

      function isImageFile(file) {
        return (file.type && file.type.startsWith('image/')) || IMAGE_EXTS.includes(fileExt(file.name));
      }

      function isVideoFile(file) {
        return (file.type && file.type.startsWith('video/')) || VIDEO_EXTS.includes(fileExt(file.name));
      }

      function hasFiles(e) {
        const types = e.dataTransfer && e.dataTransfer.types;
        if (!types) return false;
        for (let i = 0; i < types.length; i++) {
          if (types[i] === 'Files') return true;
        }
        return false;
      }

      function maxImageSizeBytes() {
        const cfg = window.__wfUploadConfig;
        const mb = cfg && typeof cfg.max_image_size_mb === 'number' ? cfg.max_image_size_mb : 10;
        return mb * 1024 * 1024;
      }

      /**
       * 超限图片前端压缩（utils.js 的 compressImageFile）。
       * 返回压缩后的新 File；不可压缩（GIF/解码失败/工具缺失）返回 null。
       */
      async function compressOversizeImage(file, maxBytes) {
        if (typeof compressImageFile !== 'function') return null;
        try {
          const compressed = await compressImageFile(file, maxBytes);
          if (compressed && compressed !== file) return compressed;
        } catch (err) {
          console.error('图片压缩失败:', err);
        }
        return null;
      }

      /**
       * 把 File 注入节点的 file input 并触发 change，复用现有上传逻辑。
       * 浏览器原生 drop 到 file input 会填充 files 但不派发 change，统一走这里。
       */
      function applyFileToInput(inputEl, file) {
        try {
          const dt = new DataTransfer();
          dt.items.add(file);
          inputEl.files = dt.files;
          inputEl.dispatchEvent(new Event('change'));
          return true;
        } catch (err) {
          console.error('拖放文件注入节点失败:', err);
          return false;
        }
      }

      // dragenter/dragleave 在子元素间移动会成对触发，用计数器维持高亮
      let dragDepth = 0;

      container.addEventListener('dragenter', (e) => {
        if (!hasFiles(e)) return;
        e.preventDefault();
        dragDepth++;
        container.classList.add('drag-over');
      });

      container.addEventListener('dragover', (e) => {
        if (!hasFiles(e)) return;
        e.preventDefault();
        if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy';
        if (dragDepth === 0) dragDepth = 1;
        container.classList.add('drag-over');
      });

      container.addEventListener('dragleave', () => {
        if (dragDepth > 0) dragDepth--;
        if (dragDepth === 0) container.classList.remove('drag-over');
      });

      container.addEventListener('drop', async (e) => {
        if (!hasFiles(e)) return;
        e.preventDefault();
        dragDepth = 0;
        container.classList.remove('drag-over');

        const files = e.dataTransfer ? Array.from(e.dataTransfer.files) : [];
        if (files.length === 0) return;

        // 落点恰好是图片/视频节点的 file input：让原生填充的 files 生效（补派 change）
        const directInput = e.target && e.target.closest ? e.target.closest('.image-file, .video-file') : null;
        if (directInput && files.length === 1) {
          applyFileToInput(directInput, files[0]);
          return;
        }

        const containerRect = container.getBoundingClientRect();
        const dropX = (e.clientX - containerRect.left - state.panX) / state.zoom;
        const dropY = Math.max(MIN_NODE_Y, (e.clientY - containerRect.top - state.panY) / state.zoom);

        const maxImageBytes = maxImageSizeBytes();
        const maxImageMb = Math.round(maxImageBytes / 1024 / 1024);
        let created = 0;
        let unsupported = 0;
        let offset = 0;

        for (const file of files) {
          if (isImageFile(file)) {
            let uploadTarget = file;
            if (file.size > maxImageBytes) {
              // 超限图片先在前端压缩（GIF 等不可压缩格式返回 null）
              const compressed = await compressOversizeImage(file, maxImageBytes);
              if (!compressed) {
                showToast(translate('canvas_drop_image_too_large', `图片不能超过${maxImageMb}MB：${file.name}`, { max: maxImageMb, name: file.name }), 'error');
                offset += 40;
                continue;
              }
              uploadTarget = compressed;
              const compressedMb = (compressed.size / 1024 / 1024).toFixed(1);
              showToast(translate('image_auto_compressed', `原图超过${maxImageMb}MB，已自动压缩至${compressedMb}MB`, { max: maxImageMb, size: compressedMb }), 'success');
            }
            const nodeId = createImageNode({ x: dropX + offset, y: dropY + offset, checkCollision: true });
            const inputEl = canvasEl.querySelector(`.node[data-node-id="${nodeId}"] .image-file`);
            if (inputEl) applyFileToInput(inputEl, uploadTarget);
            created++;
          } else if (isVideoFile(file)) {
            const nodeId = createVideoNode({ x: dropX + offset, y: dropY + offset, checkCollision: true });
            const inputEl = canvasEl.querySelector(`.node[data-node-id="${nodeId}"] .video-file`);
            if (inputEl) applyFileToInput(inputEl, file);
            created++;
          } else {
            unsupported++;
          }
          offset += 40;
        }

        if (unsupported > 0) {
          showToast(translate('canvas_drop_only_media', '仅支持拖入图片/视频文件'), 'warning');
        }
        if (created > 1) {
          showToast(translate('canvas_drop_files_added', `已创建 ${created} 个节点`, { count: created }), 'success');
        }
      });
    })();
