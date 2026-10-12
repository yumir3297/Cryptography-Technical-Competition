# 工业场景协议开发交接

2026-10-11 · `IND-DEMO-1 / lab / tenant-1 / industrial` · 配套[比赛协议](competition-protocol.md)。主展示固定为 INITIAL 阶段、uncertain 标签进入 INSPECT，效果为签名模拟产线路由登记。

## 输入、来源与必要批准

- C 认证 POLICY、IND_TASK、IND_UNIT、IND_PACKAGE、UNIT 当前行、Behavior 与 KEY/ROLE；E 对 IND_EVIDENCE 的数据、身份/工件引用、采样时间和标签作 SourceAttestation。准备与接受均重取当前版本，E 的业务范围须覆盖本 Action。
- Action 包含 line/station、unit/batch、inspection_cycle、phase、route 和原工具目的地。决策包映射 DEMO_NORMAL→RELEASE、DEMO_DEFECT→QUARANTINE、DEMO_UNCERTAIN→INSPECT；AH 承诺全部 Action，不能在工具调用时换 route。
- H 提交原签名链，G 签 Permit，U（LINE_OPERATOR）必须批准 EXECUTE；INSPECT 另须 V（QUALITY_REVIEWER）批准 QUALITY_REVIEW。W 独立重算用途，不信上传批准数量；适用 DENY 即使未随请求上交也阻断。

## 场景安全规则

工件、批次、产线、工位、任务允许工件集合、cycle/phase、来源和包引用精确一致。意图固定为完整 scope 下的 line/unit/cycle/phase，换 route 或 operation_id 不形成新业务意图。接受时工件必须 READY；容量、累计接受次数和任务在途共同限制，预占与 UNIT→ACCEPTED 同步形成。领取检查本操作冻结 scene_after 及占用归属。

成功终态依原路由：RELEASE→RELEASED，QUARANTINE→QUARANTINED，INSPECT→AWAITING_REINSPECT；确认无效果失败→STOPPED。原规则允许受控推进到 cycle2/REINSPECT，需原前驱 COMMIT、成功终局、已结算及新来源/Task/Basis/批准；本次所选主路径止于 AWAITING_REINSPECT，不能自动视作复检已完成。

## 展示路径、终态及证据

| 路径 | 展示行为与结果 | 证据及等级 |
|---|---|---|
| 正常主路径 | E uncertain 来源→U EXECUTE＋V QUALITY_REVIEW→跨秒 prepare/accept→原回执→claim→一次 INSPECT→query 同事实→settle；1 接受/attempt/发送/效果/结算，UNIT=AWAITING_REINSPECT | [normal](../../evidence/w-slice-20261011-final/IND-DEMO-1-normal.json)，端到端已运行 |
| 缺必要复核 | 其余消息重新合法签名但删除 Review；共同 W prepare 拒绝 REVIEW_REQUIRED；业务计数增量全 0 | [本轮拒绝](../../evidence/protocol-handoff-20261011-final/IND-DEMO-1-missing-review.json)，共同入口已验证；原[A 授权例](../../evidence/authorization-slice-20261011-final/IND-DEMO-1-missing_review.json)保留组件身份 |
| 省略否决/依赖 | 适用否决未上交仍 REVIEW_DENY；删承重依赖后合法签名仍 DEP_CONFLICT | [hidden_deny](../../evidence/authorization-slice-20261011-final/IND-DEMO-1-hidden_deny.json)、[missing_dependency](../../evidence/authorization-slice-20261011-final/IND-DEMO-1-missing_dependency.json)，公共授权组件已验证 |
| 意图与资源竞争 | 八条全链同业务意图仅一次接受；不同工件意图争最后容量只有一个成功，另一 RESOURCE_EXHAUSTED | [same_intent8](../../evidence/w-slice-20261011-final/IND-DEMO-1-same_intent8.json)、[last_resource](../../evidence/w-slice-20261011-final/IND-DEMO-1-last_resource.json)，真实事务路径已运行 |
| 坏/错绑定终局与可信矛盾 | 坏签名、错 attempt/ledger 拒绝输入；经认证不可变事实矛盾 HALTED，保留未决占用 | [conflicting_final](../../evidence/w-slice-20261011-final/IND-DEMO-1-conflicting_final.json)，真实路径＋显式受控签名对抗输入已验证 |

## 恢复与开发约定

- [lost_ack](../../evidence/w-slice-20261011-final/IND-DEMO-1-lost_ack.json)：工具真实提交后 exit98；新进程只查原 attempt，原 FinalFactID/effect 不变，重复 EXEC 无新发送，重复 settle 无新结算。恢复成功仍止于原场景终态。
- [unknown_query](../../evidence/w-slice-20261011-final/IND-DEMO-1-unknown_query.json)：query 查不到→EFFECT_UNKNOWN，原预占/Flight/意图保留。确认效果 0 是已确认数量，不表示确定不会有迟到效果。
- [w_commit_crash](../../evidence/w-slice-20261011-final/IND-DEMO-1-w_commit_crash.json)：W 提交后 exit97，只补原 Core 的回执；1 接受/预占、0 attempt/EXEC/效果/结算。
- [claim_cancel_revoked](../../evidence/w-slice-20261011-final/IND-DEMO-1-claim_cancel_revoked.json)：确定失效且未领取可以取消，仅释放自己的占用；[claimed_cancel8](../../evidence/w-slice-20261011-final/IND-DEMO-1-claimed_cancel8.json)证明领取后不能取消或重派。

开发复用 CommonW 和 line-sort-sim，身份/工具注册由受信配置提供；刷新和回放只读 status/audit 投影。源码位置与调用见[公共 W 开发契约](../w-transaction-contract.md)，读取名称按[查询审计口径](query-audit-scope.md)。二阶段完整演示属于另选路径，需新验证；界面和安装包不属于此次协议收尾。
