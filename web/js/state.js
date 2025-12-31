    const state = {
      ratio: '16:9',
      nodes: [],
      connections: [],
      imageConnections: [],
      firstFrameConnections: [],
      nextNodeId: 1,
      nextConnId: 1,
      nextImgConnId: 1,
      nextFirstFrameConnId: 1,
      selectedNodeId: null,
      selectedConnId: null,
      selectedImgConnId: null,
      selectedFirstFrameConnId: null,
      drag: null,
      connecting: null,
      panning: null,
      panX: 0,
      panY: 0,
      zoom: 1,
      timeline: {
        clips: [],
        nextClipId: 1,
        selectedClipId: null,
        visible: false,
      },
      style: {
        name: '',
        referenceImageUrl: ''
      },
      defaultWorldId: null,
      selectionMode: false,
      selecting: null,
      selectedNodeIds: [],
      topZIndex: 21,
      history: [],
      historyPointer: -1,
      historyLimit: 50,
      isRestoringHistory: false
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
