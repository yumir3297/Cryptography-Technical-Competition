# ZJJ-CORE 通用接口补齐：隔离可行性实验

**结论：在本仓库 IND-DEMO-1 可信模拟条件下，可通过新增受信适配层完成简化输入到安全执行的闭环；本轮无需修改密码学核心。** 这不是生产上线，也不证明任意行业可无条件接入。

基线为 `competition/zjj-core-final-20261010`，实际提交 **cc4e36b4e302fcdc53cc809a012c77d8464182af**，提交时间 2026-10-13 10:49:38 +08:00。实验前后核实远端均为此提交。实验仅新增本目录，原 350 个受版本控制文件逐字节不变（包括稳定核心、R2 Schema、原有证据）。不合并 main。

## 实验结果

- 当前基线回归：**137/137 通过**，实际运行 268.187 秒，见 [baseline-ready.log](evidence/baseline-ready.log)。此前历史 137 项结果没有用来替代本次运行。
- 最终实验：**22/22 通过**；见 [最终机器结果](evidence/probe-final-22/results.json) 和 [逐项日志](evidence/probe-final-22/tests.log)。测试运行器拒绝覆盖已有结果目录。
- 精确命令、环境故障、首轮实验失败及修正见 [COMMANDS.md](evidence/COMMANDS.md)；依赖版本见 [requirements-lock.txt](evidence/requirements-lock.txt)。

| 项目 | 实际验证与结果边界 |
|---|---|
| E1 | Agent 输入仅 request_id、unit_id、route；拒绝额外安全字段、非法类型、未认证/错绑/过期提案、撤销 KEY/ROLE、篡改 Task、缺失工具配置。原 Action Schema 校验通过。READER 撤销在读取 EVIDENCE 前拒绝。 |
| E2 | 由新 Action 独立构造 Assessment/Basis，使用既有签署代理生成完整真实签名链；原 CommonGuard/CommonW 接受；缺 U、缺 V、缺 Permit/CommitProof、动作篡改和坏签名被拒。 |
| E3 | W 受信边界内事务分配随机 16 字节 B16；8 并发同请求获得同一 ID；重启保持映射；同请求异内容冲突；完整 op 写一次冻结；原请求重复提交摘要、回执不变；重签被适配器和 W 分别拒绝。新请求 ID 也不能重复接受同业务意图。 |
| E4 | prepare→accept→claim→execute_once→settle 全链；真实 W 提交后退出 97，重启恢复同一回执并完成执行；工具提交后退出 98，查询恢复同一终局，无第二次执行发送；未知工具结果保持资源和 flight，无效果、无结算。 |

关键计数断言：正常 IND 路径 accepts=1、attempts=1、exec_invocations=1、settlements=1，工具工业效果行=1，实际效果 payload 与新 Action 一致。重复结算保持同一 final_fact_id。公开 COMMIT、工具终局和状态快照保存在最终 results.json，不含私钥。

## 字段来源与边界

应用侧认证使用实验域 `EXP-PROPOSAL-AUTH-v1`：H 对 profile、服务端固定 task_id、完整 proposal 和有效期签名；既有可信时钟与当前 KEY/ROLE 验证身份。这是新增应用认证封装，未改变 R2 或当前竞赛消息的签名域。

| Action 字段 | 受信来源 |
|---|---|
| scope | 服务端固定 IND Profile 登记 |
| operation_id | W 数据库新 exp_proposal 表中的随机 B16、唯一约束、同事务请求映射 |
| principal | C 认证的当前 Task |
| holder | 已认证 H，且与 Task 绑定 |
| holder_kid | 当前有效 KEY，与 Task 和 H 公钥一致 |
| executor | Task、Policy、C 的 X 身份/KEY/ROLE 交叉校验 |
| tool / tool_version | Task 与 Policy 相等，且匹配当前工具信任证书 |
| destination | Task 与 Policy 的建议路由映射一致，且匹配工具证书 |
| payload | Task 允许工件中的 batch/cycle/phase、Task 的 line/station、提案 unit/route；既有业务派生器再核实 E 来源证据、PACKAGE、状态及权限 |

`adapter.py` 只持有公开受信状态，不导入签署辅助器；`submit` 是唯一模拟的 Agent 输入面。`freeze/load` 属于受信编排端内部方法。`lab.py` 则明确是测试端，拥有既有 seed 的模拟身份和批准能力，不注册为 Agent 工具。提案认证不等于 U/V 授权，Agent 不能通过提案参数请求签署、执行或批准。

## request_ref 的实测结论

原 W 的摘要是 `digest(['COMP-APP-CALL-v1', profile, op])`，对象是**完整 op**，不是 ActionHash。

相同 Action 重新构造签名链，会产生新的消息 ID、挑战和引用，即使 ActionHash 一致，request_ref 也不同。最终证据分别保存原摘要、重签摘要和相同 ActionHash；适配器返回 `FROZEN_REQUEST_CONFLICT`，直接绕过适配器请求 W 仍返回 `ID_CONFLICT`。

