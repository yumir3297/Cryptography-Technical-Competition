# 有限状态形式化抽象、安全性质与证明边界

## 0. 范围声明

本文件**不是** ZJJ-CORE-2.6-R2 完整密码协议的计算安全证明。与 `abstract_checker.py` 配套的状态机仅抽象授权当前性、单意图接受、派发至多一次、不可变终局事实和换钥后的再认证。Ed25519、SHA-256、精确字节编码、依赖图闭包、读写事务实现、跨进程崩溃恢复、真实工具效果、支付/工业/医疗场景语义均在模型之外。

探查采用穷举有限状态 BFS、默认最长 18 个转换（实际可达状态的最短路径深度最多为 14；模型图在本界限内已遍历穷尽），2 个共享同一意图键的候选操作，revision 和 epoch 为 0/1。它验证的是**这些边界条件、这些状态和转换下的安全性质**，而不是任意长执行、任意数量主体或密码算法的正确性。

## 1. 状态与角色假设

状态 `S` 包括：

- `revision`：W 当前权威基础依据代；`u_approved`：经独立 U 签署的依据代；`denied`：W 已发布 DENY 的依据代；`permit[i]`：候选 G Permit 所绑定依据代。
- `accepted[i]` 与 `legitimate_at_accept[i]`：W 的接受墓碑和在接受线性化时合法守卫的历史快照。历史合法与**当前**有效要分开，否则合法接受后的撤销会制造错误反例。
- `revoked`、`calls[i]`、`final_fact[i]`、`proof_epoch[i]`、`settled[i]`、`tool_epoch`、`ledger_continuous`：分别代表撤销、派发次数、工具持久原事实、原事实认证密钥世代、结算次数、当前工具钥世代、原账连续性。

W 串行提交 W 可见的状态改变；G 可以不经 U 同意生成候选 Permit，但不能修改 W 或独立 U 签名结果。C/工具诚实，角色分离在合法模型里成立；信任密钥、时钟和原始账内容被抽象为受信谓词。审查只声称 **W 提交次序**，不保证工具实际效果与现实世界一致。

## 2. 接受守卫

令候选 `i` 的原子接受位置为 `Commit_i`。在合法模型中：

\[
G_i(S) = UApproved(S.rev) \land Permit_i.rev=S.rev \land
\neg Denied(S.rev) \land \neg Revoked \land Separated(U,G,X,V)
\land \bigwedge_j \neg Accepted_j.
\]

在 `Commit_i` 中，仅当 `G_i(S)` 成立，W 才记录 `Accepted_i:=true`，并冻结历史 `Legitimate_i:=true`。使用两个候选同一业务意图，可搜索并发候选是否破坏单意图至多一次接受。

这是 **简化守卫**，不等于协议实际 `RequiredDeps` 解析过程；`revision` 只有一个抽象覆盖代，现实协议要求核对多个不同键与空集范围。

## 3. 安全不变量

`I1` 任何 ACCEPTED 必须有合法的接受时刻守卫历史（而非不断变化的当前授权）。

\[
\forall i : Accepted_i \Rightarrow LegitimateAtAccept_i.
\]

`I2` 同一稳定业务意图候选只允许一个 ACCEPTED。

\[
\sum_i \mathbf{1}[Accepted_i] \le 1.
\]

`I3` 每个 operation 的应用层派发次数最多一次。

\[
\forall i : calls_i \le 1.
\]

`I4` 每个 operation 的结算次数最多一次。

\[
\forall i : settled_i \le 1.
\]

`I5` 持久终局存在前必须至少发生过一次派发；结算须有既存合法接受和已知原事实。

\[
finalFact_i \Rightarrow calls_i \ge 1,\quad
settled_i>0 \Rightarrow (finalFact_i\land Accepted_i).
\]

`I6` 旧认证钥世代证明在轮换后不触发首次结算；再认证只能读取原事实更新 `proof_epoch`，不改变 `calls/final_fact`。此性质主要由场景测试和动作定义观察，不是对真实工具账的证明。

## 4. 转换系统与威胁操作

- `UApprove(rev)`、`VDeny(rev)`、`ReviseBasis()`、`Revoke()`：W 权威资料变化。
- `IssuePermit(i)`：不限制 G 是否恶意生成候选许可，故授权安全须在 **Commit** 端检查。
- `Accept(i)`：线性化检查合法守卫，登记不可改接受墓碑。
- `Claim(i)`：已接受操作派发一次。已 started 的未知结果不能默认重派。
- `Finalize(i)`：工具在受信持久账中固定原事实（抽象），不会由网络报文或客户端自行产生。
- `Reattest(i)`：仅在连续原账中按当前 epoch 再认证，绝不再次派发。
- `Settle(i)`：验证当前证明、既存原事实并至多一次结算。
- `RotateKey` / `LoseLedgerContinuity`：工具合法换钥或账连续性失去；后一种情况下不推导一个失败终局。

## 5. 核验方法与反例诊断

`abstract_checker.py` BFS 对每个配置记录 `visited_states`、`explored_edges`、`max_reached_depth` 与 `first_violation.trace`。

变异实验有 8 组：忽略 U、忽略修订代、忽略 DENY、忽略意图墓碑、允许再次派发、允许重复结算、忽略撤销、允许同主体且忽略 U。每组若在有限搜索中出现违反不变量的轨迹，说明模型至少不是仅检查空规则；**不能据此断言该机制相对先前文献原创**，也不能得出实际攻击成功率。

## 6. 分层论证计划

1. **密码对象层**：严格 Ed25519、受限 JCS、签名域分离及未知字段拒绝；用独立编码/验签实现 + 负例向量交叉核验。
2. **业务状态层**：在上述抽象状态机基础上，将 W 原子读写、覆盖 revision、DENY 范围、U/G 主体分离逐项精化为实现可执行的业务轨迹。需要独立于同一个 Schema 生成器的测试 oracle。
3. **持久执行层**：验证派发见证、持久工具账、Crash/恢复、换钥账连续性；在没有持久实现之前 `I3/I4` 只在抽象层成立。
4. **跨 Profile 层**：PAY/IND/MED 的 evidence/intent/role/limit 具体策略和 39 项完整版语义测试，待最小完整协议参考执行器实现后执行。

完整性质最终应声明前提—保证关系：若 C、W、身份登记与工具账连续性等假设满足，那么 W 不接受未授权动作；若假设失效，则明确报告为模型外，不用安全术语模糊覆盖。
