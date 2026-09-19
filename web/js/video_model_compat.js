// 视频模型与图片模式兼容性判定（TaskConfig 加载后补偿刷新用）
// 修复事故：分镜/分镜组节点保存了首尾帧专属模型（如 minimax_h3），切到参考模式后
// 补偿刷新把它原样塞回下拉保留，提交后后端 validate_model 拒绝
// （MODEL_INPUT_UNSUPPORTED「模型 MiniMax H3 不支持多参考图输入」）。
// 正确行为：已知模型不支持当前模式时必须迁移到兼容模型；仅两种情况保留原值——
// 模型支持当前模式（如被驱动状态过滤但仍兼容），或模型不在配置中（沿用历史行为）。

// 返回应保留的模型值；返回 null 表示调用方应迁移到当前模式的首个可用模型
function resolveSavedVideoModelForMode(allVideoOptions, mode, savedValue){
  if(!savedValue) return null;
  const savedOpt = (allVideoOptions || []).find(o => o && o.value === savedValue);
  if(!savedOpt) return savedValue; // 未知模型：不在配置中，保留原值（旧行为）
  const supportedModes = savedOpt.supportedImageModes || savedOpt.supported_image_modes || ['first_last_frame'];
  if(supportedModes.includes(mode)) return savedValue; // 支持当前模式：保留（可能仅被驱动状态过滤）
  return null; // 已知但不支持当前模式：迁移
}
