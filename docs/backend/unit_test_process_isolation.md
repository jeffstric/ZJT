# 单元测试进程隔离与全局状态防污染方案

> 创建：2026-08-27（develop_f665）
> 关联提交：d01ec49e（25 项连锁失败的四类根因修复）、88d5fe4b、95794853 等历史同类事故

## 1. 背景与根因

`scripts/testing/run_unit_tests.py`（GitLab CI `unit_tests` job 在 Docker 容器 `/app` 内的唯一执行路径）
历史上在**同一 Python 进程**内按分类顺序串行执行全部 ~206 个测试模块。而 tests/ 下大量测试
在**模块级**（import 时）操纵全局状态，任何一处泄漏都会向后连锁：

| 污染模式 | 典型案例 | 后果 |
| --- | --- | --- |
| `sys.modules['requests'] = MagicMock()` 注入且不恢复 | `tests/driver_integration/` 22 个文件 | 后续所有用到真实 requests 的模块连锁失败 |
| "模块级注入 + 文件尾部恢复" | `tests/task/test_visual_task_failure_reason.py` 等 | import 链中途抛 ImportError 时尾部恢复永不执行，stub 永久残留（d01ec49e 放大器） |
| 恢复了 sys.modules 但漏掉父包属性 | 全部手工恢复代码 | `config.constant` 属性仍指向 stub |
| 清空 `UnifiedConfigRegistry` 不恢复 | `tests/config/test_unified_config_frontend.py` 等 7 个文件 | 后续测试查不到任何真实任务 |
| `importlib.reload` 后 stub 绑定版模块驻留 | `test_visual_task_failure_reason.py` | 后续 import 拿到 MagicMock 版业务模块 |

每次事故都是"修一处、下一处再犯"。本方案从执行机制与增量防护两层根治。

## 2. 方案总览

```
┌─────────────────────────────────────────────────────────────┐
│ 第一层（治本）：run_unit_tests.py 默认按测试模块起独立子进程   │
│   污染被物理限制在单个模块内，存量脏测试零改动                 │
├─────────────────────────────────────────────────────────────┤
│ 第二层（防新增）：                                             │
│   - tests/base/test_isolation.py 官方隔离工具（唯一合法方式）  │
│   - lint_blocking_calls.py R8 静态红线（CI 拦截新增裸赋值）    │
│   - 高风险存量已迁移官方工具（16 个文件）                      │
└─────────────────────────────────────────────────────────────┘
```

## 3. 第一层：进程隔离执行器

`run_unit_tests.py` 的 `_discover_and_run` 默认（`--isolate`，默认开启）对每个测试模块执行：

```python
subprocess.run(
    [sys.executable, '-m', 'unittest', '-v', <module>],
    cwd=APP_DIR, env=继承(comfyui_env/DB_*) + PYTHONIOENCODING=utf-8,
    timeout=UNIT_TEST_MODULE_TIMEOUT_SECONDS,  # config/constant.py，默认 600s
    stdout/stderr 合并捕获,
)
```

- **超时保护**：超时模块记 1 条 error 并继续，同时治"单模块挂死拖垮整轮 CI"；
- **方法级结果还原**：解析 `unittest -v` 输出（兼容 Python 3.10 单行版式与
  3.11+ docstring 换行/裸 `ok` 行版式），失败详情按用例归属 FAIL/ERROR 报告块；
- **报告兼容**：失败详情聚合、`测试执行摘要`、`test-results.xml`（GitLab junit）
  schema 与历史一致，CI 下游零改动；
- **`--no-isolate`**：保留同进程快速模式（本地增量调试用，存在串扰风险）；
- **`--module-timeout N`**：临时覆盖单模块超时。

配套：`.gitlab-ci.yml` 的 `unit_tests` job 容器等待轮询 timeout 由 600s 上调至 1800s
（每模块子进程启动开销使整轮耗时增加约 3~8 分钟）。

## 4. 第二层：官方隔离工具与静态红线

### 4.1 tests/base/test_isolation.py

