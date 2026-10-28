# 剧本创作页实体名称校验

## 范围

角色名称、场景名称、剧本标题在新建、暂存区编辑和数据库资产编辑时统一校验。数据库资产保存后仍会回同步暂存文件，因此两条编辑链路使用同一规则。

## 规则

- 去除首尾空格后不能为空，最长 200 字符。
- 禁止 `< > : " / \ | ? *` 及 ASCII 控制字符（U+0000～U+001F）。
- 完整名称不能是 `.` 或 `..`，也不能以空格或点号结尾。
- 不自动替换非法字符，避免自动改名导致重名或引用关系不一致。

## 实现

- 前端公共函数位于 `web/js/script_writer.js`：`getEntityNameValidationError` 返回错误文案，`validateEntityName` 展示错误并返回是否可提交。
- 新建角色/场景输入时，在原有重名检查前显示命名校验错误；新建剧本、新建角色、新建场景提交前均再次校验。
- `saveEditedFile` 覆盖暂存区编辑；`web/js/script_writer_library.js saveLibraryAsset` 覆盖数据库资产编辑。
- 后端共享规则位于 `script_writer_core/file_manager.py validate_entity_name`，非法字符正则及长度常量位于 `config/constant.py`。
- `save_character`、`save_location` 在构造实体文件路径前校验内容中的实际名称；`save_script` 即使使用集数作为文件名，也校验 JSON 中的剧本标题。
- 非法名称抛出 `EntityNameValidationError`；角色、场景、剧本保存 API 捕获后返回 HTTP 400 和具体错误，而不是通用 500。AI/其他内部调用经过 FileManager 时同样受到约束。

## 回归测试

- `tests/utils/test_file_manager_name_validation.py`：特殊字符、空名称、非法结尾、长度、合法写入，以及带集数文件名时仍拒绝非法剧本标题。
- `web/tests/script_writer_name_validation.test.js`：前端共享函数及新建、暂存编辑、数据库编辑入口覆盖。
