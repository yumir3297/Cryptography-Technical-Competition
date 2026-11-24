# 剩余限制（2026-11-24）

## 核心限制

1. **正式 39 项未闭合**：2 PASS、0 FAIL、22 PARTIAL、15 NOT_RUN。PARTIAL 只是局部证据，不是正式 PASS。
2. **真实 W 并发历史 40 条**，未达到 1,000 / 200 目标；10,000 条是独立参考模型，不能补足真实数量。
3. **长序列真实配对 20 条**，未达到 100 条目标；10,000 条随机序列是参考模型。
4. **工具换钥/账丢失 AUD-02B/C 未跑**；只有高水位/head 矛盾检测，不能证明整库回滚检测。
5. **Linux/WSL 全量 526 tests，1 failure / 3 errors**；四项隔离复跑通过，尚需修正环境后的单次全量回归。
6. **离线验证器不证明 W 账本现实真实性、证据当期性、证据集合完整性、真实设备效果**。
7. **无跨 Profile 原子性**；资源账按 `(profile,key)` 隔离。
8. **无 HSM/远端治理/多机共识**；C/W/X/工具/时间源仍是本地受信组件。
9. **性能样本仍有限**；8 单元批量样本属探索性，不宣称稳定 p99 或统计显著低开销。
10. **`status/audit` 是认证投影**，不是正式签名 Result/AUDITBundle。
11. **安全事件响应工作流复用 IND wire**，不是第四个官方 Profile，也不代表真实隔离设备。
12. **Goal 停用的治理**：enforce 在 PENDING 链接存在时阻止新接受；所有链接 DONE 后停用不再阻止。完全恶意 C 不在威胁模型内。

## 已修补

- Goal epoch 删除/改名 obligation → `GOAL_MIGRATION_REQUIRED`。
- enforce `w_goal` 部分唯一索引；shadow 不建，允许观察重复。
- 停用但仍有 PENDING → `GOAL_INACTIVE_PENDING`。
- PAY/MED 资源键大写（如 `CNY`）→ GoalFloor schema/validate 支持。
- 合法 C 签名但 W 容量不匹配 → `GOAL_CAPACITY_MISMATCH`。
