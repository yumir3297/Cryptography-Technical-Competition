# 实验矩阵与状态

状态口径：`PASS` 表示本轮真实运行并保存原始结果；`PARTIAL` 表示已运行但覆盖不完整；`NOT_RUN` 表示未运行；`OUT_OF_SCOPE` 表示明确不声称。

| # | 实验 | 目标 | 状态 | 原始结果 | 结论/限制 |
|---|---|---|---|---|---|
| 1 | 长序列决策差分 | 连续局部合法动作逐步侵占必要资源，GoalFloor 在下界处拒绝 | PASS | `results/long-sequence.json`、`results/long-sequence-summary.json`、`counterexamples/` | 20 条真实配对、112 动作、off 84 / enforce 76、20 个反例、Oracle mismatch 0；10,000 条四类模型序列 |
| 2 | 线性化并发 | 多 Agent 同资源/同 obligation 不因旧读造成双重接受 | PASS | `results/concurrency-summary.json` | 40 条真实 W 历史全线性化；10,000 条独立模型历史、240,000 转移、0 违反；不是 1,000 条真实 W 历史 |
| 3 | 故障注入/崩溃恢复 | 持久化边界不产生第二次执行资格/结算 | PASS | `results/crash-recovery.json`、`tests/test_crash_boundaries.py` | 3 个边界；UNKNOWN 保留；停用有 PENDING 时 `GOAL_INACTIVE_PENDING` |
| 4 | 密码学篡改/重放/上下文替换 | 单签名合法但对象关系非法必须拒绝 | PASS | `results/crypto-attacks.json`、`tests/test_evidence_verifier.py` | 15 个定向篡改全部拒绝；新增 Goal capacity/Profile/资源/epoch 关系测试 |
| 5 | 差分/消融 | 每项机制的独立贡献 | PARTIAL | `results/ablation.json` | Baseline A/B、Original、Shadow、Proposed；A/B 是规则级基线 |
| 6 | 端到端独立审计 | 评委只用证据包+固定信任根复验 | PASS | `evidence/20261123/*`、`results/evidence-audit.json` | 三 Profile/Goal/Incident 各 13 类检查；干净 checkout 13/13 PASS |
| 7 | 跨业务场景 | IND/PAY/MED + 安全事件响应 | PASS（GoalFloor 子集） | `results/cross-goal.json`、`results/cross-scenario.json` | PAY/MED 正常 GoalFloor 审计 PASS、挤占拒绝；事件响应复用 IND wire，不是第四官方 Profile |

## 1. 线性化并发

运行：

```powershell
python -m competition.evaluation.experiments.concurrency --repetitions 10 --model-count 10000
```

场景：
- `two_required_obligations`：A/B 两个必要动作并发，容量 2；期望恰好一个接受，另一个 `GOAL_PENDING_UNKNOWN`。
- `optional_last_slot`：C/D 两个可选动作并发，C GoalFloor 为必要动作 A 保留 1 单位；期望恰好一个接受，另一个 `GOAL_CAPACITY_FLOOR`。

判定：
- `accept_seq` 唯一；
- winner 的 `reserved_before` 形成 `0→1` 链；
- 资源账 `reserved/spent` 与 reservation 求和一致；
- 拒绝请求没有 `w_operation` 行；
- 不接受“只看最终余额”的弱检查。

限制：20 条真实历史，不是 1,000 条；1,000+ 用独立模型补足，二者分开报告。

## 2. 崩溃恢复

运行：

```powershell
python -m unittest -v competition.tests.test_crash_boundaries
```

边界：
1. `accept(crash_after_commit=True)` 后进程退出：重开 W，operation 存在、receipt PENDING、reservation 1；`complete_receipt` 恢复，不重新接受。
2. `execute_once(crash_after_marker=True)`：EXEC-0 标记已提交、工具未调用；重试返回 `EXEC_ALREADY_CONSUMED`，查询 UNKNOWN，结算保留预留，工具效果 0。
3. `settle(crash_after_settlement=True)`：结算已提交、客户端未收到成功；重开 W，`w_settlement` 1 行、reservation SPENT；重复结算返回 `existing=True`，不新增结算。

现有 `lost_ack`/`unknown_query` 覆盖工具已执行但应答丢失、查询原 attempt。

限制：单机 SQLite；不是物理恰好一次；没有真实网络分区。

## 3. 密码学篡改

运行：

```powershell
python -m unittest -v competition.tests.test_evidence_verifier
```

15 项：
- 合法包 PASS；
- action payload 替换；
- action_hash 替换；
- Goal capacity 篡改；
- TaskRef 替换；
- resource capacity 篡改；
- scope 替换；
- Permit ref 替换；
- Acceptance commit ref 替换；
- Acceptance 签名篡改；
- C 控制记录签名篡改；
- attempt_id 替换；
- 工具终局 outcome/effect 篡改；
- FinalFactID 替换；
- 私钥不存在于包内。

限制：这些是定向单点篡改；不是所有字段的穷举模糊测试。

## 4. 差分/消融

模型：
- Baseline A：本地 shape/policy/task 门控，无签名、无状态。
- Baseline B：A + H 的 CommitProof 单签名 + action hash 一致。
- Baseline C：原 CommonW（`goal_mode='off'`）。
- Proposed：CommonW + GoalFloor enforce。

案例：合法、payload 篡改、重复接受、容量竞争、GoalFloor 挤占、UNKNOWN 后继续。

结果见 `goalcommit_ablation.md` 与 `results/ablation.json`。限制：A/B 不是完整 W 实现，不能用来声称“原协议不安全”；它们只用于说明每层机制的独立贡献。

## 5. 独立审计

```powershell
python -m competition.evaluation.verify `
  competition/evaluation/evidence/20261123/IND-DEMO-1-package.json `
  competition/evaluation/evidence/20261123/anchor-three-profiles.json
```

证据包包含：C 控制记录、完整授权链、COMMIT、X Acceptance、W 执行包、工具终局/检查点、W 资源/reservation/settlement、可选 GoalFloor 见证。验证器不打开 W 数据库、不导入 CommonW。

## 6. 跨场景

- `IND-DEMO-1`、`PAY-1`、`MED-DEMO-1`：各有真实 W 端到端链和离线包；业务状态/审批/效果规则不同（工业质检、支付异常复核、临床复核）。
- 安全事件响应：复用 IND wire；新增 C 认证 `INCIDENT` 记录（severity/status/required_actions）、独立 containment 工具账与资源、GoalFloor 优先级保留、状态变化使旧 Goal 失效并 epoch 2 恢复。**明确不宣称新增官方 Profile 或真实隔离设备。**
