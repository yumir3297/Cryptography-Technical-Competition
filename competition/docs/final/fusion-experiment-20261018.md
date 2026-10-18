# PR #5 + PR #6 隔离融合实验（2026-10-18）

> 后续收束：本页保留实验阶段记录。融合提交 c04692b 的 CI 已成功，现已整理为直接基于比赛分支的单个统一交付提交；当前范围、接入和验收以[统一交付说明](unified-competition-delivery-20261018.md)为准。工业为全流程主展示，工业/付款/医疗本地 CLI 为补充演示。下文“仅验证候选树”等描述属于当时阶段，不代表最新验收状态。

**分支**：`experiment/pr5-pr6-fusion-20261018`。这是独立候选实验，不是正式交付，也未修改 `main`、`competition/zjj-core-final-20261010` 或两个原 PR 的头。

## 选取的基础与增量

- 基础：PR #6 的 `feature/zjj-core-ind-complete-20261018` @ `e772ec2d9febe0f23680419ba33ac900d16ea719`。**不改**其 `competition/application/**`、`competition/core/**`、`competition/deployment/**`，保留 V2 操作生命周期、版本 CAS、RequestBoundW 和 IND 严格白名单。
- 从 PR #5 的 `release/competition-complete-20261018` 移植三个**只用于可信本地模拟**的目录：`competition/bridge`、`competition/server` 和 `competition/cli`（新增文件）；同时移植 `test_bridge_facade.py`、`test_cli_session.py` 和 `test_server_service.py`。
- 新增 `test_fusion_boundaries.py`，核对公开 IND OperationService 的固定方法列表、所需 RequestBoundW、运行时模块和旧版本地签名辅助器之间的静态隔离。
- 不移植 PR #5 的旧 `request_store.py`、`operation_orchestrator.py`；不合并 `dev` 的删除型重构，不增加另一套线上 Resolver。

## 两种模式的关键安全差异（请勿混用）

1. **IND 公开接口（PR #6）**：`competition.application.operation_service.OperationService`，十方法白名单；调用者签自己的认证材料；原多方批准、短期证明版本、接受事务守卫必须通过。只有 `RequestBoundW` 绑定的 W 被服务调用。HTTP/MCP 若启用只承载此层，不能暴露模拟签名。
2. **本地离线比赛演示（PR #5）**：`competition.server.service.TrustedService` / `competition.cli.app`，借助 `LocalSigner` 和受控 `WRun` 生成三场景的模拟签名链，以便 CLI 展示。该本地受信模拟接口**绝不视作**新的公开 Agent/HTTP/MCP 服务，也不得连接 IND 公开运行账或作为绕过批准的备用生产入口。
3. 两者共用**未修改的** CommonW 核心实现，但不是同一个公开 API，也没有验证把两套入口指向同一生产状态数据库的可行性。
4. IND 公开服务的安全声明只适用于 PR #6 内部绑定受信持久账的受控调用方式。CLI 辅助器不被导入 PR #6 的公开宿主模块。

## 联合验收要求

- 本实验分支自己的 GitHub CI 必须经过完整 `python -m unittest discover -s competition/tests -v`、仓库链接/导入、结构契约、历史签名证据验证；**不得**将旧 PR #5 或 PR #6 的绿灯算成本分支结果。
- 原 PR #6 的操作生命周期、恢复、签名负测和工业部署测试继续通过。
- 原 PR #5 的三场景本地 `TrustedService` 正向流程、CLI、错误角色签名和重放拒绝测试继续通过。
- 新 `test_fusion_boundaries.py` 单独检查旧模拟签名器不会进入 IND 公开服务及调用白名单。
- 如果 CI 不通过，保留失败证据，只在本实验分支修复；不能合入比赛分支。
- 在没有额外验证前，**不能**声称已经统一了两套接口、PAY/MED 具备 PR #6 的受控提案入口、真人授权或实体设备能力，也不能声称原 R2 39 项正式验收通过。

## 复现

```bash
python -m pip install -r requirements.txt
python -m unittest competition.tests.test_fusion_boundaries -v
python -m unittest competition.tests.test_bridge_facade competition.tests.test_server_service competition.tests.test_cli_session -v
python -m unittest discover -s competition/tests -v
python -m competition.verify_repository --report .runtime/fusion-repository.json
python system_dev/v26/tools/verify_contracts.py
python competition/docs/final/verify-existing-evidence.py
```

在隔离的新模拟目录可使用 `python -m competition.server` 的可信本地交互式 CLI；IND 对外部署仍须按 [原 PR #6 的独立部署说明](../../deployment/README.md) 在私有目录执行。**不可把 CLI 的 LocalSigner 注册为 HTTP 或 MCP 工具**。

## 结论口径

本文件只列本实验方案和验收条件。真正结果以本实验 PR 的 GitHub CI 和具体提交 SHA 为准；出现失败时记录第一失败测试和根因。当前**仅验证代码已组成候选树**，不能预先写 PASS。
