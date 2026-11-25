# 威胁模型与能力边界对照（THREAT MODEL COMPARISON）

本文件只比较与本项目研究范围相关的部分。不同协议的“动作”语义不同，不能用同一张表声称某一个协议全面更强。

## 1. ZJJ-CORE 的信任与职责边界

| 角色/对象 | 职责 | 是否可信 |
|---|---|---|
| Agent | 提出动作、规划、目标 | 不可信 |
| C | 登记密钥、策略、资源、签发 GoalFloor/控制记录 | 受信约束制定者 |
| W / worker | 确定性核验、原子接受、资源预留、唯一 attempt、证据 | 受信执行点 |
| H | 证明提交身份、持有关系、读取身份 | 受信持钥方 |
| G/U/V/X | 许可、批准、独立评审、接受签字 | 受信持钥方 |
| 工具/效果端 | 执行外部效果、返回签名 final | 受信但外部效果不由 W 原子保证 |
| SQLite 账本 | 保存 spent/reserved/状态 | W 的受信断言 |
| 时间源/事件时钟 | 提供窗口 | 受信 |

**协议负责：** 密码学可验证动作授权、资源下界、原子接受、唯一执行资格、终局/结算证据绑定。

**协议不负责：**

- 证明目标可达、规划正确、路径最优或最终成功；
- 证明 W 的账本数字对应现实世界的银行余额/库存；
- 保证外部工具效果 exactly-once；
- 保护被攻陷的 W/C/X/工具私钥；
- 防御绕过受信执行入口的旁路；
- 对纯语义型提示注入提供通用检测；它只在动作被映射为可验证业务动作后约束该动作；
- 跨 Profile 原子性；
- 发布跨组织 bound-permit 规范（这是 P13 的缺口）。

## 2. 对照表

| 威胁/性质 | AADP/onedoor | AP2 | CaMeL | Tether | ZJJ-CORE |
|---|---|---|---|---|---|
| 未授权工具调用 | PDP 默认拒绝/边界/审批 | mandate 约束 | 控制/数据流隔离解释器 | OS 级策略 | C/W 授权链、ActionHash、策略/任务绑定 |
| 共享预算/并发预留 | 原生强项（SQLite 事务、回收） | 累计/周期预算约束，无执行账本 | 非目标 | 状态策略可表达，未在业务预算层验证 | W 资源事务 + GoalFloor 同事务 |
| 目标必要资源下界 | 没有 GoalFloor 对象；最强静态 cap 可近似 | 无通用未来义务 | 非目标 | 可写状态策略，需 OS 语义映射 | C 签名的 GoalFloor，动态 OPEN 义务求和 |
| 多源对象关系 | 单请求/证据链，无 Task/Basis/Review/Attempt 图 | SD-JWT 链、约束、receipt，关系强 | 数据/能力标签，不是业务对象图 | 资源标签/IFC，不是业务 Task/Policy | Ctx/Basis/RequiredDeps/ActionHash/Refs/版本/作用域 |
| 审批/撤销 | 原生 | mandate 层可表达 | 非目标 | 策略可表达 | U/V、DENY 覆盖、角色撤销、Goal 停用 |
| 重放/重复执行 | request_id / permit 单次 | 收据/jti/链校验 | 解释器级 | 状态策略可表达 | intent 墓碑、nonce、唯一 attempt、唯一 settlement |
| 崩溃恢复 | 有 rebuild/恢复，公开套件无进程崩溃测试 | SDK 无执行账本 | 非目标 | 论文未给实现 | 3 个真实子进程边界；发现交错结算缺陷 |
| 独立证据验证 | hash-chain audit + 可选签名 | mandate/receipt 验证 | 轨迹/策略，不是业务审计包 | Lean 策略/轨迹 | 离线 verifier 13 项，含 W 总账限制声明 |
| 跨信任边界凭证 | bound-permit profile，23/24 | delegated mandate chain | 非目标 | 非目标 | 内部 W→tool delivery；无公开跨组织 profile |
| LLM 提示注入 | 不检测模型输出；决策前置 | 约束支付语义 | 设计目标（控制/数据流） | OS 副作用策略 | 只约束被映射的动作；端到端未测 |
| 信息流/机密性 | 非核心 | 选择性披露 | 核心 | 核心（IFC） | 非核心；不是 IFC 协议 |
| 形式化保证 | 规范不变量 + 测试 | 密码学链 + 测试 | 解释器隔离 | Lean 证明（论文） | 有限状态模型 + 测试；不是全局定理 |

## 3. 关键不可比之处

### 3.1 “动作”不同
- AADP 的 action_type 是 PDP 策略键；没有 ZJJ 的 Task/Basis/Review/Attempt 对象图。
- AP2 的 payment/checkout mandate 是商业支付对象；没有通用 W 资源事务。
- Tether 的 read/write/uploadNet 是 OS 级抽象动作；没有业务目标/必要资源概念。
- CaMeL 的 capability 是解释器中的数据/控制能力；没有业务预算。

所以：

- AADP 对 P03 的 N/A 不是“它不会做关系约束”，而是“它没有这组对象”；
- Tether 对业务预算的 N/A 不是“它做不到”，而是“它的抽象层不同”；
- ZJJ 对 IFC 的 N/A 不是“它更安全”，而是“不在范围”。

### 3.2 “安全效果”不同
- AADP 的 eval 是固定脚本，16→3 是脚本场景的计数，不是 LLM 防御率。
- AgentDojo 的 16/16 utility、9/9 injection 是 ground-truth 回放，不是模型行为。
- Tether 的 100% in-scope recall 是论文的回放子集，且没有公开实现可复现。
- ZJJ 的 75 个测试是真实 W 路径，但不是对所有业务策略的证明。

## 4. 本项目的真正差异化候选

1. **C 认证的动态必要资源下界 + W 同事务**：不是“预算”本身，而是“当前 Goal 的 OPEN 义务下界”与接受的原子耦合。固定成本下可被静态 cap 近似；动态成本/多 Goal 更新仍缺少端到端证据。
2. **跨对象关系约束**：同一套 Ctx/Basis/RequiredDeps/ActionHash/Ref/版本/作用域绑定，拒绝 10 类签名有效但关系非法的组合。
3. **接受事实与证据链的耦合**：COMMIT、X Acceptance、attempt、tool final、settlement 的绑定；但交错结算缺陷说明并发路径尚未闭合。

## 5. 不可宣称

- 不宣称 ZJJ 能阻止所有提示注入；它只阻止未通过其业务动作授权的效果。
- 不宣称 GoalFloor 证明目标可达或任务成功。
- 不宣称 W 账本等于现实世界余额。
- 不宣称 ZJJ 的外部工具效果 exactly-once。
- 不宣称 AADP 的 N/A 是安全失败，或 AP2 的两个原生失败是已利用漏洞。
- 不宣称 Tether 的论文数字已被本次复现。
