# 工业任务完成路径 · RELEASE 批次 v1

首轮验证基于本地 `origin/main` 快照 `1aa5a9e36e1558b95972941d5ce7dbf6553da431`，定版基于后续比赛交付提交 `cc4e36b4e302fcdc53cc809a012c77d8464182af`。审查提交 `c7e86dc` 和指定审查报告尚不可用。

| 分类 | 基线保证与位置 |
|---|---|
| 现有实现已满足 | [工业合同 §2.2–2.4](../../system_dev/v26/03_industrial_medical_profiles.md) 中 `IND_TASK` 授权工件、阶段、路线与在途上限。工件次序可变，路线由 E 签署的标签和固定映射确定。C 认证 Task/Policy，Resolver 在 [SceneAuthorizationAdapter](../profiles/authorization_scene.py) 重建当前依赖，W 在 [CommonW.prepare/accept](../core/common_w.py) 复验。 |
| 现有实现已满足 | `CommonW.accept` 在 [TrustedState.tx](../core/trusted_state.py) 的 SQLite 写事务内提交 COMMIT、消费标记、意图、在途、场景、行为、资源预留和 outbox。领取后效果可为 UNKNOWN，保留 RESERVED。可信成功转 SPENT，允许取消转 CANCELED，确认无效果终局转 RELEASED。后两种释放容量，保留意图墓碑。参见 [CommonW.claim/cancel/settle](../core/common_w.py) 和 [W 事务契约](w-transaction-contract.md)。 |
| 规范已定义但实现缺失 | 工业合同定义 `AdvanceIndustrialPhase` 和新证据、新任务、新批准要求。共用比赛入口的 INITIAL/INSPECT 演示止于 AWAITING_REINSPECT，见 [工业交接](final/industrial-handoff.md)。 |
| 需要新的协议语义 | 把任务列出的工件声明为必须完成的集合，并核验候选动作之后的路径。附件 GoalGuard 复验状态引用与剩余槽位下界。其模型覆盖单步容量必要条件。 |

## 接受规则

C 认证的 `IND_TASK.value.completion_model` 可选值为 `release-all-initial-v1`。该值使 allowed_units 成为必须完成 RELEASE 的工件集合。作用域为 INITIAL/cycle 1，每个工件恰出现一次。未声明字段的 Task 使用原授权语义。新字段随 Task RecordRef 进入 Basis 和动作批准链，更新后按原规则重新派生和签署。两个新增字段由 `ZJJ-CORE-COMP-1` 的比赛 Schema 定义，原 R2 结构合同文件保持原始字节。

W 先按原入口检查候选动作。它在同一接受事务内读取当前 Task/Policy 和每个必需工件的状态。已完成工件须有本任务同一工件的 W 结算成功记录。其他工件须处于 READY，有当前可验的身份、E 证据及适用的 RELEASE 权限，且没有已消费的阶段意图。候选与其余 READY 工件按固定次序组成一条 RELEASE 路径。每步占一个同一目的地槽位，成功时转为已花费并清除 TaskFlight。W 按当前资源容量减去 SPENT 和所有 RESERVED（含对外工具结果未知的操作），并按 Behavior 剩余累计次数，核验整条路径。候选提交复用原预留、TaskFlight 和 outbox。

这一存在性判断在接受时按 W 可验证的状态计算。路径假设串行领取和成功结算，未来步骤仍需新的有效审批，依赖版本、时间窗口、工具权限和共享容量在未来接受时重校验。一个任务的路径是接受时快照性质，其他任务后续接受可能改变共享资源。外部系统的实际效果以原尝试的可信对账结果确定。

同 Task 的某一必需工件已有关联意图，且该操作对同一资源仍有 `RESERVED`、活动 TaskFlight 和 `UNKNOWN` 效果状态时，W 在路径判断中返回 `TASK_COMPLETION_PENDING_UNKNOWN`。首笔沿既有对账流程结算成功后才计为已完成。旧 TaskFlight 上限仍适用。

W 将判断输入及路径写入冻结记录，并以规范化摘要绑定到 COMMIT。由 X 签署的 Acceptance 引用 COMMIT。历史 COMMIT 无可达性引用时按原版本处理。

## 复验

在仓库根目录运行以下命令。输出目录须尚未存在。

```powershell
python -m unittest -v competition.tests.test_industrial_task_completion
python -m competition.run_industrial_completion --output .runtime/industrial-completion-demo
$pins = Get-Content .runtime/industrial-completion-demo/fixture-public-keys.json -Raw | ConvertFrom-Json
python -m competition.verify_industrial_completion .runtime/industrial-completion-demo/acceptance-1.json --c-public $pins.c_public --x-public $pins.x_public --e-public $pins.e_public
python -m competition.verify_industrial_completion .runtime/industrial-completion-demo/acceptance-2.json --c-public $pins.c_public --x-public $pins.x_public --e-public $pins.e_public
```

演示预期得到两次 SETTLED，路径依次为 `[unit-a, unit-b]` 和 `[unit-b]`，共享同一个 TaskRef。首次路径包括当前候选，第二次路径使用由 W 核验的首件成功结算。专项测试还覆盖 Policy 修订、无解且无新增接受副作用、并发、幂等、允许取消、UNKNOWN 保留容量及证据篡改。

离线验证器使用独立给定的 C、X、E 公钥。它验 C 的 Task、Policy 与容量证书，验 E 的源数据签名，验 X 的 Acceptance，并复算任务、Basis、动作、状态、证据和 COMMIT 引用，以及路径覆盖、逐步资格的业务输入和容量、行为上限。当前记录是否为接受时最新、全部承诺是否完整、角色资格、已完成工件的原始工具终局以及可信时间，由 W 在接受时核验并通过 X 的回执绑定快照。离线验证器信任这些 W 断言。演示生成的公钥清单是本次隔离夹具的信任输入，正式证据的公钥应通过独立可信渠道提供。

仓库单测、合同向量核验和本次演示有各自的输出。正式 39 项沿用原清单和原身份核验，其结论须单独取得。