正确恢复流程为：先事务保存提案映射及构造结果；受信审批完成后写一次保存整个 op；在任何 W.prepare 之前完成持久化；超时或进程重启只读取原 op 并重新取得外层身份/accept 认证凭据。外层凭据、ticket 可以更新，已冻结 op 不变。W 的 COMMIT/outbox 是已提交后的进度真源，不另外发明相冲突的状态机。

三个真实退出点分别是：映射提交后应答前（96）；首次 full_op 冻结后应答前（95）；W COMMIT 后签回执前（97）。前两个验证适配层持久化，第三个验证与原 W 恢复兼容。

## 失败和修正

1. 本机 Python 路径及依赖导致首次回归无法完整加载，见 baseline.log。明确使用临时 Python 3.14 venv 后运行原有 137 项全部通过，未修改仓库 requirements。
2. 适配器实现前红灯：缺少模块，见 red.log。
3. 首轮 15 项中重签测试 1 error：测试错用旧 Action 上下文，既有 broker 正确拒绝 BROKER_ACTION_BINDING。修正测试签署上下文后通过；未弱化 broker。
4. 首版 full_op 崩溃用例由父进程先冻结，不能充分证明首次冻结后崩溃；补强为先确认 APPROVAL_PENDING，由子进程首次冻结并直接退出，再恢复。
5. 额外读取边界红灯：H 的 READER 撤销后，初版会在最终拒绝之前先读取 EVIDENCE 计算有效期。没有把证据返回调用方，但读取顺序不符合要求。已在适配器增加提前 READER 校验和证据前 ACL 校验；新增回归见 reader-red.log 与最终测试。

6. 第一次 20 项全测中 1 error：构造提案调用可信时钟时签名样本 healthy=false，被 CLOCK_UNKNOWN 安全拒绝；此时尚未分配 ID、未提交或执行。未修改任何时钟参数，也未在测试内吞错重试。同用例独立复测通过，完整 20 项重跑结果见最终目录。该现象的环境根因未确定；不能用重跑成功掩盖偶发可用性风险。

7. 独立审查发现缓存重试仍需重新检查 Policy ACL 与 READER 动作范围。两项回归先复现失败，随后在缓存返回前对原 Action 调用 read_permission；最终 22 项完整复测通过。审查记录见 REVIEW.md。

## 限制及后续最小修改建议

- 这是单主机 SQLite、C/Task/Policy 和 E 来源可信模拟、IND uncertain→INSPECT 路径实验；执行的是工业模拟工具。未连接真实 Agent、MCP、Web 身份系统、工业设备，也未验证 PAY/MED 的新提案适配器。原三 Profile 回归通过不等于新入口三场景都完成。
- 本轮验证接口能力分离，不证明同一操作系统用户下 Agent 与测试私钥的进程隔离。正式服务必须将 Agent 输入面、身份提供者、审批端、worker 与密钥访问边界落实到部署权限；不能公开 lab.py 或 seed 辅助器。
- H 认证使用实验签名封装及短期有效期；生产身份接入、密钥轮换及人工审批等待流程未实现。审批尚未形成完整 op 时可以保持 PENDING；完整 op 一旦冻结，超时不自动换 ID、不自动重签，已失效的未接受请求需另行明确取消/重新授权规则。
- 真实进程退出只覆盖选定已提交持久化点，未声称覆盖每条指令崩溃、掉电、磁盘损坏、存储丢失、备份恢复、恶意数据库管理员或多节点分配。SQLite 唯一约束拒绝 ID 碰撞，本轮未强制构造随机碰撞或实现碰撞重试。
- 未测提案 ID 的跨 Task/租户业务含义；请求映射当前按 profile/H/Task/request_id 分域，业务意图去重继续由原 W 保证。8 并发请求验证映射幂等，非性能/容量压测。
- 原 W 的未知终局保持保留资源；查询不把“没查到”变成执行失败，原 EXEC-0 一次执行语义不变。

建议正式补齐仅新增：①可选 CandidateProposal 严格解析入口，保留 CandidateIngress 原入口；②受信 Action 构造器及 Profile 字段映射，认证和读取授权先于证据访问；③W 控制范围内分配器/持久化请求映射及完整请求 outbox；④只接收真正已批准产物的受信编排接口。当前结果不支持修改 CommonW、原 R2 Schema、签名域、COMMIT 或一次执行语义。下一步先将本实验拆出正式适配层，再为 PAY/MED 定义各自业务提案并单独验收。

## 复现

从实验分支仓库根目录运行（替换 Python 路径和结果目录）：

```sh
python3 -m venv /tmp/zjj-interface-new-venv
/tmp/zjj-interface-new-venv/bin/python -m pip install -r experiments/interface_feasibility_20261017/evidence/requirements-lock.txt
/tmp/zjj-interface-new-venv/bin/python -m unittest discover -s competition/tests -v
/tmp/zjj-interface-new-venv/bin/python -m experiments.interface_feasibility_20261017.run_probe /tmp/zjj-interface-new-results
```

精确本机命令见 evidence/COMMANDS.md。每个用例独立初始化并清理临时密钥、W/工具账本；最终证据包仅保留公开记录。
