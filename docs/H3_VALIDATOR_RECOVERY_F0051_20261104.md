# F0051 提交前校验恢复

仅处理当前接续计划 F0051 第一次本机 CPU 校验进程访问冲突，错误码 0xc0000005，未提交。独立核对原图、前段原生尾图、服务输入、原稿和回执 SHA，再在新的审计目录用同一图及同一原生校验器运行一次。仅此子进程设置 DISABLE_SQLALCHEMY_CEXT_RUNTIME=1，保持其余离线参数和 D 盘缓存。CPU 校验不执行媒体节点。真实回执必须 valid=true、node_errors 为空、node_execution_performed=false 并匹配实际图哈希。其他异常、未知提交或人工暂停不能用本恢复。
