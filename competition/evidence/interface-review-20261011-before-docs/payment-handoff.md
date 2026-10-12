# 付款场景协议开发交接

2026-10-11 · `PAY-1 / lab / tenant-1 / payment` · 配套[比赛协议](competition-protocol.md)。展示为合成订单、历史与风险推导后的一次模拟付款登记；所选正常例包含风险复核。

## 输入、来源与必要批准

- C 认证 POLICY、PAY_TASK、ORDER 当前 PAY_EVIDENCE、EXPERIENCE 的 PAY_HISTORY、Behavior 及 KEY/ROLE；E 签原严格 v2.5 PAY Evidence，由 v2.6 PAY_EVIDENCE 明确桥接 source_version/profile/type/ref 与完整 source_envelope。来源版本不改标成 v2.6 新 Evidence 消息。
- 来源绑定 order/stage、payer/payee、amount_minor/currency、order_revision、验收货物、未结算及收款人有效等事实。PAY_HISTORY 是 C 认证当前分区记录，风险按原 history-int-v2 的 cutoff、合法 case 集、整数特征和固定规则独立重算。
- H 为 HOLDER、G 为 ISSUER、X 为 EXECUTOR；U（FINANCE）必须签 EXECUTE。风险 CLEAR 无 V，FLAG 要 ANOMALY，INSUFFICIENT 要 LOW_EVIDENCE；本次 FLAG 正常例由登记 ANOMALY 角色 V 签相应用途。风险输出和必要用途不能由上传 Permit 自定。

## 场景安全规则

Action 的订单阶段、付款/收款主体、金额币种和任务、来源逐项一致；业务主体范围与额度受当前 ROLE/PAY_TASK/POLICY 限制。稳定意图为 scope/order/stage，不因换 operation_id 或付款描述而改变。预占以金额最小单位计数；接受同时检查预算、累计次数、唯一意图及 TaskFlight。PAY 原 PAY_TASK 无 max_inflight 字段，比赛沿原单 TaskFlight 槽位采用 1，不扩原 Schema。

比赛检查当前来源依赖的有限图，含 C/E 资格、ORDER、EXPERIENCE 和版本；合法签名不能消除承重项。该展示基于固定登记的合成历史与当前性，不将其描述为完整独立历史发布认证或银行账户证明。模拟工具 pay-sim 固定原 payload 并记录一次 payments 效果。

## 展示路径、终态及证据

| 路径 | 展示行为与结果 | 证据及等级 |
|---|---|---|
| 正常 | 合成订单 ord/pay、payer→payee、2000 CNY 最小单位→可信历史 FLAG→V ANOMALY＋U EXECUTE→跨秒接受/原回执→唯一 attempt→一次模拟付款→query/settle；效果 SUCCEEDED，内部 SETTLED | [normal](../../evidence/w-slice-20261011-final/PAY-1-normal.json)，共同 W 端到端已运行 |
| 缺风险复核 | 删除必要 Review、其余链重新合法签名；共同 W prepare 拒绝 REVIEW_REQUIRED，业务计数增量全 0 | [本轮拒绝](../../evidence/protocol-handoff-20261011-final/PAY-1-missing-review.json)，共同入口已验证；原[A 授权例](../../evidence/authorization-slice-20261011-final/PAY-1-missing_review.json)为组件证据 |
| 省略否决/依赖、陈旧来源 | REVIEW_DENY / DEP_CONFLICT / ROW_VERSION；拒绝仍有合法签名的请求 | [hidden_deny](../../evidence/authorization-slice-20261011-final/PAY-1-hidden_deny.json)、[missing_dependency](../../evidence/authorization-slice-20261011-final/PAY-1-missing_dependency.json)、[stale_source](../../evidence/authorization-slice-20261011-final/PAY-1-stale_source.json)，公共授权组件已验证 |
| 并发重复 | 多次领取共享同 attempt、多次结算共享同 FinalFactID；一次效果/支出/结算 | [concurrent_claim_settle](../../evidence/w-slice-20261011-final/PAY-1-concurrent_claim_settle.json)，真实事务路径已运行 |
| 坏/错绑定终局与可信矛盾 | 坏签名、错 attempt/ledger 拒绝；受控生成的真实签名矛盾→HALTED，保留未决预占和 Flight | [conflicting_final](../../evidence/w-slice-20261011-final/PAY-1-conflicting_final.json)，真实路径＋显式签名对抗输入已验证 |

## 恢复与开发约定

- [lost_ack](../../evidence/w-slice-20261011-final/PAY-1-lost_ack.json)：工具效果提交后 exit98；新进程 query 原 attempt 得同 effect/FinalFactID，一次结算。不能因丢应答再次付款。
- [unknown_query](../../evidence/w-slice-20261011-final/PAY-1-unknown_query.json)：查不到→EFFECT_UNKNOWN，保留付款预占与在途；不给“付款失败，可再次提交”的执行许可。
- [w_commit_crash](../../evidence/w-slice-20261011-final/PAY-1-w_commit_crash.json)：W 提交后 exit97，补原回执不新增接受，attempt/EXEC/效果/结算仍 0。

成功结算使预占一次转 spent 并释放 Flight/inflight；确认无效果失败按规则释放可释放占用，意图墓碑与累计次数保留。正式失败终局语义已定义，本次正常工具效果和未知/矛盾路径的证据分别列出，不声称已有银行失败流程。

复用 CommonW、PayAuthorizationAdapter、TransactionPlans 与 pay-sim；固定来源、账户约束和风险方法由受信端配置。演示金额及容量是合成配置。开发细节查[公共 W 契约](../w-transaction-contract.md)，输出按[查询审计口径](query-audit-scope.md)；界面、安装包和真实资金接入不属于此次协议收尾。

开发旁注：比赛暂不实现付款失败后的自动补偿和超时释放；执行资格已经消费而工具查不到时，预占可能长期保留。领取后撤销与内部状态接法见[开发注释](developer-scope-notes.md)，不能把一次调用 UNKNOWN 变成重新付款的许可。
