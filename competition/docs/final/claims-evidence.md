# 比赛声明与实际证据对应清单

2026-10-12 · 配套 `CORE-SPEC-1.3`。较早既有证据的构建提交为 `42021274a2f7d6adf35337bb153f05bf89b3e8f9`；本轮核对源码为 `1aa5a9e36e1558b95972941d5ce7dbf6553da431`，新检查另列。以下声明适用于受信单机、固定登记范围和三签名模拟工具；“已验证”始终附组件或具名端到端范围。

等级：**规则已定义**=精确合同/Schema 有规则；**组件已验证**=实际组件或入口拒绝验证；**端到端已运行**=真实共同 W、签名链和模拟工具账路径。受控篡改签名测试明确标识，不作为第二个真实效果。

| 可用于文书的声明 | 规则/实现选择 | 实际证据与准确等级 |
|---|---|---|
| 动作、来源、批准和执行请求绑定同一完整 Action | R2 AH/Ctx/Refs；固定来源映射是 Profile 规则 | [三场景 normal](../../evidence/w-slice-20261011-final/report.json)：端到端已运行；[场景绑定组件](../../tests/test_scene_authorization_adapter.py)核 defect 不能 RELEASE、患者替换拒绝 |
| 签名有效还须当前 subject/kid/角色/用途/业务范围有效 | 协议规则；固定 roster 为比赛实现选择 | [A 报告](../../evidence/authorization-slice-20261011-final/report.json)：三场景 wrong_subject/stale_source 等组件例，授权 T 不等于接受 |
| 缺必要复核的合法签名链被共同 W 拒绝 | 协议独立重算；所选工业 INSPECT、付款 FLAG、医疗强制复核 | [本轮六例](../../evidence/protocol-handoff-20261011-final/report.json)：三场景 common_W_missing_review，组件/共同入口已验证，0 新业务副作用 |
| 省略既有适用 DENY、承重依赖不能绕过 | 协议规则；C 完整范围＋W 单发布序为比赛实现选择 | [A hidden_deny / missing_dependency](../../evidence/authorization-slice-20261011-final/report.json)：三场景公共授权组件已验证；原拒绝码保留 |
| 工业、付款、医疗复用同一 W 接受和事务域 | 比赛实现选择，遵原规则 | [W 主报告](../../evidence/w-slice-20261011-final/report.json) 22 具名端到端例；[同 ID 三例](../../evidence/w-same-oid-20261011/report.json)各自 COMMIT/资源/FinalFactID 不串账 |
| 当前准备和接受可相隔至少 1 秒 | 原当前事件规则；单机 C 时钟实例/年龄为实现选择 | 各 Profile normal.actual.prepare_to_accept_seconds ≥1：端到端已运行；旧研究 TIME_CHANGED 预期不改 |
| 先持久接受，再签原冻结回执；恢复不二次接受 | R2 顺序；单 W 逻辑守卫和 X 只读签署为实现选择 | 各 Profile w_commit_crash：真实 exit97，原 COMMIT/Core/Ref 不变，1 接受，0 attempt/效果/结算：真实恢复已运行 |
| 资源、稳定意图和在途随接受一起受约束 | 协议规则；C 认证固定容量为实现选择 | IND same_intent8 / last_resource，真实事务已运行；三 Profile normal 各有独立资源/归属/结算账 |
| 唯一 attempt、一次 EXEC 资格；资格与实际发送分别计数 | EXEC-0 规则；本地先记资格后发送为实现选择 | 三 Profile concurrent_claim_settle / lost_ack；[发送边界回归](../../tests/test_w_final_regressions.py)：资格已耗但发送未观察时保留 0..1 上界 |
| 工具提交后丢应答只查询原 attempt，不新增效果 | R2 恢复规则；独立签名模拟工具账为实现选择 | 三 Profile lost_ack，真实 exit98/新 PID，原 effect/FinalFactID、一次发送与结算：端到端恢复已运行 |
| query 查不到保持未知和占用，不确认失败 | 协议规则 | 三 Profile unknown_query：原预占/Flight 保留，结算 0：端到端故障路径已运行；确认效果数 0 不作现实无效果证明 |
| 同事实新认证 Ref 不重复结算 | R2 FinalFactID 规则 | 三 Profile normal：跨秒得到不同 RecordRef、同 FinalFactID，一次 settle：端到端已运行；同钥认证，不扩称长期换钥已运行 |
| 坏输入拒绝；可信不可变事实矛盾停止 | R2 规则 | 三 Profile conflicting_final：真实路径＋显式受控工具签名对抗输入，HALTED、未决占用保留；未伪造第二个模拟效果 |
| 读取核当前资格且不产生接受/执行/结算副作用 | 协议读取原则；H 本地应用挑战为比赛约定 | W normal 读取前后计数相同；[本轮 authenticated_reads](../../evidence/protocol-handoff-20261011-final/report.json)三 Profile：正常 status/audit、重放 REPLAY、预签请求撤权 REVOKED；共同入口已验证 |
| 离线核验原签名、引用与独立 W/工具账 | 比赛审计方式；外部 manifest pin 为信任前提 | [重核 W](../../evidence/protocol-final-20261011-w-verification.json)：22 例/5168 项；[重核同 ID](../../evidence/protocol-final-20261011-same-oid-verification.json)：3 例/849 项 |
| 工业复检、正式 STATUS、长期工具换钥按精确合同定义 | 规则已定义；所选展示范围分别限定 | [工业医疗](../../../system_dev/v26/03_industrial_medical_profiles.md)、[核心 STATUS](../../../system_dev/v26/01_core_contract.md)、[终局恢复](../../../system_dev/v26/04_tool_final_recovery.md)；当前投影及同钥查询不作为这些完整端到端能力证明 |
| 当前签名链与回执采用明确的比赛应用语义 | R2 原字段/域保留，应用 deps、Review 受众、资格寿命及异常响应行为按[对应表](r2-application-mapping.md)限定 | [公共守卫](../../core/authorization.py)、[W 冻结 Core 与应用事务](../../core/common_w.py)、[场景当前资格](../../profiles/authorization_scene.py)及三场景 normal 原字节；规则/行为已核对，不作完整 R2 符合声明 |

