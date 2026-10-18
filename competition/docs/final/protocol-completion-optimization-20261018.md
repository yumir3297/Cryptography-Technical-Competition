# ZJJ-CORE 总协议补全与工程优化记录

> 历史阶段记录：以下验证与“未推送”状态按当时保留。当前完整交付、替代关系与最新验证请从[统一交付入口](ind-complete-delivery-20261018.md)阅读。

记录日期：2026-10-18（Asia/Shanghai）。状态：**本地方案与证据汇总，供开发审阅；未发布新的协议版本，未推送 GitHub。**

本文保存本轮确定的共同设计、实际实现范围、剩余工程工作及远程同类资料关系。其内容不能替代原 R2 精确合同、竞赛实现对照或部署验收。P1/P3 沿用用户既定分层，不重复开发其他任务的隔离实验。

## 1. 版本与结论边界

- 原 R2：`system_dev/v26/` 的 `ZJJ-AAP / 2.6` 精确合同及 Schema。
- 现有竞赛线：`ZJJ-CORE-COMP-1`，字段基础版本 2.6。竞赛标识由签名覆盖；当前接收器并不接受原 R2 标识，不能称二者消息可直接互换。
- 比赛基线：`competition/zjj-core-final-20261010 @ cc4e36b4e302fcdc53cc809a012c77d8464182af`。
- 远程 Resolver V1：PR #3，`86f284bf4787e9990b47b8159cd1e6b9e5824b03`，仍为开放 Draft。
- 本地统一实现：`integration/unified-operation-lifecycle-20261017 @ 63c5da6e6985d5d28102f1c905f2451abf7133a5`。

**建议采纳的共同方向：通用安全核心＋可插拔业务适配层；在 W 信任边界内于签署前持久分配 ID；请求身份、授权事实与执行事实分别保存；恢复原事实，不因超时另建执行。**

当前新公开服务仅接入 IND-DEMO-1。PAY/MED 既有共同 W 组件及恢复测试不等于它们已接入新受控服务。因此可以确认 IND 本地原型的相关路径通过验证，不能宣称三场景统一公开服务或完整原 R2 已完成。

本记录不消除既有竞赛变体差异，例如 Acceptance deps、Review 受众、资格寿命继承、正式签名 Result/STATUS、拒绝响应账与审计对象。仍以[原 R2 与比赛应用对照](r2-application-mapping.md)逐项说明；没有通过本轮测试证明这些差异已经修复。

## 2. P1/P3：调用契约与字段权威

外部 Agent、Web、人或服务提供业务候选；`CandidateProposal` 属于适配层，不替代完整 Action。当前 IND 提案恰含 `request_id、unit_id、route`；这三个字段不是所有场景通用的业务 Schema。

受信 Resolver 在认证 Task、Policy、KEY/ROLE 和工具配置约束下构造完整 Action：

| 字段 | 权威来源 |
|---|---|
| operation_id | W 信任边界内的受控持久分配机制 |
| principal | 认证 Task 的业务主体 |
| holder | Task 绑定且已认证的合法 H |
| holder_kid | C 的有效 KEY 登记，与 H/Task 匹配 |
| executor | Task、Policy 与 C 的 X 登记交叉一致 |
| destination | 认证 Task/Policy 路由和有效工具登记 |

保留 Action 十字段、ActionHash、既有核心签名域、完整批准链及 CommonW 守卫。Resolver 返回未签署审批材料，不能替代 H/U/V/G/X 作决定或签名。C 认证 Task 是当前主体授权绑定的信任依据，不等于签名本身证明了现实业务权属。

DelegationProof 保留为将来的独立扩展；当前没有允许 Agent 冒用 H 或其他参与方身份的规则。

## 3. P2：分配、幂等、重签与恢复

### 3.1 ID 与稳定业务意图

`operation_id` 标识具体操作并进入完整 Action、哈希、签名及持久事实。受信分配防止外部调用者任意声明其来源；持久映射使超时后仍能找到原操作。它不是唯一执行的全部保障：业务意图去重、nonce 消费、W 原子接受和工具效果账仍各自必要。

“W 受控分配”按信任边界解释，不要求代码一定放在 `CommonW.prepare()` 中。受信宿主固定 Resolver、RequestStore 与 RequestBoundW，共享原数据库及事务；分配提交后才返回动作供审批、签署。

请求键按 profile/H/Task/request_id 分域。同键同内容返回原构造；同键异内容拒绝。客户端必须保存并在重试时复用 request_id。不同请求键可以形成多个待审批草稿，**不在分配时强加同 intent 只能存在一个草稿**；W 仍按场景推导的稳定 intent 唯一接受。不能靠换 ID 消除已接受意图。

### 3.2 保存与受限更新

一个 `app_request` 保存原请求映射、B16、完整构造、当前 op、request_ref、版本及短期标识历史；原 `a_journal` 保存每版完整提交和最终认证见证。不叠加旧实验的第二套分配账。

