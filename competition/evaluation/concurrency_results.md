# 线性化并发实验结果

生成脚本：`python -m competition.evaluation.experiments.concurrency --repetitions 10 --model-count 10000`。原始：`results/concurrency.json`。

## 1. 实际 W 历史

- 真实历史：20 条（10 次 × 2 场景），每次从新的 C/W/tool 初始化开始。
- 全部 `linearizable = true`。
- 每个 winner 的 `reservation_plan` 见证形成串行链：`reserved_before` 等于前一个 winner 的 `reserved_after`；`accept_seq` 唯一。
- 拒绝调用没有 `w_operation` 行；`w_resource.reserved/spent` 等于 `w_reservation` 求和；容量不超限。

| 场景 | 并发请求 | 预期/实际 | 拒绝码 |
|---|---|---|---|
| `two_required_obligations` | 必要动作 A、B，容量 2 | 恰好 1 接受；另一个因 UNKNOWN/PENDING 不得并行 | `GOAL_PENDING_UNKNOWN` |
| `optional_last_slot` | 可选 C、D 抢最后 1 单位，C GoalFloor 为必要 A 保留 1 | 恰好 1 接受；另一个被下界拒绝 | `GOAL_CAPACITY_FLOOR` |

示例历史（`results/concurrency.json`）：

```text
required_race 0 True {'accept_seq': [1], 'reserved_chain': [1],
                      'rejected_codes': ['GOAL_PENDING_UNKNOWN']}
optional_race 0 True {'accept_seq': [1], 'reserved_chain': [1],
                      'rejected_codes': ['GOAL_CAPACITY_FLOOR']}
```

## 2. 独立参考模型

`Model` 位于实验脚本内，**不调用** `competition.core.goal_floor.evaluate`，也不打开 W。它独立实现：
- `0 <= spent + reserved <= capacity`；
- 必要事项 `OPEN/PENDING/DONE/BLOCKED`；
- PENDING/BLOCKED 阻止新接受；
- 已 DONE 的同一必要事项不能再次接受；
- `spent + reserved + cost + remaining_floor <= capacity`。

结果：
- 10,000 条随机历史；
- 每条 24 次操作/转移；
- 240,000 次受检转移；
- 0 违反；
- 固定随机种子 `20261123`，失败会保存最小反例（本轮无失败）。

## 3. 判定 Oracle

不是“最终余额正确”这一弱检查，而是：
1. `accept_seq` 唯一；
2. winner 的 `reserved_before` 链连续；
3. `w_resource` 与 `w_reservation` 求和一致；
4. 拒绝请求没有 operation 行；
5. 资源容量不超限；
6. 场景特定的拒绝码符合 GoalFloor 语义。

## 4. 限制

- 20 条是真实 W 历史，不是 P1 建议的 1,000 条真实 W 历史。1,000+ 由独立模型补足，二者在报告中分开，不能混算。
- 单机 SQLite `BEGIN IMMEDIATE`；没有多机/网络分区。
- 没有测 1,000 个真实并发线程的吞吐；见 `performance_results.md` 的样本量说明。
- 没有把 `w_goal` 的 shadow 重复链接当作安全通过；enforce 才是结论对象。
