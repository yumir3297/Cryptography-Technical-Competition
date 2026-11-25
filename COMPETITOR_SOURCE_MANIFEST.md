# 外部公开基准与竞品来源清单（COMPETITOR_SOURCE_MANIFEST）

**冻结基线：** `c5caa73f711da93a24efacbac0456ed82a79dd4e`（main，2026-11-25 08:36:09 +08:00）
**实验工作分支：** `research/external-benchmark-20261125`
**实验提交：** `5a06f5e5c57393cffcb4c9b030992c870bf4e100`
**检查日期：** 2026-11-25
**机器可读版本：** `external_benchmark/manifests/source_manifest.json`

本清单只记录**实际检查过**的公开入口。上游代码不复制进 Git 提交，使用 SHA 和原始 URL 固定身份；本地克隆位于 `external_benchmark/sources/`（已忽略）。

## 1. AADP / onedoor（优先级 1）

| 项 | 值 |
|---|---|
| 规范 | `draft-saha-aadp-04`，2026-09-27，Active Internet-Draft，Standards Track |
| 规范 URL | https://datatracker.ietf.org/doc/html/draft-saha-aadp-04 |
| 扩展规范 | `draft-saha-aadp-bound-permit-00`，2026-09-29 |
| 扩展 URL | https://datatracker.ietf.org/doc/html/draft-saha-aadp-bound-permit-00 |
| 参考实现 | https://github.com/shamiksaharcciit-oss/onedoor |
| 提交 | `9d0b69879273af21b8cbf5d1098ff50f2cb1d6ea`（`9d0b698`） |
| 包版本 | `onedoor 0.12.1` |
| 许可证 | Apache-2.0 |
| 运行环境 | Windows，Python 3.13.9，pytest 9.2.0，`cryptography 46.0.4` |
| 原始测试 | 204 个测试文件，2513 个用例：2501 PASS / 8 FAIL / 4 SKIP |
| 原始测试命令 | `python -m pytest -q --junitxml=../../results/aadp-native-junit.xml` |
| 原生公开基准 | `python -m eval run`，32 个脚本化场景，8 类 |
| 公开组件 | 决策引擎、SQLite/ WAL 账本、审计链、审批、预留回收、bound-permit issuer/recipient、eval harness、service/studio |
| 未公开/未覆盖 | V17 `status-checked` currentness 明确是 gap；冻结版本没有进程崩溃边界测试；没有真实跨组织部署 |
| 复现结论 | 决策/预算/并发/审计主套件通过；8 个失败均为构建、code page、PATH 或 venv 扫描环境问题，不在决策语义路径 |

**直接复现的测试类别：** 授权、默认拒绝、边界、预算、并发预留、回收、重放/幂等、审批消费、审批人身份、结果报告、审计追加、序列规则、不可信输入、bound permit、permit recipient。

**范围交集：** 动作授权、身份与授权、共享预算、原子预留、审批/撤销、重放、审计证据、执行结果关联、跨信任边界 permit。AADP 没有 ZJJ 的 GoalFloor 和多源对象图（Task/Basis/RequiredDeps/Ctx/Attempt），因此关系类测试需按“能否表达”区分，而不是把不适用当成竞品漏洞。

## 2. CaMeL / AgentDojo（优先级 2）

| 项 | 值 |
|---|---|
| CaMeL 论文 | https://arxiv.org/html/2503.18813v2 |
| CaMeL 代码 | https://github.com/google-research/camel-prompt-injection |
| CaMeL 提交 | `f083b6b396399d3b3c7f2ddaf613a5945eaf32d8` |
| CaMeL 许可证 | Apache-2.0 |
| AgentDojo 代码 | https://github.com/ethz-spylab/agentdojo |
| AgentDojo 提交 | `089ed468cf3ed0322acc66b0211f26d9d90dbf60` |
| AgentDojo 版本 | 0.1.35 |
| AgentDojo 许可证 | MIT |
| Banking suite | v1.2.2：16 个 user task，9 个 injection task |
| 原始测试 | 32 个：31 PASS / 1 FAIL（Anthropic typing 环境问题） |
| 公开组件 | Banking 环境/工具、用户任务、注入任务、utility/security 评分、攻击实现 |
| 未公开/不可用 | 模型 API key；本次没有可用的 LLM 运行环境 |
| 复现结论 | 原生测试 31/32；Banking **确定性 ground-truth 工具轨迹回放** 16/16 utility，9/9 注入目标在无防御时成功。该结果不是模型端到端评测，也不能当作 ZJJ/CaMeL 的防御成绩 |

