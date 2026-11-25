# 差异化有效性报告（DIFFERENTIAL EFFECTIVENESS）

**问题（H2）：** 对于竞品原生机制尚未覆盖、不能充分表达或需要额外可信组件才能满足的安全问题，ZJJ-CORE 能否通过自身已有设计有效解决，同时保持合理的性能和业务可用性？

**结论先行：H2 只在“对象关系一致性”维度得到较强支持；在“目标必要资源下界”固定成本场景中没有超过 AADP 的最强静态配置；在“原子接受与证据耦合”维度发现了真实核心缺陷。不能给出统一的“本协议更优”结论。**

## 1. 实验 B：GoalFloor 必要资源下界

### 1.1 四组对照

同一组 20 条生成序列（seed `20261125`）：

- **A**：AADP 原生共享预算，可选动作与必要动作共用 `capacity`。
- **B**：AADP 原生最强静态配置：可选动作额度 = `capacity - Σ必要动作成本`，共享 effect cap 仍为 `capacity`。这不是故意弱化；它是 AADP 原生 cap 能表达的最强固定预留。
- **C**：ZJJ `goal_mode=off`（真实 CommonW，无 GoalFloor）。
- **D**：ZJJ `goal_mode=enforce`（真实 CommonW，C 签名 GoalFloor，同一事务预留）。

| 指标 | A AADP 预算 | B AADP 静态预留 | C ZJJ off | D ZJJ enforce |
|---|---:|---:|---:|---:|
| 序列数 | 20 | 20 | 20 | 20 |
| 必要资源下界违反序列 | **6** | **0** | **6** | **0** |
| 非法可选接受（Oracle 视为不可接受，含 PENDING） | 17 | 10 | 7 | 0 |
| 合法可选动作被拒 | 0 | 0 | 0 | 0 |
| 接受的可选动作 | 23 | 16 | 23 | 16 |
| 已成功必要动作 | 46 | 51 | 46 | 47 |
| 全部动作完成（含可选） | 10 | 10 | 10 | 10 |

**直接结论：**

1. **A（普通累计预算）确实会破坏必要资源下界：6/20 序列出现违反。**
2. **B（原生静态预留）也达到 0/20 违反，且与 D 的可选动作接受数相同（16）。**
3. B 的必要动作完成数更高（51 vs 47），因为 B 没有 GoalFloor 的 PENDING 阻断；D 在必要结果未知时更保守。
4. 因此，**固定单位成本、单 Goal 场景下，GoalFloor 没有呈现出相对 AADP 最强静态配置的安全增量**。这是本次实验的负结果，不能改写成“D 更安全”。

### 1.2 更大规模

AADP 原生 1000 条序列（同一生成器）：

| 指标 | A 原生预算 | B 静态预留 |
|---|---:|---:|
| 序列数 | 1000 | 1000 |
| 下界违反 | 490 | **0** |
| 可选接受 | 1512 | 841 |
| 必要完成 | 2169 | 2785 |
| 全部完成 | 287 | 287 |

B 用“牺牲可选动作吞吐”换取下界安全；它不是免费的，但仍然是一个可用的原生配置。这进一步削弱了“只有 GoalFloor 能保护下界”的强断言。

ZJJ enforce 实际 W 运行：

- 120 条启动，14 worker 负载下出现 22 个 `CLOCK_UNKNOWN` 行和 4 个 abort；**排除受干扰序列后 93 条干净序列**，0 下界违反、0 Oracle mismatch、0 非法可选接受、76 个可选动作、229 个必要动作完成、33 条全部完成。
- 20 条配对数据与上表一致；93 条更大样本没有对应的 C off 配对，不能把 93 与 20 直接做显著性检验。
- **未达到 1,000 条真实 ZJJ 序列目标。** 这不是协议拒绝，而是运行环境时钟窗口（2 s）在高并发下失配和宿主重启。未用数学模型填补。

### 1.3 静态配置无法表达的情形

AADP B 的预留额度是**配置时固定值**，不读取 C 认证的当前 Goal 状态。以下情形需要额外的可信配置管理器或人工更新，属于“额外可信组件”，不能算 B 原生自动满足：

