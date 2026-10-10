# ZJJ-CORE Competition Edition｜最终交付目标、剩余修复与本地端对齐规范

> **这是竞赛开发的优先阅读入口（对齐版 v1.0，2026-10-10）。**  
> **当前状态：TARGET / HANDOFF，不是已全部实现的承诺，也不是正式 R2 协议修订。**  
> 开发基线：`competition/zjj-core-final-20261010`，起始核对提交 `f5ace604034ff212a3ebba625ed394769cb0a13c`。  
> 研究基线：Phase 18 `3633db637c52bb0429c0b61af426d4c7eced5097`；时间研究 `afc00bd23e89c13487a6aa8a368b573c9a21f2df`。  
> 相关：[`competition/README.md`](competition/README.md) · [统一核心迁移设计](competition/docs/unified-core-migration.md) · [研究 PR #1](https://github.com/yumir3297/Cryptography-Technical-Competition/pull/1) · [竞赛 PR #2](https://github.com/yumir3297/Cryptography-Technical-Competition/pull/2)。

## 0. 一句话定调（本地端先确认）

**最终交付不是“三套各自能动的场景 UI”，也不是“生产级密码学新标准”；而是：一个真实验证签名、角色、必要批准/否决、可信时间、事务唯一性与执行审计的通用安全核心，通过三个真实 Profile 适配器，使工业 AI 质检、模拟交易和合成医疗授权分别完成可重现的真实软件闭环。**

优先级：**安全不变量不可降级 > 三个闭环确实共用一套核心 > 复现与展示质量 > 工程优雅 > 生产级扩展/科研全证明**。

这一文件的作用是与**本地 Codex/开发端对齐实现颗粒度**：先确认差异，再按验收证据推进；它不要求重新实现已经验证的 Phase 14–18 代码。

## 1. 我心目中最终观众应看到的成果（Definition of Done）

### 1.1 三场景同一入口、同一安全流程

演示程序可以是本地 Web UI + Python 服务/CLI；**不必为比赛部署到公网**。建议有三个页面 / tab，但三个按钮必须命中**同一个 CoreService/通用 W 核心代码路径**：

| Profile | 场景输入（可合成） | 一次正常操作的可见结果 | 业务差异只在 Adapter |
| --- | --- | --- | --- |
| `IND-DEMO-1`（主讲） | 设备/质检证据、任务、策略、候选分拣动作 | E 签名证据 → 审批 → W 验签及原子接受 → 有签名的派发 → 模拟产线完成记录 → 一次结算/只读审计；可展示普通路由与需质检复核的 `INSPECT` | 工业证据、路由映射、`QUALITY_REVIEW` 条件、模拟设备 |
| `PAY-1` | 订单、账户、行为/历史、风险评估 | 可信来源推导风险 → 需要的复核 → 外部 X 签名接受 → 一次模拟账户预留/付款结果 → 可核验模拟结算；**不接真实资金** | `history-int-v2`、`RequiredDeps`、`ANOMALY` 等所需复核、账户约束、模拟付款 |
| `MED-DEMO-1` | 合成患者就诊记录、合成医嘱 | E 证明来源 → **必要** `CLINICAL_REVIEW` → 授权 → W 原子接受 → 一次模拟医嘱登记/结算与审计；**不接真实医疗系统** | 就诊/医嘱绑定、临床复核、模拟登记 |

**同一个核心**不等于“把各 Profile 的不同业务事实硬编码为一个固定审核规则”。三套现有官方 Schema、Ref/消息域和场景定义继续分别严格验证。

### 1.2 建议演示的 5 个可见步骤（主讲工业）

1. **读取真实的合成输入**：给出数据来源 E 的签名、Profile/scope、当前 C 授权和策略版本。
2. **获得必要批准**：展示 H/G/U/X（V 在适用时）的实际 Ed25519 证明；点击“篡改签名 / 缺 REVIEW / 已有 DENY”能看到明确拒绝。
3. **安全接受**：展示 PREPARE 与真实流逝的时间；FINALIZE 在当前可核验授权状态下形成唯一已提交 COMMIT/Acceptance；超时/撤销/资源竞争时不留下接受副作用。
4. **工具执行与恢复**：向独立模拟工具发送 W 签名派发；故障模拟为“工具已持久化但 ACK 丢失”，重试返回**同一条**原工具事实，模拟效果计数保持 1。
5. **独立审计**：另一只读程序核验签名与哈希绑定、接受账、派发、工具账、结算账及拒绝原因；三场景均能下载/导出**不含私钥**的验证材料。

UI 展示内容必须来源于这些已写入数据库/签名的实际记录；不能以造假动画、预置成功 JSON 或仅前端计数代替协议执行。

### 1.3 交付包最少应该有

- **一套**可在干净 Linux/CI 环境运行的安全核心源码，三个适配器；独立 C/E/X/V/... 签名进程/服务和公钥 W（比赛可用 Linux DAC 受限签名器）。
- 一个本地演示入口（命令/页面）、三场景正向与负向示例、故障恢复示例、短录屏脚本。
- 自动回归命令、实验配置、输出证据目录、机器可读竞赛验收矩阵及只读审计报告。
- 竞赛说明文档（威胁模型、安全机制、创新性、业务对应、测试、限制），明确“真实密码签名 + **模拟**财务/医疗/设备效果”。
- 独立于竞赛矩阵的原 `research/formal39` 和原始官方三套 Schema/39 条语义规范；完整官方 PASS 不能被竞赛 PASS 替代。

## 2. 已经证实的现状（不要在交接时重复开发）

核对时间：2026-10-10；竞赛分支指向 `f5ace604`。公开 CI：[`38025278905`](https://github.com/yumir3297/Cryptography-Technical-Competition/actions/runs/38025278905) 三个作业均成功。

| 模块 / 能力 | 已有依据 | 严格状态 |
| --- | --- | --- |
| 工业 IND 最小模拟闭环 | Phase 18：25 阶段、Linux DAC 角色隔离、签名派发、工具 ACK 丢失恢复、1 接受/1 派发/1 结算/1 模拟效果 | **PASS_SCOPED**（固定实验时刻，不是生产证明） |
| MED 最小模拟闭环 | 竞赛分支：26 阶段，含 V 角色真实签名 `CLINICAL_REVIEW`，复用 Phase 18 签名隔离 + Phase 16 交付；新 E 来源绑定修复 | **PASS_SCOPED**（固定实验时刻、尚未共同 CoreService） |
| PAY 可验证接受 / RequiredDeps 复算 | Phase 15：外部 X 验签、风险审核、缺依赖/缺 X KEY/ROLE 拒绝、事务及模拟工具验收 | **PASS_SCOPED**（独立软件路径、尚未同核心集成） |
| 角色 Broker | `research/phase18/key_broker.py` 支持 IND/MED 固定角色与范围，并有 PAY X 的受限绑定 | **PARTIAL**；PAY H/G/U/V 尚未可信注册/接入 |
| 可信区间 / 不回退时间地板 | `competition/core/trusted_clock.py` 以及签名、超界、回退、重放/回滚测试 | **PASS_UNIT_ONLY**；尚未接入 Phase14/15 接受路径 |
| 真实时间 PREPARE→签署→FINALIZE | 旧路径要求时刻相等；`competition/tests/test_acceptance_gap.py` 证明跨 1 秒会被拒绝 | **BLOCKED**；旧拒绝测试通过**不是**新正向路径成功 |
| 独立竞赛三 Profile 服务 | 目前有复用实现片段 / 进程流水线；没有一个完整统一入口和同一 W 后端 | **NOT_IMPLEMENTED** |
| 原 39 项完整正式符合性 | 原始语义规则与 Schema 保留 | **0 FULL PASS / 39 BLOCKED_FULL_CONFORMANCE**，不可改写 |

**注意：** 曾有修改 Phase11 已固定文件而使正式验收报 `PHASE11_EVIDENCE_STALE_OR_CODE_TAMPER`；此问题已通过恢复历史文件并把新时间模块隔离在 `competition/core/` 解决。**本地端不得直接修改历史证据所绑定的 Phase11 代码来“修”时钟。**

## 3. 交付阻塞问题按优先级排列（要修到什么程度）

### P0-A｜非零延迟时间与接受顺序（全项目首要阻塞）

**现象**：Phase14/15 的签署提案基于 PREPARE 时刻生成，FINALIZE 却要求相同时间；真实经过几秒就不能成功。仅删除 `TIME_CHANGED`、将时钟 tolerance 改为 ±N 秒、把签名回填成旧时间，均不属于正确修复。

**比赛所需最小修复**：

- PREPARE **只生成不产生业务权限/预留的 ticket**，其时钟只证明准备检查发生的逻辑点。
- FINALIZE 以**新鲜且 C 认证的当前时间区间**、当前依赖/角色/权限/撤销/DENY/资源状态决定；受保护 W 事务确定要冻结的 COMMIT、接受事实与唯一性槽。
- X 必须对**精确最终提案**签名，W 严格验签、核签名时钥/角色资格及有效窗口，签署失败或不可确定时**不得产生接受/派发副作用**。
- 明确 **R2 实际接受点、原签名发生点、W 持久提交点**三者各是什么，以及授权时效究竟在哪个点受保障；不能将“已签署”偷换为“已提交接受”。
- 签署或提交之间若发生资格变更/时钟不确定/源数据变化，必须受同序隔离/版本栅栏/重验约束。签名器 RPC 有有界超时，长事务和时钟样本过期时拒绝/安全重试；未知提交结果须**先查询永久状态**，不能当未提交重新执行。
- 实现隔离的受信时间 Provider，保留有效范围的 lower-floor/replay/unknown 处理；测试中要有真正推进的时间，而不只手填两个相等常数。
- **新研究候选 `06_time_observation_candidate_contract.md` 只能作为独立历史观察思路参考**，不可在 R2 Result/Acceptance 中偷偷替换原对象。若原 R2 时序无法在现有精确合同下满足，要显式提出最小版本化竞赛扩展与兼容边界，不能伪称 R2 正式完全符合。

**P0-A 出口**：工业至少一次 **PREPARE 和 FINALIZE 的 C 认证时间严格不同（≥1 秒）仍正常被接受并安全派发**；时效失效、签署间撤销、时钟 U、过期 ticket、资源竞争、提交 ACK 丢失均有负向/恢复实验；账本只有一个事实。随后这套接受语义要在 MED/PAY 复用，不各修一版。

### P0-B｜拒绝/必要批准/依赖不能靠省略绕过

最低要求：

- W 独立根据可信 C/E 状态 **重算 RequiredDeps 和 required_reviews**，禁止直接信任 Permit/COMMIT 上传的 deps/review 数量。
- IND：`INSPECT` 必需 `QUALITY_REVIEW`；其他演示路由依现有策略。MED：`CLINICAL_REVIEW` 必需。PAY：按认证历史风险（`history-int-v2` 等）推导，包括必要异常审核，不能让 H/G/U 合谋从提交件里删掉。
- W 搜索**既有、适用、完整的 DENY/否决历史**；同一事实既有 DENY 即使其他签名都合法也应拒绝；历史缺失或认证源不可用时 `U`/fail closed，不能把没查到视为“没有否决”。
- 必要批准的**角色、kid、授权 purpose、scope、审计时序、合法窗口**必须交叉验证；错误角色签名不能由于 Ed25519 数学上正确就被接受。

**P0-B 出口**：至少每个 Profile 一组“合法签名但遗漏必要批准 / 依赖 / 既有否决”负向用例，均核对接受/预留/派发/模拟效果增量为 0；PAY 必保留 Phase15 已有缺依赖与风险审核回归。

### P0-C｜事务一次接受、执行一次效果、可核验审计

- 一个 W 原子提交保护操作/意图/nonce/尝试去重、资源与行为状态、接受记录、永久墓碑和审计，不允许多次接受或部分更新。
- 已接受→派发的资格与 `dispatch_before` 仍独立检查；工具/模拟账端也校验来自 W 的签名、精确 Action/attempt/ledger 绑定。
- W outbox 和工具 `attempt` 幂等：并发重复和恢复重传仍仅记录 **1 个模拟事实**。工具已提交但没回应时不能反复产生业务效果。
- 不明结果区分 `ACCEPTED`、`EFFECT_UNKNOWN`、`SUCCEEDED`、`FAILED_CONFIRMED`、`HALTED` 等已定义状态，不能全部显示“失败可再执行”。
- 另一个只读审计过程校验原始签名、COMMIT/Acceptance 精确引用、工具账、结算账和数字计数；日志/截图不能替代受信账本。

**P0-C 出口**：三个 Profile 都有正常执行 + 强制故障后幂等恢复 + 并发重复请求 + 独立审计，且 W 接受/派发/结算各最多一次、工具模拟效果至多一次（正常正向场景恰为一次）。

### P1-A｜真正复用一个通用 CoreService（不能只代码目录看起来通用）

目标拓扑：

```text
Demo Web / CLI / automated regression
               |
            CoreService (唯一共用的安全流程入口)
               |
    +----------+----------+
    | public verifier / role-policy / C clock |
    | trusted source & RequiredDeps / DENY    |
    | W transactional accept + durable outbox |
    | tool result settle + read-only audit    |
    +----------+----------+
               |
        ProfileAdapter registry
        /        |          \
 IND-DEMO-1    PAY-1     MED-DEMO-1
  industrial    payment     medical
  state/tool    account     order/encounter
  approvals     risk        clinical review
               |
   Separate signed simulated tool gateways
```

**统一接口建议（可按代码适配重命名；行为必须一致）**：

```python
CoreService.prepare(profile, request, trusted_sources) -> PrepareTicket
CoreService.finalize(ticket, authenticated_time, x_signer) -> AcceptedFact | Reject | Defer
CoreService.claim(profile, operation_id, attempt_id, authenticated_time) -> DispatchFact
CoreService.deliver(profile, dispatch_fact, tool_adapter) -> SignedToolFact
CoreService.settle(profile, signed_tool_fact, authenticated_time) -> SettlementFact
CoreService.audit(profile, operation_id) -> AuditBundle

ProfileAdapter.validate_action(action)
ProfileAdapter.resolve_required_deps(trusted_snapshot, action)
ProfileAdapter.required_approvals(trusted_snapshot, action)
ProfileAdapter.resource_rule(action, authoritative_state)
ProfileAdapter.tool_simulator()
```

本地代码可以保留 SceneW/PayW 不同**业务存储实现**作为后端适配，但共用同一安全决策入口/同一状态契约和同一 W 事务/去重逻辑；**不能**只加一个 if/profile 调用三套彼此独立的旧 `accept()` 然后宣称统一核心。

建议业务与安全共用接口明确包含：`profile`、`scope`、`operation_id`、`attempt_id`、`trusted time interval`、`control/source revision`、`refs`、`decision`、`audit/provenance reference`。整个流程中 `Reject` / `Defer` 与永久接受事实必须可区分。

**P1-A 出口**：三 Profile 同一 `CoreService` 类/协议实现（至少同一验证、接受与工具交付组件）运行集成用例；业务差异存在适配器测试，故意绕过公共 guard 会失败；移除某个 Profile 不影响其他 Profile。

### P1-B｜签名器及工具端通用化

- 继承 Phase18 受限 Ed25519 broker；角色/用途/消息类型/issuer/kid/scope/Profile **由受信登记约束**，不得由调用方随意选择。完成 PAY H/G/U/V 的可信 roster/授权，不允许靠放宽 `ALLOW_DOMAINS` 实现“支持三场景”。
- W 只保留公钥与专用 W→Tool 交付私钥；C/E/X/V 等的权威私钥不交给 W。Linux DAC 可作为竞赛可核验分离方案；明确 bootstrap/sudo 管理员仍为集中信任前提。
- 既有 Phase16 工具 outbox/网关支持 MED；继续把 PAY 接到同一可校验派发/故障恢复契约，三个模拟工具都须能做原子去重。
- 使用新的、逐次运行生成的实验钥匙；禁止提交任何 `.key`、配置 secrets、完整私钥 trace 到 Git。任何 C/E/X 依赖须是真签名验证，不接受“签名字段非空”。

**P1-B 出口**：三个 Profile 的跨角色/跨 Profile/错误 scope 拒绝、真签名正向、W 无法读取权威私钥的权限测试均有可复现实验；PAY 走实际工具签名与模拟原子账，而不是 Phase15 自己的独立捷径。

### P2｜统一演示、文书和安装复现

- 主展示工业，可在同一个 UI 快速切到 PAY/MED；显示“数据、角色、批准、Decision、COMMIT、派发、工具事实、审计”真实证据链。
- 负向按钮至少覆盖篡改签名、缺审核/既有否决、超时/撤销、并发/故障；**不需要**给每项造漂亮动画。
- 一条脚本从干净环境创建测试身份/数据库、运行三个场景、做负向验证、输出 `competition_evidence/report.json`、`competition_evidence/matrix.csv` 和完整可审查的**脱敏**证据包；CI 可直接复现。
- 文书写清：协议核心机制、三个适配器、对比无安全门时的危险、可重现攻击/拒绝实验、真实限制。不能把模拟结算说成真实银行交易或把合成医嘱说成临床诊疗。

## 4. 建议的最小竞赛验收矩阵（独立于原 39 项）

每项应包含：`case_id / profile / setup / input mutations / expected / actual / trace_ref / CI commit / status / limitation`。状态仅用 `PASS`、`FAIL`、`BLOCKED`、`NOT_RUN`；旧研究证据最多注明 `PASS_SCOPED`，不能自动升级。

| ID | 检查项目 | PASS 的最低证据 |
| --- | --- | --- |
| C-CORE-01 | 三 Profile 真正走同一入口、同一授权/提交 guard | 调用轨迹 + 组件相同代码位置 + 完成签名/资源/接受状态 |
| C-CORE-02 | 正常授权 | 各场景 1 ACCEPT / 1 DISPATCH / 1 SETTLE / 1 **模拟** EFFECT |
| C-TIME-01 | PREPARE→FINALIZE 实际非零时延 | C 时钟签名区间不同（≥1 秒）、最终 COMMIT 时间正确、独立验证成功 |
| C-TIME-02 | 到期、时间回退、过宽区间/无可信源 | 明确拒绝或 DEFER；无非法接受和效果 |
| C-TIME-03 | 签署阶段撤销/控制 revision 竞态 | 完整受信当前性栅栏 + 无非法 COMMIT |
| C-AUTH-01 | 篡改任意核心签名 | 真实验签拒绝；账本计数无变化 |
| C-AUTH-02 | 错误 kid / role / purpose / scope / profile | 验证失败且不可跨 Profile 代理签署 |
| C-AUTH-03 | 必要审批缺失（IND INSPECT、PAY 风险、MED） | 各 Profile 负向；既有有效签名不能补掉缺项 |
| C-AUTH-04 | 已有适用 DENY，且提交批准已签名 | 查受信持久历史拒绝；不能靠删掉 DENY 输入绕过 |
| C-DEPS-01 | RequiredDeps 被合法签名者删改 | 从受信源独立重算，拒绝缺项 |
| C-DEPS-02 | C/E 证据撤销、源变更或依赖 stale | 当前性复核拒绝，无错误预留 |
| C-STATE-01 | 资源竞争/操作/nonce/intent 重放 | 最多一个原子接受，资源/行为计数不漂移 |
| C-EXEC-01 | 工具拒绝伪造 W 派发、错 attempt/ledger | 模拟效果增量 0 |
| C-EXEC-02 | 工具写账后丢 ACK，再恢复 | 返回相同原工具事实，模拟效果总数 1 |
| C-EXEC-03 | 并发/重启重复派发、结算 | 无第二次派发资格/第二次模拟效果/第二次结算 |
| C-AUD-01 | 只读独立归档审计 | 核验 Ed25519、Refs、COMMIT、Acceptance、派发、工具及结算；发现篡改 |
| C-COMP-01 | 原 R2 合同/39 用例与旧证据保护 | 固定文件字节/hash 不变，原 runner 不被修改或虚报 |
| C-DEMO-01 | 统一演示与一键复现 | 净环境脚本 + 三 Profile 实际运行 + 报告一致 |

**冻结门槛：** 所有 P0 对应验收项必须 `PASS`；全部三场景的 C-CORE-01/02、C-EXEC-02、C-AUD-01 必须 `PASS`；竞赛演示脚本可复现。不能以“单元测试数量很多”替代其中任何一项。非关键 UI/额外异常矩阵可以更轻。

## 5. 实施顺序、预计修改文件及每波“停工条件”

| Wave | 必须交付的代码/文档 | 只有达到此条件才进入下一波 |
| --- | --- | --- |
| **W1 时间闭环（P0）** | `competition/core/trusted_clock.py` 接入新 W；新的 FINALIZE/签署接口（**在竞赛目录**，避免覆写 Phase11）和故障回归 | IND 跨秒正向 + 过期/撤销/资源竞态反例，原工业 25 阶段不回退 |
| **W2 公共安全门（P0）** | TrustedSource/Deps/DENY 与 Role/Policy 验证共用组件；先 IND/MED 后 PAY | 三 Profile 均不能通过漏必要审核、漏已有 DENY 或缺 RequiredDeps 绕过 |
| **W3 三场景同核运行（P1）** | `CoreService`、三个 ProfileAdapter、Broker/PAY 角色与统一 outbox | IND、MED、PAY 用同一入口签名接受/派发/模拟结算；每个至少有一正一负实验 |
| **W4 最终证据与展示（P1/P2）** | `competition/tests`、独立 audit、CI、证据导出、UI/CLI、写作 | 竞赛矩阵达冻结门槛、干净 Linux/CI 一键复现、私钥不泄露 |

可并行：W1 期间本地端可以做与接受内核隔离的 UI 框架/场景资产，**但不能假装 UI 已证明安全闭环**。可保留现有 W 表/工具账/fixture，采用 adapter 包装；先做薄切口测试，再迁移，不大规模推倒重写。

### 当前建议首先动手的最小文件集合

1. **新增** `competition/core/acceptance.py` / `competition/core/service.py`（接口名可协商）：最终时间、签署/事务顺序、安全门；
2. **扩展** `competition/core/trusted_clock.py`：确保真实时间 Provider 和接受点可信绑定（当前仅单位测试）；
3. **复用/适配** `research/phase14/verifier.py`、`research/phase15/pay_accept.py`、`research/phase16/industrial_delivery.py`，不直接破坏旧研究语义；
4. **扩展** `research/phase18/key_broker.py` 或提取为 `competition/core/signer_broker.py`：完成 PAY 受信签署 roster；
5. **新增** `competition/tests/test_elapsed_finalize.py`、`test_cross_profile_guard.py`、`test_exactly_once_audit.py` 和三 Profile 流程入口。

以上是**责任边界清单，不是强制文件名设计**。本地端如果已实现更合适的接口，优先比对行为契约和 CI 证据，不机械重构。

## 6. 现在明确**不做**的事情（避免过度开发）

- 不以 39 条原始完整官方 PASS 为竞赛冻结前提；**不**删改其任何一条。
- 不建设真正银行清算、真实病历系统、真实产线机器人或证明物理世界恰好执行一次。
- 不部署生产 HSM/KMS、多机构独立治理、跨机房强一致共识、多租户商业 SaaS、完整公网 mTLS 基础设施（可在限制中说明）。
- 不引入新的自创密码学原语来替代已用的 Ed25519 和 SHA-256；不为了论文增加海量形式化证明。
- 不在当前流程混用研究候选的 `AcceptanceObservation` 和原 R2 `Acceptance`，不伪称协议原版严格兼容。
- 不追求全部 UI 视觉设计完善后再解决内核；先实现实际证据链。

## 7. 必须保持的信任边界与真实性说明

- 当前 Linux signer 使用专有 OS UID / 0600 文件证明 DAC 隔离；**bootstrap 曾见全部密钥，sudo runner 可调用 broker，签名器尚不自行决定完整业务授权**。不得宣传为 HSM 或完全独立治理。
- C 的时间签名是实验性认证时钟，需要独立验证提供时间样本的可信性、实际覆盖事件、窗口和新鲜度；**签名正确 != 真实世界时间正确**，单独 monotone floor 也不证明样本不是旧的。
- W/工具签名和 SQLite 唯一账证明的是**模拟效果唯一**；不是外部银行/物理设备/医疗动作准确发生。
- 受信历史账若丢失不可恢复且没有独立防回退锚，就不能声称任意崩溃都能辨认真实的历史尾部；比赛可以在明确的单节点持久化与可检查故障模型下验收。
- 对最终不可完成的正式 R2 义务，应标 `BLOCKED` 并写清原因；与竞赛闭环成功并不冲突。

## 8. 给本地 Codex 的对齐指令（可直接复制）

> **目的**：与云端竞赛版对齐开发粒度，不立即重写协议。  
> 请先拉取远端 `competition/zjj-core-final-20261010`，阅读仓库根目录 `00_COMPETITION_FINAL_DELIVERY_SPEC.md`、`competition/README.md` 及 `competition/docs/unified-core-migration.md`，对比你本地当前的分支/未推送提交/未提交工作区。不要覆写本地未提交内容，不要合并研究 PR #1，不要修改原 Schema 与 39 项规范。  
> 输出一份**逐项差异表**：模块、远端已有实现、本地已有实现、差异等级 `MATCH/PARTIAL/MISSING/CONFLICT`、证据路径、下一步最小改动、风险。重点核对真实时间 FINALIZE、DENY/RequiredDeps 全历史、PAY 角色 Broker、公共 W/Tool 接口以及 IND/MED/PAY 同一 CoreService。  
> 每项明确区分 **PROTOCOL_GAP（规范不闭合） / CODE_BUG（实现错误） / TEST_LIMIT（实验环境） / POST_COMPETITION（生产增强）**。先列 3–5 个最小代码 PR（带通过条件）再施工。现有 25 阶段 IND、26 阶段 MED 与 PAY Phase15 局部证据不得倒退；用新竞赛矩阵验收，原 39 项完整 PASS 状态不得冒充。  
> 对真正时序冲突，先列旧 R2 约束与候选扩展差异、定义可被测试的接受线性化点、签署者资格与失效行为，再落地；不得通过去掉 TIME_CHANGED 或回填旧签名时间让测试假绿。  
> 回传你目前 HEAD SHA、本地修改摘要、已经能跑的测试及真实失败项，我们再按同一颗粒度决定下一项。

### 本地回传的最小对齐表

| 项目 | 本地现状（填） | 远端/目标 | 差异等级（填） | 证据或阻塞（填） |
| --- | --- | --- | --- | --- |
| 分支/HEAD/未提交代码 | | `competition/...` | | |
| 跨秒 FINALIZE | | 非零时延正向 PASS | | |
| C 时钟可信性/rollback | | 当前竞赛独立时钟已单测，待 W 接入 | | |
| IND RequiredDeps / INSPECT 审核 / DENY | | 每一项受信派生与负向验证 | | |
| MED CLINICAL_REVIEW / DENY | | 26 阶段旧正向 + 新的真实拒绝用例 | | |
| PAY 风险/RequiredDeps/角色 Broker | | Phase15 证据保留，迁入共同代码 | | |
| W 原子接受/nonce/资源 | | 同一守卫 + 崩溃/并发单事实 | | |
| W outbox/ToolGateway/幂等 | | 三场景复用单事实机制 | | |
| 只读审计、私钥隔离与原39资产 | | 三 Profile 验证/不泄钥/不误报 | | |
| UI/一键复现实验与文书 | | 可证据驱动的最终交付 | | |

## 9. 最终冻结判断（最短版本）

**可以提交竞赛**：三场景真实调用同一套安全门，签名/角色/时间/依赖/否决都实际检查；每个场景有正常 1 次模拟执行与违规 0 次执行证据；跨秒 FINALIZE 正常运行；故障重试不会第二次效果；独立审计可复现；原研究资产未被改动；文书如实披露模拟与信任边界。

**暂不能提交为“最终完成”**：只有 IND/MED 旧固定时间闭环、PAY 单独一套软件，或者靠 UI 假动作/删检查/回填时间绕过核心协议安全性。

**下一步唯一最高优先级：W1 的非零时间 FINALIZE 接受闭环。** 其他分支工作不得为赶进度牺牲安全门；先与本地端对齐差异表，再锁定最小修复 PR。

---
**版本约束**：本文件是一份可迭代的比赛交付规格/对齐清单；每次重大变更应更新版本与对应提交、运行证据。**不反向修改或宣称覆盖** `research/protocol-time-closure-20261010` 的条件研究结论与 `research/zjj-core-phase13-handoff-20261009` 的正式历史研究证据。
