# Trusted Action Resolver V1.0 六字段专项验证

本报告验证现有隔离 `TrustedAdapter` 的受信解析契约，**不是新增生产 Resolver 实现**。只增加验证代码和独立证据；DelegationProof 未实现。

结果以本目录 evidence 的实际机器结果及逐项日志为准。上轮实验基线为 `4b301f9cbdc61440a9f5ee7e79b7e0af70628f8c`；稳定核心为 `cc4e36b4e302fcdc53cc809a012c77d8464182af`。

## 六字段权威来源与约束

| 字段 | 权威来源 | 绑定及授权约束 | 验证方式 |
|---|---|---|---|
| operation_id | W 受控信任边界内，认证成功后随机分配的 16 字节 B16；exp_proposal 唯一约束与事务映射 | profile/H/Task/request_id 确定请求域；同请求同 ID；ActionHash 及完整签名链建立前分配 | 提案夹带拒绝、签后替换拒绝、持久化映射、并发/崩溃恢复、重复 COMMIT/一次执行 |
| principal | C 认证的当前 Task.principal | 与 Task 的 holder、holder_kid、executor 及任务业务范围共同绑定；并非由 Agent 声称，也不要求 principal 字符串等于 holder | 读取认证 Task 独立比对；提案夹带及签后替换拒绝 |
| holder | 已通过 H 公钥认证的调用身份，同时等于 Task.holder | 当前 KEY、HOLDER ROLE、READER、Policy ACL、任务和路由约束 | 提案及签后替换拒绝；即使 C 签过的 Task 错绑 H，也不能与固定已认证 H 冲突 |
| holder_kid | 当前登记 H 的有效 KEY，匹配 H 公钥、Task.holder_kid | KEY.subject、登记 kid、公钥、IssueRequest 用途、有效期和 ROLE；不是调用者自由选择的 key ID | Task 错绑拒绝；合法收窄 KEY 用途后拒绝；夹带及签后替换拒绝 |
| executor | Task、Policy、C 登记的 X 主体交叉一致 | Policy.executor_kid、X 的 KEY/EXECUTOR ROLE、工具及目标范围 | Task 替换 X 拒绝；EXECUTOR destination_set 收窄后拒绝；夹带及签后替换拒绝 |
| destination | Task 与 Policy 的路由映射一致，且等于当前工具信任证书的路由 | H/X 及后续 U/V/G/X 角色范围、工具版本、E/工业 Profile 的动作规则共同约束 | 错误 Task 目标映射在 C 发布 Schema 层拒绝；目标权限收窄拒绝；夹带及签后替换拒绝 |

完整构造顺序：认证提案 → 校验 H 资格及读取授权 → 读取认证 Task/Policy/KEY/ROLE/tool → W 受控分配 ID → 组装原十字段 Action → 原 Action Schema 与工业业务派生复核 → 受信审批端分别获得真实批准并签署 → 冻结完整 op → 原 W.prepare/accept/claim/execute_once/settle。

当前实现是 IND uncertain→INSPECT 的固定可信模拟 Profile。上表描述此实现中实际检查的来源；不宣称任意外部身份系统或任意行业可直接接入。

## 签署边界

- Resolver 提案调用前后比较 a_sign_call 与 a_publication 数量，确认构造动作没有额外调用 H/U/V/G/X 签署代理，也没有生成授权消息；仅返回构造结果，load 仍为 APPROVAL_PENDING。
- 将未完成授权的构造提交给原 W，不能得到接受或执行权。即使受信测试端误把缺少 U 授权的 op 冻结到存储，原 W 仍拒绝；存储 helper 不是批准者。
- 对 H/U/V/G/X 分别构造真实目标签署请求：缺 caller_proof 拒绝；陌生密钥伪造拒绝；H 试图为 U/V/G/X 签署请求认证也拒绝。失败调用不消耗 nonce，也不返回签名。
- 正常成功链仅由显式受信 lab 经原 ScopedSignerBroker 完成批准与签署；逐一用原 `ZJJ-SIG-v1` 域独立验签。实验中的测试端拥有私钥，不作为 Agent 接口，也不构成生产进程隔离证明。

## 兼容、幂等和恢复

专项测试用新 Action 调用实际 CommonGuard，得到 T；通过原 CommonW 完成流程。新旧请求的重复 accept 比较完整 COMMIT 和 commit_ref，而非只比较返回状态；两者保持相同，接受计数不增加。

