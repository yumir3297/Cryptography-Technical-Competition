# 能力覆盖性报告（CAPABILITY COVERAGE）

**问题（H1）：** 对竞品已经实现并验证的、与本协议研究范围相交的安全能力，ZJJ-CORE 能否达到相应安全效果？

**结论先行：** 在冻结的 13 项属性定义中，12 项属于“竞品已验证且共同适用”，ZJJ 满足 10 项、2 项为 PARTIAL。属性级覆盖率为 **10/12 = 83.3%**。这不是实现等价，也不是普遍性证明。

## 1. 定义与计数规则

```text
Coverage = ZJJ PASS 的共同适用属性数
           / 竞品至少一方 PASS 且 ZJJ 有可执行映射的属性数
```

- **PASS**：本轮有命名的 ZJJ 实际测试通过，且至少一个竞品的公开测试通过。
- **PARTIAL**：有实现或局部证据，但缺少同一语义的完整验证，或只覆盖了内部/有限场景。
- **FAIL**：有可执行测试且实际未达到。
- **N/A**：竞品没有该对象或该能力不在其协议范围。
- 同一属性下多条测试不重复计分；原始用例通过率另列，避免用重复测试放大覆盖率。
- 测试定义、来源和变更记录：`external_benchmark/manifests/test_definitions.json`。

## 2. 属性级矩阵

| ID | 能力 | AADP | AP2 | ZJJ | 结论 |
|---|---|---|---|---|---|
| P01 | 动作授权有效性 | PASS | PASS | PASS | 三方均有实际拒绝路径 |
| P02 | 身份及授权来源认证 | PASS | PARTIAL | PASS | AP2 两个中间 hop 的 aud/nonce 测试失败 |
| P03 | 动作与授权内容一致性 | N/A | PASS | PASS | AADP 无同构多源对象图 |
| P04 | 并发预算安全 | PASS | N/A | PASS | AADP 真实线程竞争；ZJJ 真实 W 竞争 |
| P05 | 原子资源预留 | PASS | N/A | PASS | 拒绝不产生业务副作用 |
| P06 | 重放与重复执行控制 | PASS | PASS | PASS | request_id / permit / attempt 三类路径不同 |
| P07 | 崩溃恢复 | PARTIAL | N/A | PASS | AADP 有 rebuild/恢复但冻结版本无进程崩溃测试；ZJJ 3/3 子进程边界 |
| P08 | 审批及撤销语义 | PASS | N/A | PASS | 审批消费、角色撤销、DENY 覆盖 |
| P09 | 执行结果关联 | PASS | PASS | PASS | 结果绑定到动作/尝试/收据 |
| P10 | 历史证据独立验证 | PASS | PASS | PASS | 审计链/收据/离线包 |
| P11 | 高后果恶意动作阻断 | PASS | PARTIAL | PARTIAL | AADP 为脚本场景 16→3；ZJJ 仅确定性授权，不是 LLM 端到端 |
| P12 | 跨步骤安全状态保持 | PASS | PARTIAL | PASS | AADP sequence；ZJJ GoalFloor/PENDING |
| P13 | 跨信任边界动作绑定凭证 | PASS | PASS | PARTIAL | AADP bound-permit 23/24；ZJJ 只有内部 W→tool 交付凭证 |

**适用集合：** P01–P06、P08–P13（12 项）。  
**满足集合：** P01–P06、P08–P10、P12（10 项）。  
**不满足/未充分验证：** P11、P13。  
**未计入覆盖：** P07（竞品只有 PARTIAL，不能把 ZJJ 的通过算成“竞品已验证”的分母）。

### 分类统计

| 分类 | 数量 | 属性 |
|---|---:|---|
| 双方均满足（至少一个竞品 PASS + ZJJ PASS） | 10 | P01–P06, P08–P10, P12 |
| 仅竞品满足/本协议 PARTIAL | 1 | P13 |
| 仅本协议满足而竞品未充分验证 | 1（不计入覆盖率） | P07（AADP PARTIAL） |
| 双方均未满足 | 0 | — |
| 不适用 | 多个单元格 | AP2 的 P04/P05/P07/P08；AADP 的 P03 |
| 尚无法验证 | 1 个端到端维度 | P11 的 LLM/AgentDojo 防御效果 |

## 3. 原始测试通过率（单独报告，不混入覆盖率）

| 对象 | 用例 | 通过 | 说明 |
|---|---:|---:|---|
| AADP 决策/预算/审计子集 | 266 | 266 | `aadp-capability-junit.xml` |
| AADP 全量 | 2513 | 2501 | 8 个构建/环境失败 |
| AP2 全量 | 188 | 186 | 2 个中间 hop 失败 |
| AgentDojo 原生 | 32 | 31 | 1 个 Anthropic typing 失败 |
| ZJJ 能力子集 | 75 | 75 | 含 15 subtests、3 个崩溃边界 |
| ZJJ 离线包 | 13 | 13 | 独立 verifier |

这些数字不能横向比较：用例数量、语义和覆盖对象都不同。AADP 的 266 个测试比 AP2 的 188 个测试多，不代表 AADP 更强；ZJJ 的 75 个测试也不代表其覆盖全部竞品能力。

## 4. 逐项解释

### P01 动作授权有效性
- AADP：未列出动作 `default_deny`；越界 `bounds` 拒绝。
- AP2：支付/结账约束拒绝（金额、商户、SKU、日期）。
- ZJJ：没有完整评审、动作/授权不匹配、发布 DENY 均拒绝。
- 结论：共同满足；但各自保护的“动作”抽象不同，不能把 AADP 的 `action_type` 直接等同于 ZJJ 的 Action。

