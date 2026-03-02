# 快速配置指南

本文档说明如何使用管理后台的「快速配置」功能，一次性配置多个 API 密钥。

---

## 首次安装引导

**系统会自动引导首位用户完成配置：**

1. 第一个注册的用户自动成为**管理员**
2. 注册成功后自动跳转到管理后台的「快速配置」页面
3. 完成配置后，系统会引导查看[使用手册](https://bq3mlz1jiae.feishu.cn/wiki/W1h2wCK3mi1CgDk36LEcVqggnLe)

---

## 功能入口

1. 登录管理后台（需要管理员权限）
2. 点击左侧菜单「系统配置」
3. 点击页面顶部的「🚀 快速配置」按钮

---

## 配置项说明

### 1. 多媒 (Duomi) 配置

| 配置项 | 必填 | 说明 |
|--------|------|------|
| Token | ✅ | Duomi API 访问令牌 |

**影响的服务：**
- Nano Banana 图片编辑（标准版）
- Nano Banana Pro 图片编辑（加强版）
- Sora2 视频生成
- Kling 可灵视频生成
- Veo3 Google Veo 视频生成

**获取方式：** 访问 [duomiapi.com](https://duomiapi.com) 注册账号获取 Token

---

### 2. Google/Gemini 配置

| 配置项 | 必填 | 说明 |
|--------|------|------|
| API Key | ✅ | Google API 密钥 |
| Base URL | ❌ | API 代理地址（可选，默认使用第三方代理） |

**影响的服务：**
- 剧本创作（AI 剧本生成）
- AI 对话交互

**获取方式：** 
- 官方：访问 [Google AI Studio](https://aistudio.google.com/) 获取 API Key
- 代理：使用第三方代理服务，填写对应的 Base URL

**测试连接：** 填写 API Key 后，可点击「🔗 测试连接」验证配置是否正确

---

### 3. RunningHub 配置

| 配置项 | 必填 | 说明 |
|--------|------|------|
| API Key | ✅ | RunningHub API 密钥 |

**影响的服务：**
- LTX2.0 视频生成
- Wan2.2 视频生成
- 数字人合成

**获取方式：** 访问 [runninghub.cn](https://www.runninghub.cn) 注册账号获取 API Key

---

## 使用步骤

1. **打开快速配置弹窗**
   - 点击「🚀 快速配置」按钮

2. **填写配置**
   - 填写各服务的 API Key/Token
   - 可只填写需要的配置项，留空的配置不会被修改

3. **测试连接（可选）**
   - 对于 Google 配置，可点击「🔗 测试连接」验证 API Key 有效性

4. **保存配置**
   - 点击「💾 批量保存」一次性保存所有配置
   - 配置立即生效，无需重启服务

---

## 注意事项

1. **首次使用前需初始化配置**
   - 如果是新安装的系统，需要先点击「初始化配置」按钮，将默认配置导入数据库

2. **敏感配置自动脱敏**
   - API Key/Token 等敏感配置在列表中会脱敏显示（如 `abcd****wxyz`）
   - 可通过「👁️ 查看」按钮查看完整值

3. **配置修改记录**
   - 所有配置修改都会记录历史，可通过「历史」按钮查看

---

## API 参考

### 批量更新配置

**请求**
```
PUT /api/admin/config/batch
Authorization: Bearer <token>
Content-Type: application/json

{
  "configs": [
    { "key": "duomi.token", "value": "your_token" },
    { "key": "llm.google.api_key", "value": "your_api_key" },
    { "key": "llm.google.gemini_base_url", "value": "https://api.jiekou.ai" },
    { "key": "runninghub.api_key", "value": "your_api_key" }
  ]
}
```

**响应**
```json
{
  "code": 0,
  "message": "批量更新完成，成功更新 3 条配置",
  "data": {
    "results": [
      { "key": "duomi.token", "status": "updated" },
      { "key": "llm.google.api_key", "status": "updated" },
      { "key": "runninghub.api_key", "status": "unchanged" }
    ],
    "errors": []
  }
}
```

### 测试 Google 连接

**请求**
```
POST /api/admin/config/test-google
Authorization: Bearer <token>
Content-Type: application/json

{
  "api_key": "your_google_api_key",
  "base_url": "https://api.aicodemirror.com"  // 可选
}
```

**响应（成功）**
```json
{
  "code": 0,
  "message": "连接成功",
  "data": {
    "success": true,
    "model_count": 15,
    "sample_models": ["gemini-pro", "gemini-pro-vision", ...]
  }
}
```

**响应（失败）**
```json
{
  "code": 1,
  "message": "API Key 无效",
  "data": {
    "success": false,
    "error": "Invalid API Key"
  }
}
```
