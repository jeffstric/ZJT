0. 请说中文
1. 所有的web调用的接口（非定时脚本任务），内部使用的函数 都必须是非阻塞函数，不允许阻塞其他接口访问。禁止在异步函数中调用同步函数，例如request库，会阻塞整个事件循环（Event Loop），导致异步特性失效
2. 功能相关的改动后，请你同步 docs 目录下的文档
3. video_workflow.html 中，需要将css以及js等相关代码，尽量独立成文件，降低token消耗。
4. 涉及到video_workflow.html 工作流相关改动时，注意工作流有重新加载功能，新建的节点需要考虑重新加载后复原。
5. 后端代码中所有的常量都位于 config/constant.py 和 config/unified_config.py 中，请你注意参考，必要时新增。
6. 系统需要兼容windows\linux\macos 三种系统，注意路径以及字符集编码问题。
7. 新建表或者修改表结构,请你同步更新下 alembic/versions, 新建迁移脚本，并更新对应model目录下的具体模型文件末尾sql内容。
8. 数据库表名类似 user_token, 常见字段 create_at, update_at