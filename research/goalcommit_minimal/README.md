# ZJJ-CORE / GoalCommit — 最小目标约束承诺（比赛版研究候选）

**定位**：保留 C-GoalRelation 唯一必要的特性：识别“局部合法动作耗尽完成目标所必需的最小资源”这一类可明确验证的错误；其余重心回到 ZJJ-CORE 的**密码学认证、状态版本、原子接受、一次派发与效果证据闭合**。

**这不是主仓库补丁，也没有接入生产 CommonW。** 当前文件是独立 Python + SQLite 契约实验。仅使用实验固定密钥和抽象账本；真实的 C.publish、Resolver、U/V/G 权限链、时间源、EXEC-0/工具账没有在这个原型中重做或测通。不能把该实验的测试通过当作正式 39 项符合性验收。

## 1. 本次主动删除/保留

| v3 组件 | 比赛最小版 | 理由 |
|---|---|---|
| Winning Region / 一般性可达性枚举 | **删** | 与已有规划/形式化验证框架重合度高；不需要再造规划器 |
| rank、严格下降策略、全模型独立审计 | **删** | 本轮无法形成新的密码学协议保证 |
| 全状态 Merkle 认证树 | **删** | 一个小型、有固定版本的签名约束包已满足本次用途 |
| 通用自定义状态转移 DSL | **删** | 防止业务规则和规划系统复杂化 |
| C 签署必要目标、资源预算、动作拥有者及依赖 | **留** | 保留目标约束的来源、含义及作用域 |
| W 对当前快照、共享资源、未知/在途做接受时检查 | **留** | 必须遵守旧 W 的线性化点与权限守卫 |
| 目标引用 → COMMIT → X Acceptance → E 原事实的哈希/签名绑定 | **留** | ZJJ-CORE 的密码学主线 |

核心判定函数 `evaluate_goal` **24 行**（含空行、注释），无需搜索未来计划。

## 2. C 发布的一份最小数据对象

`GoalFloor-v1 = (group, epoch, capacity, resource, deps, actions, model)`

- `group`：受信的目标和资源组 ID；跨 Profile 的真实共享必须由同一个 W 写者负责。
- `epoch`：C 发布版本，用于防重放/旧策略隔离。
- `resource`/`capacity`：统一预算/资源定义。测试模型固定使用一种资源，不支持多维度资源规划。
- `deps`：原 TaskRef、PolicyRef 等受信控制对象引用。更新后旧证书不得再接受新动作。
- `actions`：动作、Profile 归属、受信代价、该动作完成哪个必需项；空 `obligation` 表示可选动作。
- C 按固定域 `ZJJ-C-GOAL-FLOOR-v1` 签出 Ed25519 证书。没有新定义的密码学原语。

**注意**：实仓集成时 `actions.cost` 必须与当前 `self.plans.plan` 算出的 W 资源代价精确核对；本实验因为使用简化资源账，没有复现原业务 `plan`。Agent 不得提供受信成本或依赖版本。

## 3. 数学性质及其边界

对于二值的、单次完成的必要事项集合 \(O\)，定义其 C 认证的资源下界 \(c_i\)。在 W 原子快照 \(s\) 中：

\[
I(s)=\mathrm{SPENT}(s)+\mathrm{RESERVED}(s)+\sum_{i\in\mathrm{OPEN}(s)}c_i\leq \mathrm{Capacity}.
\]

W 对当前候选动作做投影检查：

\[
\mathrm{SPENT}+\mathrm{RESERVED}+\mathrm{candidateCost}+
\sum_{i\in\mathrm{OPEN}\setminus\{\mathrm{candidateObligation}\}}c_i
\leq \mathrm{Capacity}.
\]

如果候选是可选动作，则没有候选必需项需要从求和中排除。接受后在同一事务中把候选的资源从 `available` 移为 `RESERVED`，把候选必需项从 `OPEN` 改为 `PENDING`。因此，在**成本和状态受信且状态变更只走 W**的前提下，接受仍满足上述不变量。

这仅证明一个**必要条件**：没有把完成目标最少需要的资源提前占光。它不能证明动作顺序、外部环境、未来授权、未知结果或目标最终一定成功。 `PENDING` 代表尚未确认的原尝试，不得当作 `DONE`；需要结果时只能沿原 EXEC-0 / 查询原事实逻辑。`FAILED_CONFIRMED` 对不能重试的必需项会使本目标按原版本不可恢复，等待新的受信任务/补偿合同，而不是擦掉意图墓碑。

## 4. 密码学对象流（原协议接口的增量，不新造核心）

