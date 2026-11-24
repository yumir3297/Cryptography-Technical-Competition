# 核心贡献与创新定位（2026-11-24）

## 1. 标准技术

Ed25519、SHA-256 域分离、SQLite `BEGIN IMMEDIATE`/WAL、C 发布-订阅式控制记录、角色密钥/PoP、工具终局/检查点。这些是已有密码学与系统工程，不作为新原语宣称。

## 2. 本作品的组合贡献

1. **C 认证的目标必要资源下界**：GoalFloor 只做必要条件，不是规划器、winning region、rank function。
2. **同一 W 原子事务**：资源账、GoalFloor、意图、obligation、COMMIT 在同一个 `BEGIN IMMEDIATE` 内；拒绝回滚无业务副作用。
3. **Agent 无法选择/删除/改价**：请求中没有 goal 字段；W 用冻结 Action 的 selector 匹配 C 规则；成本来自 W `plan.amount`。
4. **COMMIT 见证 + X 间接签名**：`COMMIT.value.goal` 含 goal_refs/deps/matched、算术、`state_ref/check_ref`；X Acceptance 的 `commit_record_ref` 绑定它。
5. **UNKNOWN/PENDING 纳入下界**：PENDING/BLOCKED 不被当作 DONE；UNKNOWN 保留资源，GoalFloor 阻止新的必要接受。
6. **跨版本/停用治理**：依赖 revision/ref 新鲜、epoch 迁移保持 obligation 集合、停用时 PENDING 链接触发 `GOAL_INACTIVE_PENDING`。
7. **可离线复验**：独立验证器重算签名、refs、GoalFloor 算术和 FinalFactID，不打开 W 数据库。

## 3. 与普通安全门控的差别

消融（5 个非法案例）：本地门控 5/5、单签名 4/5、原 CommonW 2/5、Shadow 2/5、Proposed 0/5。原 W 仍会接受“局部合法但挤占必要资源”和“UNKNOWN 后继续接受”；GoalFloor 关闭这两个缺口。

## 4. 不应夸大

不证明目标最终可达；不提供跨 Profile 原子性；不证明 W 账本现实真实性、证据当期性或真实设备效果；不宣称正式 39 项全部通过；不把模拟支付/医疗/工业/隔离当生产效果。