**未完成：** CaMeL、ZJJ、CaMeL+ZJJ 的 AgentDojo 端到端四组对照未运行。原因是缺少模型 API 和可复现的模型端点；没有用脚本化“假 Agent”冒充模型结果。

## 3. Google AP2（优先级 3）

| 项 | 值 |
|---|---|
| 仓库 | https://github.com/google-agentic-commerce/AP2 |
| 提交 | `e1ea56db72a6385bce3e5c1112b3a56ce60acb43` |
| 许可证 | Apache-2.0 |
| 运行环境 | Windows，Python 3.13.9 |
| 原始测试 | 188 个：186 PASS / 2 FAIL |
| 公开组件 | SD-JWT / KB-SD-JWT、支付/结账 mandate 链、约束、receipt、样例场景、web client |
| 未公开/不可用 | 真实支付网络、真实 issuer/acquirer；样例需要 Gemini API |
| 复现结论 | 186/188；两个失败是中间 KB-SD-JWT hop 的 `aud`/`nonce` mismatch 预期未触发。最终 hop 的同类测试通过，因此记录为**上游原生失败/待判定**，不据此宣称 AP2 整体不安全 |
| 范围交集 | 授权绑定、交易一致性、连续/累计预算、收据；AP2 没有 ZJJ 的 W 资源事务、执行资格和 GoalFloor |

关键原生通过项包括：`test_full_payment_end_to_end`、`test_payment_chain_transaction_id_mismatch`、`test_full_checkout_end_to_end`、`test_checkout_chain_hash_mismatch`、`test_three_step_bank_sa_cp_merchant_flow`、`test_payment_agent_recurrence_over_limit`、`test_verify_receipt_*`。

## 4. Tether（优先级 4）

| 项 | 值 |
|---|---|
| 论文 | https://arxiv.org/html/2611.25599v1 |
| arXiv | 2611.25599v1，2026-11-19 |
| LinuxArena | https://www.linuxarena.ai/ |
| 数据入口 | https://leaderboard.linuxarena.ai/data |
| 公开代码 | **未找到公开实现**（检查时） |
| 论文声称 | Lean 4 EDSL、Isolate/OverlayFS/strace、LinuxArena/MonitoringBenchHonest 回放 |
| 实际可复现性 | 只有论文和公开轨迹数据，没有可运行的 Tether 实现、策略源码或构建脚本 |
| 结论 | **无法复现**，不构造 OS 语义到业务动作的不可信转换层；不以二手轨迹冒充 Tether 原生实验 |

## 5. 公开资源可用性与缺口

| 资源 | 可访问 | 可复现 | 备注 |
|---|---:|---:|---|
| AADP draft -04 | 是 | — | 规范 |
| AADP bound-permit -00 | 是 | — | 规范 |
| onedoor | 是 | 是（主套件） | SHA 固定 |
| CaMeL | 是 | 否 | 无模型 API |
| AgentDojo | 是 | 部分 | 原生测试/确定性回放；无模型端到端 |
| AP2 | 是 | 是（SDK 测试） | 2 个原生失败 |
| Tether | 论文是 | 否 | 无公开代码 |
| LinuxArena data | 是 | 部分 | 可下载轨迹，但属于 OS 级 coding-agent 语义 |

## 6. 适配器与原始代码隔离

- 原始克隆：`external_benchmark/sources/<name>/`，不修改上游文件。
- 适配器：`external_benchmark/adapters/aadp/`、`external_benchmark/adapters/zjj_core/`；它们调用官方 API 或真实 CommonW，不复写规则。
- 冻结测试定义：`external_benchmark/manifests/test_definitions.json`。
- 独立 Oracle：`external_benchmark/oracle/goalfloor.py`，不导入 `competition.core.goal_floor`。
- 每次运行的随机种子、命令、SHA、原始 JSON 在 `external_benchmark/results/`。

## 7. 已知限制

1. AADP 的全量 2513 用例不是全部信息语义的证明；本次只对公开测试负责。
2. AP2 的 2 个失败未修复、未忽略，原因为原生套件输出。
3. AgentDojo 没有模型结果；确定性回放只证明工具轨迹和评分函数可运行。
4. Tether 无公开实现，不能把论文数字当作本次复现结果。
5. ZJJ 的 1000 条真实序列目标未完成；实际得到 93 条干净 enforce 序列、20 条配对 C/D。详见差分报告。
