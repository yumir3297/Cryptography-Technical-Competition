# 性能测量结果

生成脚本：`python -m competition.evaluation.experiments.performance`。原始：`results/performance.json`。构建：`fcbc6b3b3ad63c9de84387c98bccc004f726a77b`。

环境：Windows 11，Python 3.13.9，cryptography 50.0.0，jsonschema 4.26.0；单机；真实子进程 X/worker/工具。

## 1. 纯 GoalFloor 判定

20,000 次，单次 `evaluate`（不打开数据库、不签名）：

| 指标 | 值 |
|---|---:|
| p50 | 98.2 µs |
| p95 | 119.7 µs |
| p99 | 165.0 µs |
| mean | 101.2 µs |
| min / max | 88.2 µs / 3.09 ms |

这是纯函数开销；不包括 W 事务、签名和工具。

## 2. 真实 W 接受

每次从新初始化的 W 开始，测一次 `accept`（包含 guard 复核、X 子进程签名、COMMIT/回执）：

| 模式 | n | p50 | p95 | p99 | mean |
|---|---:|---:|---:|---:|---:|
| `goal_mode='off'` | 5 | 1537.3 ms | 1574.2 ms | 1574.2 ms | 1547.0 ms |
| `goal_mode='enforce'` | 5 | 1552.6 ms | 1583.0 ms | 1583.0 ms | 1557.1 ms |

- 两者差异约 15 ms（约 1%），在 5 个样本的噪声范围内；GoalFloor 的额外纯计算约 0.1 ms，相对接受路径（约 1.5 s，主要是子进程签名/核验）可忽略。
- n=5 不能给出稳定的 p95/p99；表中数字只用于量级，不作为 SLA。

## 3. 生命周期

| 阶段 | off | enforce |
|---|---:|---:|
| claim | 935.9 ms | 994.4 ms |
| execute（真实子进程 + 工具 SQLite 签名事务） | 921.3 ms | 938.0 ms |
| settle | 100.5 ms | 101.3 ms |

## 5. 本轮补充：8 单元批量样本（40 次/模式）

生成：`python -m competition.evaluation.experiments.performance_bulk`；原始 `results/performance-bulk.json`。每轮初始化 8 个真实签名单元，先接受 7 个可选动作，再接受 1 个必要动作；每个动作后真实 claim/execute/settle。样本为 5 轮 × 8 次 = 40 次/模式，冷/热混合，属探索性。

| 模式 | n | p50 | p95 | p99 | mean | 证据包字节 |
|---|---:|---:|---:|---:|---:|---:|
| off | 40 | 1324.9 ms | 1555.5 ms | 1724.1 ms | 1357.9 ms | 404,170 |
| enforce | 40 | 1338.4 ms | 1605.3 ms | 1616.6 ms | 1370.4 ms | 410,701 |

- enforce 相对 off 的 p50 增加约 **13.5 ms（约 1.0%）**；p95/p99 受样本和负载影响，不能作稳定尾延迟结论。
- GoalFloor 证据包增加约 **6.5 KB（约 1.6%）**。
- 仍未达到每组 100/300 次目标；报告为实际 40 次，不用纯算法 20,000 次样本冒充真实 W 接受样本。

