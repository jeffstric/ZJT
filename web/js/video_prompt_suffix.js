let videoPromptSuffix = '';

function initVideoPromptSuffix(){
  loadVideoPromptSuffix();
  
  const suffixBtn = document.getElementById('videoPromptSuffixBtn');
  const suffixModal = document.getElementById('videoPromptSuffixModal');
  const suffixModalClose = document.getElementById('videoPromptSuffixModalClose');
  const suffixInput = document.getElementById('videoPromptSuffixInput');
  const suffixSaveBtn = document.getElementById('videoPromptSuffixSaveBtn');
  const suffixCancelBtn = document.getElementById('videoPromptSuffixCancelBtn');
  
  if(suffixBtn){
    suffixBtn.addEventListener('click', () => {
      openVideoPromptSuffixModal();
    });
  }
  
  if(suffixModalClose){
    suffixModalClose.addEventListener('click', () => {
      closeVideoPromptSuffixModal();
    });
  }
  
  if(suffixCancelBtn){
    suffixCancelBtn.addEventListener('click', () => {
      closeVideoPromptSuffixModal();
    });
  }
  
  if(suffixSaveBtn){
    suffixSaveBtn.addEventListener('click', () => {
      saveVideoPromptSuffix();
    });
  }
  
  if(suffixModal){
    suffixModal.addEventListener('click', (e) => {
      if(e.target === suffixModal){
        closeVideoPromptSuffixModal();
      }
    });
  }
}

function openVideoPromptSuffixModal(){
  const suffixModal = document.getElementById('videoPromptSuffixModal');
  const suffixInput = document.getElementById('videoPromptSuffixInput');
  
  if(suffixModal && suffixInput){
    suffixInput.value = videoPromptSuffix;
    suffixModal.setAttribute('aria-hidden', 'false');
    suffixModal.style.display = 'flex';
  }
}

function closeVideoPromptSuffixModal(){
  const suffixModal = document.getElementById('videoPromptSuffixModal');
  
  if(suffixModal){
    suffixModal.setAttribute('aria-hidden', 'true');
    suffixModal.style.display = 'none';
  }
}

function saveVideoPromptSuffix(){
  const suffixInput = document.getElementById('videoPromptSuffixInput');
  
  if(suffixInput){
    videoPromptSuffix = suffixInput.value.trim();
    
    const workflowId = new URLSearchParams(window.location.search).get('id');
    if(workflowId){
      const key = `video_prompt_suffix_${workflowId}`;
      localStorage.setItem(key, videoPromptSuffix);
    }
    
    showToast('视频提示词后缀已保存', 'success');
    closeVideoPromptSuffixModal();
  }
}

function loadVideoPromptSuffix(){
  const workflowId = new URLSearchParams(window.location.search).get('id');
  if(workflowId){
    const key = `video_prompt_suffix_${workflowId}`;
    const saved = localStorage.getItem(key);
    if(saved){
      videoPromptSuffix = saved;
    }
  }
}

function getVideoPromptWithSuffix(originalPrompt){
  if(!originalPrompt){
    return videoPromptSuffix;
  }
  
  if(!videoPromptSuffix){
    return originalPrompt;
  }
  
  const trimmedPrompt = originalPrompt.trim();
  const trimmedSuffix = videoPromptSuffix.trim();
  
  if(!trimmedSuffix){
    return originalPrompt;
  }
  
  if(trimmedPrompt){
    return trimmedPrompt + ' ' + trimmedSuffix;
  }
  
  return trimmedSuffix;
}
