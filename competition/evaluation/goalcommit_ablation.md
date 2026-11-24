# GoalCommit 差分与消融

生成脚本：`python -m competition.evaluation.experiments.ablation`。原始：`results/ablation.json`。

## 1. 模型

| 模型 | 能力 |
|---|---|
| Baseline A | 本地 shape/policy/task 门控；无签名、无状态、无原子接受 |
| Baseline B | A + H 的 CommitProof 单签名 + ActionHash 一致；无 U/G/V、无 W 状态 |
| Baseline C | 原 CommonW，`goal_mode='off'` |
| Shadow | CommonW + GoalFloor 计算并写入 COMMIT，但不改变放行 |
| Proposed | CommonW + GoalFloor enforce（`LegacyGuard AND GoalFloorGuard`） |

Baseline A/B 是“规则级基线”，不是完整协议实现；不能用它们声称“原协议不安全”。它们只用于说明每一层机制的独立贡献。

## 2. 非法案例接受率

非法案例 5 个：payload 篡改、重复接受、容量竞争、GoalFloor 挤占、UNKNOWN 后继续。

| 模型 | 非法接受 | 非法总数 | 接受率 |
|---|---:|---:|---:|
| Baseline A | 5 | 5 | 100% |
| Baseline B | 4 | 5 | 80% |
| Baseline C（原 W） | 2 | 5 | 40% |
| Shadow | 2 | 5 | 40% |
| Proposed | 0 | 5 | 0% |

## 3. 逐案例

| 案例 | A | B | C 原 W | Shadow | Proposed |
|---|---|---|---|---|---|
| 合法请求 | 接受 | 接受 | 接受 | 接受 | 接受 |
| Action payload 篡改 | 接受 | 拒绝（ActionHash/签名） | 拒绝（`CLAIM_FALSE`/绑定） | 拒绝 | 拒绝 |
| 重复接受同一 action | 第二次执行 | 第二次执行 | 幂等返回，`accepts=1` | 同 C | 同 C |
| 容量 1 两个不同请求 | 两个接受 | 两个接受 | 1 接受 + `RESOURCE_EXHAUSTED` | 同 C | 同 C |
| GoalFloor 挤占（可选动作抢必要资源） | 接受 | 接受 | 接受 | 接受但 COMMIT `goal.decision='F'` | 拒绝 `GOAL_CAPACITY_FLOOR` |
| UNKNOWN 后继续接受 | 接受 | 接受 | 接受（容量允许） | 接受但 COMMIT `goal.decision='F'` | 拒绝 `GOAL_PENDING_UNKNOWN` |

## 4. 独立贡献

- **签名/ActionHash（B）**：阻止 payload 替换，但不提供状态、唯一执行、容量或目标下界。
- **CommonW 原子接受（C）**：阻止重复接受、容量超限；仍不能阻止“局部合法但挤占必要目标”的动作，也不能把 UNKNOWN 当作不可继续。
- **GoalFloor（Proposed）**：在 C 之上补上两个独立性质：
  1. 目标必要资源下界：`Spent+Reserved+CandidateCost+RemainingGoalFloor<=Capacity`；
  2. UNKNOWN/PENDING 必要事项不被当作 DONE，阻止后续接受。
- **Shadow**：证明新 guard 能识别差异，但不改变旧放行；它的非法接受率与 C 相同，符合 shadow 设计。

## 5. 限制

- 样本是 6 个定向案例，不是统计显著性实验。
- A/B 没有真实 W/工具，只评估门控规则；因此“A/B 接受”表示其规则不会阻止该请求，不表示它们真的完成了执行。
- 没有把 GoalFloor 的收益归因于“密码学更难”；它的价值是**把 C 认证的目标资源下界放进 W 的同一原子事务**，并让 Agent 无法自报/删除。