```
C   Task/Policy/Resource references ── C-signed GoalFloor
          ↓ canonical hash GoalRef
W   current dependency refs + current resource snapshot + ActionHash
          ↓ check old Guard ∧ resource floor (same SQLite TX)
      COMMIT {GoalRef, DepsRef, StateRef, ActionRef, CheckRef}
          ↓ commit_record_ref
X   original Acceptance signed over COMMIT reference
          ↓ original W/worker EXEC0 (not reimplemented in prototype)
E   original signed tool final -> W settle once, preserve UNKNOWN
```

不能误称“C 签名证明策略数学正确”，也不能让一个 `StateRef` 自己证明状态是最新完整账。**离线验证只能核对提供的对象和绑定，完整账本/时序/当期性必须由真实 W 断言和另行可信证明承担**。 

## 5. 测试结果

- `python -m unittest -v test_goal_commit`：**31/31 PASS**，包括：多 Agent 同组资源、跨 Profile 作用域、并发旧版本、超过目标资源下界、C 证书篡改与旧 epoch、C 依赖修订、W 接受后模拟崩溃与原 X 回执恢复、E 假签名与相互冲突终局、长期 `UNKNOWN` 保守等待、失败后拒绝、离线包篡改。
- `python run_demo.py`：枚举 **7,830** 种有限状态/动作组合，判定可接受的 **2,130** 种在本模型内均保持目标资源下界，发现违反下界 **0** 种。
- 独立离线证据包 `sample_evidence.json` 包含 C 认证 GoalFloor、W 接受前状态、判定见证、COMMIT、X Acceptance 和 E 终局；验证器能够复算关系、哈希引用和 Ed25519 签名。

### 对照：容量 3，两个必要目标各占 1，另有可选检查占 1

传统仅看当前容量的局部门控允许两个可选检查（总消耗 2≤3），导致必要目标资源不足。最小 GoalCommit 在接受第一笔检查后：

- 第二笔使用旧 W 修订号：`W_STATE_STALE`；
- 第二笔在重新读取当前 W 状态后：`GOAL_CAPACITY_FLOOR`；
- 第二笔拒绝不会新增操作、预留或接受日志。

工业、PAY 和**新增安全事件响应流程**均用同一最小约束检测规则进行测试，但这不是“工业完成路径”与“安全响应全过程形式化验证”。

## 6. 真正接入 ZJJ-CORE 的最小计划

1. **C 的固定 namespace**：比赛 schema 新增 `GOAL_FLOOR`（先 shadow，只针对明确启用的组），C 的 `TrustedState.publish` 沿旧的 `COMP-APP-C-PUBLISH-v1` / root 验证发布，保持同一控制源和修订机制。
2. **Resolver 不重写**：从原 Task/Policy/E 事实得到必需项和动作 ID；W 对当前资源、未决承诺和意图归属独立重算；候选不能自报 `GoalFloor`。
3. **W 原子接入**：在 `CommonW.accept` 已有 `self.guard.verify` / `self.plans.plan` / 资源账检查之后读取当期 C 证书和依赖；对 W plan 成本进行精确比较，再调用纯函数 `evaluate_goal`；其拒绝仍回滚既有 TX。
4. **COMMIT 引用**：沿已有 `Record_COMMIT` 的比赛版本视图增加 `goal_ref`, `goal_state_ref`, `goal_check_ref`（或一个结构化摘要字段），不改原 R2 上游 schema；X 按旧签署顺序引用冻结的 COMMIT，不增加多余签名角色。
5. **工具终局沿用原机制**：`EXEC-0`、同一 attempt、FinalFactID、`w_settlement` 和 `UNKNOWN` 一律使用原路径；GoalCommit 只消费这些事实，不声称创造新的工具安全保证。
6. **shadow 回归再启用**：对同一工件做旧 `completion_basis` 与新 `GoalFloor` 对照；展示性能/拒绝差异，跑三 Profile 正反例及正式 39 项（单独统计）。真实 PAY 与 MED 模型必须先定义明确的受信资源下界，不能仅换一个 Profile 名。

### 不做的东西

不做额外规划器、Z3/Dafny 调度、rank/Winning Region、全状态证明树、分布式共识、新的硬件信任根和复杂的通用指标语言。这些都不影响比赛核心密码学主线的最小展示。

## 7. 运行与离线复验

```bash
cd ZJJ_GoalCommit_Minimal
python -m unittest -v test_goal_commit
python run_demo.py
python offline_verify.py sample_evidence.json \
  --c-public '<from-fixture_public_keys.json>' \
  --x-public '<from-fixture_public_keys.json>' \
  --e-public '<from-fixture_public_keys.json>'
```

`fixture_public_keys.json` 是**隔离实验测试**公钥，不能因为它随证据一同提供就认定为独立可信。在真实评委离线复验中，公钥应提前从可信来源固定。

**论文/比赛声明口径建议**：可说“探索了一项 C 认证的必要目标资源约束，并将其与 W 的原子接受和签名证据链接合”；不可说“形式化保证任意 Agent 总能完成最终目标”或“提出新加密算法”。
