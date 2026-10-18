# IND 完整优化交付：开发接手入口

日期：2026-10-18。范围：通用核心之上的 IND 单机竞赛原型，涵盖字段补全、P2 操作生命周期、P4 接口和工业模拟部署。本文按“解决方式、其他影响、具体补全方案、实验代码与结果”组织。P5 的比赛分支/main 合入决策、PAY/MED 新公开入口及真实设备不在完成声明内。

## 1. 代码如何解决这个问题

昨天的 [PR #3](https://github.com/yumir3297/Cryptography-Technical-Competition/pull/3) 是本版本的直接祖先，覆盖六字段可信构造和固定完整包恢复。当前版本继续补上短期证明过期后的受限更新、W 事务内旧包阻断、认证恢复、真实接口与本机部署；属于同一方案的深化，同时扩展了 P4 工程接线。

| 层次 | PR #3（V1） | 本次完整交付 |
|---|---|---|
| P1/P3 适配与字段 | IND 三字段候选 → 原十字段 Action；六字段从受信状态取得 | 继承原实现，不另建一套 Resolver，不让 Agent 代签 |
| P2 ID/幂等 | W 事务内 B16 分配，同请求键恢复同构造 | 继承同一 app_request；ID 在 ActionHash 和签署前保存 |
| P2 完整包更新 | 第一次冻结后禁止任何替换 | 仅接受前允许更新 ChallengeRequest/Challenge/CommitProof；原批准与 Permit 不变 |
| P2 并发与恢复 | 内部库原包恢复 | 版本 CAS、历史防回退、prepare/accept 事务内当前包检查、认证恢复原 COMMIT/attempt |
| P4 服务 | 内部 Python 库 | 十项白名单、回环 HTTP 短连接、可选 MCP stdio；worker/签名/登记仍内部 |
| P4 部署 | 无独立部署验收 | 固定配置、私有目录、单实例锁、账表与 C/X/W/工具绑定预检、实际启停与单效果验收 |

最小代码索引：

- [trusted_action_resolver.py](../../application/trusted_action_resolver.py)：认证 H，核对 Task/Policy/KEY/ROLE/工具，事务分配 ID 并保存构造；只返回未签署材料。
- [request_store.py](../../application/request_store.py)：同键同内容复用；`SHORT_FIELDS = frozenset(('challenge_request', 'challenge', 'proof'))` 限制可更新部分，其他授权对象逐项相等；CAS 和历史标识阻断覆盖与回退。
- [operation_orchestrator.py](../../application/operation_orchestrator.py)：真实完整签名链、当前资格、DENY、来源及时间最终检查后同事务保存；失败回滚 nonce、版本与日志。
- [request_bound_w.py](../../application/request_bound_w.py) 与 [common_w.py](../../core/common_w.py)：公开入口的 W 必须绑定同一请求账；原 prepare/accept 事务内核对分配与当前完整包。旧 ticket 不能在换包后接受。
- [operation_service.py](../../application/operation_service.py)、[http_service.py](../../application/http_service.py)、[mcp_stdio.py](../../application/mcp_stdio.py)：静态方法/参数白名单；传输 token 与 H 签名分别验证；超时先认证恢复。
- [local_runtime.py](../../application/local_runtime.py)：启动前核对持久账、权限、配置和公开密钥绑定，缺账直接拒绝，重启不清库或重新引导。

业务恢复规则：同一次请求始终复用 request_id；尚未接受且原授权仍有效时才能更新三件套。原授权过期则停止，重新审批不由本版本自动完成。已 COMMITTED 恢复原事实；工具结果未知时查询原 attempt，已消费 EXEC 不重发。不同 request_id 可建多个草稿，最终 W 的业务 intent 唯一接受约束继续生效。

## 2. 会不会影响其他部分

| 项目 | 具体影响 |
|---|---|
| 核心协议 | Action 十字段、Schema、ActionHash、原核心签名域、DENY、时间阈值、COMMIT/Core、EXEC 规则保持；CommonW 新增事务检查 hook，新公开服务通过 RequestBoundW 强制使用 |
| 持久状态 | app_request 增加版本和历史；a_journal 记录各版提交。真实旧 V1 行按原内容迁移为版本 1，不补造分配、不重置 W/工具账 |
| 旧调用方式 | 旧内部 CommonW/三场景组件仍保留，不能直接注册为公开 Agent 工具；新公开服务固定 IND/Task |
| 审批与密钥 | U/V 不修改 Action；改变动作须重新建立依据并审批。公开宿主不加载 H/U/V/G/E/worker 私钥；C/X/工具使用原受限子进程。演示操作端单独持有模拟身份，同 OS 用户的私有材料不构成生产身份隔离 |
| 部署行为 | 配置错误、缺表、错密钥、权限过宽、重复宿主均拒绝。原短期证明和来源窗口继续到期；启动不是续期 |
| 兼容边界 | PAY/MED 沿用原完整 Action 流程；原 R2 与比赛变体差异见[既有对照](r2-application-mapping.md)，本次没有宣称消除这些差异 |

新增恢复签名域为应用域 `ZJJ-APP-RECOVER-v1`，不改原协议签名域。MCP 仅为可选传输；核心与本机 HTTP 均可独立于 MCP 工作。历史时钟间歇原因未全部定位，本次不放宽阈值；macOS 防空闲休眠只是运行环境措施。

## 3. 具体补全方案与接手方式

角色表、十项 API/MCP 精确参数、认证域、状态/错误和恢复顺序见[接口契约](unified-operation-contract.md)；实际安装和启动见[部署说明](../../deployment/README.md)。

接线顺序：H 认证候选 → Resolver 构造固定 Action/未签署依据 → U/V 审批，H/G/X 各自签署 → H 认证 submit 保存版本 → prepare/accept 验证并提交原 W → 内部 worker claim/唯一 EXEC/query/settle。公开 accept 不自动取得 worker 权限。

本 PR 以比赛分支 `competition/zjj-core-final-20261010 @ cc4e36b4e302fcdc53cc809a012c77d8464182af` 为基线，继承原 V1 `86f284b`，完整整理本地统一生命周期 `63c5da6` 的源码和证据，以及本轮部署成果；发布为 V1 之后的源码补全、文档与证据两个提交，避免要求开发方叠加多个实验分支。开发同学只审阅和集成本 PR，不再叠加合入 PR #3；保留旧分支和提交用于追溯。新分支为 `feature/zjj-core-ind-complete-20261018`，不强推旧分支。

发布前已重新读取远程：比赛基线仍为 cc4e36b；main 仍为 1aa5a9e；dev 已推进至 ec29d8d（2026-10-18 03:01:06 +08:00），新增 bridge/server/CLI/外部角色签名接点并清理旧实现。dev 与比赛基线有 60 文件变化，包含删除旧支持实现，不能把本 PR 直接覆盖到 dev，也不把 dev 的服务混入本 PR。后续单独审查共享接口差异，以明确 SHA 分工；同一文件只由一个任务写入。

本次不合并比赛分支或同步 main。先按本 PR 的 SHA 验收，开发方基于该 SHA 建自己的开发分支；比赛线确认采纳后再单独安排 main 同步，避免把发布补丁与开发重构混成一次操作。

复现完整回归（在仓库根；解释器需安装 requirements.txt）：

```sh
export ZJJ_PYTHON=/absolute/path/to/python
sh competition/run_unified_checks.sh /absolute/new-regression-evidence
```

新一轮工业模拟验收必须连续执行以下两步，两个目标目录均须不存在；不用于恢复/覆盖原安装：

```sh
env -u PYTHONHOME "$ZJJ_PYTHON" -m competition.deployment.provision_demo /absolute/new-installation --port 18765
env -u PYTHONHOME "$ZJJ_PYTHON" -m competition.deployment.acceptance --config /absolute/new-installation/service.json --evidence /absolute/new-live-evidence
```

初始 E 来源 120 秒、Assessment 最多 90 秒、短期证明最多 30 秒；KEY/ROLE/worker/工具信任约 30 分钟，均服从原规则。旧安装的恢复读取仍须真实当前授权；本版本不自动重新审批或续期。真实设备、生产密钥托管、多机状态和三场景新公开入口需要独立工作，不作为本次已完成项。

## 4. 实验代码及具体结果

| 验证 | 结果与公开脱敏记录 |
|---|---|
| V1 历史回归 | 159/159，488.176 秒；[V1 原报告](trusted-action-resolver-v1-results.md)及 [V1 证据](../../evidence/trusted-action-resolver-v1-20261017/README.md) |
| 生命周期历史联合 | 196/196，559.756 秒；[统一整合报告](unified-operation-handoff.md)，后续独立复测 196/196、574.975 秒亦保留 |
| 部署完整回归 | 208/208，0 failures/errors，572.885 秒；[结果记录](../../../integration-evidence/deployment-joint-release/results.json)、[日志](../../../integration-evidence/deployment-joint-release/tests.log) |
| 最终工业服务验收 | 12 项通过，实际启停 4 次；接受、attempt、EXEC 消费、效果、结算各 1；[机器结果](../../../integration-evidence/deployment-live-ready/results.json)、[脱敏结果摘要](../../../integration-evidence/deployment-live-ready/public-evidence-summary.json) |
| 密码学及事实核验 | 15 份参与方/回执签名、根签工具证书、终局/checkpoint 与 W 结算关系通过；[核验记录](../../../integration-evidence/deployment-live-ready/offline-audit.json) |
| 失败与修正 | [部署报告](industrial-local-deployment-acceptance-20261018.md)保留错密钥/缺表红测与修复；过期安装返回 EXPIRED，四张业务表均 0，未通过续期或清账获得通过 |

**待推送版本完整回归：208/208，0 failures/errors，569.296 秒**；[结果记录](../../../integration-evidence/publication-joint-20261018/results.json)与[日志](../../../integration-evidence/publication-joint-20261018/tests.log)单独保存，运行期间源码摘要一致。发布核验结果见[发布证据索引](../../../integration-evidence/publication-summary-20261018.json)。旧 208 项之后的 EOF 清理记录与源码摘要保留；历史源码 ZIP 含本机路径条目，仅本地保留，[不上传说明](../../../integration-evidence/publication-excluded-artifacts.json)列明替代验证。当前发布运行直接验证实际交付 Python 字节版本。原始时钟采样、身份/运行配置、临时认证与完整签名账本包只留本地；GitHub 提供脱敏日志、结果与原始摘要，详见[脱敏清单](../../../integration-evidence/publication-sanitization.json)。各次测试不累加成一次更大的结果，GitHub CI 以实际状态为准。

实验代码：[短期更新/竞态](../../tests/test_submission_renewal.py)、[服务认证](../../tests/test_operation_service.py)、[HTTP/MCP 真实传输](../../tests/test_operation_transport.py)、[启动配置](../../tests/test_local_deployment.py)、[审查反例](../../tests/test_deployment_review.py)、[实际部署验收](../../deployment/acceptance.py)。批准夹具只在受控模拟操作端使用，不暴露给 Agent；测试没有删字段、伪造 H 或跳过守卫。

[公开核验脚本](../../../integration-evidence/verify_public_deployment.py)与[本机原始证据核验脚本](../../../integration-evidence/verify_deployment.py)一并交付。上表15份签名和三项篡改反例是本地完整原始材料的实际结果；公开的是脱敏核验记录，不能对结果摘要重新运行签名核验，也不将删除字段后的包伪称为有效签名包。

如需独立复核，按第3节在新目录连续引导并验收，随后在自己的安装上执行：

```sh
"$ZJJ_PYTHON" integration-evidence/verify_deployment.py /absolute/new-live-evidence/public-evidence.json
"$ZJJ_PYTHON" integration-evidence/verify_public_deployment.py /absolute/new-live-evidence/public-evidence.json
```

第一步从自己的模拟账提取公开证书/结算并核验，第二步仅使用刚生成的导出文件核验。它们生成自己的独立模拟身份，不复用本机身份、授权或账本。这些脚本检查独立于208项套件，不相加。发布前核对108个运行/测试源码摘要一致，脱敏未改协议、守卫或实验逻辑。

本次公开范围是源码、实验程序、四项说明、脱敏测试日志、结果摘要及复现步骤。私钥、token、运行数据库、lab-metadata.json、本机路径/配置、完整临时认证材料和原始签名账本包不上传。原始文件SHA256用于追溯本地结果，不等于发布了原始文件。完整脱敏范围和独立核验限制见[脱敏清单](../../../integration-evidence/publication-sanitization.json)。