- 必要动作成本随业务参数变化，且配置只能取最坏值；取最坏值会把可选动作全部拒绝（安全但可用性差），取典型值会破坏下界。
- 新 Goal/epoch 在运行中增加必要依赖；静态 quota 不会自动收缩。
- 多 Goal 共享资源时，需要按所有 Goal 的当前 OPEN 义务求和；静态配置只能预留一个上界。
- 必要结果 PENDING/BLOCKED 后，静态 quota 不会自动释放或阻断。
- 策略版本更新需要人工同步；AADP 审计记录 policy hash，但不把“当前 Goal 依赖 revision”作为原子接受条件。

本轮**没有**完成可变成本的端到端 PAY W 对照，因此上述只是设计层分析，不是已测胜负。GoalFloor 的 `test_two_goals_on_one_resource_are_summed` 和 `test_certified_cost_must_equal_w_plan_cost` 提供了模块级证据，但不能冒充 W 端到端。

### 1.4 评价

- **GoalFloor 的价值不是“普通预算一定不安全”**：普通预算 A 不安全，但原生静态预留 B 可以安全。
- GoalFloor 的差异化卖点应当改为：**由 C 签名、随 Goal epoch 更新、与 W 接受事务原子耦合、可离线复验的动态下界**。这比“静态 quota”更难配置错误，也更容易审计；本轮没有证明它在固定成本下带来更高的安全率。
- 业务可用性：D 在 PENDING 时阻断后续动作，B 不阻断；本样本中 B 的必要动作完成更多。D 的保守性是可解释的，但不能宣传为“无损”。

## 2. 实验 C：密码学关系约束

### 2.1 十类负例

所有对象由隔离测试环境中的真实注册密钥生成。被替换的对象本身签名有效；拒绝来自对象之间的关系检查。

| # | 关系负例 | 拒绝位置 |
|---|---|---|
| 1 | 各对象签名有效，但 Task 不同 | `STATE_UNAVAILABLE` |
| 2 | 合法链依赖旧 Policy 版本 | `BASIS_BINDING` |
| 3 | 合法授权/许可对应不同 Action payload | `CLAIM_FALSE` |
| 4 | 合法 Review 来自另一动作 | `REVIEW_DENY` |
| 5 | 提交的必要依赖集合缺少应有依赖 | `DEP_CONFLICT` |
| 6 | 合法但已过期的 Task 状态对象 | `BASIS_BINDING` |
| 7 | 授权后、接受前 Task/Policy 版本变化 | `BASIS_BINDING` |
| 8 | 合法执行结果与其他 attempt 组合 | `FINAL_BINDING` |
| 9 | 合法 X 回执与另一结算状态组合 | `FROZEN_RECEIPT_CONFLICT` |
| 10 | 合法 root 签名的资源证书与另一资源组合 | `RESOURCE_KEY` |

**结果：10/10 拒绝，0 接受。** 原始记录：`external_benchmark/results/crypto_relations.json`。

### 2.2 基线

- **单对象签名基线**：如果只验证每个对象的签名，10 个组合都会被接受。这里不是实际运行了一个“单签名 verifier”，而是分析性基线：所有产生签名的密钥都是登记密钥，实际拒绝码全部是关系错误，不是签名错误。该基线记为 `analytical_signature_only`，不冒充运行结果。
- **AADP**：没有 ZJJ 的 Task/Basis/RequiredDeps/Attempt 对象图，多数类别 N/A；不能把“不适用”说成“AADP 失败”。
- **AP2**：有 mandate chain、约束和 receipt 关系验证，多个同类测试通过；但 2 个中间 hop 的 aud/nonce 测试失败。AP2 在支付链关系约束上强，不能宣称 ZJJ 全面优于 AP2。
- **ZJJ**：10/10 拒绝。这一结果支持“关系约束机制有效”，但不证明覆盖所有可能关系，也不证明 Ed25519 原语安全。

### 2.3 评价

- 这是 H2 最强的正面证据：**签名均有效时，ZJJ 仍能拒绝跨 Task/Policy/Action/Review/Dep/Attempt/Receipt/Resource 的组合。**
- 但竞品不是“不会做关系约束”：AP2 也做链关系约束；AADP 的对象模型不同。差异化应表述为“ZJJ 用同一套 Ctx/Basis/RequiredDeps/ActionHash/Ref 机制覆盖了更广的业务对象图”，而不是“竞品只验单签名”。

## 3. 实验 D：原子接受与密码学证据耦合

### 3.1 通过的测试

