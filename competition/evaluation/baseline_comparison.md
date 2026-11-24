# 基线、集成与回归对照

## 1. 构建身份

| 项 | 值 |
|---|---|
| 原主线 `origin/main` | `7604d6b5b902f38d950234dec53d9375429f1e7f` |
| 集成分支 | `integration/goalcommit-shadow-20261123` |
| 集成提交 | `fcbc6b3b3ad63c9de84387c98bccc004f726a77b` |
| 集成基线 | 从 `7604d6b` 建立，未整体覆盖主线 |
| PR #12 原型 HEAD | `ee2b0153f7c5eac2450bef8d37f66bc412d007a1`（仅作研究输入） |
| 工业/支付实验分支 HEAD | `fb462240c4abdaa0f55f8eba3d541308f74ba73b`（仅审查，未整体合并） |
| Python | 3.13.9 |
| cryptography | 50.0.0 |
| jsonschema | 4.26.0 |
| 平台 | Windows（本轮）；历史 formal39 为 Linux 6.18 |

## 2. 测试命令

核心协议子集（干净基线，改动前）：

```powershell
python -m unittest -v `
  competition.tests.test_common_w `
  competition.tests.test_common_authorization `
  competition.tests.test_w_acceptance_races `
  competition.tests.test_w_recovery `
  competition.tests.test_w_final_regressions `
  competition.tests.test_w_plans `
  competition.tests.test_candidate_ingress `
  competition.tests.test_common_receipt
```

结果：`Ran 54 tests in 330.345s`，`OK`。日志：`.runtime/baseline/core-tests.log`。

同一子集 + 本轮新增 GoalFloor/离线验证（改动后）：

```powershell
python -m unittest -v ... competition.tests.test_goal_floor competition.tests.test_goal_floor_pure
```

结果：`Ran 91 tests in 551.567s`，`OK`。日志：`.runtime/baseline/core-tests-after.log`。

本轮新增专项：

```powershell
python -m unittest -v competition.tests.test_crash_boundaries
python -m unittest -v competition.tests.test_evidence_verifier
python -m unittest -v competition.tests.test_cross_scenario_evidence
python -m unittest -v competition.tests.test_incident_workflow
```

结果：3/3、15/15、3/3、1/1 均通过（分别见 `results/` 与测试日志）。

完整发现式回归：

```powershell
python -m unittest discover -s competition/tests -t . -v
```

在 Windows 上结果：`Ran 400 tests in 1434.344s`，`FAILED (failures=25, errors=101)`。失败/错误集中在：
- `DENY:LINUX_ONLY`（Linux DAC/`chmod 0600`/Unix socket 相关测试）；
- `test_agent_gateway`/`test_agent_workbench` 等测试加载失败；
- `test_client_*`、`test_caller`、`test_client_http` 的 Unix/端口/权限前置条件；
- 少量 HTTP face 生命周期错误。

该次完整运行在 Windows 上执行，**不能**作为“协议回归”结论，也不能把其中的非环境失败自动归为已修复。正式闭环需要在 Linux CI 重新运行同一完整套件并逐项比对。本轮的安全结论只基于明确通过的核心子集与新增专项，不基于这 400 项的总数。该次全量运行在改动前启动，后续子进程可能已加载改动后的源码；因此只作为环境失败清单，不作为干净的 A/B 对照。干净对照以改动前 54 项核心子集和改动后 91 项核心子集为准。

## 3. 历史失败清单与新失败清单

| 类别 | 原主线（核心子集） | 集成后（核心子集） | 新增专项 |
|---|---|---|---|
| 协议/交易/恢复测试 | 54/54 PASS | 91/91 PASS | 全部 PASS |
| Windows 环境限制 | 未在此子集触发 | 未在此子集触发 | 未触发 |
| GoalFloor | 不存在 | 16/16 PASS | — |
| 离线验证 | 不存在 | — | 15/15 PASS |
| 崩溃边界 | 部分覆盖 | — | 3/3 PASS |
| 跨场景 | 部分覆盖 | — | 3/3 PASS |
| 事件响应工作流 | 不存在 | — | 1/1 PASS |

“新增失败”在核心子集与新增专项中为 0。完整 Windows 套件的 25 F/101 E 是环境性/平台性失败，尚未在 Linux 复核；不记为协议失败，也不记为已通过。

## 4. 分支审查结论

- PR #12 的 31 项原型测试只在 `research/goalcommit_minimal/` 的隔离 SQLite harness 中运行，不是 CommonW 正式结果。本轮只提取 `evaluate` 的必要条件算术、C 发布对象形状、COMMIT 绑定思想；未合并其独立密钥/数据库实现。
  本轮在该 worktree 中独立复跑：`Ran 31 tests ... OK`；`run_demo.py` 输出 7,830 个有限状态动作组合、2,130 个接受、资源下界违反 0。它们仍是原型结果，不是正式 39 项 PASS。
- `feature/pay-batch-settlement-20261123` 相对 `main` 已分叉；本轮未整体合并支付批次封账。支付场景仍用原 `PAY-1` 模拟工具；批次封账的 UNKNOWN/防重复记账价值保留为后续工作。
- 工业完成路径分支未整体合并；GoalFloor 的 `deps`/资源下界与其 `completion_basis` 思路一致，但本轮不宣称工业完成路径已正式接线。

## 5. 可复现性

- 所有新增测试使用临时目录和真实子进程签名器；不依赖网络。
- 证据包生成命令：`python -m competition.evaluation.generate_evidence --output competition/evaluation/evidence/20261123`。
- 生成后的 `manifest.json` 含每个文件的 SHA-256；`anchor-*.json` 必须通过独立渠道固定。
- 工作树中的 `.runtime/` 为忽略目录，保留原始日志；不提交私钥或可写数据库。
