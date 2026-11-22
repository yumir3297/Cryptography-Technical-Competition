# ZJJ-CORE-2.6-R2 国赛主线定版优化方案

## 交付目标

沿 C、Resolver、W 和签名模拟工具的真实入口，交付可独立复验的高后果动作授权。C 认证任务和策略，Resolver 从当期受信输入重建动作依据，W 在同一事务中核验审批与当前依赖、判断选定工业任务是否仍有完成路径，并原子提交接受记录和资源承诺。签名回执让评委将判断对应到具体 Task、Policy、动作和 W 状态快照。

基线为已在本地保存的 `origin/main` 快照 `1aa5a9e36e1558b95972941d5ce7dbf6553da431`。本次开发使用独立本地分支 `local/industrial-task-completion-20261122`。交接报告 `CRYPTO_REVIEW_2026-11-22.md` 和报告指向的 `c7e86dc` 在核查的本地位置缺失。附件中的原型结果保留其各自的运行基线。

## 五阶段与定版门槛

| 阶段 | 定版范围与验收 |
|---|---|
| 1. 核对基线 | 固定提交、默认入口、依赖和证据来源。工业任务的既有授权语义、二阶段规范和实验 guard 的能力边界见[工业任务完成路径](../industrial-task-completion.md)。 |
| 2. 原子接受与可达性 | 工业 Task 可声明 `release-all-initial-v1`，按首轮 RELEASE 工件列表核验一条串行完成路径。当前版本一致、容量与行为预算充足时放行。Policy 或 Task 失效走原依赖复验。候选动作虽符合单步规则但无法完成批次时，事务拒绝且无接受、预留和 outbox 副作用。 |
| 3. 执行与恢复 | 复用接受、领取、工具执行、对账与结算。成功把预留转为已花费，协议允许的取消恢复可用容量，UNKNOWN 继续占用容量。以并发接受、重复请求、幂等结算以及全仓回归核验共用路径。 |
| 4. 离线复验 | X 签署的 Acceptance 通过 COMMIT 引用冻结的路径证据。验证器使用预先可信的 C、X、E 公钥核对签名，复算绑定、路径覆盖和容量。接受时账本完整性、角色资格与历史结算依赖 W 的快照断言。 |
| 5. 冻结和重跑 | 固定本地提交、命令、依赖版本和证据输出。评委依次观察两件工件成功结算、容量不足或依赖变化时拒绝、UNKNOWN 期间继续计入承诺，并离线复验对应接受记录。 |

选择离线审计作为本轮主线增强。外部 checkpoint 送审须再验证独立见证部署、跨长度一致性证明和回滚边界。C 根钥与时钟子钥分离须同时覆盖时钟校验、历史 DENY 和回执路径。这两项保留为单独增量。当前可达性适用于固定首轮工业 RELEASE 模型和接受时快照。未来审批、业务变更和实际工具效果仍走现有执行条件。付款、医疗沿用当前协议语义。

## 复现与证据登记

在本地分支根目录运行，使用 Python 3.13.9、cryptography 50.0.0 和 jsonschema 4.26.0。

```powershell
python -m unittest discover -s competition/tests -v
python -m unittest -v competition.tests.test_industrial_task_completion
python -m competition.run_industrial_completion --output .runtime/industrial-completion-demo
```

离线命令见[工业任务完成路径](../industrial-task-completion.md)。使用新的输出目录。验证记录须写入本次提交对应的交付记录。

正式 39 项沿用原清单 Git blob `b0bc9dbeedac135f6520b5e93729f63686d97bb4`。原归档报告记载完整通过为 0/39，选定探针和关联测试按各自口径保留。本轮正式验收状态为未运行。
