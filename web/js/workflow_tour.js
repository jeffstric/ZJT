(function(){
  const TOUR_KEY = 'workflow_tour_done_v1';
  const portal = document.getElementById('workflowTourPortal');
  const startBtn = document.getElementById('tourStartBtn');

  if(!portal || !startBtn){
    return;
  }

  const ensureAddMenuOpen = () => {
    const addMenu = document.getElementById('addMenu');
    if(addMenu && !addMenu.classList.contains('show')){
      addMenu.classList.add('show');
    }
  };

  const TOUR_PROGRESS_KEY = 'workflow_tour_progress_v1';
  const steps = [
    {
      id: 'selectWorld',
      title: '选择世界',
      description: '在开始搭建工作流前，请先选择故事发生的世界（占位文案，后续可替换为正式说明）。',
      target: () => document.querySelector('#defaultWorldSelect'),
      hint: '若没有可用世界，可以点击右侧 “+” 先创建一个。'
    },
    {
      id: 'addLocation',
      title: '添加场景',
      description: '点击左侧的 “+” 按钮，并在菜单中选择“场景”，为故事补充地点。',
      target: () => document.querySelector('#menuAddLocation'),
      before: ensureAddMenuOpen,
      hint: '菜单保持展开状态即可连续创建多个场景。',
      missingHint: '请先点击左侧 “+” 展开菜单后再选择场景。'
    },
    {
      id: 'addCharacter',
      title: '添加角色',
      description: '继续在 “+” 菜单中选择“角色”，建立人物素材，后续镜头可直接引用。',
      target: () => document.querySelector('#menuAddCharacter'),
      before: ensureAddMenuOpen,
      hint: '添加角色后，可在角色面板中维护更多信息。',
      missingHint: '若看不到选项，请先展开左侧 “+” 菜单。'
    },
    {
      id: 'addScript',
      title: '添加剧本',
      description: '通过 “+” 菜单选择“剧本”节点，录入剧情文本或上传现有脚本文件。',
      target: () => document.querySelector('#menuAddScript'),
      before: ensureAddMenuOpen,
      hint: '录入剧本后即可拆分分镜组，形成后续节点。'
    },
    {
      id: 'inputScript',
      title: '输入剧本内容',
      description: '在剧本节点中的文本框内输入剧情内容。',
      target: () => document.querySelector('.script-textarea'),
      hint: '输入剧本内容后，即可进行下一步拆分分镜组。',
      missingHint: '请先添加剧本节点后再输入内容。'
    },
    {
      id: 'splitShots',
      title: '独立分镜',
      description: '在分镜组节点中点击"独立分镜"按钮，拆分出单独的分镜节点。',
      target: () => document.querySelector('.shot-group-generate-btn'),
      hint: '点击独立分镜按钮后，即可完成新手指引。',
      missingHint: '请先在剧本节点拆分分镜组。'
    },
    {
      id: 'generateStoryboard',
      title: '生成分镜图',
      description: '在分镜节点中点击"生成分镜图"按钮，生成可视化画面。',
      target: () => document.querySelector('.shot-frame-generate-btn'),
      hint: '点击生成分镜图按钮后，即可完成新手指引。',
      missingHint: '请先在分镜组节点，生成分镜节点。'
    },
    {
      id: 'generateVideo',
      title: '生成视频',
      description: '在分镜节点中点击"生成视频"按钮，生成最终视频。',
      target: () => document.querySelector('.shot-frame-generate-video-btn'),
      hint: '点击生成视频按钮后，即可完成新手指引。',
      missingHint: '请先生成分镜图。'
    },
    {
      id: 'addToTimeline',
      title: '加入时间轴',
      description: '在视频节点中点击"加时间轴"按钮，将视频添加到时间轴进行编辑。',
      target: () => document.querySelector('.video-add-timeline'),
      hint: '点击加时间轴按钮后，即可完成所有新手指引！',
      missingHint: '请在分镜节点点击生成视频按钮。'
    }
  ];
  const TOTAL_STEPS = steps.length;

  portal.innerHTML = `
    <div class="tour-overlay" data-tour-dismiss="true"></div>
    <div class="tour-highlight"></div>
    <div class="tour-popover" role="dialog" aria-live="polite">
      <div class="tour-step-label"></div>
      <h3></h3>
      <p class="tour-desc"></p>
      <div class="tour-hint" style="display:none;"></div>
      <div class="tour-controls">
        <button class="tour-btn-skip" type="button">跳过</button>
        <button class="tour-btn-prev" type="button">上一步</button>
        <div class="tour-progress"></div>
        <button class="tour-btn-next" type="button">下一步</button>
      </div>
    </div>
  `;

  const overlayEl = portal.querySelector('.tour-overlay');
  const highlightEl = portal.querySelector('.tour-highlight');
  const popoverEl = portal.querySelector('.tour-popover');
  const stepLabelEl = portal.querySelector('.tour-step-label');
  const titleEl = popoverEl.querySelector('h3');
  const descEl = popoverEl.querySelector('.tour-desc');
  const hintEl = popoverEl.querySelector('.tour-hint');
  const skipBtn = popoverEl.querySelector('.tour-btn-skip');
  const prevBtn = popoverEl.querySelector('.tour-btn-prev');
  const nextBtn = popoverEl.querySelector('.tour-btn-next');
  const progressEl = popoverEl.querySelector('.tour-progress');

  let currentStepIndex = 0;
  let active = false;
  let renderPending = false;
  let completedSteps = (() => {
    try{
      const stored = parseInt(localStorage.getItem(TOUR_PROGRESS_KEY), 10);
      if(Number.isFinite(stored)){
        return Math.min(Math.max(stored, 0), TOTAL_STEPS);
      }
    }catch(err){
      console.warn('[workflow tour] failed to read progress', err);
    }
    return 0;
  })();

  const resolveTarget = (step) => {
    try{
      if(typeof step.target === 'function'){
        return step.target();
      }
      if(typeof step.target === 'string'){
        return document.querySelector(step.target);
      }
    }catch(error){
      console.warn('[workflow tour] resolve target fail:', error);
    }
    return null;
  };

  const isVisible = (el) => {
    if(!el) return false;
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  };

  const positionPopover = (rect) => {
    const padding = 16;
    const popWidth = popoverEl.offsetWidth || 320;
    const popHeight = popoverEl.offsetHeight || 180;

    let left;
    let top;

    if(rect){
      left = rect.left + rect.width / 2 - popWidth / 2;
      top = rect.bottom + padding;

      if(top + popHeight > window.innerHeight - padding){
        top = rect.top - popHeight - padding;
      }
      if(top < padding){
        top = padding;
      }

      const minLeft = padding;
      const maxLeft = window.innerWidth - popWidth - padding;
      left = Math.min(Math.max(left, minLeft), Math.max(maxLeft, minLeft));
    }else{
      left = (window.innerWidth - popWidth) / 2;
      top = window.innerHeight * 0.35 - popHeight / 2;
    }

    popoverEl.style.left = `${Math.max(left, 12)}px`;
    popoverEl.style.top = `${Math.max(top, 12)}px`;
  };

  const updateHighlight = (rect) => {
    if(!rect){
      highlightEl.style.opacity = '0';
      return;
    }
    const padding = 12;
    highlightEl.style.opacity = '1';
    highlightEl.style.width = `${rect.width + padding * 2}px`;
    highlightEl.style.height = `${rect.height + padding * 2}px`;
    highlightEl.style.left = `${rect.left - padding}px`;
    highlightEl.style.top = `${rect.top - padding}px`;
  };

  const lockMaskEl = document.getElementById('tourLockMask');
  const worldSelectEl = document.getElementById('defaultWorldSelect');
  const createWorldBtn = document.getElementById('createWorldBtn');
  const createWorldModal = document.getElementById('createWorldModal');
  const createWorldSaveBtn = document.getElementById('createWorldSaveBtn');
  const createWorldCancelBtn = document.getElementById('createWorldCancelBtn');
  const WORLD_STEP_ID = 'selectWorld';
  const LOCATION_STEP_ID = 'addLocation';
  const CHARACTER_STEP_ID = 'addCharacter';
  const SCRIPT_STEP_ID = 'addScript';
  const INPUT_SCRIPT_STEP_ID = 'inputScript';
  const SPLIT_SHOTS_STEP_ID = 'splitShots';
  const GENERATE_STORYBOARD_STEP_ID = 'generateStoryboard';
  const GENERATE_VIDEO_STEP_ID = 'generateVideo';
  const ADD_TO_TIMELINE_STEP_ID = 'addToTimeline';
  const WORLD_MODAL_HINT = '填写信息后点击“创建”即可继续下一步';
  const WORLD_CREATE_EVENT = 'worldCreateSuccess';
  let worldStepHandler = null;
  let worldModalHandler = null;
  let worldModalCancelHandler = null;
  let worldModalCloseHandler = null;
  const locationBtn = document.getElementById('menuAddLocation');
  const characterBtn = document.getElementById('menuAddCharacter');
  const scriptBtn = document.getElementById('menuAddScript');
  const menuItemHandlers = new Map();
  const scriptInputHandlers = new Map();
  let scriptInputObserver = null;
  let splitShotsHandler = null;
  let generateStoryboardHandler = null;
  let generateVideoHandler = null;
  let addToTimelineHandler = null;

  const attachMenuItemHandler = (stepId, menuItemEl) => {
    if(!menuItemEl || menuItemHandlers.has(stepId)){
      return;
    }
    const handler = () => {
      if(steps[currentStepIndex]?.id !== stepId){
        return;
      }
      detachMenuItemHandler(stepId);
      completeStepAndExit();
    };
    menuItemHandlers.set(stepId, handler);
    menuItemEl.addEventListener('click', handler);
  };

  const detachMenuItemHandler = (stepId) => {
    const handler = menuItemHandlers.get(stepId);
    if(!handler){
      return;
    }
    const menuItemEl = stepId === LOCATION_STEP_ID ? locationBtn : 
                       stepId === CHARACTER_STEP_ID ? characterBtn :
                       stepId === SCRIPT_STEP_ID ? scriptBtn : null;
    if(menuItemEl){
      menuItemEl.removeEventListener('click', handler);
    }
    menuItemHandlers.delete(stepId);
  };

  const detachAllMenuItemHandlers = () => {
    menuItemHandlers.forEach((handler, stepId) => {
      detachMenuItemHandler(stepId);
    });
  };

  const persistCompletedSteps = (value) => {
    const clamped = Math.min(Math.max(value, 0), TOTAL_STEPS);
    if(clamped === completedSteps){
      return;
    }
    completedSteps = clamped;
    try{
      localStorage.setItem(TOUR_PROGRESS_KEY, String(clamped));
    }catch(err){
      console.warn('[workflow tour] failed to persist progress', err);
    }
  };

  const updateTourButtonLabel = () => {
    if(completedSteps <= 0){
      startBtn.textContent = '新手指引';
    }else if(completedSteps >= TOTAL_STEPS){
      startBtn.textContent = '新手指引完成';
    }else{
      startBtn.textContent = `新手指引${completedSteps + 1}/${TOTAL_STEPS}`;
    }
  };

  const markStepCompleted = (stepIndex) => {
    if(stepIndex < 0){
      return;
    }
    const nextCompleted = Math.max(completedSteps, stepIndex + 1);
    if(nextCompleted !== completedSteps){
      persistCompletedSteps(nextCompleted);
      if(nextCompleted >= TOTAL_STEPS){
        try{
          localStorage.setItem(TOUR_KEY, '1');
        }catch(error){
          console.warn('[workflow tour] failed to persist state', error);
        }
      }
      updateTourButtonLabel();
    }
  };

  const completeStepAndExit = () => {
    markStepCompleted(currentStepIndex);
    endTour(false);
  };

  const attachScriptInputHandler = () => {
    const bindTextareas = () => {
      let hasTextarea = false;
      const textareas = document.querySelectorAll('.script-textarea');
      textareas.forEach((textarea) => {
        hasTextarea = true;
        if(scriptInputHandlers.has(textarea)){
          if((textarea.value || '').trim().length > 0){
            scriptInputHandlers.get(textarea)?.call(textarea, { target: textarea });
          }
          return;
        }
        const handler = () => {
          if(steps[currentStepIndex]?.id !== INPUT_SCRIPT_STEP_ID){
            return;
          }
          const value = textarea.value || '';
          if(value.trim().length > 0){
            detachScriptInputHandler();
            completeStepAndExit();
          }
        };
        textarea.addEventListener('input', handler);
        scriptInputHandlers.set(textarea, handler);
        if((textarea.value || '').trim().length > 0){
          handler();
        }
      });
      return hasTextarea;
    };

    if(bindTextareas()){
      if(!scriptInputObserver){
        scriptInputObserver = new MutationObserver(() => {
          bindTextareas();
        });
        scriptInputObserver.observe(document.body, { childList: true, subtree: true });
      }
      return;
    }

    if(!scriptInputObserver){
      scriptInputObserver = new MutationObserver(() => {
        if(bindTextareas()){
          scriptInputObserver?.disconnect();
          scriptInputObserver = new MutationObserver(() => {
            bindTextareas();
          });
          scriptInputObserver.observe(document.body, { childList: true, subtree: true });
        }
      });
      scriptInputObserver.observe(document.body, { childList: true, subtree: true });
    }
  };

  const detachScriptInputHandler = () => {
    scriptInputHandlers.forEach((handler, textarea) => {
      textarea.removeEventListener('input', handler);
    });
    scriptInputHandlers.clear();
    if(scriptInputObserver){
      scriptInputObserver.disconnect();
      scriptInputObserver = null;
    }
  };

  const attachSplitShotsHandler = () => {
    if(splitShotsHandler){
      return;
    }
    const checkAndAttach = () => {
      const btn = document.querySelector('.shot-group-generate-btn');
      if(!btn){
        return false;
      }
      splitShotsHandler = () => {
        if(steps[currentStepIndex]?.id !== SPLIT_SHOTS_STEP_ID){
          return;
        }
        detachSplitShotsHandler();
        completeStepAndExit();
      };
      btn.addEventListener('click', splitShotsHandler);
      return true;
    };
    if(!checkAndAttach()){
      const observer = new MutationObserver(() => {
        if(checkAndAttach()){
          observer.disconnect();
        }
      });
      observer.observe(document.body, { childList: true, subtree: true });
    }
  };

  const detachSplitShotsHandler = () => {
    if(!splitShotsHandler){
      return;
    }
    const btn = document.querySelector('.shot-group-generate-btn');
    if(btn){
      btn.removeEventListener('click', splitShotsHandler);
    }
    splitShotsHandler = null;
  };

  const attachGenerateStoryboardHandler = () => {
    if(generateStoryboardHandler){
      return;
    }
    const checkAndAttach = () => {
      const btn = document.querySelector('.shot-frame-generate-btn');
      if(!btn){
        return false;
      }
      generateStoryboardHandler = () => {
        if(steps[currentStepIndex]?.id !== GENERATE_STORYBOARD_STEP_ID){
          return;
        }
        detachGenerateStoryboardHandler();
        completeStepAndExit();
      };
      btn.addEventListener('click', generateStoryboardHandler);
      return true;
    };
    if(!checkAndAttach()){
      const observer = new MutationObserver(() => {
        if(checkAndAttach()){
          observer.disconnect();
        }
      });
      observer.observe(document.body, { childList: true, subtree: true });
    }
  };

  const detachGenerateStoryboardHandler = () => {
    if(!generateStoryboardHandler){
      return;
    }
    const btn = document.querySelector('.shot-frame-generate-btn');
    if(btn){
      btn.removeEventListener('click', generateStoryboardHandler);
    }
    generateStoryboardHandler = null;
  };

  const attachGenerateVideoHandler = () => {
    if(generateVideoHandler){
      return;
    }
    const checkAndAttach = () => {
      const btn = document.querySelector('.shot-frame-generate-video-btn');
      if(!btn){
        return false;
      }
      generateVideoHandler = () => {
        if(steps[currentStepIndex]?.id !== GENERATE_VIDEO_STEP_ID){
          return;
        }
        detachGenerateVideoHandler();
        completeStepAndExit();
      };
      btn.addEventListener('click', generateVideoHandler);
      return true;
    };
    if(!checkAndAttach()){
      const observer = new MutationObserver(() => {
        if(checkAndAttach()){
          observer.disconnect();
        }
      });
      observer.observe(document.body, { childList: true, subtree: true });
    }
  };

  const detachGenerateVideoHandler = () => {
    if(!generateVideoHandler){
      return;
    }
    const btn = document.querySelector('.shot-frame-generate-video-btn');
    if(btn){
      btn.removeEventListener('click', generateVideoHandler);
    }
    generateVideoHandler = null;
  };

  const attachAddToTimelineHandler = () => {
    if(addToTimelineHandler){
      return;
    }
    const checkAndAttach = () => {
      const btn = document.querySelector('.video-add-timeline');
      if(!btn){
        return false;
      }
      addToTimelineHandler = () => {
        if(steps[currentStepIndex]?.id !== ADD_TO_TIMELINE_STEP_ID){
          return;
        }
        detachAddToTimelineHandler();
        markStepCompleted(currentStepIndex);
        endTour(true);
        setTimeout(() => {
          if(window.workflowTour && typeof window.workflowTour.reset === 'function'){
            window.workflowTour.reset();
          }
        }, 100);
      };
      btn.addEventListener('click', addToTimelineHandler);
      return true;
    };
    if(!checkAndAttach()){
      const observer = new MutationObserver(() => {
        if(checkAndAttach()){
          observer.disconnect();
        }
      });
      observer.observe(document.body, { childList: true, subtree: true });
    }
  };

  const detachAddToTimelineHandler = () => {
    if(!addToTimelineHandler){
      return;
    }
    const btn = document.querySelector('.video-add-timeline');
    if(btn){
      btn.removeEventListener('click', addToTimelineHandler);
    }
    addToTimelineHandler = null;
  };

  const setStepLock = (stepId) => {
    if(!active){
      return;
    }
    const worldLocked = stepId === WORLD_STEP_ID;
    const locationLocked = stepId === LOCATION_STEP_ID;
    const characterLocked = stepId === CHARACTER_STEP_ID;
    const scriptLocked = stepId === SCRIPT_STEP_ID;
    const scriptInputLocked = stepId === INPUT_SCRIPT_STEP_ID;
    const isMenuItemStep = locationLocked || characterLocked || scriptLocked;
    
    document.body.classList.toggle('tour-world-locked', worldLocked);
    document.body.classList.toggle('tour-location-locked', locationLocked);
    document.body.classList.toggle('tour-character-locked', characterLocked);
    document.body.classList.toggle('tour-script-locked', scriptLocked);
    document.body.classList.toggle('tour-script-input-locked', scriptInputLocked);
    highlightEl.classList.toggle('spotlight', worldLocked || isMenuItemStep || scriptInputLocked);
    if(overlayEl){
      overlayEl.classList.toggle('transparent', worldLocked || isMenuItemStep || scriptInputLocked);
    }
    if(lockMaskEl){
      if(worldLocked || isMenuItemStep){
        lockMaskEl.classList.add('show');
        lockMaskEl.setAttribute('aria-hidden', 'false');
      }else{
        lockMaskEl.classList.remove('show');
        lockMaskEl.setAttribute('aria-hidden', 'true');
      }
    }
    if(worldLocked){
      attachWorldStepHandlers();
    }else{
      detachWorldStepHandlers();
      detachWorldModalHandlers();
      document.body.classList.remove('tour-world-modal', 'tour-world-focus-create');
    }
    if(isMenuItemStep){
      ensureAddMenuOpen();
      const menuItemEl = locationLocked ? locationBtn : 
                         characterLocked ? characterBtn :
                         scriptLocked ? scriptBtn : null;
      if(menuItemEl){
        attachMenuItemHandler(stepId, menuItemEl);
      }
    }else{
      detachAllMenuItemHandlers();
    }
    if(scriptInputLocked){
      attachScriptInputHandler();
    }else{
      detachScriptInputHandler();
    }
    const splitShotsLocked = stepId === SPLIT_SHOTS_STEP_ID;
    document.body.classList.toggle('tour-split-shots-locked', splitShotsLocked);
    if(splitShotsLocked){
      attachSplitShotsHandler();
    }else{
      detachSplitShotsHandler();
    }
    const generateStoryboardLocked = stepId === GENERATE_STORYBOARD_STEP_ID;
    document.body.classList.toggle('tour-generate-storyboard-locked', generateStoryboardLocked);
    if(generateStoryboardLocked){
      attachGenerateStoryboardHandler();
    }else{
      detachGenerateStoryboardHandler();
    }
    const generateVideoLocked = stepId === GENERATE_VIDEO_STEP_ID;
    document.body.classList.toggle('tour-generate-video-locked', generateVideoLocked);
    if(generateVideoLocked){
      attachGenerateVideoHandler();
    }else{
      detachGenerateVideoHandler();
    }
    const addToTimelineLocked = stepId === ADD_TO_TIMELINE_STEP_ID;
    document.body.classList.toggle('tour-add-to-timeline-locked', addToTimelineLocked);
    if(addToTimelineLocked){
      attachAddToTimelineHandler();
    }else{
      detachAddToTimelineHandler();
    }
  };

  const attachWorldStepHandlers = () => {
    if(worldStepHandler || (!worldSelectEl && !createWorldBtn)){
      return;
    }
    worldStepHandler = (event) => {
      if(currentStepIndex !== 0){
        return;
      }
      if(event && event.type === 'click' && event.currentTarget === createWorldBtn){
        document.body.classList.add('tour-world-modal');
        attachWorldModalHandlers();
        return;
      }
      detachWorldStepHandlers();
      completeStepAndExit();
    };
    if(worldSelectEl){
      worldSelectEl.addEventListener('change', worldStepHandler, { once: true });
    }
    if(createWorldBtn){
      createWorldBtn.addEventListener('click', worldStepHandler);
    }
  };

  const detachWorldStepHandlers = () => {
    if(worldSelectEl && worldStepHandler){
      worldSelectEl.removeEventListener('change', worldStepHandler);
    }
    if(createWorldBtn && worldStepHandler){
      createWorldBtn.removeEventListener('click', worldStepHandler);
    }
    worldStepHandler = null;
  };

  const attachWorldModalHandlers = () => {
    if(!createWorldModal || !createWorldSaveBtn || !createWorldCancelBtn || worldModalHandler){
      return;
    }
    document.body.classList.add('tour-world-focus-create');
    worldModalHandler = async () => {
      if(currentStepIndex !== 0){
        return;
      }
      detachWorldModalHandlers();
      document.body.classList.remove('tour-world-modal', 'tour-world-focus-create');
      try{
        await populateWorldSelector();
      }catch(err){
        console.warn('[workflow tour] populateWorldSelector failed', err);
      }
      completeStepAndExit();
    };
    worldModalCancelHandler = () => {
      detachWorldModalHandlers();
      document.body.classList.remove('tour-world-modal', 'tour-world-focus-create');
      endTour(false);
    };
    worldModalCloseHandler = (e) => {
      if(e.target === createWorldModal && currentStepIndex === 0){
        worldModalCancelHandler();
      }
    };
    createWorldModal.addEventListener(WORLD_CREATE_EVENT, worldModalHandler);
    createWorldCancelBtn.addEventListener('click', worldModalCancelHandler);
    createWorldModal.addEventListener('click', worldModalCloseHandler);
    requestAnimationFrame(() => {
      if(document.body.classList.contains('tour-world-modal')){
        renderStep();
      }
    });
  };

  const detachWorldModalHandlers = () => {
    if(createWorldModal && worldModalHandler){
      createWorldModal.removeEventListener(WORLD_CREATE_EVENT, worldModalHandler);
    }
    if(createWorldCancelBtn && worldModalCancelHandler){
      createWorldCancelBtn.removeEventListener('click', worldModalCancelHandler);
    }
    if(createWorldModal && worldModalCloseHandler){
      createWorldModal.removeEventListener('click', worldModalCloseHandler);
    }
    worldModalHandler = null;
    worldModalCancelHandler = null;
    worldModalCloseHandler = null;
  };


  const renderStep = () => {
    if(!active || renderPending){
      return;
    }
    renderPending = true;
    requestAnimationFrame(() => {
      renderPending = false;
      const step = steps[currentStepIndex];
      if(!step){
        return;
      }

      if(typeof step.before === 'function'){
        step.before();
      }

      stepLabelEl.textContent = `第${currentStepIndex + 1}步`;
      titleEl.textContent = step.title;
      descEl.textContent = step.description;
      progressEl.textContent = `${currentStepIndex + 1}/${steps.length}`;
      prevBtn.disabled = currentStepIndex === 0;
      nextBtn.textContent = currentStepIndex === steps.length - 1 ? '完成' : '下一步';

      let targetEl = resolveTarget(step);
      const worldModalActive = step.id === WORLD_STEP_ID && document.body.classList.contains('tour-world-modal');
      if(worldModalActive && createWorldSaveBtn){
        targetEl = createWorldSaveBtn;
      }
      const targetVisible = isVisible(targetEl);
      const rect = targetVisible ? targetEl.getBoundingClientRect() : null;

      if(targetVisible && typeof targetEl.scrollIntoView === 'function'){
        const withinViewport = rect.top >= 0 && rect.bottom <= window.innerHeight;
        if(!withinViewport){
          targetEl.scrollIntoView({ behavior: 'smooth', block: 'center', inline: 'center' });
        }
      }

      if(targetVisible){
        updateHighlight(rect);
        positionPopover(rect);
      }else{
        updateHighlight(null);
        positionPopover(null);
      }

      const nodeRequiredSteps = [INPUT_SCRIPT_STEP_ID, SPLIT_SHOTS_STEP_ID, GENERATE_STORYBOARD_STEP_ID, GENERATE_VIDEO_STEP_ID, ADD_TO_TIMELINE_STEP_ID];
      if(!targetVisible && nodeRequiredSteps.includes(step.id) && step.missingHint){
        alert(step.missingHint);
        endTour(false);
        return;
      }

      setStepLock(step.id);

      if(worldModalActive){
        hintEl.style.display = 'block';
        hintEl.textContent = WORLD_MODAL_HINT;
        hintEl.classList.remove('inactive');
      }else if(step.hint || step.missingHint){
        hintEl.style.display = 'block';
        if(targetVisible && step.hint){
          hintEl.textContent = step.hint;
          hintEl.classList.remove('inactive');
        }else{
          hintEl.textContent = step.missingHint || step.hint || '';
          hintEl.classList.add('inactive');
        }
      }else{
        hintEl.style.display = 'none';
      }
    });
  };

  const goToStep = (index) => {
    const clamped = Math.min(Math.max(index, 0), steps.length - 1);
    if(clamped > currentStepIndex){
      markStepCompleted(currentStepIndex);
    }
    currentStepIndex = clamped;
    renderStep();
  };

  const endTour = (completed) => {
    active = false;
    if(completed){
      markStepCompleted(currentStepIndex);
    }
    portal.classList.remove('active');
    portal.setAttribute('aria-hidden', 'true');
    highlightEl.style.opacity = '0';
    document.body.classList.remove('tour-active', 'tour-world-locked', 'tour-location-locked', 'tour-character-locked', 'tour-script-locked', 'tour-script-input-locked', 'tour-split-shots-locked', 'tour-generate-storyboard-locked', 'tour-generate-video-locked', 'tour-add-to-timeline-locked', 'tour-world-modal', 'tour-world-focus-create');
    const mask = document.getElementById('tourLockMask');
    if(mask){
      mask.classList.remove('show');
      mask.setAttribute('aria-hidden', 'true');
    }
    detachWorldStepHandlers();
    detachWorldModalHandlers();
    detachAllMenuItemHandlers();
    detachScriptInputHandler();
    detachSplitShotsHandler();
    detachGenerateStoryboardHandler();
    detachGenerateVideoHandler();
    detachAddToTimelineHandler();

    if(completed){
      try{
        localStorage.setItem(TOUR_KEY, '1');
      }catch(error){
        console.warn('[workflow tour] failed to persist state', error);
      }
    }
  };

  const startTour = (force) => {
    if(active){
      return;
    }
    const alreadyDone = completedSteps >= TOTAL_STEPS || localStorage.getItem(TOUR_KEY);
    if(!force && alreadyDone){
      return;
    }
    active = true;
    currentStepIndex = completedSteps >= TOTAL_STEPS ? 0 : completedSteps;
    portal.classList.add('active');
    portal.setAttribute('aria-hidden', 'false');
    document.body.classList.add('tour-active');
    renderStep();
  };

  const handleKeydown = (event) => {
    if(!active){
      return;
    }
    if(event.key === 'Escape'){
      endTour(false);
    }else if(event.key === 'ArrowRight'){
      event.preventDefault();
      if(currentStepIndex === steps.length - 1){
        endTour(true);
      }else{
        goToStep(currentStepIndex + 1);
      }
    }else if(event.key === 'ArrowLeft'){
      event.preventDefault();
      goToStep(currentStepIndex - 1);
    }
  };

  skipBtn.addEventListener('click', () => endTour(true));
  overlayEl.addEventListener('click', () => endTour(false));
  prevBtn.addEventListener('click', () => goToStep(currentStepIndex - 1));
  nextBtn.addEventListener('click', () => {
    if(currentStepIndex === steps.length - 1){
      endTour(true);
    }else{
      goToStep(currentStepIndex + 1);
    }
  });
  startBtn.addEventListener('click', (event) => {
    event.preventDefault();
    startTour(true);
  });

  const resetBtn = document.getElementById('tourResetBtn');
  if(resetBtn){
    resetBtn.addEventListener('click', (event) => {
      event.preventDefault();
      if(confirm('确定要重置新手引导吗？这将清除所有进度。')){
        window.workflowTour.reset();
        alert('新手引导已重置！');
      }
    });
  }

  window.addEventListener('keydown', handleKeydown);
  window.addEventListener('resize', () => active && renderStep());
  window.addEventListener('scroll', () => active && renderStep(), { passive: true });

  const observeTargets = [
    document.getElementById('canvas'),
    document.getElementById('timelineContainer'),
    document.getElementById('addMenu')
  ].filter(Boolean);

  observeTargets.forEach(target => {
    const observer = new MutationObserver(() => active && renderStep());
    observer.observe(target, { attributes: true, attributeFilter: ['class', 'style'], childList: true, subtree: true });
  });

  window.workflowTour = {
    start: () => startTour(true),
    reset: () => {
      localStorage.removeItem(TOUR_KEY);
      localStorage.removeItem(TOUR_PROGRESS_KEY);
      completedSteps = 0;
      updateTourButtonLabel();
    }
  };
})();