重复 claim、execute_once 和 settle 后，接受数、attempt、EXEC-0 消耗、结算、工业工具效果行均为 1；工业效果行的 payload 与新 Action.payload 一致（由原 E1–E4 用例核验）。原 22 项 E1–E4 一起复测，继续覆盖 8 并发分配、请求冲突、换 ID 重复意图、首次映射/full_op 持久化后进程退出、W COMMIT 后崩溃、工具提交后丢应答、未知终局保留资源。

恢复必须重放已持久化完整 op。仅有相同 ActionHash 不足以确保相同 request_ref；合法重新签署也会改变消息 ID、挑战和引用，从而改变完整请求摘要。适配器禁止替换已冻结请求，原 W 继续 ID_CONFLICT 拒绝。这是当前正确的请求身份与重放规则，不应靠修改 ActionHash/签名域/COMMIT 来“修复”。

兼容性结论针对当前竞赛实现（既有 `ZJJ-CORE-COMP-1` 消息头及原 R2 字段定义），不宣称原 R2 不同协议标识的消息头可以直接混用。所有既有协议签名域与 Schema 均不变。

## 失败、修改项与问题分类

最终运行数量、通过/失败、失败详情和精确命令写入 RESULTS.md、evidence/results 与 COMMANDS.md，不使用上轮通过数量替代本轮结果。

| 分类 | 本轮评估与必要处理 |
|---|---|
| 协议设计 | 六字段有明确的身份/授权/路由职责，不支持删字段或让 Agent 自填；未发现需要改核心消息或一次执行语义的依据。这个结论受本轮有限场景与攻击用例约束，不是完整安全证明。 |
| 普通软件工程 | 对外简化提案契约、受信字段组装、当前权限重查、ID 请求映射、完整 op 持久化与恢复、审批编排、生产权限隔离仍需作为正式应用层工程落实。当前已有隔离原型，不等于正式入口上线。 |
| 信任边界/规范澄清 | C 认证 Task 被信任为 principal→holder/holder_kid 的授权依据；签名能验证来源，不能证明 C 的业务决定符合现实权限。若不接受该信任前提，应显式设计额外授权证明，不能把来源验证描述成已证明现实所有权。 |
| 实验工程与环境 | 测试模拟审批与故障注入不开放给 Agent。若出现脚本、依赖或 CLOCK_UNKNOWN，按真实日志单独归类；不能将安全拒绝计作接受成功，也不放宽原检查。 |

本轮优先只增加验证资料；任何实际代码修改都须在结果文档中列明，且保持在隔离实验目录，原核心与旧证据不变。

## DelegationProof 未来接入边界（未实现）

当前提案不接受 delegation_proof、DelegationProof、act_as、on_behalf_of 或 sign_as。陌生调用者不能通过附加 principal/holder 字段或自签认证成为当前 H。此负向验证**只证明当前入口不接受这些字段，不代表存在 DelegationProof 解析或验签实现**。

如未来需要跨主体委托，至少须先明确并另行验证：

1. 谁有权代表 principal 授予委托，证明发行者的权威来源是什么；不能只验证“某个 key 的签名正确”。
2. 委托绑定的 scope、principal、holder、holder_kid、任务、允许动作/工具/目标、额度、有效期、次数、撤销及版本；与 Task/Policy/KEY/ROLE 做权限交集，不能并集放权。
3. 验证发生在字段解析/分配与批准之前，并在接受时按明确的冻结/撤销规则复核；审计能恢复当时依据。作用于完整 Action 的授权绑定规则须单独定义。
4. 委托证明不会授权 Resolver 代替 U/V/G/X 作决定或签署，也不能让 Agent 获取任一参与方私钥；H 仍通过自己的已登记 key 认证。
5. 委托链深度、循环、再委托、key 轮换、重放、幂等以及与业务意图去重的关系。本轮不为这些问题编造已实现语义。
6. 新证明若需要进入既有 R2 消息或签名内容，应另行评估版本化和兼容性；不得在本轮偷偷增加字段或改变原签名域。

## 复现

在本轮实验分支仓库根目录，使用已安装原 requirements 的 Python：

```sh
python -m experiments.trusted_action_resolver_v1_20261017.run_validation /tmp/zjj-resolver-v1-new-run
python -m unittest discover -s competition/tests -v
```

前者默认执行 25 个六字段专项用例和原 22 个 E1–E4，用例各自使用新临时数据库和密钥。结果目录必须不存在；运行器拒绝覆盖。实际本机路径、依赖、源文件摘要和命令见 evidence。
