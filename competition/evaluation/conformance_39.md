# 原 R2 官方 39 项语义符合性清单

清单来源：仓库 `system_dev/v26/semantic_cases.json`（`ZJJ-CORE-2.6-R2`，39 项）。本表逐项恢复原始 `id / scenario / expected`，不把原型 31 项、局部实验或本轮新增测试混算为正式 PASS。构建：`fcbc6b3b3ad63c9de84387c98bccc004f726a77b`。

状态口径：
- `PASS`：官方定义的完整语义已在本轮真实运行并保存证据。
- `FAIL`：真实运行发现可复现违例。
- `NOT_RUN`：未按官方完整定义运行；可能有局部组件测试，但不等于 PASS。
- `OUT_OF_SCOPE`：明确不在本作品范围。

## 总览

| 状态 | 数量 |
|---|---|
| PASS | 2 |
| FAIL | 0 |
| PARTIAL | 22 |
| NOT_RUN | 15 |
| OUT_OF_SCOPE | 0 |

**结论：2/39 PASS，0 FAIL，22 PARTIAL，15 NOT_RUN。** 这与原 `formal39` 报告“0/39 完整 PASS”的口径一致：本轮补齐了 GoalFloor 与离线审计，但没有把全部官方子变体、全部 Profile 和三场景正式证据闭合。不能把本表读成“39 项全部通过”。

