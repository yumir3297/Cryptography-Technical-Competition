# 答辩用结果（PPT_READY_RESULTS）

以下 5 页均可由仓库内原始 JSON/JUnit 复验。所有数字是“本轮外部实验”的实际结果，不是论文引用。

## 结论 1｜竞品公开实验可复现，但 ZJJ 只覆盖 10/12 共同属性

**一句话：** 在 13 项冻结属性中，12 项共同适用，ZJJ PASS 10 项，PARTIAL 2 项，属性级覆盖率 83.3%。

| 对象 | 实际运行 |
|---|---|
| AADP 决策/预算/审计/许可子集 | 266/266 PASS |
| AADP 全量 | 2501/2513 PASS，8 个构建/环境失败 |
| AP2 SDK | 186/188 PASS，2 个中间 hop 失败 |
| AgentDojo 原生测试 | 31/32 PASS |
| ZJJ 能力子集 | 75/75 PASS |

**ZJJ 缺口：**
- 跨组织 bound-permit / recipient / currentness：PARTIAL（AADP 23/24，AP2 mandate 链通过）。
- LLM 高后果动作端到端：PARTIAL（AgentDojo 只做了 ground-truth 回放）。

**数据：** `RESULTS.json`、`CAPABILITY_COVERAGE_REPORT.md`、`fig1-capability-matrix.png`。  
**复验：** `python external_benchmark/benchmarks/capability_coverage/build_matrix.py`。  
**边界：** 这是属性级覆盖，不是实现等价或普遍安全证明。

## 结论 2｜10 类“所有签名都合法但关系非法”的组合全部被拒

**一句话：** 跨 Task、Policy 版本、Action、Review、依赖集合、历史状态、授权/接受版本、attempt、receipt、资源的 10 类负例，ZJJ 10/10 拒绝，拒绝码全部是关系错误，不是签名错误。

| 负例 | 拒绝位置 |
|---|---|
| 不同 Task | `STATE_UNAVAILABLE` |
| 不同 Policy 版本 | `BASIS_BINDING` |
| 合法许可对应不同 Action | `CLAIM_FALSE` |
| 合法 Review 用于另一动作 | `REVIEW_DENY` |
| 缺少必要依赖 | `DEP_CONFLICT` |
| 旧 Task 状态 | `BASIS_BINDING` |
| 授权/接受之间版本变化 | `BASIS_BINDING` |
| 合法结果与另一 attempt | `FINAL_BINDING` |
| 合法 X 回执与另一结算 | `FROZEN_RECEIPT_CONFLICT` |
| 合法 root 资源证书与另一资源 | `RESOURCE_KEY` |

**对照：**
- 单对象签名分析基线：0/10 拒绝（会接受）。
- AP2：mandate/约束链有同类关系验证，部分能力已满足；不能宣称 ZJJ 全面优于 AP2。
- AADP：没有 ZJJ 的 Task/Basis/Attempt 对象图，多数类别 N/A，不能当作竞品漏洞。

**数据：** `external_benchmark/results/crypto_relations.json`、`fig4-crypto-relations.png`。  
**复验：** `python external_benchmark/benchmarks/differential_effectiveness/run_crypto_relations.py`。  
**边界：** 证明的是本轮 10 类关系负例；不是所有可能关系、不是 Ed25519 原语证明。

## 结论 3｜GoalFloor 在固定成本下没有超过 AADP 最强静态配置

**一句话：** 20 条配对序列中，普通预算 A 有 6/20 下界违反；但 AADP 静态预留 B 与 ZJJ enforce D 都是 0/20。B 与 D 接受的可选动作均为 16，B 的必要动作完成更多（51 vs 47）。

| 组 | 下界违反 | 可选接受 | 必要完成 | 全完成 |
|---|---:|---:|---:|---:|
| A AADP 普通预算 | 6/20 | 23 | 46 | 10 |
| B AADP 静态预留 | 0/20 | 16 | 51 | 10 |
| C ZJJ off | 6/20 | 23 | 46 | 10 |
| D ZJJ enforce | 0/20 | 16 | 47 | 10 |