### P02 身份及授权来源认证
- AADP：审批人/proposer 身份、bound permit presenter key。
- AP2：issuer/holder 签名、KB-JWT cnf。
- ZJJ：登记角色密钥、subject 分离、来源 E 和签名域。
- 注意：AP2 的 2 个中间 hop 测试失败，因此 AP2 记为 PARTIAL；AADP 仍为 PASS。

### P03 动作与授权内容一致性
- AP2：mandate chain 的 constraint/transaction binding；`action_digest`/`sd_hash` 路径。
- ZJJ：`ActionHash`、`Ctx`、`Basis`、`Permit` 的绑定；broker 拒绝把不同 action 的 payload 塞入签名。
- AADP：决策按单次请求，缺少 ZJJ 的 Task/Basis/RequiredDeps 对象图，因此 N/A；这不是 AADP 的失分。

### P04 并发预算安全
- AADP：真实多连接、多线程、`BEGIN IMMEDIATE` 竞争；4/8/16 线程均未超预留。
- ZJJ：4 个真实 W 竞争用例，最后一次资源只产生一个 accept。
- 结论：双方都有并发预算安全；实现机制不同。

### P05 原子资源预留
- AADP：`decide_and_reserve` 与 `report_result` 分离，未报告预留可回收；拒绝不执行 connector。
- ZJJ：`ENFORCE` 拒绝时 `accepts/outbox/attempts/goal_links = 0`，reservation 为 0。
- 结论：共同满足。

### P06 重放与重复执行
- AADP：`request_id` 重放返回原结果、不重复预留；permit 单次。
- AP2：收据/闭环引用与存储校验；不是执行账本级 exactly-once。
- ZJJ：intent 墓碑、ACC nonce、唯一 attempt、结算唯一。
- 结论：共同满足，但保证层次不同；不能把 AP2 的 receipt 校验当成真实支付去重。

### P07 崩溃恢复
- AADP 公开套件有 rebuild/恢复逻辑，但本轮没有发现同等的进程在 COMMIT 边界被杀测试；记为 PARTIAL。
- ZJJ：3 个真实子进程边界（accept 提交后、EXEC 消费后、settle 提交后）全部通过；UNKNOWN 保留资源、不重派。
- 不把 ZJJ 的通过计入覆盖率分母，因为“竞品已验证”这一半不成立。

### P08 审批及撤销
- AADP：审批消费、proposer 不能自批、过期/重放语义。
- ZJJ：U/V 分离、角色撤销后旧链不可复活、DENY 覆盖不能被后续批准擦除。
- 结论：共同满足；ZJJ 的 DENY coverage 更接近“不可撤销的否决”，AADP 的 kill switch/approval 是另一条路径。

### P09 执行结果关联
- AADP：四种 outcome，`timeout` 提交预算、`not_attempted` 释放。
- AP2：receipt 引用 closed mandate。
- ZJJ：attempt_id/action_hash/commit_ref/final_fact_id/settlement 绑定；15 个篡改测试拒绝。
- 结论：共同满足。

### P10 历史证据独立验证
- AADP：hash chain + policy hash + signed receipt（可选）。
- AP2：ES256 receipt + reference store callback。
- ZJJ：离线 verifier 不打开 W 数据库，从锚点重算 13 项检查。
- 结论：共同满足；但 ZJJ 的 verifier 明确声明“W 总账是受信断言”，不证明物理效果。

### P11 高后果恶意动作阻断
- AADP：脚本 eval 将 harmful 从 16 降到 3；仍有注入收件人/重试缺口。
- AP2：约束阻止越权支付，但无 LLM 注入语义。
- ZJJ：真实授权拒绝未绑定动作；**未完成 AgentDojo LLM 端到端**，因此 PARTIAL。
- 这是本轮最重要的未完成能力，不应把确定性拒绝包装成“LLM 防御率”。

### P12 跨步骤安全状态保持
- AADP：sequence rule 的 `count_over` 拒绝第二次超阈值退款。
- ZJJ：GoalFloor 的 PENDING 阻断第二次 accept，required 动作完成后转 DONE。
- 结论：共同满足。

### P13 跨信任边界动作绑定凭证
- AADP：bound-permit profile，23/24 向量有测试（V17 currentness 为 gap）；recipient 独立验证、presenter key、一次性消费、confirmation。
- AP2：跨域 mandate 链，3 步 bank→SA→CP→merchant 流程通过。
- ZJJ：W→tool 的 delivery packet 绑定 action/attempt/commit/acceptance，但它是内部受控进程边界；没有公开发布的跨组织 bound-permit profile、recipient SDK 或状态 currentness 机制。
- 因此 ZJJ PARTIAL。这是 H1 的真实缺口，不应隐藏。

## 5. 结论

1. **H1 在属性级得到部分支持：10/12（83.3%）共同适用属性满足，2 项未充分满足。**
2. 不能声称“ZJJ 覆盖了竞品全部能力”。P13 跨信任边界凭证与 P11 LLM 端到端是明确缺口。
3. AADP 的单请求决策模型没有 ZJJ 的多源对象图；这既解释了 ZJJ P03/P12 的增量，也意味着不能把 AADP 的 N/A 当成 FAIL。
4. AP2 的 mandate/约束链在支付语义上更强；ZJJ 的资源事务/GoalFloor 在通用业务动作上更强。二者不是替代关系。
5. 所有“共同满足”只覆盖本轮测试语义；不构成对所有部署、所有策略或所有攻击者的证明。
