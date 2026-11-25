# 复现指南（REPRODUCTION GUIDE）

本指南只包含本轮实际执行过的命令，以及用于核验结果的入口。所有路径相对于仓库根目录。

## 1. 固定基线与获取代码

```powershell
git fetch origin main
git rev-parse origin/main
# c5caa73f711da93a24efacbac0456ed82a79dd4e
git switch -c research/external-benchmark-20261125 c5caa73f711da93a24efacbac0456ed82a79dd4e
```

上游竞品不提交到本仓库，使用以下 SHA 克隆到 `external_benchmark/sources/`：

```powershell
git clone --depth 1 https://github.com/shamiksaharcciit-oss/onedoor.git external_benchmark/sources/onedoor
git clone --depth 1 https://github.com/ethz-spylab/agentdojo.git external_benchmark/sources/agentdojo
git clone --depth 1 https://github.com/google-research/camel-prompt-injection.git external_benchmark/sources/camel-prompt-injection
git clone --depth 1 https://github.com/google-agentic-commerce/AP2.git external_benchmark/sources/AP2
```

固定 SHA 见 `external_benchmark/manifests/source_manifest.json`。若上游 main 已前进，必须显式 checkout 清单中的 SHA，不能直接用新的 main 替代。

## 2. 环境

本轮使用 Windows、Python 3.13.9、Node 24.14.1、Git 2.53。
三个隔离 venv：

```powershell
python -m venv external_benchmark/.venv_aadp
python -m venv external_benchmark/.venv_agentdojo
python -m venv external_benchmark/.venv_ap2
```

> 这些 venv 在 `.gitignore` 中，不进入交付 zip。它们只用于复现，不是交付物。

## 3. AADP 原生实验

```powershell
cd external_benchmark/sources/onedoor
..\..\.venv_aadp\Scripts\python.exe -m pip install -e ".[signed,dev]"

# 全量（约 16 分钟）
..\..\.venv_aadp\Scripts\python.exe -m pytest -q --disable-warnings `
  --junitxml=..\..\results\aadp-native-junit.xml

# 决策/预算/审计/许可子集（约 21 秒）
..\..\.venv_aadp\Scripts\python.exe -m pytest -q --disable-warnings `
  tests/guardrail/test_default_deny.py tests/guardrail/test_bounds.py `
  tests/guardrail/test_caps.py tests/guardrail/test_concurrency.py `
  tests/guardrail/test_reservation_reclaim.py tests/guardrail/test_resume_idempotency.py `
  tests/guardrail/test_approval_consumption.py tests/guardrail/test_approver_identity.py `
  tests/guardrail/test_report_outcome.py tests/guardrail/test_audit_append_only.py `
  tests/guardrail/test_sequence.py tests/guardrail/test_untrusted_input.py `
  tests/guardrail/test_present_bound.py tests/guardrail/test_bound_permit_issuance.py `
  tests/permit tests/eval/test_measures.py `
  --junitxml=..\..\results\aadp-capability-junit.xml

# 官方脚本化 eval
..\..\.venv_aadp\Scripts\python.exe -m eval run
```

预期：全量 2501/2513；决策子集 266/266；eval 16→3，合法误停 0，held 4，重复效果 2/2。

## 4. AP2 原生实验

```powershell
cd external_benchmark/sources/AP2
..\..\.venv_ap2\Scripts\python.exe -m pip install -e .
..\..\.venv_ap2\Scripts\python.exe -m pytest -q code/sdk/python/ap2/tests `
  --junitxml=..\..\results\ap2-native-junit.xml
```

预期：186/188；两个失败固定为 `kb_sd_jwt_intermediate_tests` 的 aud/nonce 中间 hop 测试。不要修测试或隐藏失败。

## 5. AgentDojo / CaMeL

```powershell
cd external_benchmark/sources/agentdojo
..\..\.venv_agentdojo\Scripts\python.exe -m pip install -e .
..\..\.venv_agentdojo\Scripts\python.exe -m pip install pytest
..\..\.venv_agentdojo\Scripts\python.exe -m pytest -q tests `
  --junitxml=..\..\results\agentdojo-native-junit.xml
```

确定性 Banking 回放（没有模型 API 时）：

```powershell
cd <repo-root>
$env:PYTHONPATH=(Get-Location).Path
$env:PYTHONUTF8='1'
external_benchmark\.venv_agentdojo\Scripts\python.exe `
  external_benchmark\benchmarks\native_reproduction\agentdojo_banking_replay.py
```

预期：16/16 utility，9/9 injection ground truth 无防御成功。  
这**不是** LLM 或 CaMeL 端到端结果；若需要真正的端到端，必须配置模型 API 并保留原始任务、工具、攻击、评分、模型、参数和种子。

## 6. ZJJ 能力子集与离线证据

```powershell
$env:PYTHONPATH='.'
python -m pytest -q competition/tests/test_common_authorization.py `
  competition/tests/test_goal_floor.py competition/tests/test_goal_floor_pure.py `
  competition/tests/test_w_acceptance_races.py competition/tests/test_crash_boundaries.py `
  competition/tests/test_evidence_verifier.py competition/tests/test_common_w.py `
  competition/tests/test_w_recovery.py competition/tests/test_cross_scenario_evidence.py `
  --junitxml=external_benchmark/results/zjj-capability-junit.xml
```

