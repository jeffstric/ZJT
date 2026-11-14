---
id: power-budget-route-missing
patch: patches/power-budget-route-missing.json
tests:
  - tests/api/test_user_power_budget_api.py
  - auto_test/e2e/test_power_budget.py
replay_tests:
  - tests/api/test_user_power_budget_api.py::test_power_budget_routes_are_registered
feature_ids:
---

## 当时坏成什么样

单次算力上限的接口在商业版漏挂。处理函数还在，页面上保存失败，请求打到 `/api/user/power-budget` 不是 401，而是找不到路由。

## 代码大概在哪

- `api/user.py` 的 `GET/PUT/DELETE /power-budget`

## 怎么操作、怎样算没修好

回放补丁去掉这三条路由的装饰器，函数还留着。`test_power_budget_routes_are_registered` 必须失败。`auto_test/e2e/test_power_budget.py` 是每次推送都会打到运行中服务的那条痕迹：未登录应是 401。要让那条端到端也变红，服务得用改坏后的代码启动。

## 永久测试

- `tests/api/test_user_power_budget_api.py`
- `auto_test/e2e/test_power_budget.py`
