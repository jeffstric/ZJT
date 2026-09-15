// ============================
// canvas_shortcuts.js - 画布快捷键说明弹窗
// 工具栏「快捷键」按钮 → 打开 shortcutHelpModal；
// 关闭方式：× 按钮 / 点击遮罩 / Esc。
// ============================
(function(){
  'use strict';

  function init(){
    var btn = document.getElementById('shortcutHelpBtn');
    var modal = document.getElementById('shortcutHelpModal');
    if(!btn || !modal) return;
    var closeBtn = document.getElementById('shortcutHelpModalClose');

    function open(){
      modal.classList.add('show');
      modal.setAttribute('aria-hidden', 'false');
    }
    function close(){
      modal.classList.remove('show');
      modal.setAttribute('aria-hidden', 'true');
    }

    btn.addEventListener('click', function(e){
      e.stopPropagation();
      open();
    });
    if(closeBtn){
      closeBtn.addEventListener('click', function(e){
        e.stopPropagation();
        close();
      });
    }
    // 点击遮罩空白处关闭（点在卡片上不关）
    modal.addEventListener('click', function(e){
      if(e.target === modal) close();
    });
    window.addEventListener('keydown', function(e){
      if(e.key === 'Escape' && modal.classList.contains('show')) close();
    });
  }

  if(document.readyState === 'loading'){
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