预期：75 PASS，15 subtests。  
注意：`test_crash_boundaries` 会启动真实子进程，路径依赖仓库根目录和 `.runtime/`。

```powershell
python -m competition.evaluation.verify `
  competition/evaluation/evidence/20261123/IND-DEMO-1-package.json `
  competition/evaluation/evidence/20261123/anchor-three-profiles.json
```

预期：`PASS`，13 passed，0 failed。

## 7. 能力矩阵

```powershell
python external_benchmark/benchmarks/capability_coverage/build_matrix.py
```

输出：`external_benchmark/results/capability_coverage.json`，覆盖率 10/12 = 0.833333。

## 8. GoalFloor 差分实验

### 8.1 AADP A/B

```powershell
$env:PYTHONUTF8='1'
$env:PYTHONPATH=(Get-Location).Path
external_benchmark\.venv_aadp\Scripts\python.exe `
  external_benchmark\benchmarks\differential_effectiveness\run_aadp.py `
  --sequences 1000 --out external_benchmark\results\aadp-goalfloor-differential.json
```

预期：A 490/1000 违反，B 0/1000。B 的可选接受更少（841 vs 1512），必要完成更多（2785 vs 2169）。

### 8.2 ZJJ C/D

建议先跑小样本，确认没有 `CLOCK_UNKNOWN`：

```powershell
python external_benchmark\benchmarks\differential_effectiveness\run_zjj.py `
  --sequences 20 --workers 4 --modes off enforce `
  --checkpoint-every 5 --out external_benchmark\results\zjj-smoke.json
```

本次交付中的真实数据：

- `zjj-goalfloor-off-20-clean.json`：20 条，6 下界违反。
- `zjj-goalfloor-enforce-paired-20.json`：实际完成 20 条，0 违反。
- `zjj-goalfloor-enforce-attempted-120.json`：尝试 120 条，93 条干净；22 个 CLOCK_UNKNOWN 行和 4 个 abort 已保留在原始文件，不应把它们算成协议拒绝。

**为什么没到 1000 条真实 ZJJ：** 高并发下 2 s 事件时钟窗口产生 `CLOCK_UNKNOWN`；宿主重启中断了批次。没有用参考模型替代。若要在稳定宿主复跑，目标命令：

```powershell
python external_benchmark\benchmarks\differential_effectiveness\run_zjj.py `
  --sequences 1000 --workers 6 --modes off enforce `
  --checkpoint-every 10 --out external_benchmark\results\zjj-goalfloor-paired-1000.json
```

如果出现 `CLOCK_UNKNOWN`，必须按失败记录，不得自动丢弃后宣称 1000/1000。

## 9. 关系负例

```powershell
python external_benchmark\benchmarks\differential_effectiveness\run_crypto_relations.py
```

输出：`external_benchmark/results/crypto_relations.json`，10/10 拒绝。  
脚本会生成真实 C 证书、签名链、两个/三个真实 operation、真实 W package 和离线 verifier 交叉组合。

## 10. 交错结算缺陷复现

```powershell
python external_benchmark\benchmarks\differential_effectiveness\repro_interleaved_settlement.py
```

预期：`settle_a_after_b_final` 返回 `LEDGER_STALE_UNKNOWN`；`settle_b` 成功；A 仍 STARTED，reserved=1，settlements=1。  
该结果不得被改成 PASS；修复建议见 `CORE_DEFECT_INTERLEAVED_SETTLEMENT.md`。

## 11. 汇总与图表

```powershell
python external_benchmark\build_results.py
python external_benchmark\make_figures.py
```

输出：

- `external_benchmark/results/RESULTS.json`（另有一份根目录 `RESULTS.json`）
- `external_benchmark/figures/fig1..fig7` PNG/SVG

## 12. 交付核验清单

| 文件 | 核验内容 |
|---|---|
| `RESULTS.json` | 机器可读总表 |
| `COMPETITOR_SOURCE_MANIFEST.md` | 来源、SHA、许可证、测试数 |
| `NATIVE_REPRODUCTION_REPORT.md` | 原生命令与失败 |
| `CAPABILITY_COVERAGE_REPORT.md` | 10/12 与逐项依据 |
| `DIFFERENTIAL_EFFECTIVENESS_REPORT.md` | A/B/C/D、关系、原子与负结果 |
| `THREAT_MODEL_COMPARISON.md` | 信任与边界 |
| `FINAL_RESEARCH_CONCLUSIONS.md` | H1/H2 判定 |
| `PPT_READY_RESULTS.md` | 答辩页 |
| `CORE_DEFECT_INTERLEAVED_SETTLEMENT.md` | 缺陷与修复建议 |
| `external_benchmark/results/*.json` | 原始机器可读记录 |
| `external_benchmark/results/*.log` / JUnit | 原始命令输出 |
| `external_benchmark/figures/*.png/svg` | 图表 |

## 13. 安全与合规

- 所有负例在隔离临时目录、临时 SQLite、一次性测试密钥中运行；未对真实支付、医疗、工业或外部网络发起动作。
- 不把 W 的模拟工具效果表述为真实世界效果。
- 不把 AgentDojo 的 ground-truth 回放表述为模型评测。
- 不修改上游竞品源码；所有适配层在本仓库。
- 本轮不向线上 main 推送实验代码。
