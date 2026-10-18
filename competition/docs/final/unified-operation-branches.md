# P5 分支、证据与单一开发基线

> 历史分支快照：dev 已继续推进，当前发布基线及整合策略见[统一交付入口](ind-complete-delivery-20261018.md)。

2026-10-17 恢复阶段重新下载远程后核查；完整每文件统计与 SHA 见本轮 remote-state.json。没有名为 final 的远程分支。以下 SHA 是当前已核实状态，不是以后提交的永久保证。

| 分支 | SHA | 提交时间（上海） | 关系 |
|---|---|---|---|
| main | 1aa5a9e36e1558b95972941d5ce7dbf6553da431 | 10-12 10:11:21 | 比赛基线的直接父提交 |
| competition/zjj-core-final-20261010 | cc4e36b4e302fcdc53cc809a012c77d8464182af | 10-13 10:49:38 | 竞赛软件正式核查基线 |
| dev | 32370d4e39c2d9cb6f664ce672c0ec8210eee0ae | 10-17 19:16:06 | 比赛基线之后两个提交，现已与比赛分支不同 |
| feature/trusted-action-resolver-v1 | 86f284bf4787e9990b47b8159cd1e6b9e5824b03 | 10-17 11:56:18 | 从比赛基线新增一个提交；PR #3 仍 Draft／未合并 |
| experiment/trusted-action-feasibility-20261017 | 4b301f9cbdc61440a9f5ee7e79b7e0af70628f8c | 10-17 11:00:25 | 比赛基线新增一个隔离实验提交 |
| experiment/trusted-action-resolver-v1-20261017 | 202f34e75f0b6e13ec49c58a313f0c32ab9e3095 | 10-17 11:12:43 | 在上一实验上再增加一个提交 |

## 1. 实际差异

恢复阶段的新变化：dev 已加入 de14737（清理旧 vertical slice 链）和 32370d4（同进程最小输入 facade）；相对比赛分支为 51 文件、718 行新增、3770 行删除。其中旧测试删除、支持模块迁移和 bridge 新增必须分别审查，不能把测试总数下降解释为本轮回归通过。CommonW 的变化是 tool_final→final_fact 导入迁移，TrustedState 也迁移 scene_contract 导入。

新 TrustedFacade 持有测试 WRun，通过 identity_proof、accept_proof、worker_proof 和 read_proof 自动取得身份/执行证明；prepare 调用 fork_operation 从演示语料形成签署链。该 facade 适合受信同进程演示编排，不能原样注册为不受信 Agent 的工具，也不能把“无需传 proof”解释为不需要 H/worker 授权。其内存 ticket/response 缓存不替代本轮持久 RequestStore 和恢复语义。本轮没有合入这两个提交；本轮 196 项验证针对 PR #3 加统一整合代码，不证明最新 dev 的安全性或兼容性。未来移植须显式解决导入迁移和公共边界，不直接批量注册 facade。

main→比赛分支共 61 个文件变化：13 个 Python 代码/工具文件、3 个测试文件、20 个说明/规范文件、25 个证据文件。证据新增 31,554 行，占大部分行数；其余代码 358 行新增／23 行删除，测试 169／1，说明 440／85。因此“三万行差异”不能解释为三万行协议代码。

已检查的源码变化包括：显式 ZJJ-CORE-COMP-1 与保留 R2 ZJJ-AAP 的协议身份分离、固定竞赛 Schema 视图、W 启动绑定、签署 broker 的调用者挑战认证及到期重检、严格候选入口/数字解析、fork 读取当前 W 业务状态。原 system_dev/v26 文件无差异；新增 CompetitionSchema 是代码视图，不改原 R2 文件。

PR #3 相对比赛基线仅新增 36 个文件：5 个应用 Python 文件、2 个测试文件、4 个说明文件、25 个证据文件；原代码/Schema 没有修改。本轮整合在该精确 SHA 之上继续，不以旧本地 87f3a22 的提交身份代替远程 SHA（两提交树相同，但提交身份不同）。

两个远程实验与 PR #3 具有共同比赛基线，包含早期重复适配器和实验材料；不应整支合并叠加。P2 本地 OperationRegistry/ControlledW 只吸收事务协调的行为和反例，不直接移植第二套分配表。历史 patch、失败和计数继续保留为实验来源。

## 2. 开发与整合建议

当前正式说明以比赛分支为准；新功能工作以 PR #3 的最新已核查提交为起点。开发文档应同时列明“比赛基线 SHA”和“当前集成 SHA”，不要仅写 final。

本轮只在独立 clone 的 integration/unified-operation-lifecycle-20261017 修改。项目 sources、旧实验、另一任务工作副本与远程分支均不覆盖。本地 clone 采用独立 Git 对象和 refs，避免 git worktree 共享 refs 影响其他任务。

核查发现另一个 Work 任务正在独立复验原 PR/P2，使用自己的验证目录；没有把其结果加进本轮，也未向它发送消息、打断任务或修改其文件。并发验证会共享宿主资源，诊断报告必须记录这一环境因素，不能据此直接断言时钟故障原因。

开发交接采用单一写入者：本轮负责新整合分支；开发同学/其他 Work 只审阅该分支，或在另一个命名分支提交增量。禁止共同编辑同一临时目录或共享功能分支。每次交接记录 expected head SHA；发送前重新 fetch，若 PR #3 已变化则停止推送旧基线并评估新差异。不得 force-push 共享分支，也不能拿一个残留进程或锁文件当作任务仍在运行的证据。

若最终联合验证和审查通过，可先从本整合分支向 feature/trusted-action-resolver-v1 发增量 Draft PR，明确它依赖 PR #3；审批后再按团队选定顺序进入比赛分支。不得把旧 P2 补丁改名上传冒充本整合结果。时钟未决项或联合失败须在 Draft 描述中突出保留。

main 当前只是落后于比赛分支，不存在需要反向合入的独有提交。最小集成不需要同步 main；未来若团队决定 main 也发布竞赛版，可在明确审批后推进经过验证的祖先链。本轮不执行 main 同步、合并或分支删除。