| ID | Profile | 官方场景 | 官方期望 | 状态 | 本轮证据/缺口 |
|---|---|---|---|---|---|
| CORE-01 | ALL | 合法完整链，全部守卫 T | 唯一 ACCEPTED，原 COMMIT/Core/Ref 一致 | PASS | `test_common_w.test_three_profiles_share_real_acceptance...`、`test_full_chain...`、`test_cross_scenario_evidence`；三 Profile 各自唯一接受、COMMIT ref 与 X Acceptance 一致 |
| CORE-02 | ALL | 正文、Profile、scope、aud 或路径替换 | F 拒绝；0 新接受/0 派发 | NOT_RUN | 有 `test_evidence_verifier` 的 scope/profile 替换和 `CommonGuard` 绑定测试；未覆盖全部消息类型/路径矩阵 |
| CORE-03 | ALL | G 对漏一个必要 Dep 的 Permit 合法重签 | F 拒绝；独立重建检出 | PARTIAL | `test_common_authorization` 有依赖校验；未按官方完整子变体逐项运行 |
| CORE-04 | ALL | 同 Dep 键异 revision/ref，错 kind，引用环 | F 拒绝，不能从备用对象库找替代类型 | PARTIAL | `test_common_authorization` 局部；无完整递归图/环测试 |
| CORE-05 | ALL | 承重空集合新增记录、revision 回退或 A-B-A | 旧依据 STALE；重新准备 | PARTIAL | `test_goal_floor.test_dependency_revision_invalidates_goal` 覆盖 GoalFloor 依赖；未覆盖所有 W protected range/A-B-A |
| CORE-06 | ALL | 必需引用暂不可读/确认不存在 | 分别 U/DEFER 与 F/REJECT，无新接受 | NOT_RUN | 无正式 U/DEFER 证据 |
| CORE-07 | ALL | G 替代 U、Review 当 EXECUTE、U/V 同 subject 不同 kid | F 拒绝；独立授权/分离成立 | NOT_RUN | `test_common_authorization` 有 subject separation；未覆盖全部组合 |
| CORE-08 | ALL | 接受前事务故障与提交结果未知 | 前者整体回滚；后者通信未知不假造 DEFER | PARTIAL | 只测了提交后崩溃；提交前故障注入未逐点跑 |
| CORE-09 | ALL | 提交后签名失败/恢复/原钥撤销 | 原 Core/Ref 固定，不重接受、不换 kid；历史已存回执可验 | PARTIAL | `test_common_receipt`、`test_crash_boundaries` 有局部；未按三 Profile 完整语义逐项断言 |
| CORE-10 | ALL | 已存回执同 Core 坏 sig 或有效重签替换 Core | OBJECT_INTEGRITY 或 BAD_SIGNATURE，禁止直接返回 | PARTIAL | `test_common_receipt.test_uncommitted_or_modified_core...` 覆盖 PAY；未覆盖全部 Profile/读取路径 |
| CORE-11 | ALL | 同 nonce 同证明/异证明、同操作同动作/异动作 | 原响应/REPLAY 及 EXISTING/OPERATION_CONFLICT | PARTIAL | `test_common_w` 有 replay/nonce 局部；未做完整官方矩阵 |
| CORE-12 | ALL | 8 路同 intent 提交与共享资源竞争 | 至多一次接受/许可消费；容量不超限 | PASS | `test_w_acceptance_races.test_eight_distinct_valid_permits...`（8 路，容量 1）、`test_independent_intents...`；本轮并发实验另证 |
| CORE-13 | ALL | 领取前撤销、到期、跨期限区间 | 确定失效可安全取消；未知保持占用且不调用 | PARTIAL | `test_common_w.test_ownership_loss...`、`test_w_acceptance_races.claim_cancel_revoked` 局部；未覆盖全部期限边界 |
| CORE-14 | ALL | 接受自身 BEHAVIOR 变更、丢 reservation/flight 或错归属 | 合法自身变化不误拒；错误 HALTED 且不部分释放 | PARTIAL | `test_common_w` 有 `FLIGHT_OWNERSHIP`；未按官方全部子项运行 |
| CORE-15 | ALL | pending 取消与领取竞争、started 后进程故障 | 一个转换获胜；未知不回 pending、不重派 | PARTIAL | `test_w_acceptance_races.claimed_cancel8`、`test_crash_boundaries` 局部；未覆盖三 Profile 完整语义 |
| CORE-16 | ALL | 普通 SUCCESS、错 tool/kid/attempt 终局、相同/矛盾终局 | 未认证不结算；同终局一次结算；矛盾 HALTED | PARTIAL | `test_w_final_regressions`/`test_w_recovery` 覆盖 PAY；三 Profile 未完整逐项 |
| CORE-17 | ALL | STATUS 当前 H 换钥恢复，旧 Permit 已过期 | 当前查询授权成立可读原接受；无派发/结算副作用 | PARTIAL | `test_common_w` 有 status/audit 投影；未做换钥恢复场景 |
| CORE-18 | ALL | 相同业务意图跨 v2.5/v2.6、终态后重新登记 | 保留同去重事实，不能第二次接受 | NOT_RUN | 无 v2.5/v2.6 跨版本正式测试 |
| CORE-19 | ALL | 公钥持有证明替换 scope/purpose/期限/root 或 nonce 重用 | 只匹配原 pending 授权 tuple 可登记；不授业务 role | PARTIAL | `test_evidence_verifier` 验证 PoP；未覆盖全部替换组合 |
| CORE-20 | ALL | 同 subject 多 G/X 钥或服务换钥 | 只使用 POLICY 固定 kid；换钥新 POLICY 使旧依赖失效 | PARTIAL | 无完整多钥/换钥矩阵 |
| PAY-01 | PAY-1 | CLEAR、FLAG、INSUFFICIENT 合法路径 | 分别 0、ANOMALY、LOW_EVIDENCE Review，均需 FINANCE EXECUTE | PARTIAL | 现有 PAY 模拟链路只覆盖默认路径；未跑三路径完整子变体 |
| PAY-02 | PAY-1 | n=2，n=5 d=4，ratio 距离 1000、双时间边界 | 精确 history-int-v2 结果与 selected_cases 顺序 | NOT_RUN | 无此专项运行 |
| PAY-03 | PAY-1 | 重复 case_id/intent、候选自报 cutoff/风险结果 | F 拒绝；整快照先验，输出独立重算 | NOT_RUN | 无此专项运行 |
| PAY-04 | PAY-1 | 来源三事实 false、付款金额或收款人不匹配 | 硬 F，复核或 CLEAR 不能覆盖 | NOT_RUN | 无此专项运行 |
| PAY-05 | PAY-1 | 旧 Evidence 白名单以外类型/版本、原签名被删 | F 拒绝；原认证与新当前资格分别验证 | NOT_RUN | 无此专项运行 |
| IND-01 | IND-DEMO-1 | 三合成标签、错误 route、无 QUALITY_REVIEW | 严格映射；缺陷 RELEASE 硬拒绝；UNCERTAIN 需 V+U | PARTIAL | 默认 IND 链是 INSPECT；未跑三标签完整矩阵 |
| IND-02 | IND-DEMO-1 | 决策包检测器/预处理/mapper 混搭 | POLICY 包精确组合不等即 F | NOT_RUN | `bound_scene` 有包绑定；未做混搭专项 |
| IND-03 | IND-DEMO-1 | 接受后 UNIT 自变/外部证据更新 | 前者精确 scene_after 允许；后者停止派发 | PARTIAL | `test_w_recovery` 有状态保持；未做此专项 |
| IND-04 | IND-DEMO-1 | cycle1 INSPECT 成功推进/cycle2 INSPECT/未知推进 | 仅确认前终局受控推进；第二次人工留置；未知禁止推进 | NOT_RUN | 无二阶段复检专项 |
| MED-01 | MED-DEMO-1 | 必需 CLINICAL_REVIEW 与独立医师授权 | 精确批准集合，两 subject，不能 PAY CLEAR 免 V | PARTIAL | `test_med_required_review` 局部；未做完整官方矩阵 |
| MED-02 | MED-DEMO-1 | 换患者/就诊/模板/record 或同就诊新 group | 绑定/权限/稳定组拒绝；不能重建意图 | NOT_RUN | `bound_scene` 有绑定；未做完整子变体 |
| MED-03 | MED-DEMO-1 | 已知记录不可用/完整性不足、来源未知 | 已知 F 与未知 U 分别处理，普通 APPROVE 不覆盖 | NOT_RUN | 无此专项 |
| MED-04 | MED-DEMO-1 | 缺 READER、AUDITOR 读取患者详情、读权撤销 | 执行前已约束读取；裁剪审计；旧批准失效 | PARTIAL | `test_common_authorization` 有读权；未做 AUDITOR/撤销矩阵 |
| SC-01 | IND/MED | 300 秒证据边界、8 槽、累计 32 次 | 边界 T/F/U 正确；资源/次数拒绝，不 reset | NOT_RUN | 未跑 300 秒/8 槽/32 次专项 |
| SC-02 | ALL | 跨 Profile 重用签名/Record/Task/许可或路径 | 隔离拒绝，无自动降级 | PARTIAL | `test_chain_isolation` 局部；未覆盖全部对象组合 |
| AUD-02A | ALL | 工具已完成但首次 TOOL_FINAL 到达 W 时过期 | 原过期首证明拒绝；当前同账原事实再认证可以一次结算；不重派、不新增效果 | PARTIAL | `test_w_final_regressions` 有 final time gate；未按官方三 Profile 完整语义 |
| AUD-02B | ALL | W 首次结算前工具换钥，再认证改变 Ref 而效果事实不变 | C 核同账连续后当前钥再认证；同事实不同 Ref 一次结算，不 HALTED；矛盾事实 HALTED，原账不逆转 | NOT_RUN | 无工具换钥专项 |
| AUD-02C | ALL | 账丢失/查不到原 attempt，新工具 ledger 不同 | 未知保留预占；不得凭不存在签失败或用新账结算原账 | NOT_RUN | 无此专项 |
| AUD-02D | ALL | 坏签名/错绑定的矛盾包与真正可信矛盾 | 前者不改变操作账；后者 HALTED 且不自动解除 | PARTIAL | `test_w_recovery.test_bad_final...` 覆盖 PAY；三 Profile 未完整 |

## 与原型 31 项的关系

PR #12 `research/goalcommit_minimal` 的 31/31 与 7,830 个有限状态组合是**隔离原型**结果，不是本表任何一项的正式 PASS。本轮把 GoalFloor 的纯函数与 W 原子接受接入 CommonW，新增 18 项测试；这些测试用于 `INV-7`/`INV-8`，不改变 39 项官方状态。

## 下一步闭合 39 项的最小工作

1. 为 CORE-02..07、CORE-10..11、CORE-13..20 建立官方逐子变体脚本，三 Profile 全部运行。
2. 建立 PAY-01..05、IND-01..04、MED-01..04 的 Profile 专项运行，保留原始输入/输出/计数。
3. 建立 SC-01/SC-02 的时间/槽位/跨 Profile 矩阵。
4. 建立 AUD-02A..D 的工具换钥/账丢失/矛盾包专项。
5. 每项保存 `build_commit + run_id + 原始日志 + 证据包`，再由独立验证器复验。