首次完整验证后固定 Action、Task/scene、Assessment、Basis、ctx、deps、required、reviews、Authorization、IssueRequest 和 Permit。接受前只允许替换 ChallengeRequest、Challenge、CommitProof；仍由真实参与方签署，保留原批准、原 Permit 与 DENY 适用范围。

替换需预期版本与 request_ref，通过 CAS 和历史消息 ID/session/nonce/提交 attempt 检查。验证原签名链、来源、当前资格、DENY、全部原窗口和最终时间关口后同事务保存；失败连同 nonce、版本和日志整体回滚。短期证明更新不能延长原授权寿命；原依据过期后停止自动更新，受控重新审批流程尚未实现。

### 3.3 W 接受与故障恢复

RequestBoundW 在 prepare 和 accept 的原事务内核对已分配 ID 和当前完整提交。先换包则旧 ticket 拒绝；先接受则禁止换包。不能用事务外预查询替代两个检查点。

| 情况 | 恢复动作 |
|---|---|
| 分配或提交响应超时 | 认证读取持久映射、当前完整包和版本，复用原请求键 |
| 尚未接受，仅短期证明失效 | 原授权仍有效时，真实签署新三件套并按预期版本更新 |
| 已接受、回执待签 | 保留 COMMIT/占用；内部宿主只补签原冻结 Core |
| 已接受后重试 | 恢复原接受与回执，不建立第二次接受 |
| 工具调用响应未知 | 核对原 attempt 与 EXEC 消费事实；已消费或无法确认时只查询原尝试，不自动重发 EXEC |
| 可信终局仍未知 | 保留资源和在途状态；不以“没有查到”判定无效果 |

短期提交 attempt、W ticket_id 与工具派发 attempt_id 均不能混同 operation_id。网络超时和 503 不能证明事务未提交。

## 4. P4：工程边界及已存在的本地实现

Agent 是候选提出者；MCP/HTTP 是可选传输；Resolver 构造动作；H 认证提交；U/V 批准或否决固定动作；G 签 Permit；X 签挑战与原冻结回执；W 验证、接受并维护账；内部 worker 领取、执行、查询和结算。

公开提交者可以转交真实 H 认证材料，不因持有传输 token 自动成为 H。公开接口不得暴露任意签名、登记写入、原 W、完整回执补签或 worker 特权。U/V 不静默修改 Action；改变动作须重新建立依据及相应签署。

本地已有 OperationService、回环 HTTP 短连接和 MCP stdio 桥接，静态白名单及真实认证仍保留。详细角色、十项方法、认证域、错误及调用顺序见[统一服务契约](unified-operation-contract.md)。这说明 P4 已有本地实现和测试资料，不能写成完全没有实现；正式部署配置及全部场景接线仍需单独验收。

长连接中断属于传输可用性与工程恢复问题；采用本机服务、短连接和认证恢复可缓解，不需要把 MCP 加入密码学核心。实际认证材料、完整 op 和事务事实决定恢复，连接是否存活不授予权限。

## 5. 对现有部分的影响及剩余工作

本轮保留原 Action/哈希/核心签名域、DENY、intent、COMMIT/Core、唯一派发及时间阈值。CommonW 增加 prepare/accept 两个事务检查接点；新受控入口强制绑定 RequestStore。旧 V1 已保存行可迁移为版本 1，不补造历史分配，不重置运行账。

仍需完成的工程事项：

1. 明确比赛演示的正式范围：若包含三场景的新对外调用，PAY/MED 须接入相应受控分配、提交和恢复路径；无需为此发明未经确认的简化业务字段。
2. 所有实际暴露入口统一采用受控边界，避免另外暴露绕过登记的原 CommonW；内部测试组件不直接注册为 Agent 工具。
3. 使用真实部署配置验收 H 身份、审批签署端、持久目录、服务启动/重启、工具端点及时间源。
4. 原依据/批准失效后的受控重新审批需要另行定义；当前短期证明更新不是该流程。
5. 以单一集成提交交付开发方，再决定更新哪一条 PR。不能以本地通过代替 GitHub 合入或现场验收。

多机一致性、数据库恶意回滚/损坏、物理设备效果、生产密钥托管与长期委托不是本轮已验证能力。可把当前方案作为 IND 单机竞赛原型的 P2 优化基础；若目标是全场景闭环，以上接线仍须完成。

## 6. 验证证据与声明口径

