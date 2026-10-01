# Moomoo 策略执行组件

活动源码位于 `D:/us-tech-quant/apps/moomoo_trading_component`。所有账户、冻结执行计划、幂等记录、恢复状态与日常日志，均由项目共享 resolver 路由到 `daily_root/moomoo_trading_component`；默认是 `D:/us-tech-quant-daily/moomoo_trading_component`。C 盘原源码与原 runtime 保留为迁移前恢复证据，原启动入口只转发到本目录。迁移记录见每日状态根下的 `migration_20261001.json`，7 个 SQLite 数据库已用合法 backup 合并 WAL，逐表行内容与完整性验证通过；未改写旧成交。

默认控制台接入三个固定策略：Raw A2、HGB＋对角风险、HGB＋因子／收缩风险。每套各有独立的 10,000 USD 本地纸面账户，使用本机 MOOMOO OpenD 的真实行情。`-WithMoomooBest` 恢复既有唯一美国股票 SIMULATE 账户的 HGB_DIAG_5 策略，预算仍为 10,000 USD；原账户、持仓、订单与幂等身份保持连续，不自动接入新的账户。

```powershell
# 打开控制台及原有模拟账户，调度保持停止
& "D:/us-tech-quant/apps/moomoo_trading_component/start.ps1" -WithMoomooBest
# 启动已授权的三策略调度及原有模拟账户
& "D:/us-tech-quant/apps/moomoo_trading_component/start.ps1" -WithMoomooBest -ActivateStrategies
```

地址为 <http://127.0.0.1:8766/paper>；正式 DEMO <http://127.0.0.1:8506/paper-trading> 嵌入同一组件。`/manual` 保留手动工作台，`/live` 仅提供明确操作后的实盘只读查询。`-Offline` 使用隔离的本地合成行情演示，不能同时启用策略或券商模拟。所有启动使用项目规范 Python 环境，不创建仓库内 `.venv`。

## 收盘信号与开盘执行

2026-10-01 用户明确将默认执行延迟从开盘后 150 分钟改为 **0 分钟**。使用最新已完成美股交易日的收盘信号，在下一交易日开盘后第一份合格实时报价上执行。接近开盘及执行窗口内按约 1 秒检查；数据读取、网络与券商处理仍有实际延迟，记录真实报价时间、委托时间和成交时间，不倒签到 09:30。开盘前 5 分钟仅验证证券及预订阅，不取得可执行价格、不下单。

本地纸面执行窗口仍为 600 秒，券商模拟窗口仍为 3,600 秒；可用 `-ExecutionWindowSeconds` 与 `-BrokerExecutionWindowSeconds` 明确覆盖。旧信号已有订单时保留原到期约束，修改时钟不会重发历史成交或过期买单。未获得报价或窗口错过时显示等待/错过及具体原因，不使用昨日收盘价或补造开盘价。

纸面收盘估值优先使用原生 MOOMOO RAW USD 日线。仅当目标日原生记录为零行时，可复用当前推荐中已绑定 SHA、五日 OHLCV 重叠资格及原生锚点的 MASSIVE_GROUPED RAW USD 收盘收据；记录真实来源、收盘后观察时间与资格证据，继续校验原始字节、身份和前后哈希。异常或重复原生记录不能回退，PIT 价格指数不能充作美元收盘价。开盘执行仍须使用合格 MOOMOO 实时报价。

纸面账本按实际盘口买入 ask、卖出 bid，整数股，单边 5bp 成本，先卖后买；每个策略各自使用真实收盘持仓与现金。股票身份、常规交易时段、报价时间、新鲜度、价差、冻结模型与输入哈希继续校验。日更由原 `scripts.daily_recommendation` 全局锁保护；打开页面、查看状态与服务停止态启动都不会自动采集或买卖。模型只做冻结推断，不使用 2026 数据训练、调参或改变策略。

券商模拟沿用现行逐股执行的 MARKET 实现，旧 NORMAL 限价订单仍保留原始订单类型、重报价与到期约束。市场报价用于执行资格和资金检查，券商确认的实际成交均价独立记录，不能等同于官方 09:30 开盘价。未知提交、未知成交均价或未完成订单先对账，禁止重复买入；原券商模拟身份变化时停止。窗口结束后不发送新单或改单，但窗口内已提交的 DAY 委托可能依券商规则稍后成交。暂停只阻止后续操作，不撤销已有委托。实盘下单、改单、撤单、解锁与自动执行能力仍不存在。

## 存储和验证

三策略状态位于 `applied/books`，券商模拟状态位于 `applied/moomoo-best`，三策略模式的手动工作台位于 `applied/manual`，原独立手动工作台位于 `manual`。备份必须停止对应服务或使用 SQLite backup；不能只复制有 WAL 的主数据库，不能删除幂等记录、清空账户或换目录来处理未知订单。运行端校验解析后的真实路径必须处于共享 daily_root 下，仓库、canonical data、cache 和其它用途根会拒绝作为活动账户目录。

组件测试全部使用离线合成来源与模拟 SDK，不证明当前券商端到端成交。运行时将 TEMP/TMP 指向任务 cache_root 子目录，并在仓库根执行：

```powershell
$env:PYTHONPATH = "D:/us-tech-quant;D:/us-tech-quant/apps/moomoo_trading_component"
& "D:/us-tech-quant-envs/us-tech-quant-main/Scripts/python.exe" -B -m unittest discover -s apps/moomoo_trading_component/tests -q
```

`GET /api/health` 返回组件身份、版本与 `live_execution_enabled: false`，不连接券商。`GET /api/applied/state` 只读当前缓存；POST `/api/applied/start`、`stop`、`halt` 使用同源 JSON 和本服务进程的 `X-CSRF-Token`。CSRF 令牌不是账户授权机制；SIMULATE/REAL 隔离与实盘执行锁由后端实际能力界定。早期 `VERIFICATION.md` 为历史证据，当前执行时钟与 D 盘路径以本说明和现行启动器为准。
