# 待优化事项（按风险排序）

## P0：安全闭环前提

| # | 事项 | 当前状态 | 风险 | 下一步 |
|---|---|---|---|---|
| P0-1 | 选定正式场景端到端 | IND/PAY/MED + 事件响应工作流均有真实 W 链和离线包 | 已满足所选范围 | 继续扩大 Profile 子变体 |
| P0-2 | 关键密码学关系 | 15 项篡改拒绝；合法包 PASS | 已满足所选范围 | 补全 39 项逐子变体 |
| P0-3 | 未授权接受/不合法结算 | 本轮未发现可复现案例 | 未做形式化证明 | 继续定向攻击 + 模型检查 |
| P0-4 | 并发线性化 | 20 条真实历史 + 10,000 模型历史 | 真实历史数量不足 | 扩大到 1,000 条真实 W 历史 |
| P0-5 | 崩溃恢复不产生第二次资格 | 3 个新增边界 + 既有 lost-ack/unknown | 单机；未做网络分区 | 做远程工具/网络故障注入 |
| P0-6 | UNKNOWN 不误判 | GoalFloor `PENDING` 阻止新接受；reservation 保留 | 依赖 W 状态 | 加入周期性审计/告警 |
| P0-7 | 回执/工具应答/结算重试 | 已测 | 已满足所选范围 | 继续做工具换钥/账丢失 |
| P0-8 | 追踪到原始动作 | COMMIT/attempt/final/ref 链可离线重算 | 已满足所选范围 | 补全 Result/AUDITBundle |
| P0-9 | 不破坏既有安全测试 | 核心 70/70 PASS | Windows 全量套件环境失败 | Linux CI 全量回归 |
| P0-10 | 正式 39 项 | 2 PASS / 37 NOT_RUN | 不能宣称全通过 | 逐项闭合 |

## P1：比赛级实验证据

| # | 事项 | 状态 | 缺口 |
|---|---|---|---|
| P1-1 | 五组实验 | 1/2/3/5 PASS，4 PARTIAL | 消融的 A/B 是规则级基线，不是完整实现 |
| P1-2 | 每组正常/拒绝/故障 | 基本覆盖 | GoalFloor 的故障路径还可增加工具换钥/账丢失 |
| P1-3 | 四种不同业务模型 | 3 官方 Profile + 1 工作流 | 第四工作流复用 IND wire，不是第四官方 Profile |
| P1-4 | 每种业务一条真实 W 证据链 | 有 | 事件响应包是独立运行，未纳入三 Profile 同一 anchor |
| P1-5 | 1,000 条真实并发历史 | 20 条 | 需批量运行/更轻的初始化 |
| P1-6 | 10,000 条状态转移 | 10,000 × 24 = 240,000 | 参考模型不是 W 本体 |
| P1-7 | 关键字段至少一种定向篡改 | 15 项 | 未穷举所有字段 |
| P1-8 | 崩溃边界逐点 | 3 个新增 + 既有 | 接受前回滚、工具执行后应答丢失中的更多窗口 |
| P1-9 | 重复运行 | 部分实验重复 10 次 | 未做跨日/跨机复现 |
| P1-10 | 原始日志/构建 SHA/审计脚本 | 有 | 需在最终提交中固定 SHA |

## P2：竞争力增强

| # | 事项 | 状态 |
|---|---|---|
| P2-1 | GoalCommit 消融 | 已有 5 模型 × 6 案例；可扩展到统计样本 |
| P2-2 | 高并发 p50/p95/p99 + 吞吐 | 只有 n=5 的接受延迟；无 QPS |
| P2-3 | 独立证据包 + 评委复验 | 已有 |
| P2-4 | 有界模型检查/归纳不变量 | 只有参考模型 10,000 条；无 TLA+/Alloy/Coq |
| P2-5 | 区分已有密码学与组合设计 | 已在 `innovation_summary.md` 写清 |
| P2-6 | 接受成功但执行 UNKNOWN 的完整恢复 | 已有 `unknown_query`/`lost_ack`，但未做成演示视频/单页 |
| P2-7 | 测试发现问题转回归 | 本轮新增 16+15+3+3+1 测试已固定 |

## 具体技术风险

1. **`w_goal` 唯一性**：enforce 模式启动时创建 `w_goal(profile,goal_group,obligation)` 的 partial unique index，且同事务 `evaluate` 先拒绝重复；shadow 模式刻意不建该 index，以允许观察重复拒绝差异。若未来有人绕过 `accept` 直接写 `w_goal`，仍需独立不变量检查。
2. **资源容量只允许 revision 1**：`register_resource` 不支持容量变更；GoalFloor 要求 `capacity` 精确等于资源行。若 C 需要扩容，需要新的资源证书/迁移规则。
3. **GoalFloor 依赖 `INCIDENT` 状态**：事件响应工作流在状态变化后必须由 C 发布新 epoch；这是刻意的新鲜性要求，但增加了运行复杂度。
4. **跨 Profile 无原子性**：不能把两个 Profile 的资源放在一个 GoalFloor 里；`validate_claim` 要求 action profile 与 goal profile 一致。
5. **离线验证器对 W 账本的信任**：`spent/reserved` 是 W 断言；验证器只检查算术和签名链。要更强，需要 W 对资源账/结算行签名，或使用可验证账本。
6. **Windows/Linux 回归**：Windows 全量测试存在 Linux DAC/Unix socket 环境失败；本轮已尝试在 WSL Ubuntu 上运行完整套件，结果以 `results/regression.json` 为准。若仍有失败，必须逐项分类，不能统一归因于环境。
7. **工具换钥/账丢失**：AUD-02B/C 未跑；当前只有高水位/head 矛盾检测，不能证明工具账完整回滚会被发现。
8. **性能样本量**：常规 accept 样本仅 5 次；本轮新增 8 单元批量测量（40 次/模式）仍属探索性，不宣称稳定 p99 或统计显著的低开销。
9. **Goal 停用与未决 obligation**：C 可将 GOAL 置为 inactive。W 现在会在 `w_goal` 仍有 PENDING 链接时以 `GOAL_INACTIVE_PENDING` 阻止新接受（enforce），shadow 仅记录；所有链接 DONE 后停用不再阻止。这是受信 C 的治理边界，不是对恶意 C 的防护。
10. **Goal 容量变更**：同一 group 的 epoch 必须保持 capacity/resource/unit 不变（`GOAL_MIGRATION_REQUIRED`）；扩容需要新 group 或新的迁移规则，当前未实现。