**AADP 1000 条：** A 490/1000 违反；B 0/1000；B 可选 841 vs A 1512，必要完成 2785 vs 2169，全完成同为 287。

**结论：** “普通累计预算不足”成立；“只有 GoalFloor 能保护下界”不成立。GoalFloor 的差异化必须限定为**C 认证、动态 OPEN 义务、随版本更新、与接受事务原子耦合、可审计**，而不是固定成本下的安全率。  
**数据：** `DIFFERENTIAL_EFFECTIVENESS_REPORT.md`、`fig3-floor-violation.png`、`fig6-availability.png`。

## 结论 4｜原子接受与离线证据大部分通过，但发现一个核心缺陷

**通过：**

- 3/3 真实子进程崩溃边界（accept 提交后、EXEC 消费后、settle 提交后）。
- 4/4 接受竞争测试（同 intent 8 permit→1 accept；最后一次资源；claim/cancel）。
- 13/13 离线证据包检查（外部锚点重算，不打开 W 数据库）。
- 15/15 证据篡改/重放拒绝。

**缺陷（必须披露）：**

- 两个真实 attempt A/B 同一工具账本，先执行 A/B 再逆序结算：A 的合法 final 被 `LEDGER_STALE_UNKNOWN` 拒绝；B 成功；A 仍 STARTED，资源 reserved 未释放。
- 无重复效果、无越权、无签名伪造；是**活性/最终一致性**缺陷。
- 代码位置：`competition/core/common_w.py:497` 用当前 `tool.high_water` 比较较早 final 的 checkpoint。

**数据：** `external_benchmark/results/interleaved-settlement-defect.json`、`CORE_DEFECT_INTERLEAVED_SETTLEMENT.md`、`fig5-atomic-evidence.png`。  
**边界：** 修复前不能宣称“所有并发/故障路径都闭环”。

## 结论 5｜统一机制有真实组合价值，但成本与边界必须一起讲

**同一路径承载：**

```text
C 签名 GoalFloor
+ W BEGIN IMMEDIATE 资源事务/COMMIT
+ ActionHash/Ctx/Refs/RequiredDeps
+ X Acceptance + attempt + tool final + settlement
```

**可验证价值：**

- GoalFloor 拒绝不产生业务副作用（accepts/outbox/attempts=0，reservation=0）。
- 10/10 关系负例在同一 W/证据路径被拒。
- 证据包 13/13 可由外部锚点独立复验。

**代价：**

- 本轮 4–6 worker 负载下 accept p50 2.63–3.11 s，p95 4.1–4.3 s；样本小，p99 不稳定，不能给 QPS。
- GoalFloor 在 PENDING 时保守阻断，B 的必要动作完成数更高。
- 1000 条真实序列目标未达到；实际 93 条干净 enforce + 20 条配对 C/D。
- 外部工具效果不由 W 原子保证；W 总账仍是受信断言。

**数据：** `RESULTS.json`、`fig7-performance.png`、`REPRODUCTION_GUIDE.md`。  
**边界：** 统一机制的价值是“同一个可复验路径”，不是“所有安全性质都由它证明”。

## 答辩建议页序

1. 公开基准复现与 83.3% 覆盖（结论 1）
2. 10/10 关系一致性（结论 2）
3. GoalFloor 固定成本负结果（结论 3，主动讲，避免被质疑）
4. 原子证据与核心缺陷（结论 4，主动披露）
5. 统一机制价值与边界（结论 5）

## 不能放进答辩的表述

- “ZJJ 覆盖了 AADP/AP2 的全部能力” —— 事实是 10/12，P13/P11 PARTIAL。
- “GoalFloor 比 AADP 更安全” —— 固定成本下 B 与 D 都是 0/20。
- “AgentDojo 端到端已通过” —— 只做了 ground-truth 回放，无 LLM/CaMeL。
- “Tether 已复现” —— 无公开代码。
- “所有并发路径一致” —— 交错结算缺陷已复现。
