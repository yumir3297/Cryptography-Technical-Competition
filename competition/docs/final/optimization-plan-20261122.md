# ZJJ-CORE-2.6-R2 国赛主线定版优化方案

## 交付目标

沿 C、Resolver、W 和签名模拟工具的真实入口，交付可独立复验的高后果动作授权。C 认证任务和策略，Resolver 从当期受信输入重建动作依据，W 在同一事务中核验审批与当前依赖、判断选定工业任务是否仍有完成路径，并原子提交接受记录和资源承诺。签名回执让评委将判断对应到具体 Task、Policy、动作和 W 状态快照。

首轮验证使用本地 `origin/main` 快照 `1aa5a9e36e1558b95972941d5ce7dbf6553da431`。定版基于其后续比赛交付提交 `cc4e36b4e302fcdc53cc809a012c77d8464182af`，包括独立比赛 wire 标识、签署认证和严格候选入口。定版留在本地分支 `local/industrial-task-completion-20261122`。交接报告 `CRYPTO_REVIEW_2026-11-22.md` 和报告指向的 `c7e86dc` 在核查的本地位置缺失。附件中的原型结果保留其各自的运行基线。

## 五阶段与定版门槛

| 阶段 | 定版范围与验收 |
|---|---|
| 1. 核对基线 | 固定提交、默认入口、依赖和证据来源。工业任务的既有授权语义、二阶段规范和实验 guard 的能力边界见[工业任务完成路径](../industrial-task-completion.md)。 |
| 2. 原子接受与可达性 | 工业 Task 可声明 `release-all-initial-v1`，按首轮 RELEASE 工件列表核验一条串行完成路径。当前版本一致、容量与行为预算充足时放行。Policy 或 Task 失效走原依赖复验。候选动作虽符合单步规则但无法完成批次时，事务拒绝且无接受、预留和 outbox 副作用。 |
| 3. 执行与恢复 | 复用接受、领取、工具执行、对账与结算。成功把预留转为已花费，协议允许的取消恢复可用容量，UNKNOWN 继续占用容量。以并发接受、重复请求、幂等结算以及全仓回归核验共用路径。 |
| 4. 离线复验 | X 签署的 Acceptance 通过 COMMIT 引用冻结的路径证据。验证器使用预先可信的 C、X、E 公钥核对签名，复算绑定、路径覆盖和容量。接受时账本完整性、角色资格与历史结算依赖 W 的快照断言。 |
| 5. 冻结和重跑 | 固定本地提交、命令、依赖版本和证据输出。评委依次观察两件工件成功结算、容量不足或依赖变化时拒绝、UNKNOWN 期间继续计入承诺，并离线复验对应接受记录。 |

选择离线审计作为本轮主线增强。外部 checkpoint 送审须再验证独立见证部署、跨长度一致性证明和回滚边界。C 根钥与时钟子钥分离须同时覆盖时钟校验、历史 DENY 和回执路径。这两项保留为单独增量。当前可达性适用于固定首轮工业 RELEASE 模型和接受时快照。未来审批、业务变更和实际工具效果仍走现有执行条件。付款、医疗沿用当前协议语义。

## 旧版与新版的协议保证

旧版以比赛交付提交 `cc4e36b` 为准。新增约束仅适用于 C 认证且声明 `release-all-initial-v1` 的工业 Task。

| 环节 | 旧 W 已有机制 | 新版新增保证 |
|---|---|---|
| 接受谓词 | 重验授权、Task/Policy 及候选依赖、时限、意图唯一性、行为、当前动作容量和 TaskFlight。 | 在旧条件之上，W 还须找到一条覆盖本 Task 所有未完成工件的串行 RELEASE 路径。候选为首步，每件工件核验当前状态和证据。容量须满足 `SPENT + RESERVED + 路径步数 ≤ 容量`，行为累计次数也须容纳全部路径步。 |
| 原子读取 | 同一 SQLite 写事务读取候选依赖、资源余额和预留账、TaskFlight、意图、消费标记及工具资格。 | 同一事务读取整批 UNIT、后续步骤的受信来源和资格，以及已完成工件的成功结算。对同一 Task 和同一资源的前笔操作，W 将工件意图、活动 TaskFlight、`UNKNOWN` 与 `RESERVED` 关联。前笔工件无法计作已完成，也不能安排为新的路径步骤。第二笔返回 `TASK_COMPLETION_PENDING_UNKNOWN`，旧单在途上限继续适用。 |
| 原子写入 | 接受时写入 COMMIT、操作、意图、消费标记、行为与场景状态、资源预留、TaskFlight、outbox 和日志。 | 同次提交将判断输入及路径冻结为 `completion_basis`，并将其摘要写入 COMMIT 的 `completion_ref`。拒绝回滚接受事务。X 在提交后签出的 Acceptance 引用该 COMMIT。 |
| 保留、结算与释放 | 接受即预留。领取及工具结果未知期间保留 `RESERVED`。经可信对账确认成功后转 `SPENT`。确认无效果的失败转 `RELEASED`，协议允许的领取前取消转 `CANCELED`。后两种释放容量，意图墓碑仍保留。 | 沿用旧 W 的状态转换。路径判断持续计入共享资源的未结算预留。只有同一 Task 的工件成功结算后，路径判断才把该工件计为已完成。未来路径步骤在各自接受时重新校验。 |

