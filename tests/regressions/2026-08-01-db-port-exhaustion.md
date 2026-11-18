---
id: 2026-08-01-db-port-exhaustion
patch: patches/2026-08-01-db-port-exhaustion.json
tests:
  - tests/model/test_database_pool.py
replay_tests:
  - tests/model/test_database_pool.py::test_get_db_connection_borrows_from_pool_not_short_connection
feature_ids:
---

## 当时坏成什么样

每次数据库查询都短连接打开再关掉。并发高的时候本机临时端口被 TIME_WAIT 占满，全站访问数据库失败，表现像 MySQL 挂了，其实数据库一直在线。

## 代码大概在哪

- `model/database.py` 的连接池

## 怎么操作、怎样算没修好

改坏补丁把 `model/database.py` `get_db_connection()` 里的 `connection = _get_pool().connection()`（从池借连接）改回当年写法——直接 `pymysql.connect(...)` 每次新建短连接、finally `close()` 真关闭，高并发下 TIME_WAIT 占满客户端临时端口。

怎样算没修好：`tests/model/test_database_pool.py::test_get_db_connection_borrows_from_pool_not_short_connection` 没红，即改坏没被抓住。该测试为效果断言：哨兵拦截 `pymysql.connect`，借池路径下它不得被调用，`_FakeConn.close` 记录归还。原有测试（池单例/默认值/pid 漂移）锁的是 `_get_pool` 本身，拦不住 `get_db_connection` 绕池直连的回归，本用例补这个口子。

## 永久测试

- `tests/model/test_database_pool.py`
