# 原生公开实验复现报告（NATIVE REPRODUCTION）

**基线：** `c5caa73f711da93a24efacbac0456ed82a79dd4e`
**日期：** 2026-11-25
**原则：** 只报告实际运行的命令和实际输出；不把“上游 README 的数字”当成本次复现。

## 1. AADP / onedoor 0.12.1

### 1.1 全量测试

```powershell
python -m venv .venv_aadp
.venv_aadp\Scripts\python.exe -m pip install -e ".[signed,dev]"
.venv_aadp\Scripts\python.exe -m pytest -q --disable-warnings `
  --junitxml=..\..\results\aadp-native-junit.xml
```

**结果：2513 个测试，2501 PASS，8 FAIL，4 SKIP，耗时 963.35 s。**

8 个失败均在非决策路径：

| 失败 | 性质 |
|---|---|
| `tests/eval/test_chart.py::test_the_chart_s_numbers_equal_results_md` | Windows GBK 默认编码读取 UTF-8 SVG |
| `tests/eval/test_not_shipped.py::test_eval_examples_and_docs_img_are_absent_from_the_built_artifacts` | 缺少固定版本 `setuptools/wheel/build` |
| `tests/test_formatter_fence.py::test_every_virtualenv_in_the_tree_is_excluded_from_the_formatter` | 树内残留虚拟环境被 ruff 扫描 |
| `tests/test_gate_discipline.py` 2 项 | `ruff` 未在 PATH |
| `tests/test_packaging.py` 3 项 | 构建工具固定版本/`build` 模块缺失 |

补充：`tests/eval/test_chart.py` 与 `tests/test_gate_discipline.py` 在设置 `PYTHONUTF8=1` 并把 venv `Scripts` 加入 PATH 后，**17/17 PASS**（`results/aadp-env-rerun.log`）。没有把这 17 项倒灌回全量结果；全量仍是 8 FAIL。

### 1.2 决策/预算/审计公开测试子集

为避免把构建噪声混进安全能力结论，单独运行：

```powershell
pytest -q tests/guardrail/test_default_deny.py `
  tests/guardrail/test_bounds.py tests/guardrail/test_caps.py `
  tests/guardrail/test_concurrency.py tests/guardrail/test_reservation_reclaim.py `
  tests/guardrail/test_resume_idempotency.py tests/guardrail/test_approval_consumption.py `
  tests/guardrail/test_approver_identity.py tests/guardrail/test_report_outcome.py `
  tests/guardrail/test_audit_append_only.py tests/guardrail/test_sequence.py `
  tests/guardrail/test_untrusted_input.py tests/guardrail/test_present_bound.py `
  tests/guardrail/test_bound_permit_issuance.py tests/permit tests/eval/test_measures.py
```

**结果：266/266 PASS。** 原始 JUnit 是 `external_benchmark/results/aadp-capability-junit.xml`。

### 1.3 官方脚本化 eval

```powershell
python -m eval run
```

**结果与上游 README 一致：**

| 类别 | 无 onedoor 有害执行 | 有 onedoor 有害执行 | 合法误停 | held | 重复效果（无/有） |
|---|---:|---:|---:|---:|---:|
| ambiguity | 2 | 0 | 0 | 0 | 0/0 |
| approval | 1 | 0 | 0 | 3 | 0/0 |
| conflicting_constraints | 3 | 0 | 0 | 0 | 0/0 |
| injected_instruction | 3 | 1 | 0 | 1 | 0/0 |
| kill_switch | 2 | 0 | 0 | 0 | 0/0 |
| ordinary_work | 0 | 0 | 0 | 0 | 0/0 |
| permits | 3 | 0 | 0 | 0 | 0/0 |
| tool_failure | 2 | 2 | 0 | 0 | 2/2 |
| **总计** | **16** | **3** | **0** | **4** | **2/2** |

解释：这是**固定脚本**，不是模型或生产测试。它证明 onedoor 的公开决策 API 复现了 README 数字；`injected_instruction` 仍有 1 个漏放，`tool_failure` 仍不知道如何关联重试。ZJJ 对这些类别的比较不能只拿 16→3 当“安全率”，因为场景不同。

## 2. AP2 Python SDK

```powershell
python -m venv .venv_ap2
.venv_ap2\Scripts\python.exe -m pip install -e .
.venv_ap2\Scripts\python.exe -m pytest -q code/sdk/python/ap2/tests `
  --junitxml=..\..\results\ap2-native-junit.xml