| API | 用途 |
| --- | --- |
| `module_stub(name, **attrs)` | 构造带属性的轻量 stub 模块 |
| `stub_modules({名字: stub})` | with 块内安装 stub；finally 必然恢复 **sys.modules 条目 + 父包属性**，即使块内 import 抛 ImportError |
| `install_module_stubs / restore_module_stubs` | 手工 API（setUpClass/tearDownClass 场景） |
| `unified_registry_guard()` | with 块保护 UnifiedConfigRegistry（快照/恢复） |
| `dropped_modules(*names)` | with 块内临时移除模块（离开恢复） |
| `purged_modules(*names)` | 移除且不放回（清理其他测试 reload 出的污染版本） |

工具自身行为由 `tests/utils/test_isolation_tools.py` 覆盖（含 import 中断恢复、
父包属性还原、stub 被覆盖时不误删等场景）。

### 4.2 lint R8 红线

`scripts/lint_blocking_calls.py` 新增 R8（仅作用于 tests/ 目录）：

> 模块级（不在函数/类/with 块内）`sys.modules['字符串字面量'] = ...` 裸赋值 → error。

- 函数/类/with 内的赋值（时序可控）不拦截；动态键（`sys.modules[spec.name]`）不拦截；
- 存量 50 个文件已进 `scripts/lint_blocking_calls_allowlist.txt`（`path:R8` 文件级条目），
  在进程隔离下它们无法再跨模块污染，后续逐步迁移并从清单移除；
- 与 R4/R6/R7 相同的双 CI 执行点：GitHub `lint-blocking.yml` 与 GitLab `lint:blocking_calls`。

### 4.3 AGENTS.md

新增第 12 条红线【测试隔离红线·模块级 stub】，与 R8 一一对应。

## 5. 已迁移的高风险存量（16 文件）

| 文件 | 修复内容 |
| --- | --- |
| tests/config/test_unified_config_frontend.py | 4 个类 registry 清空不恢复 → snapshot/restore |
| tests/config/test_implementation_config.py | TestImplementationConfig 同上 |
| tests/utils/test_video_resolution.py | tearDown 留空 → 恢复快照 |
| tests/api/test_script_writer_image_model_task_snapshot.py | 结尾三清不恢复 → unified_registry_guard |
| tests/agents/test_video_tools_resolution.py | fixture/函数内 clear 不恢复 → 快照恢复 |
| tests/task/test_visual_task_failure_reason.py | 手工 stub + reload 驻留 → stub_modules + purged_modules |
| tests/task/test_audio_task_utils.py | 尾部恢复 → stub_modules |
| tests/task/test_recalc_scene_duration.py | 同上 |
| tests/model/test_async_task.py | 注入无恢复 → stub_modules |
| tests/drivers/test_runninghub_face_mask_driver.py | 部分恢复 → stub_modules |
| tests/drivers/test_runninghub_image_face_mask_driver.py | 同上 |
| tests/utils/test_pm_agent_message_queue.py | 13 个注入名不卸载 → 条件 stub_modules |
| tests/test_driver_factory.py | sentry 注入 + `_registered_drivers` 清空不恢复 → stub_modules + 快照恢复 |
| tests/drivers/test_seedance_kkidc_v1_driver.py | 裸属性赋值 → patch |
| tests/drivers/test_seedance_huimengi_v1_driver.py | 同上 |
| tests/model/test_storyboard_scene_duplicate.py | 冗余裸赋值 → 删除（monkeypatch 已覆盖） |

## 6. 验收标准

1. `--isolate` 模式下按 CI 顺序跑 utils→config→drivers→task，结果与同进程模式一致
   （除本地无 MySQL 的 DB 依赖用例）；
2. 对照实验：构造"注入不恢复"模块，隔离模式下后续模块不受影响；
3. `python scripts/lint_blocking_calls.py --allow-file ...` 退出码 0；
4. `pytest tests/scripts/test_lint_blocking_calls.py` 与
   `unittest tests.utils.test_isolation_tools` 全绿。

## 7. 后续可选（二期）

- 按分类并行子进程执行（DB 集成分类保持串行）；
- `--failed` 仅重跑上次失败模块；
- api/storyboard/scripts 目录纳入 runner 分类覆盖；
- allowlist 存量逐步迁移清零。
