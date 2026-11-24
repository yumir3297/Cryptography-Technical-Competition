# 最终验收矩阵（2026-11-24）

## P0：安全闭环前提

| # | 条件 | 状态 | 依据 |
|---|---|---|---|
| P0-1 | 选定正式场景从真实入口到可信终局 | PASS | IND/PAY/MED + 事件响应；`evidence/` |
| P0-2 | 关键密码学关系 | PASS | 15 项篡改 + GoalFloor 关系测试 |
| P0-3 | 无已知未授权接受/不合法结算 | PASS（本轮范围） | 核心+专项回归；不宣称形式化证明 |
| P0-4 | 并发历史满足原子接受 | PASS（40 条真实） | `concurrency*.json`；未达 1,000 |
| P0-5 | 崩溃恢复不产生第二次资格 | PASS | 3 边界 + lost-ack/unknown |
| P0-6 | UNKNOWN 不误判 | PASS | `GOAL_PENDING_UNKNOWN`、reservation 保留 |
| P0-7 | 回执/应答/结算重试 | PASS | 崩溃/unknown/lost-ack |
| P0-8 | 可追踪到原始动作 | PASS | COMMIT/attempt/final/ref |
| P0-9 | 不破坏既有安全测试 | PASS（核心 91） | Windows 全量环境问题另列 |
| P0-10 | 正式 39 项 | PARTIAL | 2 PASS / 22 PARTIAL / 15 NOT_RUN |

## P1：比赛级实验证据

| # | 条件 | 状态 | 说明 |
|---|---|---|---|
| P1-1 | 五组实验 | PASS/PARTIAL | E1–E5/E7；E6 探索性 |
| P1-2 | 正常/拒绝/故障路径 | PASS | 各实验含反例/故障 |
| P1-3 | 四种不同业务模型 | PARTIAL | 三官方 Profile + 事件响应扩展；不是第四官方 Profile |
| P1-4 | 每种业务真实 W 证据链 | PASS | IND/PAY/MED/事件响应 |
| P1-5 | 1,000 条真实并发历史 | PARTIAL | 实际 40；模型 10,000 分开 |
| P1-6 | 10,000 条状态转移 | PASS | E1 10,000 + E2 10,000 |
| P1-7 | 关键字段定向篡改 | PASS | 15 项 + 新增关系测试 |
| P1-8 | 崩溃边界逐点 | PARTIAL | 3 新增 + 既有；工具换钥/账丢失未跑 |
| P1-9 | 重复运行 | PARTIAL | 20 序列、40 历史；未跨日/跨机 |
| P1-10 | 结果/SHA/审计脚本与日志 | PARTIAL | `results`、`manifest`、复验脚本已提交；原始日志在运行工作区，待独立归档 |

## P2：竞争力增强

| # | 条件 | 状态 |
|---|---|---|
| P2-1 | GoalCommit 消融 | PASS（定向 5 案例） |
| P2-2 | 高并发 p50/p95/p99/吞吐 | PARTIAL（探索性样本） |
| P2-3 | 独立证据包/评委复验 | PASS |
| P2-4 | 有界模型检查 | PASS（4,363 状态/67,746 转移） |
| P2-5 | 标准技术 vs 组合创新 | PASS（`core-contributions.md`） |
| P2-6 | 接受成功执行 UNKNOWN 全过程 | PASS（`unknown_query`/`lost_ack`） |
| P2-7 | 发现问题转回归 | PASS（本轮新增测试） |

## 环境

- Windows：核心 91/91、专项 45/45、目标/跨场景 23/23。
- Linux/WSL：完整套件 **526 tests，1 failure / 3 errors**；4 项均为环境（负载下 clock 超 2s、复制树无 `.git`、HTTP proxy 拦截 127.0.0.1），隔离复跑均通过；未在单一修正进程重跑 526/526。
- 证据：`evidence/20261123/`、`evidence/incident-20261123/`；干净 checkout 13/13 PASS。

## 结论

当前状态：**CONDITIONAL_READY**。核心创新和主要安全路径有真实差分、并发、篡改、崩溃和离线复验支持；但正式 39 项未闭合、真实历史/样本量未达目标、工具换钥/账丢失和 Linux 全量仍有明确缺口。不得把本表读成 READY 或 39/39 PASS。
