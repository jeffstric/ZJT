# Claude Code 启动器 - 完整权限模式

## 概述

这个脚本用于启动 Claude Code Router 和 Claude Code，并自动绕过所有权限检查，无需用户手动确认。

## 文件说明

### `start_claude_full_permissions.ps1`
统一的 PowerShell 启动脚本，包含：
- 通过 Claude Code Router (ccr) 启动 Claude Code
- Claude Code Router 安装状态检查
- 详细的启动信息
- 错误处理

**使用方法：**
```powershell
.\start_claude_full_permissions.ps1
```

## 权限配置

脚本使用以下参数来绕过权限检查：
- `--dangerously-skip-permissions`: 绕过所有权限检查
- `--permission-mode bypassPermissions`: 设置权限模式为绕过权限

## 注意事项

⚠️ **安全警告**: 此脚本会绕过所有权限检查，请确保在可信的环境中使用。

✅ **推荐用法**: 
- 在开发和测试环境中使用
- 确保工作目录安全可信
- 定期检查 Claude Code 的更新

## 故障排除

### 问题：Claude Code 未找到
**解决方案**: 确保 Claude Code 已正确安装并添加到系统 PATH 中。

### 问题：权限被拒绝
**解决方案**: 以管理员身份运行 PowerShell 或命令提示符。

### 问题：脚本执行策略限制
**解决方案**: 
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

## 更新日志

- 2024-12-22: 创建初始版本，支持完整权限绕过
