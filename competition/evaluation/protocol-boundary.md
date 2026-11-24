# 协议边界与信任模型（2026-11-24）

## 受信前提

C 根、W 主机与账本、X 签名者、工具/效果端、C 时间源、worker/delivery 密钥均在受信范围内。签名的前提是密钥未泄露；离线证据不能证明现实账本未被整体伪造、证据当期性或真实设备效果。

## 明确覆盖

- 恶意/错误 Agent：自报动作、payload、成本、依赖、角色、Goal 字段。
- 重放/替换：旧消息、旧 acceptance、旧 attempt、旧 final fact、跨操作/跨 Profile 拼接。
- 状态版本：旧 Task/Policy/Goal/Incident，prepare 与 accept 之间的 C 发布。
- 并发：同资源、同 intent、同 obligation、multi-goal。
- 崩溃：接受提交、EXEC-0、工具应答丢失、结算提交、重启恢复。
- 离线证据包篡改。

## 明确不覆盖

- 攻破 C/W/X/工具/时间源或窃取私钥后以合法身份签新对象。
- 完全回滚 W/工具 SQLite 并伪造高水位/head。
- 跨机共识、拜占庭 W、网络分区、真实支付/医疗/工业/隔离设备。
- 真人同意的法律效力、动态组织治理、长期密钥轮换全历史撤销。
- 物理世界“恰好一次”。

## Goal 治理边界

- C 可以将 Goal 置为 inactive；若 `w_goal` 仍有 PENDING 链接，enforce 返回 `GOAL_INACTIVE_PENDING`，shadow 只记录。所有链接 DONE 后停用不再阻止。
- 同一 group 新 epoch 必须保持 `resource_key/capacity/unit` 和非空 obligation 集合；删除/改名被 `GOAL_MIGRATION_REQUIRED` 拒绝。
- 旧 POLICY/TASK/INCIDENT revision 变化使 Goal `GOAL_DEPS_STALE`；需要 C 发布新 epoch。
- 这是受信 C 的治理规则，不防御完全恶意的 C。

## 离线验证器不能证明

- W 账本 `spent/reserved` 的现实真实性；
- 证据是“当前”的；
- 证据包外没有隐藏历史；
- 真实设备效果；
- 信任根没有被攻破。
