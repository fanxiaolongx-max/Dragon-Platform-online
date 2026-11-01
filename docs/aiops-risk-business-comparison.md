# AiOps-Risk 业务库样例对比（1.5.6）

检查对象为用户通过主页导入的 AiOps-Risk 0.9.8 原始 package.zip。其 app/config.py、app/db.py、run.py 与导入后的文件逐字节一致；压缩包不含 .env。没有执行或修改样例，也没有访问其他应用数据库。

## 请求契约

两者均向 BASE_QUERY_URL 发送 POST，业务查询 JSON 使用 datasourceName、sql、limit；应用查询另用 datasourceId、schema。业务查询都使用 trust_env=False，不走环境代理。对相同配置，使用 HTTPX MockTransport 重放 SELECT 1 和风险表 COUNT 查询，捕获的 HTTP 方法、接口路径、JSON 完全相同。该验证不连接实际基座，不能代替内网验收。

Report 另有只读 SQL 校验、请求节奏控制、连接复用、取消支持和脱敏诊断；这些差异没有改变上述正常查询的请求契约。

## 配置差异与结论

Risk Settings 写有测试环境地址、应用 schema 和业务组 netcareClaw-operate-digital-readonly 作为默认值，允许进程环境或 .env 覆盖。Report 不硬编码任何环境的业务组；只能使用基座分配并注入的 BUSINESS_DATASOURCE_NAME。两者都是进程环境优先，其次 .env，最后代码默认值。

此前内网月报诊断明确返回“数据源不存在: netcare-digital-human-readonly”。它与样例默认组名不同，也不能仅凭管理页面显示的数据库连接名称推断实际查询组名。业务 SELECT 1 同样失败，说明该次失败发生在业务源路由阶段，不能归因于特定风险表字段或 SQL 引号。

样例配置仅说明其默认目标，不能证明样例实际进程未被环境变量覆盖，也不能证明两套内网的组名相同。不要把样例组名作为跨环境 fallback，更不能遍历、试查未分配的数据源。

1.5.5 起数据库套件可导出实际加载的业务组、配置来源、PID、启动标识、底层响应和请求编号。应在新进程启动成功后重新导出，确认基座注入的组名和绑定关系。1.5.6 同时修复 HTTP 错误分支传递诊断 data 时的异常构造兼容问题，避免原错误被 TypeError 覆盖。
