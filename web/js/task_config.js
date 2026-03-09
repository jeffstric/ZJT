/**
 * 任务配置模块
 * 
 * 统一管理任务类型、模型、时长、比例、算力等配置
 * 从 /api/system/task-configs 接口获取数据，供多个模块使用
 */

(function(window) {
  'use strict';

  // 配置缓存
  let taskConfigCache = null;
  let configLoaded = false;
  let loadingPromise = null;

  // 配置加载回调列表
  const onLoadCallbacks = [];

  /**
   * 从后端加载任务配置
   * @returns {Promise<Object>} 配置数据
   */
  async function loadTaskConfigs() {
    // 如果正在加载，返回现有的 Promise
    if (loadingPromise) {
      return loadingPromise;
    }

    // 如果已加载，直接返回缓存
    if (configLoaded && taskConfigCache) {
      return taskConfigCache;
    }

    loadingPromise = (async () => {
      try {
        const response = await fetch('/api/system/task-configs');
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }
        
        const result = await response.json();
        if (result.code === 0 && result.data) {
          taskConfigCache = result.data;
          configLoaded = true;
          console.log('[任务配置] 已加载:', taskConfigCache);
          
          // 触发所有回调
          onLoadCallbacks.forEach(cb => {
            try { cb(taskConfigCache); } catch(e) { console.error('[任务配置] 回调错误:', e); }
          });
          
          return taskConfigCache;
        } else {
          throw new Error(result.message || '加载配置失败');
        }
      } catch (error) {
        console.error('[任务配置] 加载失败:', error);
        // 返回空配置
        taskConfigCache = { tasks: [], categories: {}, providers: {} };
        return taskConfigCache;
      } finally {
        loadingPromise = null;
      }
    })();

    return loadingPromise;
  }

  /**
   * 获取所有任务配置（同步，需先调用 loadTaskConfigs）
   * @returns {Array} 任务配置列表
   */
  function getAllTasks() {
    return taskConfigCache?.tasks || [];
  }

  /**
   * 根据任务类型ID获取配置
   * @param {number} taskTypeId 任务类型ID
   * @returns {Object|null} 任务配置
   */
  function getTaskById(taskTypeId) {
    const tasks = getAllTasks();
    return tasks.find(t => t.id === taskTypeId) || null;
  }

  /**
   * 根据模型key获取配置
   * @param {string} modelKey 模型标识符（如 'sora2', 'kling'）
   * @returns {Object|null} 任务配置
   */
  function getTaskByKey(modelKey) {
    const tasks = getAllTasks();
    // 支持简短key匹配（如 'sora2' 匹配 'sora2_image_to_video'）
    return tasks.find(t => t.key === modelKey || t.key.startsWith(modelKey + '_')) || null;
  }

  /**
   * 根据模型key获取任务类型ID
   * @param {string} modelKey 模型标识符
   * @param {string} category 可选，指定分类以精确匹配
   * @returns {number|null} 任务类型ID
   */
  function getTaskIdByKey(modelKey, category) {
    const tasks = getAllTasks();
    let task;
    if (category) {
      // 如果指定了分类，在该分类中查找
      task = tasks.find(t => 
        (t.key === modelKey || t.key.startsWith(modelKey + '_')) &&
        (t.category === category || (t.categories && t.categories.includes(category)))
      );
    } else {
      task = tasks.find(t => t.key === modelKey || t.key.startsWith(modelKey + '_'));
    }
    return task ? task.id : null;
  }

  /**
   * 获取指定分类的所有任务（支持多分类）
   * @param {string} category 分类名称
   * @returns {Array} 任务配置列表
   */
  function getTasksByCategory(category) {
    const tasks = getAllTasks();
    return tasks.filter(t => 
      t.category === category || 
      (t.categories && t.categories.includes(category))
    );
  }

  /**
   * 获取模型支持的时长选项
   * @param {string} modelKey 模型标识符
   * @returns {Array<number>} 时长选项列表
   */
  function getDurationOptions(modelKey) {
    const task = getTaskByKey(modelKey);
    return task?.supported_durations || [5, 10];
  }

  /**
   * 获取模型支持的比例选项
   * @param {string} modelKey 模型标识符
   * @returns {Array<string>} 比例选项列表
   */
  function getRatioOptions(modelKey) {
    const task = getTaskByKey(modelKey);
    return task?.supported_ratios || ['9:16', '16:9', '1:1'];
  }

  /**
   * 获取模型支持的尺寸选项
   * @param {string} modelKey 模型标识符
   * @returns {Array<string>} 尺寸选项列表
   */
  function getSizeOptions(modelKey) {
    const task = getTaskByKey(modelKey);
    return task?.supported_sizes || ['1K', '2K'];
  }

  /**
   * 获取模型的默认时长
   * @param {string} modelKey 模型标识符
   * @returns {number} 默认时长
   */
  function getDefaultDuration(modelKey) {
    const task = getTaskByKey(modelKey);
    return task?.default_duration || 5;
  }

  /**
   * 获取模型的默认比例
   * @param {string} modelKey 模型标识符
   * @returns {string} 默认比例
   */
  function getDefaultRatio(modelKey) {
    const task = getTaskByKey(modelKey);
    return task?.default_ratio || '9:16';
  }

  /**
   * 获取模型的默认尺寸
   * @param {string} modelKey 模型标识符
   * @returns {string} 默认尺寸
   */
  function getDefaultSize(modelKey) {
    const task = getTaskByKey(modelKey);
    return task?.default_size || '1K';
  }

  /**
   * 计算任务的算力消耗
   * @param {number|string} taskTypeIdOrModelKey 任务类型ID或模型key
   * @param {number} duration 时长（可选，用于按时长计费的任务）
   * @returns {number} 算力消耗
   */
  function getComputingPower(taskTypeIdOrModelKey, duration) {
    let task;
    if (typeof taskTypeIdOrModelKey === 'number') {
      task = getTaskById(taskTypeIdOrModelKey);
    } else {
      task = getTaskByKey(taskTypeIdOrModelKey);
    }
    
    if (!task) return 0;
    
    const power = task.computing_power;
    if (typeof power === 'object' && power !== null) {
      // 按时长计费
      return power[duration] || power[Object.keys(power)[0]] || 0;
    }
    return power || 0;
  }

  /**
   * 获取所有视频模型的时长选项（兼容旧格式）
   * @returns {Object} { modelKey: [durations] }
   */
  function getVideoModelDurationOptions() {
    const tasks = getAllTasks();
    const result = {};
    tasks.forEach(task => {
      if (task.category === 'image_to_video' || task.category === 'text_to_video') {
        // 使用简短key（如 'sora2' 而非 'sora2_image_to_video'）
        const shortKey = task.key.replace(/_image_to_video|_text_to_video/g, '');
        result[shortKey] = task.supported_durations || [];
      }
    });
    return result;
  }

  /**
   * 获取所有模型配置（兼容旧格式）
   * @returns {Object} { modelKey: { ratios, sizes, durations, defaults } }
   */
  function getModelConfigs() {
    const tasks = getAllTasks();
    const result = {};
    tasks.forEach(task => {
      // 使用简短key（与 getModelOptionsForCategory 保持一致）
      const shortKey = task.key.replace(/_image_to_video|_text_to_video|_text_to_image|_image_edit/g, '');
      
      result[shortKey] = {
        ratios: task.supported_ratios || [],
        image_sizes: task.supported_sizes || [],  // 兼容前端字段名
        sizes: task.supported_sizes || [],
        durations: task.supported_durations || [],
        default_ratio: task.default_ratio,
        default_image_size: task.default_size,  // 兼容前端字段名
        default_size: task.default_size,
        default_duration: task.default_duration
      };
    });
    return result;
  }

  /**
   * 获取算力配置（兼容旧格式）
   * @returns {Object} { taskTypeId: power }
   */
  function getTaskComputingPowerConfig() {
    const tasks = getAllTasks();
    const result = {};
    tasks.forEach(task => {
      result[task.id] = task.computing_power;
    });
    return result;
  }

  /**
   * 获取指定分类的任务类型ID列表
   * @param {string} category 分类名称
   * @returns {Array<number>} 任务类型ID列表
   */
  function getTaskTypeIdsByCategory(category) {
    const tasks = getTasksByCategory(category);
    return tasks.map(t => t.id);
  }

  /**
   * 获取任务类型配置（兼容旧格式）
   * @returns {Object} { image_edit_types, image_to_video_types, text_to_image_types, ... }
   */
  function getTaskTypeConfig() {
    return {
      image_edit_types: getTaskTypeIdsByCategory('image_edit'),
      image_to_video_types: getTaskTypeIdsByCategory('image_to_video'),
      text_to_video_types: getTaskTypeIdsByCategory('text_to_video'),
      text_to_image_types: getTaskTypeIdsByCategory('text_to_image'),
      visual_enhance_types: getTaskTypeIdsByCategory('visual_enhance'),
      audio_types: getTaskTypeIdsByCategory('audio'),
      digital_human_types: getTaskTypeIdsByCategory('digital_human')
    };
  }

  /**
   * 获取指定分类的模型选项列表（用于前端下拉框渲染）
   * @param {string} category 分类名称 (image_edit, text_to_image, image_to_video, etc.)
   * @returns {Array} [{ value, label, taskType, computingPower, key }, ...]
   */
  function getModelOptionsForCategory(category) {
    const tasks = getTasksByCategory(category);
    return tasks.map(task => {
      // 提取简短的模型值（去掉 _image_to_video, _text_to_image 等后缀）
      const shortKey = task.key.replace(/_image_to_video|_text_to_video|_text_to_image|_image_edit/g, '');
      const power = typeof task.computing_power === 'object' 
        ? Object.values(task.computing_power)[0] 
        : task.computing_power;
      return {
        value: shortKey,
        label: `${task.name} (${power}算力)`,
        taskType: task.id,
        computingPower: task.computing_power,
        key: task.key
      };
    });
  }

  /**
   * 获取分类信息
   * @returns {Object} 分类名称映射
   */
  function getCategories() {
    return taskConfigCache?.categories || {};
  }

  /**
   * 获取供应商信息
   * @returns {Object} 供应商名称映射
   */
  function getProviders() {
    return taskConfigCache?.providers || {};
  }

  /**
   * 注册配置加载完成回调
   * @param {Function} callback 回调函数
   */
  function onConfigLoaded(callback) {
    if (configLoaded && taskConfigCache) {
      // 已加载，立即执行
      try { callback(taskConfigCache); } catch(e) { console.error(e); }
    } else {
      onLoadCallbacks.push(callback);
    }
  }

  /**
   * 检查配置是否已加载
   * @returns {boolean}
   */
  function isConfigLoaded() {
    return configLoaded;
  }

  /**
   * 强制重新加载配置
   * @returns {Promise<Object>}
   */
  async function reloadConfigs() {
    configLoaded = false;
    taskConfigCache = null;
    return loadTaskConfigs();
  }

  // 导出到全局
  window.TaskConfig = {
    load: loadTaskConfigs,
    reload: reloadConfigs,
    isLoaded: isConfigLoaded,
    onLoaded: onConfigLoaded,
    
    // 获取配置
    getAllTasks,
    getTaskById,
    getTaskByKey,
    getTaskIdByKey,
    getTasksByCategory,
    
    // 获取选项
    getDurationOptions,
    getRatioOptions,
    getSizeOptions,
    
    // 获取默认值
    getDefaultDuration,
    getDefaultRatio,
    getDefaultSize,
    
    // 算力
    getComputingPower,
    
    // 兼容旧格式
    getVideoModelDurationOptions,
    getModelConfigs,
    getTaskComputingPowerConfig,
    getTaskTypeIdsByCategory,
    getTaskTypeConfig,
    
    // 动态渲染
    getModelOptionsForCategory,
    getCategories,
    getProviders
  };

})(window);