## 同一 Task 的端到端验收

容量为 2。第一笔动作经真实 W 接受并领取，模拟工具提交后丢失回执，W 的结算入口返回 `UNKNOWN`。第二个工件使用同一 Task 和 TaskRef，并在首笔接受后按当前依赖重新签署。此时仍有 1 个槽位可供第二笔动作使用。W 在完成路径判断中读到首笔未结算预留，返回 `TASK_COMPLETION_PENDING_UNKNOWN`。接受、预留、outbox 表均各有 1 行，且只属于首笔。随后沿原执行记录查询并成功结算，首笔预留转为 `SPENT`，重新准备的第二笔成功接受。

```powershell
python -m unittest -v competition.tests.test_industrial_task_completion.IndustrialTaskCompletionTests.test_same_task_unknown_commitment_blocks_completion_until_reconciled
```

## 复现与证据登记

最终可执行版本为 `308572d65c00644b620c587bb4c4e419cdecb404`。在本地分支根目录运行，使用 Python 3.13.9、cryptography 50.0.0 和 jsonschema 4.26.0。

```powershell
python -m unittest discover -s competition/tests -v
python -m unittest -v competition.tests.test_industrial_task_completion
$evidenceDir = '.runtime/industrial-completion-replay'
python -m competition.run_industrial_completion --output $evidenceDir
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$pins = Get-Content -Raw (Join-Path $evidenceDir 'fixture-public-keys.json') | ConvertFrom-Json
python -m competition.verify_industrial_completion (Join-Path $evidenceDir 'acceptance-1.json') --c-public $pins.c_public --x-public $pins.x_public --e-public $pins.e_public
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m competition.verify_industrial_completion (Join-Path $evidenceDir 'acceptance-2.json') --c-public $pins.c_public --x-public $pins.x_public --e-public $pins.e_public
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

使用新的输出目录。示例公钥由隔离夹具生成。评委复验已交付的证据时，应通过事先可信的渠道取得公钥，再将 `$evidenceDir` 指向已有证据目录，执行公钥读取和两条验证命令。

### 2026-11-22 首版证据

首版全仓 145 项、工业专项 8 项及以下两份离线证据，均对应定版提交 `dedcb426f3b4f38d454424e97941d5ff9fa048b6` 的运行代码树。测试与证据生成在该版本代码树提交封存前执行。

- 全仓回归 145 项通过，用时 784.508 秒。运行覆盖三场景共用接受和恢复、比赛签署与候选入口，以及本轮新增工业规则。
- 工业专项 8 项通过。覆盖完成路径、单步可行但批次无解、Task/Policy 修订、后续工件状态变化、并发与重复请求、允许取消、UNKNOWN 保留承诺及证据修改。
- 两次真实模拟工具结算均返回 SETTLED。离线命令分别复算 `[unit-a, unit-b]` 和 `[unit-b]`，共同 TaskRef 为 `TR0aJASoLf2grzPhWv6x8JDlNTq92fSW42p5lJxYsCU`。本次输出在 `.runtime/industrial-completion-final`。
- `acceptance-1.json` SHA-256 为 `8b276401e3d2cb290e506e7a8d21512b838b1e3cb9e33cc14f8bd1a8755a3b39`。`acceptance-2.json` SHA-256 为 `aa425a5484289fbc084171876fa624d5a114ea123fddf829406579df70185b1b`。
- `python -m competition.verify_repository` 检查通过，包括 344 个文档链接和 35 项历史证据文件摘要。原 R2 向量经 `node system_dev/v26/tools/check_vectors.mjs system_dev/v26/vectors/wire_vectors.json` 核验 70 项。

### 同 Task 联合验收修订

运行时提交为 `308572d65c00644b620c587bb4c4e419cdecb404`。联合用例在首版运行时返回 `TASK_FLIGHT_LIMIT`，在该修订返回 `TASK_COMPLETION_PENDING_UNKNOWN` 并通过全部后置断言。

- 全仓回归 146 项通过，用时 825.776 秒。
- 工业专项 9 项通过，用时 139.403 秒。

该提交生成的离线证据在 `.runtime/industrial-completion-308572d`。两次结算成功，两条路径经独立命令复验，共同 TaskRef 为 `1kW8UnA3X5lOiFlp0cGaf_WffkFSoGUtRkqaUtg5U0k`。

| 文件 | SHA-256 |
|---|---|
| `acceptance-1.json` | `48d83a2c25c833b1764c2349d7d8117e58ec4a2a097ec503667138f989f37c55` |
| `acceptance-2.json` | `fce47a20bb9c2e62dc6ddd1f25038a42c3f24e503849e1d75cacec834c1a1256` |
| `fixture-public-keys.json` | `a83a1eae6fe8df8455126d63543943ed0a6de08632fc602db542485fc3fff0ca` |

正式 39 项沿用原清单 Git blob `b0bc9dbeedac135f6520b5e93729f63686d97bb4`。原归档报告记载完整通过为 0/39，选定探针和关联测试按各自口径保留。本轮正式验收状态为未运行。
