# ZJJ-CORE 安全协议：统一协议正文

**正文基线：CORE-SPEC-1.3（2026-10-12）＋ GoalFloor 最终集成（2026-11-24）。** 本文为当前比赛协议共同机制的统一规范，以原共同协议为基础增补经实验支持的目标必要资源下界、原子接受与密码学见证规则。原 [GoalFloor 集成原稿](goalcommit-integration-20261123.md)、[研究定论](../../../RESEARCH-STATUS-20261124.md)、[不变量原稿](../../evaluation/invariant_spec.md)及各实验记录保留各自内容与身份，作为溯源依据；它们不是另一个并行协议版本。原共同正文见 [2026-11-24 统一前 Git 快照](https://github.com/yumir3297/Cryptography-Technical-Competition/blob/77e760ef3e7fbdbd68c4492e86311c392e987d84/competition/docs/final/competition-protocol.md)。

本次为规范层的统一，不修改代码、消息标识、原 R2 合同或签名域。比赛消息标识仍为 `ZJJ-CORE-COMP-1`、字段基础版本仍为 `2.6`，新增 `GOAL_FLOOR` 与可选 COMMIT.goal 属于现有 CompetitionSchema 扩展，不宣称原 R2 正式合同已被替换或全部符合。精确消息字段和兼容差异见[消息与实现对照](r2-application-mapping.md)，具体业务规则、运行条件及验证范围见[应用开发交接](scenario-integration-handoff.md)。统一正文采用最终实验源码 `7f5dd03c404a9320dfebd4bcf0d87c8cd53e8a7c` 及审查基线 `77e760ef3e7fbdbd68c4492e86311c392e987d84` 对应的实现口径。

本文中“必须”指适用条件下的协议要求；“当前实现”指比赛应用的实际行为；实验通过不等于一般安全定理。GoalFloor 保证专指明确配置 enforce 的新接受，默认 off 与 shadow 不获得该保证。

## 1. 目的与信任前提

协议面向 agent 参与的高风险、高后果流程，将动作建议与执行权限分离。agent 提出候选动作，独立的受信核心验证身份、来源、批准、安全条件及执行约束，满足必要条件后才允许效果端执行。机制用于阻止未经授权、条件不满足、动作被替换或重复的执行，降低失控自动化造成的人员负担与后果风险。

信任前提包括 C 的登记与发布、E 的来源认证、W 的验证与持久账、受控签名者、效果端的持久状态，以及承载执行边界的运行环境和时间源。相应私钥和权威状态写权限只能由获准职责持有。agent 与调用者自报的公钥、角色、风险结论、依赖列表或成功标志不构成权限；候选内容作为数据处理，不能成为受信代码或执行入口。

签名证明登记主体认证了所绑定内容，不独立证明来源所述现实事实，也不代替人的业务判断。协议不承诺 agent 永不出错或免除人的责任。保证成立于上述信任前提与唯一受信执行入口之内。

在智能体连续自主提案的情形，仅对每一步验证签名、权限和当前资源余额仍不足以保护已确定的目标必要资源：单个合法动作可能消耗后续必要事项所需的资源。本协议扩展的职责是使 C 认证的必要资源下界进入 W 的同一接受事务，并使该次判定可经原有证据链复验。Agent 仍负责目标提出、推理和规划；C 负责认证必要事项及成本；W 负责确定性核验。目标可达性、初始规划正确性、最优路径、最终任务成功与否不属于协议职责。业务必要性和成本估计的正确性由受信约束制定方负责，签名只认证其来源和内容。

## 2. 角色与动作承诺

| 角色 | 职责 |
|---|---|
| agent | 基于获准信息分析、规划并提出候选动作 |
| C | 登记密钥、主体、角色、用途、范围、策略、当前版本和资源；认证并发布适用的 GoalFloor 与控制依赖 |
| E | 认证来源事实；其来源资格与业务范围独立核验 |
| H | 证明提交身份、持有关系和读取身份 |
| G | 依据验证链签发 Permit |
| U | 对具体动作给出必要 EXECUTE 批准 |
| V | 对受信推导的必要用途进行独立复核 |
| X | 认证挑战与已冻结的 Acceptance |
| W / worker | W 独立验证并记录接受、领取和结算，在 enforce 下检查适用 GoalFloor、原子预留并冻结见证；worker 凭当前职责触发相应步骤 |
| 效果端 | 验证原派发，固定执行事实并认证原尝试的查询结果 |

完整 Action 承诺 scope、operation_id、业务主体、H 身份及 kid、X、工具及版本、目的地和业务 payload。ActionHash 承诺完整动作；Basis、Assessment、批准、Permit、Challenge、CommitProof、COMMIT、Acceptance 和效果端请求通过 Ctx、Refs 与 AH 指向同一动作。动作字段改变须重新建立依据并取得相应签署，派发只使用冻结 Action。

签署请求须由对应登记角色证明持钥，绑定完整待签内容与 Action，并通过一次性 nonce、当前资格和窗口验证。密钥须同时满足登记、用途、角色、范围与版本条件。主体分离按登记 subject 判断：U 与 G/X 分离，必要 V 与 U/G/X 分离；H 与 U 可为同主体。每份签名独立核验，Ref 相同不能代替验签。

## 3. 授权条件与安全门

| 机制 | 规则与作用 |
|---|---|
| 来源与独立重算 | W 从当前认证对象及已登记业务规则重建 Basis、Assessment、required_reviews 与 RequiredDeps；输入自报的安全结论和删减依赖不能替代验证 |
| 必要批准与否决 | 每个必要用途须有精确绑定的 APPROVE，另须 U 的 EXECUTE；完整检查认证登记范围内的适用 DENY，后续批准不擦除既有适用否决 |
| 读取及业务资格 | 先核读取资格再访问敏感输入；签名用途、scope、主体及业务对象范围共同约束操作 |
| 当前性与时间 | 在各规定阶段重核来源、资格、依据和窗口；准备成功不缓存为接受或新领取权限 |
| 意图、资源与在途 | 按已登记规则确定稳定业务意图、资源用量和在途归属，在同一接受序列点检查并持久保存 |
| 目标必要资源下界 | enforce 下读取 C 认证的同资源活跃约束，以 W 账本及计划成本判定，禁止必要资源被新动作挤占；见 §3.1–3.6 |
| 冻结与唯一执行资格 | 原接受内容、回执和唯一 attempt 固定；恢复不能换动作或形成第二次执行资格 |
| 未知与可信矛盾 | 未决效果保留占用；已消费或无法确认消费情况时不重复执行；可信不可变事实矛盾停止推进 |

提交的承重依赖须与受信推导集合精确一致；直接依赖及传递承诺的承载方式由消息契约规定。否决适用范围绑定已登记的 Profile、完整 scope、operation、Basis 和用途，检查完整性依赖认证的初始范围与唯一发布序列。未知覆盖不能当作没有否决，新依据也不清除已接受业务意图。

安全门采用 T/F/U：全部必要条件确定为 T 才推进，F 或 U 均阻断本次推进。只有完整且可信的检查集合才能形成“有 F 则拒绝，无 F 而有 U 则暂缓”的聚合结论；顺序检查的首个阻断理由不能代替完整聚合结果。

时间窗口满足 `iat ≤ lo` 且 `hi < exp`。明确到期为 F，区间跨界或时钟无法确认时为 U；签署结束和各最终守卫仍须复核其窗口与时间见证。交互 nonce、来源观测、登记/策略版本、授权与派发窗口分别核验当前性，不能互相替代。

在已登记业务意图定义下，接受形成永久意图墓碑；更换 operation_id 或不改变意图的业务字段不能重新接受。取消和结算不删除墓碑，也不重置累计接受次数。资源不足、次数超限、在途冲突或归属不明时不能推进。

### 3.1 C 认证的 GoalFloor 对象

GoalFloor 是 C 发布的控制对象，不是 Agent 请求字段、授权消息或独立规划协议。命名空间为 `GOAL`，记录种类为 `GOAL_FLOOR`，record 的封装为 `{version, profile, kind, scope, value}`，其中 version 为 `2.6`，scope 必须与受信 Profile 一致。C 通过原有 TrustedState.publish 认证发布，其证书结构为 `{claim, signature}`，claim 包含 `profile, scope, namespace, key, previous_revision, record, active, enrollment`，签名字节为：

```text
canonical(["COMP-APP-C-PUBLISH-v1", claim])
```

签名算法 Ed25519，验签使用已固定的 C 根公钥。GOAL 的控制键由 Profile scope 前缀与 group 对应；控制记录按 namespace/key 具有独立单调 revision，发布须满足 previous_revision 与上一版本一致。读取当前记录须核 C 签名、active、scope、namespace/key、revision 与 RecordRef 的一致性。epoch 是 Goal 自身的业务版本，不应与控制 revision 混同。

| value 字段 | 约束与意义 |
|---|---|
| model | 固定 `goal-floor-v1` |
| group | C 定义的 Goal 标识，作用于同一 Profile |
| epoch | 正十进制整数字符串；更新须为上一 epoch + 1 |
| resource_key | 1–8 个符合 Schema 的资源键分量，允许大小写字母、数字、点、下划线、冒号和连字符；对应 W 资源账 |
| unit | UNIT / ORDER / CNY_MINOR |
| capacity | 正十进制整数字符串，接受时须与受信资源账容量相等 |
| deps | 1–16 条 `{namespace,key,revision,ref}`，仅 POLICY/TASK/INCIDENT；至少一条 POLICY；按 namespace/key 不重复 |
| actions | 1–64 条 `{name,profile,action_digest,obligation,cost}`；profile 一致，name 和 selector 不重复；非空 obligation 不重复且至少一个；cost 为正十进制整数字符串 |

非空 obligation 表示必要事项；空字符串表示不构成必要义务的规则。每个 Goal 自身所有必要事项的成本之和不得超过其声明容量，否则 `GOAL_UNREACHABLE_AT_PUBLISH`。此名称只表示必要资源算术不满足，不表示已经求解可达性。多 Goal 合计可能超过容量；在接受时由 W 统一核验。字段精确约束由 [CompetitionSchema](../../support/schema.py) 和 [validate_claim](../../core/goal_floor.py) 共同执行；包括资源键唯一分量、标识格式和受限整数编码。原完整示例保留于[集成原稿 §2](goalcommit-integration-20261123.md)。

### 3.2 动作匹配、哈希承诺与权威量

设 p 为 Profile，A 为冻结 Action，A° 为移除 operation_id 后的对象。A° 必须包括 scope、principal、holder、holder_kid、executor、tool、tool_version、destination、payload 九个字段。定义 D 为现有规范编码后 SHA-256、无填充 Base64URL 编码的 digest。现有 wire 对象使用严格 canonical JSON（对象键排序、紧凑 UTF-8、限制类型及深度；协议整数用十进制字符串）；精确算法见 [wire.py](../../support/wire.py)。

```text
ActionHash(p,A) = D(["ZJJ-ACTION-v1", "2.6", p, A])
Selector(p,A)   = D(["ZJJ-GOAL-ACTION-v1", "2.6", p, A°])
GoalRef(p,v)    = D(["ZJJ-C-GOAL-FLOOR-v1", "2.6", p, v])
RecordRef(r)    = D(["ZJJ-RECORD-v1", r.version, r.profile,
                     r.kind, r.scope, r.value])
```

Selector 与 ActionHash 不能互相替代。前者排除 fresh operation_id，使同一业务形状在更换操作标识后仍能匹配原约束；后者承诺完整动作和操作标识，继续约束授权、接受及执行。GoalRef 承诺 Goal 的 value；C 发布证书签名认证完整控制 claim，控制记录的 RecordRef 与 GoalRef 是不同域的引用。

Agent 不提供 Goal 选择字段，不能以自报 goal_ref、成本或义务状态替代受信选择。W 从当前控制状态枚举同 Profile 的活跃 GOAL，认证记录后选择与自身计划 resource_key 一致的全部 Goal。按 Selector 匹配其中的规则，不因候选未匹配某一 Goal 而排除该 Goal 的必要资源下界。匹配的 cost 必须与 W 计算的 plan.amount 一致；Goal 的 unit/capacity 必须与 W 资源证书及账本一致。C 签名有效本身不代替这些对象关系检查。

对于每个适用 Goal 的 deps，W 必须在接受事务中查当前认证记录并同时核对 revision 与 RecordRef；缺失/不可用为 `GOAL_DEPS_UNKNOWN`，版本或引用不同为 `GOAL_DEPS_STALE`。此新增依赖位于 GoalFloor 见证的独立 deps 字段，不改写原授权消息的 RequiredDeps 或 Acceptance.body.deps。Policy/Task/Incident 更新后，旧 Goal 不再作为新的有效下界凭证，须由受信 C 按版本规则重新发布。

### 3.3 必要资源下界的数学定义

固定同一资源域 (p,k)。令 K 为 C 认证且 W 核对的容量，S 为 W 的已消耗量 Spent，R 为预留量 Reserved，c(A) 为 W 的 TransactionPlans.plan 对候选动作计算的 amount。S、R 与对应 w_reservation 的 SPENT、RESERVED 求和一致；原资源上界为 `0 <= S + R <= K`。

令 G(p,k) 为适用的活跃 Goal 集合；每个必要义务以 (group, obligation) 唯一标识，cost(o) 来自其认证规则。令 M(A) 为候选 Selector 匹配的非空义务集合。令 O 为 G 中当前状态为 OPEN 的所有义务。定义：

```text
F(A) = sum(cost(o) for o in O if o not in M(A))
T(A) = S + R + c(A) + F(A)
Headroom(A) = K - T(A)
GoalFloorGuard(A) = T(A) <= K
                    AND 所有适用的对象、版本、状态关系合法
```

F(A) 即 RemainingGoalFloor。候选匹配的必要事项被排除出剩余下界，是因为本次候选成本已经计入 c(A)；未匹配的 OPEN 事项仍计入。DONE 不再计入 OPEN，PENDING 与 BLOCKED 依 §3.4 阻断，不作为可忽略的已完成事项。多个 Goal 对同一资源的 OPEN 必要成本保守求和，不做析取目标选择或全局调度；若同一候选同时匹配多个 Goal，其各自匹配成本都须等于 W 的候选成本，但候选资源预留仅计一次。

在接受时，enforce 要求原全部接受条件和 GoalFloorGuard 同时满足。对适用且通过的候选，持久接受使 R 增加 c(A)，匹配义务由 OPEN 成为 PENDING。因而在该接受转换中，接受前核对的剩余必要下界与新的占用不会超出 K。成功结算把该预留转为消耗，匹配义务 DONE；未知则保留占用，失败/取消转为 BLOCKED 并阻断后续适用接受。以上是**限定接受转换的资源必要条件**，依赖 C 约束正确、有效且 W 账一致，不是任意状态演化下的充分可达性定理，也不保证每一后续必要动作的业务授权、时间或环境条件均可满足。

### 3.4 义务状态、唯一性与治理

| 状态 | 含义与转换 |
|---|---|
| OPEN | 尚无对应义务的 W 链接；可在满足全部条件时接受匹配动作 |
| PENDING | 匹配动作已接受，未成功结算；包括待回执、STARTED、UNKNOWN 等情形 |
| DONE | 匹配动作经可信成功终局完成首次结算；不得重复接受匹配同一义务的动作 |
| BLOCKED | 已确认非成功结算或合法取消；不得自动当作成功或 OPEN |

对于同一资源的适用活跃 Goal 集合，任一必要事项 PENDING 则新的接受返回 `GOAL_PENDING_UNKNOWN`（不只阻止另一必要动作）；任一 BLOCKED 则返回 `GOAL_BLOCKED`。候选匹配 DONE 义务则返回 `GOAL_ALREADY_COMMITTED`。状态来自 W 的 w_goal 链接而非 Agent。shadow 允许观察重复链接，状态折叠优先级为 PENDING > BLOCKED > DONE > OPEN；enforce 建立 `w_goal_obligation_once` 部分唯一索引，约束 (profile,goal_group,obligation) 的非空义务，已有重复链接的账不能静默切换为 enforce。

C 更新同一 group 时，epoch 必须递增一，resource_key、capacity、unit 和非空 obligation 集合保持不变；删除或改名义务触发 `GOAL_MIGRATION_REQUIRED`。状态链接以 group/obligation 持久关联，新 epoch 不自动清空已存在的 PENDING/DONE/BLOCKED，不能把更新解释为重做或重置授权。改变容量或重置失败义务的通用迁移/治理尚未实现；不得以新 ID 或清库规避。

C 可以认证停用 Goal。若同一 Profile 任一 Goal 存在 PENDING 链接而其 C 记录不活跃或不存在，则 enforce 阻断该 Profile 的新接受（`GOAL_INACTIVE_PENDING`），即使候选使用不同资源；shadow 记录此差异。现实现明确保护 PENDING，不应扩称停用时所有 OPEN 或 BLOCKED 义务均被永久强制保留。Goal 停用不撤销已接受事实，也不改变原执行/恢复规则。以上治理以 C 可信为前提，并不对抗恶意 C 根。

### 3.5 模式与判定范围

| mode | 当前行为 |
|---|---|
| off | 默认兼容配置；不读取 GoalFloor，不产生 GoalFloor 见证，不宣称必要资源保障 |
| shadow | 计算适用下界并记录 COMMIT.goal，但不以 GoalFloor 的拒绝结果阻断原守卫允许的接受；可形成 F 见证 |
| enforce | 适用时要求 GoalFloor 决策 T，且原安全门全部通过；否则拒绝并回滚新接受 |

在无同资源适用 Goal 且无停用 PENDING 或控制加载错误时，扩展不适用，仍由原规则判定。当前实现先认证同 Profile 活跃 GOAL，控制记录加载失败时也保守阻断 enforce 新接受。不能把“已启用 enforce 但没有发布适用 Goal”说成存在具体资源下界；亦不能把 off/shadow 的 PASS 审计结果理解为 enforce 合规。模式由受信 W 初始化配置，不由 Agent 候选选择。当前协议不定义在线模式迁移/历史补造见证。

常见阻断理由包括 `GOAL_CAPACITY_FLOOR`、`GOAL_CAPACITY_MISMATCH`、`GOAL_COST_MISMATCH`、`GOAL_RESOURCE_MISMATCH`、`GOAL_UNIT_MISMATCH`、`GOAL_DEPS_STALE`、`GOAL_DEPS_UNKNOWN`、`GOAL_PENDING_UNKNOWN`、`GOAL_BLOCKED`、`GOAL_ALREADY_COMMITTED`、`GOAL_INACTIVE_PENDING`；发布/校验还可能拒绝非法 epoch、字段和迁移。具体分支以 [goal_floor.py](../../core/goal_floor.py)、[CommonW](../../core/common_w.py) 与 [TrustedState](../../core/trusted_state.py) 为准。这些是比赛应用原因码，不新增原 R2 正式签名 Result 类型。

### 3.6 与原授权门的关系

GoalFloor 不是替代 Permit、复核、DENY 或资源上界的第二个核心；它是同一 W 接受守卫上的必要附加条件。原权限链、意图、任务在途、来源、时钟、工具信任等条件仍须满足。任一失败即不得形成新的接受事实。GoalFloor 不为被拒绝动作签发新的执行权；其决策只限定接受时点，不是领取时重新计算所有目标，也不是对未来工具效果的承诺。

## 4. 接受与回执

1. 构造完整的认证依据、必要批准、Permit、挑战和持有证明。W 独立检查后可以返回短时准备凭据；该凭据不授予接受、占用或执行权。
2. 在接受序列点重验完整链、当前性、批准/否决、唯一性、资源和归属，并按 §3.1–3.6 执行适用 GoalFloor。全 T 才原子持久保存消费、意图墓碑、资源预占、在途、COMMIT、冻结 Acceptance Core、匹配义务链接及派发意图；接受前失败不形成这些接受事实。
3. 先固定 COMMIT 并求 RecordRef，再固定 Acceptance Core 与 Ref，避免摘要循环。accepted_at 表示最终受信逻辑守卫的 lo；持久提交形成接受事实，不将该时间解释为物理落盘瞬间。
4. 接受提交后，X 读取原 Core，在当前签署资格与原窗口内签署。保存回执前再核原字节、签名、资格及窗口；合法回执保存后才允许新领取。
5. 回执失败或资格失效保留已接受事实与占用。恢复只处理原 Core，不能换 kid、iat、exp 或 Ref；已保存回执返回原字节。提交应答丢失先认证查询原事实，超时不证明回滚。

### 4.1 同一事务与 GoalFloor 见证

在当前实现中，TrustedState.tx 的 BEGIN IMMEDIATE 将 C 发布、W 接受涉及的当前账及控制状态置于单一数据库写事务序列。CommonW.accept 在新接受分支认证 ticket/holder、重验原授权门、计算 W 计划、检查 intent 和资源账、读取并判定适用 GoalFloor、检查在途与工具信任及最终窗口，随后同一事务写入原 COMMIT 和业务账。匹配非空义务在 w_goal 记为 PENDING；原接受序号、资源预留、意图、派发账、义务链接与冻结回执核心一起提交。拒绝回滚本次接受事务，不增加这些业务接受事实；既有准备记录及此前合法事实不因此删除。原 operation_id 的幂等接受返回/恢复原事实，不进行一次新的 GoalFloor 接受或补造历史见证。

适用时，COMMIT.value.goal 是结构化见证，字段如下（字段与 [CompetitionSchema](../../support/schema.py) 一致）：

| 字段 | 含义 |
|---|---|
| mode, decision, reason | shadow/enforce，T/F，判定原因 |
| goal_refs, deps | 适用 GoalRef 集合及 C 依赖引用集合 |
| matched | 匹配项列表，含 group、goal_ref、epoch、action、obligation、cost |
| capacity, spent, reserved, candidate_cost | 接受前容量、支出、预留及 W 计划成本 |
| remaining_floor, total, headroom | §3.3 的 F(A)、T(A)、Headroom(A) |
| state_ref, check_ref | 接受时状态快照及判定内容的域分离承诺 |

状态承诺与正常 evaluate 判定承诺的精确构造为：

```text
StateRef = D(["ZJJ-GOAL-STATE-v1", {
  capacity: str(K), spent: str(S), reserved: str(R),
  statuses: sorted status rows {group, obligation, state}
}])
CheckRef = D(["ZJJ-GOAL-CHECK-v1", decision_object])
```

statuses 来自同一 Profile 的 W 链接状态折叠，按 (group,obligation) 排序；不存在的 OPEN 项由 evaluate 推导。decision_object 为 profile、decision、reason、capacity、spent、reserved、candidate_cost、remaining_floor、total、headroom、matched（canonical 排序）及 obligations（按 group/obligation 排序，含 group、obligation、cost、state、obligation_name），不含 check_ref 自身。控制加载、依赖、停用等提前失败分支使用源码规定的精简 F 见证承诺，不得一律按正常 evaluate 格式重算。

COMMIT 完整 RecordRef 在冻结 Acceptance 前计算；X 签署的 Acceptance.payload.commit_record_ref 绑定 COMMIT（含 goal、原 Action、授权引用、接受序号、时间与预留见证），无需新签名类型或把全部 Goal 字段复制入 Acceptance。密码学关系沿用：

```text
C 签名控制 claim -> 认证 Goal value / GoalRef 及依赖
冻结 Action -> ActionHash + Selector
W 账本与候选计划 -> StateRef / CheckRef / GoalFloor witness
完整 COMMIT（包含 goal） -> RecordRef -> X 签名 Acceptance
Acceptance Ref + COMMIT Ref + ActionHash -> W 签名派发 / attempt
工具签名终局 + 检查点 -> FinalFactID -> W 一次结算
```

任一改变已签名或已引用对象内容会使原签名/引用核验不一致，不能以复用原 Acceptance 认证改变后的 GoalFloor 见证。此为在规范编码、哈希抗碰撞、签名不可伪造、固定受信根与正确验证前提下的对象绑定关系，不是对 W 账本现实真实性的零知识证明。W 自身并未新增独立签名的资源账或结算行。

### 4.2 状态维度

| 事实维度 | 状态含义 |
|---|---|
| 接受 | 未接受或已持久接受；终态仍保留原接受及意图墓碑 |
| 回执 | 原 Core 待合法签署或已合法签署；不可补签不撤销原接受事实 |
| 派发 | 未领取、已领取、合法取消、已结算或可信矛盾停止；已领取不回未领取 |
| 效果 | 无原尝试、未确认、可信成功、可信确认无效果且不会迟到生效，或领取前合法取消的无效果 |
| 结算 | 原 FinalFactID 尚未结算或已一次结算 |

各维度不能相互替代。调用成功标签不等于效果已验证，效果已验证不等于已结算；停止状态仍可能保留此前的效果观测和结算事实。Goal 义务维度按 §3.4 独立记录，不等同于操作状态或原工具效果。状态字段及响应格式按消息与应用契约解释，不从异常或显示文字推断状态变更。

## 5. 派发与执行资格

新领取重新核 dispatch_before、当前来源、资格、批准/否决、工具信任、依赖及本操作占用。接受自身造成的业务状态变化按冻结后见证与归属核验；来源、任务和外部控制变化不获豁免。全 T 才原子领取并生成唯一 attempt，冻结原工具、ledger 和签名派发。重复领取只返回原领取信息，不重新产生执行权。

EXEC-0 要求每操作的首次执行资格至多消费一次：先持久记录消费，再调用效果端。领取后效果未确认不表示资格已消费；已认证确认原资格未消费、原派发仍通过守卫时，可以使用原 attempt 的首次资格。资格已消费或消费情况无法确认时不得重复 EXEC，只按可用权限认证读取原事实并查询原 attempt。消费与实际发送之间故障仍保留未知和未决占用；资格消费、实际发送和已确认效果分别计数。

效果端核完整冻结 Action、AH、operation、attempt、COMMIT/Acceptance、工具信任及原账绑定，将效果、去重与不可变终局共同持久保存。查询只读取和重新认证同一事实，不执行。

来源、资格、批准及否决的当前性检查在接受和新领取点形成相应保证。已领取的派发按原冻结绑定、权限和窗口执行，领取后新增撤销不保证阻止原派发。若要求撤销在效果提交前生效，须由效果端参与权威排序与检查，不能由一次发送前复验推定。

GoalFloor 的新增 guard 在接受时运行；当前领取实现沿用原 _claim_checks，不重新运行 _goal_context 或重算 GoalFloor。已接受动作的冻结见证、预留与义务链接继续存在；Goal 更新或停用不被解释为自动撤销已获接受的动作。后续派发仍必须通过原领取/执行约束。

## 6. 恢复与一次结算

未知可能涉及依据、接受提交或工具效果。通信失败、查询不到、日志缺失或读取权限不可用，均不能证明此前未接受、未执行或不会迟到生效，也不授予释放占用、换动作或重派权限。

只有确定失效且尚未领取的操作可按规则取消并释放自己的占用；已领取操作不因错误或超时回到可重派状态。确认无效果必须有可靠的无效果且无迟到效果依据；取消事实不能伪造为工具终局。

首次结算须验证终局认证、当前工具信任及窗口、原派发绑定、账连续性与占用归属，按原 FinalFactID 一次更新资源及在途。同一事实的重新认证即使签名、时间或 RecordRef 改变，也不重复结算。

匹配义务链接的状态更新与原结算事务一起提交：可信 SUCCEEDED 使预留转为 SPENT、链接转为 DONE；合法非成功终局使预留 RELEASED、链接转为 BLOCKED。领取前合法取消释放原占用并将链接置为 BLOCKED。无终局的 UNKNOWN 保持原预留和 PENDING，不重派、不新建义务链接；可信矛盾停止亦不得把未决义务当作 DONE。重复结算返回原事实，不重新消耗或重复转移义务状态。

坏签名或错误绑定的输入拒绝；经认证和绑定后的不可变事实矛盾使操作停止，保留账与调查证据，不自动重派、释放未决占用或补偿。普通归属拒绝只阻断本次调用，不能由抛错推断已经持久停止。

## 7. 查询、审计与消息契约

查询须认证读取主体、用途、范围和当前读取资格，并绑定原操作及相应接受事实。读取结果属于受信读取时点的状态；不能覆盖原签名对象或因读取失败将原接受、效果与结算改为失败。审计核对原认证对象、动作引用、接受、派发与结算事实，并明确证据根与完整性前提。

正式签名 STATUS/AUDIT 证据对象与经过身份认证的应用投影分别说明。认证调用不自动使返回字典成为签名协议响应；独立离线核验也不重新授予当前执行权。

当前 [离线验证器](../../evaluation/verify.py) 从公开证据包与独立渠道固定的信任锚核验 C 控制记录及历史、角色公钥、工具与资源证书、原授权链、COMMIT/X Acceptance、W 派发签名、GoalFloor、工具终局及结算。它不打开 W 数据库、不导入 CommonW，但复用 goal_floor.py 的纯 evaluate、selector、state_digest 逻辑；因此“独立”指脱离在线 W 运行环境，不表示第二套独立算法实现。独立参考模型与 Oracle 实验另行提供算法级交叉检查。

对于常规 GoalFloor 证据，验证器从包中的控制记录、资源账及义务链接重建适用集合、接受前状态和判定，核对 StateRef、CheckRef、GoalRef、依赖和算术；当前重建通过移除本操作的链接、扣除本操作预留或消耗得到前态，对本操作相关 INCIDENT 的结算后变化有专门处理。它不是任意历史状态的完备重放器；更广泛的历史快照、全部状态变迁或拒绝分支验证不从这些实验自动推出。无 Goal 见证而包中存在适用活跃 Goal 的情况返回 GOAL_WITNESS_MISSING。shadow 的 F 见证可以真实记录一次不满足 GoalFloor 的接受；审计 PASS 仅表明所检查的证据关系满足相应规则，不等价于 enforce 通过、实时资格或真实效果证明。

精确字段、编码及密码域引用[核心消息合同](../../../system_dev/v26/01_core_contract.md)、[终局与恢复合同](../../../system_dev/v26/04_tool_final_recovery.md)和[Schema](../../../system_dev/v26/contracts/)。当前标识及语义对应见[消息与实现对照](r2-application-mapping.md)；具体字段承载、内部接口、查询实现和已运行证据统一进入[应用开发交接](scenario-integration-handoff.md)。

## 8. 安全性质、研究依据与验证边界

以下表格将新增规范与实现、已记录证据逐项对应。实验统计以 [最终实验结论](../../evaluation/experiment_conclusions.md) 和 [最终验收](../../../FINAL_VERDICT.md) 为准；具体数据在 [结果索引](../../evaluation/results/README.md)，这里不生成新实验数字。原共同协议的既有保证、条件与证据等级继续适用。

| 统一正文规则 | 研究/实现来源 | 已记录的验证依据 |
|---|---|---|
| §1、§3.3：必要条件而非可达性 | [研究定论](../../../RESEARCH-STATUS-20261124.md)、[原集成 §1–3](goalcommit-integration-20261123.md)、[纯判定](../../core/goal_floor.py) | E1：20 条真实配对、112 个动作位置、20 个 off 接受而 enforce 拒绝的位置，Oracle mismatch 0；另 10,000 条独立模型序列 |
| §3.1–3.2：C 认证、Selector、版本及关系约束 | [TrustedState](../../core/trusted_state.py)、[Schema](../../support/schema.py)、[协议审计](../../evaluation/protocol_audit.md) | E3：15 个定向篡改/重放拒绝；合法证据包 PASS；容量、Profile、资源、旧依赖及 epoch 专项 |
| §3.4、§4.1：同一事务、唯一义务、资源与意图 | [CommonW](../../core/common_w.py)、[不变量原稿](../../evaluation/invariant_spec.md) | E2：40 条真实 W 并发历史均有合法串行解释；10,000 条独立参考模型历史、240,000 次转移，0 违反 |
| §4.1、§5–7：签名见证与端到端执行/恢复 | [核心贡献](../../evaluation/core-contributions.md)、[离线验证器](../../evaluation/verify.py) | E3、E4：3 个新增持久化崩溃边界通过，UNKNOWN 保留、停用保护及唯一索引专项 |
| §3.3–3.5：跨业务同构 | [跨场景实验](../../evaluation/experiment_conclusions.md) E5 | IND/PAY/MED 及复用 IND wire 的事件响应；PAY/MED 正常审计和挤占拒绝；并非四个官方 Profile 或真实设备 |
| §3.3–3.4：限定状态空间不变量 | [模型检查](../../evaluation/experiments/model_check.py) | E7：4,363 状态、67,746 转移、0 违反；有限模型结果，不是一般形式化证明 |

统一正文不宣称 Ed25519、SHA-256 或数据库事务本身为新原语；贡献在于 C 认证的必要资源下界、同一接受事务及已有密码学执行证据链的组合。性能 E6 为探索性测量，不构成安全条件。正式 39 项当前记录为 2 PASS / 0 FAIL / 22 PARTIAL / 15 NOT_RUN；原 Linux/WSL 实验的 526 项全量记录含 1 failure / 3 errors 且隔离复跑通过，后续主线 CI 结果属于不同构建身份，不能改写原实验。本次统一未新增实验、未改变最终 CONDITIONAL_READY 验收口径。

保证仅在受信 C/W/X/工具/时间源、密钥未泄露、正确认证与完整可用账本、唯一受信执行入口等前提下成立。协议不提供跨 Profile 原子性、任意多机共识、拜占庭 W、防整库回滚证明、长期工具换钥完整验证、真人法律同意证明、现实账本真实性、证据包完整性或当期性、生产设备效果和物理恰好一次。详细攻击者能力及未覆盖范围见 [威胁模型](../../evaluation/threat_model.md)、[协议边界](../../evaluation/protocol-boundary.md) 与 [剩余限制](../../evaluation/remaining-limitations.md)。

## 9. 规范与原始材料的追溯关系

- **本正文**：比赛共同协议统一语义；基础七章保持原有机制，新增章节以 2026-11-24 最终实现、实验与研究边界补齐。原 R2 合同、CompetitionSchema 与源码分别承担精确消息定义、应用扩展校验与实现职责。
- [GoalFloor 最小正式集成原稿](goalcommit-integration-20261123.md)：原始新增设计与字段示例，保留原文件，不删除、不重写。对其中“新 epoch”“新的必要动作”等容易被扩大解释的文字，本正文 §3.4 明确当前源码行为。
- [研究定论](../../../RESEARCH-STATUS-20261124.md)、[核心贡献](../../evaluation/core-contributions.md)、[不变量原稿](../../evaluation/invariant_spec.md)：研究职责、组合创新及测试依据，保持原记录。对于不变量原稿中较早的“无数据库唯一索引”描述，以本正文 §3.4 及最终源码的实际 enforce 部分唯一索引为准。
- [原 R2 对照](r2-application-mapping.md) 与 [R2 合同](../../../system_dev/v26/01_core_contract.md)：历史规范和应用差异保持原身份，本正文不把应用扩展写回旧合同。原始实验 JSON、证据包、源码、测试、图表及软件交接规范均不因本次正文统一而修改。
