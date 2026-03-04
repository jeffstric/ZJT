# 功能权限代码清单

## 概述
本文档定义了系统中所有功能的权限名称和权限代码，采用"模块:操作"的标准格式。

## 视频工作流权限

### 基础权限
- **视频工作流列表查看** - `video_workflow:list`
- **视频工作流查看** - `video_workflow:view`
- **视频工作流创建** - `video_workflow:create`
- **视频工作流更新** - `video_workflow:update`
- **视频工作流删除** - `video_workflow:delete`
- **工作流素材上传** - `video_workflow:upload`
- **工作流状态轮询** - `video_workflow:poll_status`
- **工作流导出草稿** - `video_workflow:export_draft`

## 剧本创作权限

### 会话管理
- **创建剧本会话** - `script_session:create`
- **查看剧本会话** - `script_session:view`
- **更新剧本会话** - `script_session:update`
- **删除剧本会话** - `script_session:delete`
- **清空会话历史** - `script_session:clear_history`
- **切换会话模型** - `script_session:change_model`

### 智能体任务
- **创建智能体任务** - `agent_task:create`
- **查看任务状态** - `agent_task:view`
- **流式获取任务消息** - `agent_task:stream`
- **提交人工验证** - `agent_task:verify`

### 角色管理
- **查看角色列表** - `character:list`
- **查看角色详情** - `character:view`
- **创建角色** - `character:create`
- **更新角色** - `character:update`
- **删除角色** - `character:delete`
- **创建角色卡** - `character:create_card`
- **查询角色卡状态** - `character:view_status`

### 剧本管理
- **查看剧本列表** - `script:list`
- **查看剧本详情** - `script:view`
- **创建剧本** - `script:create`
- **更新剧本** - `script:update`
- **删除剧本** - `script:delete`
- **解析剧本** - `script:parse`

### 场景管理
- **查看场景列表** - `location:list`
- **查看场景详情** - `location:view`
- **创建场景** - `location:create`
- **更新场景** - `location:update`
- **删除场景** - `location:delete`

### 道具管理
- **查看道具列表** - `prop:list`
- **查看道具详情** - `prop:view`
- **创建道具** - `prop:create`
- **更新道具** - `prop:update`
- **删除道具** - `prop:delete`

### 世界管理
- **查看世界列表** - `world:list`
- **查看世界详情** - `world:view`
- **创建世界** - `world:create`
- **更新世界** - `world:update`
- **删除世界** - `world:delete`
- **查看世界文件** - `world:view_files`
- **保存世界文件** - `world:save_files`

## AI图片处理权限

### 基础权限
- **图片编辑** - `image:edit`
- **AI文生图** - `image:text_to_image`
- **图片高清放大** - `image:upscale`
- **查看任务状态** - `image:view_status`
- **宫格拆分** - `image:grid_split`
- **宫格合并** - `image:merge_grid`
- **查看历史记录** - `image:view_history`
- **AI应用运行图片** - `image:ai_app_run`

## AI视频生成权限

### 基础权限
- **AI视频生成** - `video:ai_generate`
- **图片生成视频** - `video:image_to_video`
- **图生视频智能体** - `video:ai_script_gen`
- **视频高清修复** - `video:enhance`
- **视频Remix** - `video:remix`
- **查看视频状态** - `video:view_status`
- **查看视频历史** - `video:view_history`

## 数字人视频权限

### 基础权限
- **数字人视频生成** - `digital_human:create`
- **查看数字人状态** - `digital_human:view_status`
- **查看数字人历史** - `digital_human:view_history`
- **下载数字人视频** - `digital_human:download`

## 音频生成权限

### 基础权限
- **音频生成** - `audio:generate`
- **查看音频状态** - `audio:view_status`
- **下载音频** - `audio:download`
- **声音克隆** - `audio:voice_clone`
- **情感控制** - `audio:emotion_control`
- **查看音色库** - `audio:view_voices`

## 用户管理权限

### 基础权限
- **用户注册** - `user:register`
- **用户登录** - `user:login`
- **用户登出** - `user:logout`
- **重置密码** - `user:reset_password`
- **查看用户信息** - `user:view`
- **更新用户信息** - `user:update`
- **发送验证码** - `user:send_verification_code`
- **查看邀请码** - `user:view_invite_code`
- **查看邀请统计** - `user:view_invite_stats`

### 管理员权限
- **切换用户身份** - `user:admin_switch`
- **管理所有用户** - `user:manage_all`

## 算力管理权限

### 基础权限
- **查看算力余额** - `computing:view_balance`
- **算力充值** - `computing:recharge`
- **查看算力日志** - `computing:view_logs`
- **查看充值套餐** - `computing:view_packages`
- **使用算力** - `computing:use`

### 高级权限
- **管理算力配置** - `computing:manage_config`
- **查看任务算力配置** - `computing:view_task_config`

## 支付订单权限

### 基础权限
- **创建订单** - `order:create`
- **查看订单** - `order:view`
- **验证支付** - `order:verify_payment`
- **外部充值** - `order:external_recharge`

## 系统配置权限

### 基础权限
- **查看上传配置** - `config:view_upload`
- **查看调试密码** - `config:view_debug_password`
- **查看版本信息** - `config:view_edition`
- **系统健康检查** - `system:health_check`

## 文件管理权限

### 基础权限
- **文件上传** - `file:upload`
- **工作流文件上传** - `file:workflow_upload`
- **文件查看** - `file:view`
- **文件下载** - `file:download`
- **文件删除** - `file:delete`
- **图片代理访问** - `file:proxy_image`

## AI工具历史记录权限

### 基础权限
- **查看AI工具历史** - `ai_tools:view_history`
- **查看图片编辑历史** - `ai_tools:view_image_history`
- **查看文生图历史** - `ai_tools:view_text_to_image_history`
- **查看视频生成历史** - `ai_tools:view_video_history`
- **查看数字人历史** - `ai_tools:view_digital_human_history`


