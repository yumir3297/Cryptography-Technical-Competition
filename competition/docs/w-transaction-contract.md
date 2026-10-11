# COMP-APP-W-1.0：受信单机公共W与模拟工具

三Profile调用 `competition.core.common_w.CommonW`，复用 `CommonGuard` 与 C 签名事件；`TransactionPlans`只推导计划，工具各用独立SQLite。原R2 2.6 Schema、消息域、COMMIT/Acceptance/TOOL_TRUST/TOOL_FINAL字段不变。旧研究/IND纵切保留回归，产品入口调用新公共路径。

实际八方法：`prepare(p,op,identity_proof)`、`accept(p,ticket,holder_proof)`、`claim(p,oid,worker_proof)`、`execute_once(p,oid,worker_proof)`、`query_attempt(p,oid,worker_proof)`、`settle(p,oid,tool_response,worker_proof)`、`status(p,oid,holder_read_proof)`、`audit(p,oid,holder_read_proof)`。固定registry包含完整scope，不接收pub/eligible/工具URL/外部attempt作为权威。

身份挑战：TrustedState.challenge+H签`COMP-APP-AUTHZ-IDENTITY-v1`；challenge_accept+H签`COMP-APP-ACCEPT-v1`；challenge_worker+worker签`COMP-W-WORKER-v1`；challenge_read+H签`COMP-W-READ-v1`。挑战30秒、用途/op/scope/COMMIT绑定、同W一次消费。worker资格由C签`COMP-W-WORKER-GRANT-v1`启动证书pin；W仅持独立delivery key，不持worker/H/G/X/U/V/E/C私钥。bootstrap持角色钥用于生成真实输入，不是部署权限证明。

同一BEGIN IMMEDIATE重核全链签名、当前有限C/E来源、批准、全量DENY、时间、request/permit/proof/session/nonce唯一性、stableintent、资源/Behavior/Flight/场景，原子保存COMMIT/Core、预占、墓碑和outbox。PAY intent为订单/阶段；IND为产线/工件/周期/阶段；MED为患者/就诊/医嘱组/阶段。route/template/随机op不创造新意图。PAY_TASK原Schema无max_inflight，原单TaskFlight槽位为1；Scene Task显式1。资源初始容量由C签`COMP-W-RESOURCE-v1`登记，不超过Profile上限。

W更新BEHAVIOR/UNIT/ENCOUNTER落w_mutable，保留a_current原C证书/genesis。每次核genesis、revision/StateRef；领取仅对自身before使用冻结覆盖重新derive，实际after/归属/Behavior汇总另核。来源/任务/资格无自变豁免。新阶段需受控登记；不自动复检/重置未知意图。

COMMIT后独立X只读原Core，核当前C认证KEY/EXECUTOR业务范围，签原kid/iat；W写锁下用RECEIPT_SIGN_GUARD及新RECEIPT_PUBLISH检查窗口/资格/原bytes。未形成回执仍COMMITTED/PENDING，不能claim。认证原请求只取原事实/补原Core；status/audit不补签。complete_receipt是内部受信恢复方法，不能作为公开免认证接口。

领取事务核dispatch_before、非自变deps/来源、审批/DENY、工具、scene_after及自己预占/flight，PENDING→STARTED生成唯一attempt/W签EXEC。确定失效pending可cancel释放自己占用并保留墓碑；未知不能取消。STARTED不能返回pending、取消或另派。

EXEC先持久消费一次资格，再调用一次工具子进程；标记与发送间退出可永远未知。重复execute_once不再调用工具。query从原packet取Action/attempt/ledger，附新query_id/30秒窗口并签`COMP-W-TOOL-QUERY-v1`；找不到=UNKNOWN，不执行/不签失败。工具公钥来自C证书，W公钥来自受信启动配置。绑定Profile/scope/op/AH/Action/COMMIT/Acceptance/ToolTrust/attempt/ledger_id/origin。

工具独立事务写dedup＋原PAY/IND/MED payload效果＋不可变FinalFact/序列，提交后在TOOL_FINAL_AUTH当前C事件签TOOL_FINAL及账checkpoint。新进程查询重新认证同事实，不新建效果/序列。FinalFactID不含新iat/exp/签名；RecordRef变化不重复结算。origin/high_water/head检测代表性账不连续，恶意整盘回滚/换钥长期认证后置。

W验当前工具证书/窗口、真实签名/绑定/checkpoint，保存观测但不结算。显式settle按同FactID一次更新资源spent/released、Flight、Behavior/场景终态。坏签名/错绑定拒绝输入；可信矛盾HALTED保留未决占用，不重派/补偿。status/audit先核当前H资格/读ACL，返回应用投影；完整R2 STATUS/AUDITBundle和通用Outcome序列化仍S/T包装，应用码不加原协议白名单。

P时间参数：单C全局seq、W持久floor、固定epoch1；总年龄≤2秒（mono≤1.975秒＋25ms）、区间宽≤2、健康偏差≤12.5ms。最终逻辑守卫在验签后更新年龄/hi并重核承重窗口。不是物理COMMIT完成瞬间、外部时间、跨epoch/主机连续性或机械完成期限证明。

计数：accepts/outbox/attempts/exec_invocations/execution_sends_observed/execution_sends_unobserved_upper_bound/queries/confirmed_simulated_effects/settlements/cancellations/halts。EXEC资格不是发送证明；未观察发送保留0..1界，未知确认效果0不表示确定没效果。独立payments/industrial_routes/medical_orders和不可变事实支持模拟效果计数。

运行`python -m competition.run_w_slice --output <new-directory>`导出公共W/工具账，再`python -m competition.verify_w_slice <directory> --manifest-sha256 <external-pinned-hash> --report <report.json>`只读核签名/Refs/绑定/计数。审计根须外部可信manifest pin；包内root只证明一致。不导私钥/SQLite，私有run在ignored.runtime。21组需完整覆盖才聚合；本纵切不是全21组或formal39 PASS。Linux DAC/HSM/真实设备/资金/医疗系统/动态组织治理后置。
