# 医疗场景协议开发交接

2026-10-12 · `MED-DEMO-1 / lab / tenant-1 / medical` · 配套 `CORE-SPEC-1.3` [共同安全协议](competition-protocol.md)。展示为合成患者/就诊记录与固定合成模板的一次医嘱登记，不赋予模板临床含义。

共同协议中的来源、复核、意图及资源规则在本场景的具体值由下文规定；固定登记、调用顺序、状态字段与证据等级先读[比赛开发总交接](scenario-integration-handoff.md)。

## 输入、来源与必要批准

- C 认证 POLICY、MED_TASK、MED_ENCOUNTER、ENCOUNTER、Behavior 与 KEY/ROLE；E 对 MED_EVIDENCE 的 patient/encounter、记录引用/版本、采样时间与模板标签作 SourceAttestation。当前读取权先于来源读取、资料投影和候选模块回调。
- Action 精确绑定 synthetic_patient_id、encounter_id、order_group_id、SUBMIT 阶段、record_ref、template_id、destination_system 及工具。DEMO_A→DEMO-ORDER-A，DEMO_B→DEMO-ORDER-B，按固定 med-fixed-v1 重算，不由 agent 指定任意模板。
- H/G/X 分别提交/签 Permit/签原回执；U（MEDICAL_AUTHORIZER）必须签 EXECUTE；V（CLINICAL_REVIEWER）始终必须签 CLINICAL_REVIEW，且与 U/G/X 登记主体分离。读取资格不能从“临床角色”名称推导。

## 场景安全规则

患者、就诊、医嘱组、资料记录、模板、任务及 ENCOUNTER 当前行精确绑定。patient_set 与 encounter_set 同时满足并核登记关联，避免把某患者的授权用于另次就诊。在接受与新领取守卫中，记录/资格变化会使旧依据不再满足当前条件；合法签名不代替权限检查。已领取后的变化按领取点边界说明。稳定意图为完整 scope/patient/encounter/order_group/phase，换模板或操作号不重新授予一次登记权。

接受时场景为 READY；医嘱容量、累计次数和 TaskFlight 检查后同步预占并转 ACCEPTED。成功登记终态 REGISTERED，确认无效果失败 STOPPED；未知保留占用。普通 AUDITOR 只按原规则读取裁剪状态；当前演示 H 的完整 audit 投影须保持 H 读取权限，不能直接开放给普通审计主体。

## 展示路径、终态及证据

| 路径 | 展示行为与结果 | 证据及等级 |
|---|---|---|
| 正常 | 合成 patient-a/encounter-a、DEMO_A 来源→V CLINICAL_REVIEW＋U EXECUTE→跨秒接受/回执→唯一 attempt→模拟医嘱登记→query/settle；1 接受/发送/效果/结算，ENCOUNTER=REGISTERED | [normal](../../evidence/w-slice-20261011-final/MED-DEMO-1-normal.json)，共同 W 端到端已运行 |
| 缺临床复核 | 其余链重新合法签名而删除 Review；共同 W prepare 拒绝 REVIEW_REQUIRED，业务计数增量全 0 | [本轮拒绝](../../evidence/protocol-handoff-20261011-final/MED-DEMO-1-missing-review.json)，共同入口已验证；原[A 授权例](../../evidence/authorization-slice-20261011-final/MED-DEMO-1-missing_review.json)为组件证据 |
| 省略否决/依赖 | 适用 DENY 未上交仍 REVIEW_DENY，删依赖仍 DEP_CONFLICT | [hidden_deny](../../evidence/authorization-slice-20261011-final/MED-DEMO-1-hidden_deny.json)、[missing_dependency](../../evidence/authorization-slice-20261011-final/MED-DEMO-1-missing_dependency.json)，公共授权组件已验证 |
| 读权撤销 | 资料详情及候选回调前 NO_ROLE，不新增候选调用；已签状态读取请求也因当前 H 资格撤销拒绝 | [资料读取组件](../../evidence/authorization-slice-20261011-final/MED-DEMO-1-current_acl_before_candidate_detail.json)、[本轮状态读取](../../evidence/protocol-handoff-20261011-final/MED-DEMO-1-authenticated-reads.json) |
| 坏/错绑定终局与可信矛盾 | 错 attempt/ledger、坏签名拒绝输入；显式受控签名矛盾→HALTED，保留未决占用 | [conflicting_final](../../evidence/w-slice-20261011-final/MED-DEMO-1-conflicting_final.json)，真实路径＋签名对抗输入已验证 |

## 恢复与开发约定

- [lost_ack](../../evidence/w-slice-20261011-final/MED-DEMO-1-lost_ack.json)：工具提交医嘱登记后 exit98；新进程 query 原 attempt，仍同 effect/FinalFactID，重复 execute/settle 不新增登记或结算。
- [unknown_query](../../evidence/w-slice-20261011-final/MED-DEMO-1-unknown_query.json)：查不到→EFFECT_UNKNOWN，保留医嘱容量和 Flight；不能把未知当“无医嘱，可以再次登记”。
- [w_commit_crash](../../evidence/w-slice-20261011-final/MED-DEMO-1-w_commit_crash.json)：W 已接受但回执未存时只补原 Core；1 接受/预占，0 attempt/效果/结算。恢复不跳过临床复核或新建医嘱组。

开发复用 CommonW、SceneAuthorizationAdapter 与 med-order-sim。展示先认证 H、按患者/就诊权限取资料；已裁剪投影标原 Envelope=false。界面刷新只调用认证 status/audit，工具 query 和结算为显式受控步骤。精确字段查[工业医疗合同](../../../system_dev/v26/03_industrial_medical_profiles.md)，实现查[公共 W 契约](../w-transaction-contract.md)。本轮确认的是合成登记流程可行性；临床判断、界面与安装包分别由其责任方处理。

开发旁注：比赛暂不接真实临床执行与撤回设施；已领取登记的操作不能用“撤回批准”按钮宣称即时取消效果。跨服务撤销、UNKNOWN 保留和当前 H 审计权限的接法见[开发注释](developer-scope-notes.md)。

协议接线：新领取的效果 UNKNOWN 不等于首次 EXEC 已消费；仍须按原首次守卫登记，已消费后只按可用权限查询恢复。H 读取不可获取不证明原登记失败，也不能借 worker 冒用 H 权限补视图。诊断先认证，保留绑定和首个原因，裁剪患者资料；诊断不等于 HALTED。统一采用[当前接口第 5 节](interface-reference.md)，领取后撤销的真实竞争窗口见[优化复检](optimization-review-20261012.md)。

本轮执行标识升级后，[新的正常路径](../../evidence/security-rectification-20261012/w-slice/MED-DEMO-1-normal.json)与[新的丢应答恢复](../../evidence/security-rectification-20261012/w-slice/MED-DEMO-1-lost-ack.json)分别重跑同一场景。角色批准来自认证签名模拟器，agent 只提交 Action 数据；真人批准采集与主体能力见[安全边界](security-boundaries.md)。不将旧包字节标为新标识。
