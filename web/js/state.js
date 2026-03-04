
    const state = {
      ratio: '16:9',
      nodes: [],
      connections: [],
      imageConnections: [],
      firstFrameConnections: [],
      videoConnections: [],
      referenceConnections: [],
      nextNodeId: 1,
      nextConnId: 1,
      nextImgConnId: 1,
      nextFirstFrameConnId: 1,
      nextVideoConnId: 1,
      nextReferenceConnId: 1,
      nextScriptId: 1,
      selectedNodeId: null,
      selectedConnId: null,
      selectedImgConnId: null,
      selectedFirstFrameConnId: null,
      selectedVideoConnId: null,
      selectedReferenceConnId: null,
      drag: null,
      placing: null,
      connecting: null,
      panning: null,
      panX: 0,
      panY: 0,
      zoom: 1,
      timeline: {
        clips: [],
        audioClips: [],
        pillars: [],              // 柱子数组，每个柱子代表一个分镜的时间区域
        nextClipId: 1,
        nextAudioClipId: 1,
        selectedClipId: null,
        selectedAudioClipId: null,
        visible: false,
      },
      style: {
        name: '',
        referenceImageUrl: ''
      },
      defaultWorldId: null,
      worldCharacters: [],
      worldProps: [],
      worldLocations: [],
      editionInfo: { mode: 'community', mode_label: '社区版' },
      selectionMode: false,
      selecting: null,
      selectedNodeIds: [],
      topZIndex: 21,
      history: [],
      historyPointer: -1,
      historyLimit: 50,
      isRestoringHistory: false,
      debugMode: false
    };

    function normalizeVideoUrl(item){
      if(!item) return '';
      if(typeof item === 'string') return item;
      if(typeof item === 'object'){
        return item.url || item.video_url || item.videoUrl || item.file_url || item.fileUrl || item.oss_url || item.ossUrl || item.path || '';
      }
      return '';
    }

    function extractResultsArray(payload){
      if(!payload) return [];
      if(Array.isArray(payload)) return payload;
      if(typeof payload !== 'object') return [];

      if(Array.isArray(payload.results)) return payload.results;
      if(Array.isArray(payload.result)) return payload.result;
      if(Array.isArray(payload.videos)) return payload.videos;
      if(Array.isArray(payload.video_urls)) return payload.video_urls;
      if(Array.isArray(payload.videoUrls)) return payload.videoUrls;

      if(payload.data){
        const nested = extractResultsArray(payload.data);
        if(nested.length) return nested;
      }

      if(payload.output){
        const nested = extractResultsArray(payload.output);
        if(nested.length) return nested;
      }

      // 兼容某些返回为 { results: { videos: [...] } } 或 { result: { url: ... } }
      if(payload.results && typeof payload.results === 'object'){
        const nested = extractResultsArray(payload.results);
        if(nested.length) return nested;
        return [payload.results];
      }
      if(payload.result && typeof payload.result === 'object'){
        const nested = extractResultsArray(payload.result);
        if(nested.length) return nested;
        return [payload.result];
      }

      return [];
    }

    function isSameOriginUrl(url){
      try{
        const u = new URL(url, window.location.href);
        return u.origin === window.location.origin;
      } catch(e){
        return true;
      }
    }

    // 将相对路径转换为完整的HTTP地址
    function normalizeImageUrl(url){
      if(!url) return '';
      if(typeof url !== 'string') return '';

      // 已经是完整的URL
      if(url.startsWith('http://') || url.startsWith('https://')) return url;
      if(url.startsWith('data:') || url.startsWith('blob:')) return url;

      // 相对路径，转换为完整URL
      if(url.startsWith('/')){
        return `${window.location.origin}${url}`;
      }

      // 其他情况，返回原值
      return url;
    }

    function proxyImageUrl(url){
      if(!url) return '';
      if(typeof url !== 'string') return '';
      if(url.startsWith('data:') || url.startsWith('blob:')) return url;
      if(isSameOriginUrl(url)) return url;
      return `/api/proxy-image?url=${encodeURIComponent(url)}`;
    }

    function proxyDownloadUrl(url, filename){
      if(!url) return '';
      if(typeof url !== 'string') return '';
      if(url.startsWith('data:') || url.startsWith('blob:')) return url;
      if(isSameOriginUrl(url)) return url;
      const fn = filename ? `&filename=${encodeURIComponent(filename)}` : '';
      return `/api/download?url=${encodeURIComponent(url)}${fn}`;
    }

    const canvasEl = document.getElementById('canvas');
    const canvasContainer = document.getElementById('canvasContainer');
    const canvasWorld = document.getElementById('canvasWorld');
    const connectionsSvg = document.getElementById('connectionsSvg');
    const ratioSelectEl = document.getElementById('ratioSelect');
    const connDeleteBtn = document.getElementById('connDeleteBtn');
    const zoomInBtn = document.getElementById('zoomInBtn');
    const zoomOutBtn = document.getElementById('zoomOutBtn');
    const zoomLevelEl = document.getElementById('zoomLevel');
    const minimap = document.getElementById('minimap');
    const minimapContent = document.getElementById('minimapContent');
    const videoModal = document.getElementById('videoModal');
    const videoModalClose = document.getElementById('videoModalClose');
    const videoModalPlayer = document.getElementById('videoModalPlayer');
    const imageModal = document.getElementById('imageModal');
    const imageModalClose = document.getElementById('imageModalClose');
    const imageModalImg = document.getElementById('imageModalImg');
    const imageModalTitle = document.getElementById('imageModalTitle');

    const MINIMAP_WIDTH = 180;
    const MINIMAP_HEIGHT = 120;
    const MINIMAP_PADDING = 10;

    // 测试模式：URL添加 ?test=1 即可启用，不会真正调用API
    const TEST_MODE = new URLSearchParams(window.location.search).get('test') === '1';
    if(TEST_MODE){
      console.log('%c[TEST MODE] 测试模式已启用，API调用将被模拟', 'color: orange; font-weight: bold;');
    }

    // 获取URL参数中的工作流ID
    function getWorkflowIdFromUrl(){
      const params = new URLSearchParams(window.location.search);
      return params.get('id');
    }

    // 获取auth token
    function getAuthToken(){
      return localStorage.getItem('auth_token') || '';
    }

    function getUserId(){
      return localStorage.getItem('user_id') || '';
    }

    // 显示Toast消息
    function showToast(message, type = ''){
      const toast = document.getElementById('toast');
      toast.textContent = message;
      toast.className = 'toast ' + type;
      toast.classList.add('show');
      setTimeout(() => {
        toast.classList.remove('show');
      }, 3000);
    }

    // 自定义确认弹窗（替代 window.confirm，切Tab不会被自动取消）
    function showConfirmModal(message, opts = {}) {
      const title = opts.title || '确认';
      const confirmText = opts.confirmText || '确认';
      const cancelText = opts.cancelText || '取消';
      
      return new Promise((resolve) => {
        const overlay = document.createElement('div');
        overlay.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(15,23,42,0.65);display:flex;align-items:center;justify-content:center;z-index:10000;';
        
        const card = document.createElement('div');
        card.style.cssText = 'background:white;border-radius:12px;padding:24px;max-width:420px;width:90%;box-shadow:0 20px 60px rgba(0,0,0,0.3);';
        
        const titleEl = document.createElement('div');
        titleEl.style.cssText = 'font-size:16px;font-weight:600;margin-bottom:16px;color:#111827;';
        titleEl.textContent = title;
        
        const msgEl = document.createElement('div');
        msgEl.style.cssText = 'font-size:14px;color:#374151;white-space:pre-wrap;line-height:1.6;margin-bottom:24px;';
        msgEl.textContent = message;
        
        const btnRow = document.createElement('div');
        btnRow.style.cssText = 'display:flex;justify-content:flex-end;gap:12px;';
        
        const cancelBtn = document.createElement('button');
        cancelBtn.style.cssText = 'padding:8px 20px;border:1px solid #d1d5db;border-radius:8px;background:white;cursor:pointer;font-size:14px;color:#374151;';
        cancelBtn.textContent = cancelText;
        
        const confirmBtn = document.createElement('button');
        confirmBtn.style.cssText = 'padding:8px 20px;border:none;border-radius:8px;background:#3b82f6;color:white;cursor:pointer;font-size:14px;font-weight:500;';
        confirmBtn.textContent = confirmText;
        
        function close(result) {
          document.body.removeChild(overlay);
          resolve(result);
        }
        
        cancelBtn.addEventListener('click', () => close(false));
        confirmBtn.addEventListener('click', () => close(true));
        overlay.addEventListener('click', (e) => {
          if(e.target === overlay) close(false);
        });
        
        btnRow.appendChild(cancelBtn);
        btnRow.appendChild(confirmBtn);
        card.appendChild(titleEl);
        card.appendChild(msgEl);
        card.appendChild(btnRow);
        overlay.appendChild(card);
        document.body.appendChild(overlay);
        confirmBtn.focus();
      });
    }