## 文档层次与结果身份

共同规则采用 CORE-SPEC-1.3；[比赛开发总交接](scenario-integration-handoff.md)承载固定配置、场景规则与演示结果。1.3 只整理文档，不修改已验证代码或原证据；137 项回归与 13 项运行/72 次读取保持此前 1.2 构建身份。本轮文档与逻辑保留检查见[分层记录](protocol-separation-record-20261012.md)。

## 本轮新增证据

认证比赛标识、签署 caller proof、当前 W 依据和严格候选入口分别由[新回归与整改](rectification-results-20261012.md)支持。新签名链不是把旧包重新标版本；新的三场景正常与丢应答路径支持本轮端到端运行，签署/解析拒绝属于实际组件验证，完整流程及 72 次读取结果见[安全检查](../../evidence/security-rectification-20261012/report.json)。普通签名批准参照按同一链检验，结论只限定在有无永久业务意图账，不作为全部替代方案比较。

## 数字与材料身份

1.1 的新增接线规则及证据等级见[优化复检](optimization-review-20261012.md)：原观测与当前视图分开、阶段化原因、EXEC 消费决定重复执行边界；它们不新增签名响应或永久阻断功能。选定探索实验的事实摘要为[采纳依据](../../evidence/protocol-optimization-20261012/selected-experiment-facts.json)，不是一轮完整回归或签名状态证明。优化后新增的正常首次 EXEC、效果确认未结算、重复 EXEC 和结算后矛盾路径分别由[语义复核](../../evidence/protocol-optimization-20261012/runtime-semantics.json)支持，具体数字不与旧包合并。

- 既有 W 主包 22 例与同 ID 附加 3 例分别计数；本轮补充 6 例分别计数，不能写成原 21 组或正式 39 项全部通过。
- W 交接记录中的 124/124 竞赛测试、77/77 原回归是其原构建结果；本轮只重新运行选定相关验证，具体输出见[交付记录](finalization-record.md)。
- A 22 例是授权阶段证据：其 MED/PAY 输出没有业务提交账；最新 W 证据独立支持共同执行路径，不改 A 原报告的阶段说明。
- 历史研究中的局部模型、公开向量和预置事实只按原身份引用。所有已发现行为与已修复回归日志保留，不能通过删除失败记录改变结论。
- 本轮签名/账核验依赖受信运行根和既有来源文件，签名核对次数不等于执行次数。比赛协议正文不承诺真实银行、临床、设备效果，物理恰好一次或任何环境下绝对安全。

仓库整理说明：支持模块导入路径已迁移，既有检查按其原构建身份阅读；当前目录与新增验证见[整理记录](../../../REPOSITORY_SCOPE.md)。
