# ZJJ-CORE 完整比赛版本 · 整合候选（2026-10-18）

> **状态：整合候选，尚未合并至稳定比赛分支，也不等于正式 R2 全面符合性认证。**
>
> 唯一目标：向比赛开发同学交付 **共同安全协议 + IND/PAY/MED 三个签名模拟场景 + IND 可信提案补全 + 内部 CLI/桥接接口 + 可复现测试与证据**。
> 不恢复 Phase 1–18 研究归档，不覆盖历史实验和独立研究分支。

## 一、版本关系与可信依据

- 稳定比赛基线：`competition/zjj-core-final-20261010`，原协议/三场景/原有测试。
- 六字段补全代码：`feature/trusted-action-resolver-v1`，原提交 `86f284bf4787e9990b47b8159cd1e6b9e5824b03`。该分支自述本地 159/159 回归、371 项契约检查，且 GitHub PR #3 关联的 Competition software checks 已成功；**仅验证该分支，不自动涵盖本整合版本**。
- 三场景 CLI、bridge 和可信侧 service：**只挑选 `dev` 中新增文件与专门测试**，不合并 `dev` 删除旧模块和测试的重构。原整分支合并尝试 PR #4 因缺 `competition.support.tool_final` 导致 CI 失败，已关闭且未合并。
- 新整合分支：`release/competition-complete-20261018`。本分支要通过自己的完整 CI 后才可标记可交付。

## 二、交付清单

| 交付内容 | 主入口 | 当前声明范围 |
|---|---|---|
| 通用比赛安全协议（CORE-SPEC-1.3） | [共同协议](competition/docs/final/competition-protocol.md) | 精确合同 / Schema 与实际实现差异参阅 R2 对照；不可声称 R2 39/39 |
| 三场景安全核心与模拟工具 | [三场景交接](competition/docs/final/scenario-integration-handoff.md) · [开发入口](competition/README.md) | IND-DEMO-1、PAY-1、MED-DEMO-1，同一个 CommonW；模拟而非现实设备/支付/医疗执行 |
| P1 六字段来源 | [Resolver V1](competition/application/trusted_action_resolver.py) | 仅 IND 的可选简化提案，受信宿主内使用；其他场景依旧有完整 Action 入口 |
| P2 operation_id/重试恢复 | [RequestStore](competition/application/request_store.py) | W 单节点事务分配、冲突检查、持久映射与不可替换冻结；未覆盖跨节点 |
| P3 提案与可信核验分层 | [Orchestrator](competition/application/operation_orchestrator.py) | 不自动批准或代签，需外部真实批准链；测试 fixture 不是生产批准服务 |
| 三场景命令行桥接 | [TrustedService](competition/server/service.py) · [CLI](competition/cli/app.py) | 可信侧本地 CLI；演示使用受控本地签名者，不是远程 HTTP 服务或真实人类授权 |
| 测试及证据 | [最新 Resolver 验证记录](competition/docs/final/trusted-action-resolver-v1-results.md) · [原证据口径](competition/docs/final/claims-evidence.md) | 必须分别注明各自构建身份、失败记录与当前整合 CI |

**重要区别：** `competition/bridge/facade.py` 的 `build_op` 是三场景旧有**完整 Action** 的可信侧测试/演示接线，不等价于不可信 Agent 可只提交三个字段的 `TrustedActionResolver`。后者不得被 CLI 的本地签名兜底逻辑替代。只有经过审核的可信宿主可调用审批、存储或 W 接口。

## 三、复现命令（仓库根目录）

```bash
python -m pip install -r requirements.txt
python -m competition.verify_repository --report .runtime/release-repo-check.json
python -m unittest discover -s competition/tests -v
python system_dev/v26/tools/verify_contracts.py
python competition/docs/final/verify-existing-evidence.py
python -m competition.run_w_slice --output .runtime/release-three-profiles
python -m competition.server
```

`run_w_slice` 的输出必须使用新目录。查看并用输出 manifest 的 SHA-256 对照运行 `competition.verify_w_slice`；不能用先前实验的 manifest 冒充本轮构建。注意 `python -m competition.server` 是交互式可信端 CLI；它不代表已部署 API。

## 四、整合验收门槛

1. 由 **本候选分支** 触发独立 GitHub CI，全部核心回归、三场景、契约、仓库完整性及历史证据来源检查通过；不能仅引用旧分支 159/159。
2. IND 简化提案确认六字段可信来源、绑定、重复 ID、冻结、崩溃恢复；三场景传统完整 Action 流程独立可用。
3. 经受信工具执行的**三场景**正常与异常/丢应答恢复；结果和原始日志明确标记是模拟工具。
4. CLI/bridge 的每项操作保持挑战/签名分离，不给不可信 Agent 暴露 `LocalSigner`、`RequestStore.load`、`CommonW` 或通用受信方法。
5. 再次确认 `CLOCK_UNKNOWN` 的偶发时序风险；不得删除失败日志或改变签名时间约束以获取通过。
6. PR 审核通过再决定合并到 `competition/zjj-core-final-20261010`。`main` 与历史研究分支保持不变。

## 五、明确不做

- P4 不属于本轮问题清单；本版不要求 MCP、HTTP、跨节点协议或远程多角色服务。
- 不实现真实签署身份提供者、现实付款/医疗/工业效果、物理恰好一次、不受限制的多租户通用运行。
- 不通过强制重置 `main` 或删除 PR 历史来“重新提交”；应以单独整合 PR 的审核与最终合并完成替代。

此文件是**交付范围和验收说明，不是验收合格证明**。
