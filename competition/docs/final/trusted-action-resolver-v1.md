# Trusted Action Resolver V1.0：接口补全维护说明

> 历史阶段记录：以下验证与“未推送”状态按当时保留。当前完整交付、替代关系与最新验证请从[统一交付入口](ind-complete-delivery-20261018.md)阅读。

本分支从稳定比赛基线 `cc4e36b4e302fcdc53cc809a012c77d8464182af` 新增可选应用层库；不替换原完整 Action 入口，不修改核心协议，不自动启用对外服务。

## 1. 问题如何解决

原入口需要完整十字段 Action；业务调用者不能可信地自报身份、操作 ID 和执行目标。新入口只接受 `request_id、unit_id、route`，根据受信 Task/Policy/KEY/ROLE/工具证书补齐 Action，并返回可送往审批端的**未签署** Assessment/Basis/ctx。

| 六字段 | 权威来源及检查 |
|---|---|
| operation_id | W 数据库事务内生成随机 16 字节 B16；检查应用映射和既有 W 操作 ID；碰撞有界重试 |
| principal | C 认证 Task.principal；信任 Task 提供 principal 与 holder 的授权绑定 |
| holder / holder_kid | 经认证 H、当前 KEY/HOLDER/READER 资格，与 Task 匹配 |
| executor | Task、Policy、登记 X 主体与 key 一致，当前执行角色约束通过 |
| destination | Task/Policy 路由一致，匹配有效工具证书和各角色的目标范围 |

其余 scope、tool、tool_version、payload 由登记配置和工业业务规则补齐；仍通过原 Action Schema 和 SceneAuthorizationAdapter。新请求经 WState 读取 W 当前 UNIT/BEHAVIOR，身份、任务和策略继续使用 C 认证来源；缓存重试返回原构造材料。

```python
from competition.application.trusted_action_resolver import TrustedActionResolver
from competition.application.operation_orchestrator import OperationOrchestrator

resolver = TrustedActionResolver(trusted_state, server_selected_task_id)
workflow = OperationOrchestrator(common_w, resolver.requests)
resolved = resolver.resolve(proposal, holder_proposal_auth)
# 将 resolved['approval_request'] 送到受信审批端；各参与方自己批准并签署。
# approved_op、identity_proof、accept_proof 必须由现有认证/签署流程提供。
ticket = workflow.prepare_approved(resolved['key'], approved_op, identity_proof)
accepted = workflow.accept(ticket['ticket_id'], accept_proof)
```

这段接线不包含自动批准函数。首次冻结前，编排层通过原 CommonGuard 检查完整真实签名链；不合格审批不会冻结请求。随后持久化完整 op，再调用原 W.prepare。accept 仍需要 H 对当前 ticket 的认证凭据；worker 领取、执行、查询和结算沿用原 W。

提案认证对象为 `{claim, signature}`；claim 恰含 profile、task_id、proposal、iat、exp。signature 为 H 对 `canonical(['ZJJ-APP-PROPOSAL-v1', claim])` 的 Ed25519 签名，使用原 b64url 编码。该域是新增应用认证域，不替代或修改任何既有协议签名域。服务器固定 profile/Task，调用者不能选择任意任务或角色。

## 2. 对其他部分的影响

- 原 core、R2 Schema、ActionHash、原消息签名域、COMMIT、EXEC-0 均不变；原 CandidateIngress 及 PAY/MED 完整 Action 流程继续使用原入口。
- 新增 W 数据库 `app_request` 表；初始化要求 CommonW 已完成。表记录请求映射、构造结果及完整 op，不修改原 W 表结构，也不承担 W 的进度状态机职责。实验用 exp_proposal 不自动迁移；已有接受操作应继续通过原 W 恢复，不能把重试改成新提案。
- 增加了权限/来源读取、完整链预检及持久化开销；不宣称已测性能、容量或多节点分配。首次冻结复用当前 CommonW 的内部 `_current_windows` 检查；将来核心接口升级时需复测这处接线。
- 目前仅开放固定 IND-DEMO-1 简化提案。PAY/MED 简化输入、HTTP/MCP 服务、身份提供者接入和真实设备不在本分支实现范围。
- 应用模块不导入 seed、测试审批函数或参与方私钥。`RequestStore.load`、编排对象、W 及 worker 只能由受信宿主持有；不能把对象全部方法自动注册成 Agent 工具。
- C 认证 Task 是当前 principal→holder 的授权依据，签名不证明现实业务所有权。DelegationProof 未实现；附加 delegation/act_as/sign_as 等字段全部拒绝。