| 项目 | 结果 | 证据 |
|---|---:|---|
| 真实子进程崩溃边界 | 3/3 PASS | accept 提交后、EXEC 消费后、settle 提交后 |
| 接受竞争 | 4/4 PASS | 同 intent 8 个合法 permit 只有 1 个 accept；最后一次资源；claim/cancel 竞争 |
| 离线证据包 | 13/13 PASS | 独立 verifier，不打开 W 数据库 |
| 15 个篡改/重放 | 15/15 拒绝 | `test_evidence_verifier` |
| 重放/重复结算 | 通过 | 唯一 attempt、settlement 唯一索引、existing 返回 |

这些结果支持：在单次 accept 事务内，资源、GoalFloor、COMMIT 见证和后续证据可以保持一致；UNKNOWN 不释放预留、不重派。

### 3.2 发现的核心缺陷：交错结算被误判为旧账

真实复现（`results/interleaved-settlement-defect.json`）：

```text
accept A, accept B, claim A, claim B, execute A, execute B, settle A, settle B
```

结果：

- `settle A` → `LEDGER_STALE_UNKNOWN`（尽管 A 的 final fact 由真实工具密钥签名，且绑定 A 的 attempt）；
- `settle B` → SETTLED；
- A 仍为 `STARTED`，资源 `reserved=1`，`settlements=1`，无重复效果。

定位：`competition/core/common_w.py` 的 `_verify_final` 将本次 final 的 checkpoint `high_water` 与工具账本**当前** `high_water` 比较；B 的 final 推进了当前 high-water 后，A 的较早但真实的 checkpoint 被当作 stale。代码位置约在：

```python
if int(cl['high_water']) < tool['high_water']:
    raise ProtocolError('LEDGER_STALE_UNKNOWN')
```

**性质：**

- 不是越权、不是重复效果、不是签名伪造；
- 是**活性/可用性缺陷**：合法的较早 final 无法完成结算，资源长期占用；
- 与本次 H2 的“正确授权判断能否与真实接受事实及后续证据保持一致”直接相关；
- 本轮不修改核心语义，保留失败证据，详见 `CORE_DEFECT_INTERLEAVED_SETTLEMENT.md`。

### 3.3 外部效果边界

ZJJ 的 accept 事务原子，不等于外部工具效果原子。工具在 W 外执行；UNKNOWN 通过保留预留、禁止重派来处理。不能把“W 内一致”宣传为“外部支付/工业动作 exactly-once”。

### 3.4 评价

H2 在原子证据维度**没有得到完整支持**：大部分正向测试通过，但交错结算缺陷说明“授权—接受—执行—结算”并非在所有并发路径上都保持可用。该缺陷可通过串行化同一工具的在途 attempt，或在 final 中携带可验证的历史 checkpoint 链来修复；修复前不能宣称完整。

## 4. 性能

同一 20 条配对样本（不是稳定基准）：

| 模式 | 接受样本 | p50 | p95 | p99 | 备注 |
|---|---:|---:|---:|---:|---|
| C off | 71 | 3.11 s | 4.14 s | 4.33 s | 6 worker 负载 |
| D enforce | 67 | 2.63 s | 4.26 s | 4.41 s | 4 worker 负载 |

这是**探索性**数据，包含进程启动、签名子进程、SQLite 和宿主负载；不能把 C/D 的差异解释为 GoalFloor 开销。现有项目内部小样本曾报告 p50 1.32/1.34 s、约 +1%；那不是本次外部复现数据，不能混用。没有稳定 p99、QPS 或置信区间。

## 5. H2 分维度结论

| 维度 | 结论 | 证据强度 |
|---|---|---|
| 必要资源下界 vs AADP 普通预算 | 支持：D 0/20 vs A 6/20 | 中；真实 W |
| 必要资源下界 vs AADP 最强静态预留 | **不支持**：B 也 0/20，且可选动作相同 | 中；真实 W + 1000 AADP |
| 动态成本/多 Goal 动态更新 | 设计上需要额外可信组件；未完成端到端 | 低；只有模块测试 |
| 多源对象关系一致性 | 支持：10/10 签名有效组合被拒 | 强；真实签名 |
| 原子接受 + 证据 | 部分失败：3/3、13/13 通过，但发现交错结算缺陷 | 强（含反例） |
| 统一机制成本 | 无稳定性能结论 | 低 |

**总判断：H2 是“部分成立、带明确反例”，不是统一胜利。**
