# 工作流 / 故事板 / 营销智能体补上月度订阅

## 背景

首页 `web/index.html` 的充值中心有两个页签：「算力充值」和「月度订阅」（默认落在月度订阅）。视频工作流、故事板、营销智能体原先只有微信直付套餐，用户在这三页看不到订阅、升级和解约。

## 做法

三页共用 `web/js/recharge_center.js`，交互与首页对齐，样式继续用 `web/css/subscription.css`：

- 算力充值：套餐列表、微信扫码；展示扣邀请佣金后的 `granted_computing_power`。
- 月度订阅：套餐、入门版首期动画（29.9→18.8，328→368；系统减少动效时直接显示结果）、协议勾选、扫码签约、支付轮询、生效中管理、低档升级到高档、解约。
- 本地环境（`server-config.is_local`）不打开弹窗。
- 订阅接口 `/plans`、`/status`、`/order-status` 的后端签名要求 query `auth_token`，同时带 `Authorization` 头。直充套餐列表只走请求头，不把 token 放进 URL。

入口：

| 页面 | 接入点 |
|---|---|
| `web/video_workflow.html` | `handleRechargeClick` → `RechargeCenter.open`，支付成功后点算力刷新 |
| `web/js/storyboard/events.js` | `openRechargeModal` → `RechargeCenter.open`，成功后刷新头部算力。故事板模块入口带 `?v=20260923b`，避免浏览器沿用旧的 `events.js`（旧文件只会打开直付弹窗） |
| `web/js/marketing_agent.js` | `handleRechargeClick` → `RechargeCenter.open`，成功后 `loadComputingPower` |

首页仍用 Vue（`index.html` + `index_app.js`）。改订阅展示时两处要一起看。页面内旧的直付弹窗只在共用脚本没加载时兜底。

## 测试

`web/js/recharge_center.test.js`：首期差额 201、无首期资格时 62、升级列表，以及弹窗页签 / 生效中管理 / 本地环境拦截。
