---
id: 2026-08-01-db-port-exhaustion
patch:
tests:
  - tests/model/test_database_pool.py
replay_tests:
feature_ids:
---

## 当时坏成什么样

每次数据库查询都短连接打开再关掉。并发高的时候本机临时端口被 TIME_WAIT 占满，全站访问数据库失败，表现像 MySQL 挂了，其实数据库一直在线。

## 代码大概在哪

- `model/database.py` 的连接池

## 怎么操作、怎样算没修好

还没有改坏补丁。现有测试锁的是连接池单例和缺配置时的默认值。若再改回每次查询新建短连接，这条测试未必会红，需要另补改坏补丁。

## 永久测试

- `tests/model/test_database_pool.py`