```

**结果：188 个测试，186 PASS，2 FAIL，4.20 s。**

失败：

```text
code.sdk.python.ap2.tests.kb_sd_jwt_intermediate_tests::test_verify_rejects_aud_mismatch
code.sdk.python.ap2.tests.kb_sd_jwt_intermediate_tests::test_verify_rejects_nonce_mismatch
```

这两个测试都针对**中间 KB-SD-JWT hop**；最终 hop 的 `test_verify_rejects_aud_mismatch` / `test_verify_rejects_nonce_mismatch` 通过（见 `kb_sd_jwt_tests.py`）。因此本次只记录“上游测试套件在冻结提交上有 2 个失败”，不把它直接定性为可利用漏洞。AP2 的支付/结账链、约束、累计预算和收据测试均通过。

代表性通过项：

- `test_full_payment_end_to_end`
- `test_three_step_bank_sa_cp_merchant_flow`
- `test_payment_chain_transaction_id_mismatch`
- `test_checkout_chain_hash_mismatch`
- `test_payment_agent_recurrence_over_limit`
- `test_verify_receipt_invalid_signature`
- `test_verify_receipt_not_found_in_store`

## 3. AgentDojo / CaMeL

```powershell
python -m venv .venv_agentdojo
.venv_agentdojo\Scripts\python.exe -m pip install -e .
.venv_agentdojo\Scripts\python.exe -m pytest -q tests `
  --junitxml=..\..\results\agentdojo-native-junit.xml
```

**结果：32 个测试，31 PASS，1 FAIL。** 失败是 `tests/test_agent_pipeline/test_anthropic_llm.py::test_merge_tool_result_messages`，原因是当前 Anthropic SDK 把 `MessageParam` 表示为 `typing.Union`，`typing.Union` 不能被实例化；与 Banking 工具执行无关。

本次没有模型 API，因此没有运行 `python -m agentdojo.scripts.benchmark` 的完整 LLM 对照，也没有运行 CaMeL。作为替代，做了**确定性 ground-truth 工具轨迹回放**：

```powershell
python external_benchmark/benchmarks/native_reproduction/agentdojo_banking_replay.py
```

结果：**16/16 user task utility PASS；9/9 injection task 的 ground truth 在无防御时成功执行**。这只证明原始环境、工具、任务和评分函数可以运行，**不是** LLM 端到端成绩，也不是 ZJJ 的防御成绩。CaMeL 需要模型 API，状态为 `NOT_RUN`。

## 4. Tether

检查了论文、LinuxArena 和 leaderboard 数据入口。检查时没有找到 Tether 的公开代码、策略源码或构建脚本。论文报告的 1,372 benign / 145 adversarial LinuxArena 轨迹和 100% in-scope recall **不是本次运行结果**。

没有实现 OS 语义到 ZJJ 业务动作的转换层；没有把 LinuxArena 轨迹当作 ZJJ 原生实验。状态：`BLOCKED_NO_PUBLIC_IMPLEMENTATION`。

## 5. ZJJ-CORE 原生测试（基准，不是竞品）

为能力矩阵提供本协议一侧的实际证据，运行：

```powershell
python -m pytest -q competition/tests/test_common_authorization.py `
  competition/tests/test_goal_floor.py competition/tests/test_goal_floor_pure.py `
  competition/tests/test_w_acceptance_races.py competition/tests/test_crash_boundaries.py `
  competition/tests/test_evidence_verifier.py competition/tests/test_common_w.py `
  competition/tests/test_w_recovery.py competition/tests/test_cross_scenario_evidence.py
```

**结果：75 PASS，15 subtests PASS，544.46 s。** 包括 3 个真实子进程崩溃边界、4 个接受竞争用例、15 个证据篡改用例。

此外，独立验证历史证据包：

```powershell
python -m competition.evaluation.verify `
  competition/evaluation/evidence/20261123/IND-DEMO-1-package.json `
  competition/evaluation/evidence/20261123/anchor-three-profiles.json
```

（实际文件名为 `anchor-three-profiles.json`，见复现指南。）结果：**13/13 PASS，0 FAIL**。

## 6. 复现结论

| 对象 | 原生测试 | 是否完成 | 结论 |
|---|---:|---|---|
| AADP 决策主套件 | 266/266 | 是 | 公开能力可作为外部基准 |
| AADP 全量 | 2501/2513 | 是 | 8 个构建/环境失败，不掩盖 |
| AP2 SDK | 186/188 | 是 | 2 个中间 hop 失败，原样保留 |
| AgentDojo 测试 | 31/32 | 是 | 1 个 SDK typing 失败 |
| AgentDojo LLM | — | 否 | 无 API |
| CaMeL | — | 否 | 无 API |
| Tether | — | 否 | 无公开实现 |
| ZJJ 能力子集 | 75/75 | 是 | 真实 W/签名/事务路径 |
| ZJJ 离线证据包 | 13/13 | 是 | 独立验证器 |

**不能由本报告得出的结论：** 上游全量测试通过就等于协议安全；AP2 的两个失败等于可利用漏洞；AgentDojo 的确定性回放等于 LLM 防御效果。