- 本地完整联合复测：196 tests、0 failures、0 errors、574.975 秒；见[机器结果](../../../integration-evidence/joint-rerun-02/results.json)和[完整日志](../../../integration-evidence/joint-rerun-02/tests.log)。
- 2026-10-18 专项：首组 56 项中 52 项通过，4 项传输因沙箱 socket.bind 权限失败；见[原日志](../../../integration-evidence/p2-focused-20261018/tests.log)。同四项取得本机端口权限后重跑全部通过，见[传输结果](../../../integration-evidence/p2-transport-rerun-20261018/results.json)。
- 另有本轮 W 竞态/恢复 9 项通过、59.771 秒，终端输出已确认；本轮未另存该次原始日志，不能声称已交付该日志。
- 上述为不同运行，不能合并描述成一次 65/65 的联合验收，也不能与历史实验相加制造更大的测试总数。
- 记录前重新比对完整联合复测的 101 个已记录源文件摘要，均与当前文件一致。本轮仅新增记录和核查证据，不修改执行逻辑。
- 历史部分 CLOCK_UNKNOWN/回执待签现场未完整保留，不能宣称所有历史时钟原因已根治。保持原阈值与失败关闭；防空闲休眠仅是已知宿主条件处理，见[时钟说明](unified-operation-clock.md)。

有限测试支持当前实现路径，不能替代完整原 R2 符合性证明或真实部署验收。

## 7. GitHub 已有同类资料及继承关系

2026-10-18 通过 GitHub 只读接口重新枚举全部六个现存分支及其完整树（均未截断），读取以下文档及全部三个可发现 PR 的状态。范围为当前分支尖端和可发现 PR，不声称审计了已删除分支或所有不可达历史提交。

| 已提交资料 | 当前可见位置 | 与本记录的关系 |
|---|---|---|
| [比赛协议 1.1 优化与复检](https://github.com/yumir3297/Cryptography-Technical-Competition/blob/cc4e36b4e302fcdc53cc809a012c77d8464182af/competition/docs/final/optimization-review-20261012.md) | 比赛/dev/实验/功能分支包含 | 旧版状态、未知、否决、恢复及展示口径整理；不是本轮 P2 更新实现 |
| [共同协议与场景开发分层记录](https://github.com/yumir3297/Cryptography-Technical-Competition/blob/cc4e36b4e302fcdc53cc809a012c77d8464182af/competition/docs/final/protocol-separation-record-20261012.md) | 比赛及其相关分支 | 已有通用规则与业务交接分层；本记录沿用并明确调用者不局限于 Agent |
| [接口隔离实验说明](https://github.com/yumir3297/Cryptography-Technical-Competition/blob/4b301f9cbdc61440a9f5ee7e79b7e0af70628f8c/experiments/interface_feasibility_20261017/README.md) | 第一条实验分支，第二条实验分支也保留 | 早期 CandidateProposal、受控分配和原包恢复可行性来源，不是正式服务 |
| [六字段专项报告](https://github.com/yumir3297/Cryptography-Technical-Competition/blob/202f34e75f0b6e13ec49c58a313f0c32ab9e3095/experiments/trusted_action_resolver_v1_20261017/REPORT.md) | 第二条实验分支 | 字段权威与边界专项；不等同于新增生产 Resolver |
| [Resolver V1 维护说明](https://github.com/yumir3297/Cryptography-Technical-Competition/blob/86f284bf4787e9990b47b8159cd1e6b9e5824b03/competition/docs/final/trusted-action-resolver-v1.md)及[验证记录](https://github.com/yumir3297/Cryptography-Technical-Competition/blob/86f284bf4787e9990b47b8159cd1e6b9e5824b03/competition/docs/final/trusted-action-resolver-v1-results.md) | feature/trusted-action-resolver-v1；[PR #3](https://github.com/yumir3297/Cryptography-Technical-Competition/pull/3)，open/Draft、未合并 | 最接近的正式应用库方案；已包含六字段、B16/请求映射及原包恢复，完整 op 一旦冻结禁止替换 |
| 本地统一生命周期契约与本记录 | 仅本地集成提交及本轮未提交文档 | 延续 V1 单账，新增受限三件套更新、版本/历史、W 当前包检查、认证恢复及 HTTP/MCP；不是相同文档的重复上传 |

本次未在六个现存远程分支树中发现 `unified-operation-contract.md / unified-operation-handoff.md / unified-operation-clock.md / unified-operation-branches.md`，也没有新的统一整合 PR。故“类似方案已提交”与“最新优化已提交”须区分。

原 2026-10-12 文件正文中的“本轮未提交”描述的是其写作阶段；本次远程精确提交和文件读取已确认这些旧文档现在存在于 GitHub，不能据旧措辞认定未上传。

远程当前 SHA、文档 blob SHA 和核查范围见[GitHub 文档核查快照](../../../integration-evidence/github-docs-check-20261018.json)。本轮没有推送、合并、删分支或更新 PR。

建议后续新增增量文档并链接 V1 历史，不撤回或覆盖旧实验。原 R2、比赛变体、旧验证与新验证保留各自身份；待统一选择目标基线并复验后，再决定是否更新共同协议正文和开发总交接。
