# 比赛软件开发入口

先读[共同协议](docs/final/competition-protocol.md)及[比赛开发总交接](docs/final/scenario-integration-handoff.md)，接线时使用[真实内部接口对照](docs/final/interface-reference.md)。CommonW 是工业、付款、医疗共用的接受、领取、执行、恢复与结算入口。

当前比赛说明为 `CORE-SPEC-1.3`；[优化复检](docs/final/optimization-review-20261012.md)说明阶段分类、原观测/认证视图和 EXEC 消费边界。应用包装与诊断是开发接线约定，不由此页推定已经有公开服务。

| 目录 | 用途 |
|---|---|
| core/ | 当前身份、来源、批准、时间、持久接受、回执和共同 W |
| profiles/ | 固定三场景的绑定、安全规则及受控初始化 |
| tools/ | 三个签名模拟工具与独立效果账 |
| support/ | 运行和测试实际依赖的编码、场景校验及恢复基础模块 |
| bridge/ | 面向前端/桥接的同进程显式接口：挑战与签名分离，调用方持钥自签 |
| server/ | 可信端：编排器 + Resolver + W；最小接口 `submit / challenge / prove`（本地兜底签名） |
| cli/ | 可信端可交互 CLI，按 `submit → 发挑战 → 签名 → 回交` 驱动 |
| tests/ | 比赛组件、并发、故障恢复与终局回归 |
| docs/final/ | 共同协议、比赛配置、接口、场景交接及证据口径 |
| evidence/ | 不含运行私钥的比赛模拟与核验记录 |

从仓库根目录运行：

```powershell
python -m pip install -r requirements.txt
python -m unittest discover -s competition/tests -v
python -m competition.run_w_slice --output .runtime/demo-evidence
python -m competition.verify_w_slice .runtime/demo-evidence --manifest-sha256 <manifest摘要> --report .runtime/demo-verification.json
python -m competition.server
```

输出目录必须是新的路径。运行初始化会生成临时测试角色钥和本地 SQLite 账，保存在被 Git 忽略的 `.runtime/`；公开证据导出器只导出公钥、签名和账投影。演示先经受控初始化与批准构造，再接 CommonW，不能把 fixture 当成外部认证入口。

外部程序可以**只读观看**每一步：受信入口提供观察面（`GET /api/observe/stream`、`/events`、`/operations`、`/operations/{oid}`），事件在独立表中与决策同事务发布、已脱敏并标注 `not_evidence`，读取本身不推进业务、不消耗 nonce。要一个现成的观看者，用 `python -m competition.deploy.observer`——它持有 `observer` 会话侧（只读、不驱动），订阅并打印流程；一键部署（`competition.deploy.up`）会把它和两侧调用者一起起来。

要**看页面**，用[观察面展示页](display/README.md)：一个 Vue + Element Plus 大屏，经观察网关（`python -m competition.deploy.viewer`）同源订阅。网关托管构建产物，并把 observer 凭据加在服务端——浏览器不持私钥；它只转接上面那四条读路由，其余路径一律 404，所以页面即使被改动也驱动不了任何步骤。docker 一键部署会把展示页起在 `http://127.0.0.1:8081/`，`--local` 起在 `http://127.0.0.1:8008/`。口径见[查询与审计口径](docs/final/query-audit-scope.md)的"只读观察面"一节。

```powershell
python competition/docs/final/verify-existing-evidence.py
python -m competition.verify_repository --report .runtime/repository-check.json
python system_dev/v26/tools/verify_contracts.py
```

第一条按证据记录的 Git 提交核对既有 W 22 例和同 ID 3 例，不声称这些旧运行来自整理后的源码。第二条检查当前入口、依赖和材料引用；第三条只检查 Schema、编码和密码向量。三个场景的实际正常、拒绝和恢复路径见各自交接。

当前比赛语义、agent 能力与角色签署边界见[安全边界](docs/final/security-boundaries.md)；修复和验证结果见[整改记录](docs/final/rectification-results-20261012.md)。

本轮仅整理协议正文与场景开发规则；wire 标识及运行逻辑保持。版本与原证据身份见[分层记录](docs/final/protocol-separation-record-20261012.md)。
