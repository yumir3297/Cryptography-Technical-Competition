# 实验结论（2026-11-24 最终轮）

构建身份：基线 `7604d6b`；代码/证据生成 `fcbc6b3`；本轮新增代码/测试提交以最终 Git 记录为准。所有数字来自 `results/` 原始 JSON，未把参考模型结果冒充真实 W 结果。

## E1 长序列 Agent 决策差分（核心主实验）

- 真实 CommonW 配对序列：**20 条**（每条 5–8 个真实签名动作）。
- 总动作：**112**；off 接受 **84**，enforce 接受 **76**；UNKNOWN **8**。
- 原 W 接受但 Proposed 拒绝的真实反例：**20 个动作位置**；独立 Oracle 与实际结果 mismatch：**0**。
- 最小 headroom：**0**；这表示 Proposed 在必要资源下限处精确拒绝，而不是靠事后余额检查。
- 参考模型：**10,000 条**随机长序列，四种资源模型：固定成本 2,549、异质成本 2,463、突发成本 2,483、多 Goal 共享 2,505；以独立算术/状态机判定，未导入被测 `evaluate`。
- 保存了 2 个真实反例包：`counterexamples/seq-0-counterexample.json`、`seq-1-counterexample.json`。它们是 **off 模式**包，离线 GoalFloor 检查预期以 `GOAL_WITNESS_MISSING` 失败；这正说明 off 没有 GoalFloor 见证，不能把 off 的接受当作合规。
- 典型序列（capacity=3，required=3，optional=3）：
  - off 接受 `O0,R0,O1`，拒绝 `R1,R2`；
  - Proposed 拒绝 `O0,O1,O2`，接受 `R0,R1,R2`；
  - 两者都满足旧资源上界，但只有 Proposed 保留全部必要事项。

结论：GoalFloor 在真实 W 上识别并阻止了“局部合法但逐步侵占必要资源”的长序列；独立 Oracle 未发现错误接受/错误拒绝；没有把任务最终成功率当作核心指标。

## E2 真实 W 并发线性化

- 历史真实 W 历史：**40 条**（上一轮 20 + 本轮 bulk 20）。
- 本轮 bulk：4 个场景 × 5 次：`optional_last_slot`、`required_race`、`multi_goal_shared_resource`、`same_intent`。
- 全部存在合法串行解释：`accept_seq` 唯一、reservation 链连续、拒绝无 operation 行、资源账求和一致、无重复 attempt/结算。
- 独立参考模型：10,000 条历史、240,000 次转移、0 违反。
- 未达到 1,000 条真实 W 历史目标；本轮报告真实数量 40，不以模型数量补足。

## E3 密码学绑定完整性

- 原有 15 项定向篡改/重放：15/15 拒绝，合法包 PASS。
- 新增真实 W 关系测试：
  - C 合法签名的 GoalFloor capacity 与 W 资源容量不一致 → `GOAL_CAPACITY_MISMATCH`；
  - 跨 Profile / 跨资源借用 → `GOAL_ACTION` / `GOAL_RESOURCE_MISMATCH`；
  - 旧依赖 revision → `GOAL_DEPS_STALE`；
  - 合法 epoch 更新与非法删除 obligation → 通过/`GOAL_MIGRATION_REQUIRED`。
- 没有发现“所有单签名都合法但对象关系非法”被接受的情况。

## E4 崩溃恢复与 UNKNOWN

- 3 个新增真实子进程边界：接受提交后、EXEC-0 消费后、结算提交后；3/3 PASS。
- 既有 lost-ack/unknown：三 Profile 覆盖；不重派、不释放预留、不重复结算。
- Goal 停用：存在 PENDING 链接时 enforce 返回 `GOAL_INACTIVE_PENDING`；shadow 仅记录。
- `w_goal` enforce 部分唯一索引：实际 SQLite schema 验证 + 直接重复插入被 `IntegrityError` 拒绝。
- 未覆盖：工具换钥/工具账丢失（AUD-02B/C）、网络分区。

## E5 跨场景通用性

- IND：GoalFloor 专项证据包 13/13 PASS；长序列覆盖必要/可选/多 Goal/UNKNOWN。
- PAY：默认动作在 off 下接受；两个各自合法的 Goal 共享资源后，enforce 对同一动作 `GOAL_CAPACITY_FLOOR`；单 Goal 正常接受并结算，离线审计 PASS。
- MED：同上，`GOAL_CAPACITY_FLOOR` + 正常包 PASS。
- 安全事件响应：低优先级隔离被 `GOAL_CAPACITY_FLOOR` 拒绝；状态变化使旧 Goal `GOAL_DEPS_STALE`，epoch 2 恢复；证据包 13/13 PASS。
- 没有修改业务安全语义；事件响应仍明确为 IND wire 上的扩展，不是第四个官方 Profile。

## E6 性能

- 纯 GoalFloor：p50 98.2 µs、p95 119.7 µs（20,000 次）。
- 8 单元批量：40 次/模式；off p50 1324.9 ms，enforce p50 1338.4 ms（+约 1.0%）；证据包 +6.5 KB。
- 真实 accept 由子进程签名主导；样本仍属探索性，不宣称稳定 p99 或 QPS。

## E7 独立模型验证

- 有界穷举：4,363 个可达状态、67,746 次转移、0 违反（`results/model-check.json`）。
- 覆盖容量 2–6、必要事项 2–4、可选事项 0–4；检查资源上界、一次性 obligation、PENDING 阻断、拒绝无状态变化。
- 参考模型 10,000 条长序列（E1）+ 10,000 条并发历史（E2）独立于被测 `evaluate`。
- 没有引入 TLA+/Coq；证明范围是有限状态模型与参考实现，不是全局定理。

## 正式 39 项

仍为 **2 PASS / 0 FAIL / 22 PARTIAL / 15 NOT_RUN**。PARTIAL 只是局部证据，不是正式 PASS；逐项见 `conformance_39.md`。

## Linux/WSL 全量回归

- 526 tests，1 failure / 3 errors；失败/错误均为环境：负载下 clock 样本超过 2s（2 项）、复制树缺少 `.git`（1 项）、HTTP proxy 拦截 127.0.0.1（1 项）。
- 4 项隔离复跑均通过（NO_PROXY、git init、无并发负载）；未在单一修正进程重跑 526/526，因此不宣称全绿。
- 原始记录：`results/regression.json`、`logs/linux-full-526.log`。
