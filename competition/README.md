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

```powershell
python competition/docs/final/verify-existing-evidence.py
python -m competition.verify_repository --report .runtime/repository-check.json
python system_dev/v26/tools/verify_contracts.py
```

第一条按证据记录的 Git 提交核对既有 W 22 例和同 ID 3 例，不声称这些旧运行来自整理后的源码。第二条检查当前入口、依赖和材料引用；第三条只检查 Schema、编码和密码向量。三个场景的实际正常、拒绝和恢复路径见各自交接。

当前比赛语义、agent 能力与角色签署边界见[安全边界](docs/final/security-boundaries.md)；修复和验证结果见[整改记录](docs/final/rectification-results-20261012.md)。

本轮仅整理协议正文与场景开发规则；wire 标识及运行逻辑保持。版本与原证据身份见[分层记录](docs/final/protocol-separation-record-20261012.md)。