## 3. 具体补全与重试规则

| 新文件 | 职责 |
|---|---|
| [candidate_proposal.py](../../application/candidate_proposal.py) | 严格字段/类型/长度检查，支持规范 JSON bytes 或纯数据 dict |
| [trusted_action_resolver.py](../../application/trusted_action_resolver.py) | 认证、六字段解析、来源交叉检查及未签署审批材料生成 |
| [request_store.py](../../application/request_store.py) | W 事务内 ID/请求映射、不可替换的完整 op 与摘要、受信恢复读取 |
| [operation_orchestrator.py](../../application/operation_orchestrator.py) | 先校验批准链再首次冻结；接原 prepare/accept；恢复重放原 op |

请求键按 profile/H/Task/request_id 分域。同键同内容返回相同 Action，同键不同内容 REQUEST_CONFLICT；缓存命中仍校验当前 H 资格、READER 动作范围和 Policy ACL。资格失效不重新分配 ID。

完整请求摘要继续使用原 `digest(['COMP-APP-CALL-v1', profile, op])`。一旦冻结，op 不能换签名、换 nonce 或替换内容；相同 Action 的重签也会被 FROZEN_REQUEST_CONFLICT 拒绝。恢复调用 `resolver.requests.load(key)` 获取原 op，再取得 H 对该 op 的新 prepare 身份凭据，调用 `workflow.prepare_saved(key, proof)`。重新取得外层挑战凭据不改变冻结 op。

W 已提交后的 COMMIT/outbox 是进度真源；重复 prepare/accept 恢复原操作和回执，不按新业务重新构造依据。未接受请求若批准过期，保持原映射并失败关闭；本版不自动重签、换 ID、取消或放弃请求。若需新的业务请求，必须由受信宿主明确决定并重新走权限/意图去重规则。

Assessment 的有效期取 Task、Policy、IDENTITY、PACKAGE 和 E 证据有效期的交集。首次冻结除原签名链检查外，还刷新事件时间并检查当前窗口；过期批准不能占据不可替换的冻结槽。

首次冻结仅接受与 Resolver 持久化的 action、task、scene、assessment、basis、ctx、required/deps 完全一致的真实批准链。新应用库本身不产生 H/U/V/G/X 协议签名；CommonW 原有的 X 回执流程保持。

必要修改属于应用接口/持久化/审批编排工程；当前证据不支持删六字段或改原协议来简化调用。未来 DelegationProof 必须先定义发行者权威、权限交集、有效期/撤销/版本、动作绑定和审计，再单独验证，不在本版中默许委托。

## 4. 实验代码与实际结果

本分支新增 [应用层回归](../../tests/test_action_resolver.py) 和仅用于受信测试端的 [模拟审批 fixture](../../tests/resolver_fixtures.py)。新库代码不引用 fixture；它不构成对外审批服务。当前运行结果、失败与复测、源代码摘要及精确命令见 [本轮验证记录](trusted-action-resolver-v1-results.md)。

此前隔离实验保留在原分支，没有搬入本分支的应用入口：

- [E1–E4 原实验及代码](https://github.com/yumir3297/Cryptography-Technical-Competition/tree/4b301f9cbdc61440a9f5ee7e79b7e0af70628f8c/experiments/interface_feasibility_20261017)：22 项隔离检查；当轮核心回归 137 项通过。
- [六字段专项、失败记录及结果](https://github.com/yumir3297/Cryptography-Technical-Competition/tree/202f34e75f0b6e13ec49c58a313f0c32ab9e3095/experiments/trusted_action_resolver_v1_20261017)：专项 25 项、旧 E1–E4 22 项通过；当轮核心回归 137 项通过。

```sh
python -m pip install -r requirements.txt
python -m unittest competition.tests.test_action_resolver -v
python -m unittest discover -s competition/tests -v
python -m competition.verify_repository
python system_dev/v26/tools/verify_contracts.py
python competition/docs/final/verify-existing-evidence.py
```

两个历史核验脚本默认更新生成报告，建议在临时检出中运行；本轮已将新输出独立保存并按 Git 原字节恢复历史报告，未提交其改写。

旧实验结果不替代本分支验证；本分支使用新增库本身运行正常、拒绝、重试、ID 碰撞、崩溃恢复与实际模拟工具用例。本地测试环境与 CI 环境可能不同，CI 结果以 PR 实际检查为准。未经审查，不合并稳定比赛分支或 main。
