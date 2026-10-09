# Phase 16 — 工业 AI 执行交付边界（实验版）

**定位：** 面向工业 AI 质检/放行建议的安全决策协议演示。IND-DEMO-1 是主要参赛故事线；PAY/MED 作为兼容场景，不作为展示重点。本阶段扩充的是**工具交付、崩溃恢复和去重**，而不是自行发明新的签名算法。

**警示：** 全部流程运行在合成数据和 SQLite **模拟执行事实**之上，没有连接传感器、PLC、机器人、真实生产线或真实支付系统。此演示**没有验证真实物理动作“恰好一次”**，也没有 39 项官方完整 PASS。

## 为什么需要这一层

前一阶段证明 W 可以核对 C/E/X 提供的签名与当前依赖，并把 ACCEPT、资源占用和任务状态原子落库。但在 `ClaimDispatch` 之后，如果工具实际执行，网络在回传结果前中断，W 无法仅凭“没有收到回复”断言工具未运行。

**错误做法：** 重新生成一个 operation/attempt 再发送。设备可能已经处理过第一次操作，造成二次放行、重复执行或不可审计副作用。

**Phase16 最小实现：** 严格区分“W 的不可逆 CLAIM”“经 W 认证的同一条指令交付”“工具端的持久去重”“工具事实再次认证与 W 一次结算”。

```text
受认证的证据 / 策略 / 签名（原 Phase14）
    ↓
W: PREPARE → X 外部签名 → FINALIZE
    ↓
W: ClaimDispatch  [写入 r2_dispatch；状态 EFFECT_UNKNOWN]
    ↓
W 专用交付密钥签名 + SQLite p16_outbox（与 W CLAIM 存在绑定）
    ↓
受公钥绑定的工具网关
    ├─ 验证 W 交付签名、作用域、操作哈希、attempt、COMMIT Ref、账本 origin
    ├─ SQLite BEGIN IMMEDIATE
    └─ 原子写入唯一模拟执行事实、唯一序号和去重记录
    ↓
   （模拟：工具已经 COMMIT，但进程退出、没有返回回复）
    ↓
工具进程重启 / 重发**相同**签名指令
    ├─ 从账本读取原事实 → 不增加执行次数
    └─ Tool 签 TOOL_FINAL → W 验证账本连续性 → SETTLED
```

工具还没有权限任意把数据库日志变为 C/E/X 认证记录。W 交付签名使用独立的 `W transport` 密钥，而不是 C/E/X 的私钥。实际工业实施应把密钥放在系统密钥库或 KMS 中，网关绑定经治理的 W 公钥，并通过 mTLS/OAuth2 等部署级机制认证通道。

## 新增模块

- `research/phase16/industrial_delivery.py`：`WDispatchOutbox` 从**已存在的** W CLAIM 和冻结的 COMMIT 生成绑定的签名交付凭证，持久化令牌用于恢复。 `AuthenticatedIndustrialGateway` 只接受所绑定 W 公钥签署的令牌，把去重和原始模拟执行事实放在**同一个** SQLite 事务中。
- `research/phase16/test_industrial_delivery.py`：包含 8 个可复现实验：正常签名与结算、回复丢失、事务前失败回滚、伪造签名、重放的不同尝试、来源账本变化、8 路并发、重启后同令牌不变，以及 CLAIM 缺失拒绝（组合在 8 个 test methods 中）。
- `research/phase16/process_flow.py`：以 IND-DEMO-1 走过 C/X/W 独立实验进程，再令工具进程在 COMMIT 后硬退出（exit 97）；独立新进程恢复唯一记录，W 正常结算，再由只读审计员核查 W/工具两套数据库及原始 Schema。
- `research/phase16/build_report.py`：对三份原版 Schema、原版 `semantic_cases.json` 哈希固定校验，对源码及原始见证做 SHA-256 记录；输出不造假的原 39 项矩阵和可复现代码包。

## 复现

```bash
python -m pip install -r requirements_phase13.txt
python -m unittest research.phase16.test_industrial_delivery -v

# 下面脚本会创建并运行多个独立子进程
python -m research.phase16.process_flow --output /tmp/zjj_phase16_ind

# 保持官方验收严格，不自动将实验 PASS 映射成官方 PASS
python -m research.formal39.run_formal39
```

建议通过 `.github/workflows/phase16-ind.yml` 统一复现和下载 CI 完整证据。生成的 `research_evidence/phase16/` 包含原始运行日志、两个 SQLite、签名见证与只读审计报告。

## 面向参赛演示的三个“可观察现象”

1. **正常流程**：具备合法数据、签名和授权的质检分流建议，产生一次 ACCEPT、一次派发、一次模拟最终结算。
2. **危险回放**：伪造 W 指令、改变工具目标、修改 attempt、对另一个工具账本重放都会被阻断。
3. **故障与恢复**：工具端已记账后模拟网络掉线（进程硬退出），恢复过程只能找回第一次的不可变事实；W 不能再次创建一个新的 CLAIM。

## 不能承诺的安全性质

- 此处的 exactly-once 只成立于**本地模拟工具账本中原事实的唯一持久化**；没有证明真实设备机械动作、驱动写入或实际生产结果恰好一次。
- 虽有不同 Python 进程，测试私钥仍为公开的确定性 fixture，不意味着真实的独立身份托管、PoP、KMS 或相互信任治理。
- `TOOL_FINAL` 由测试私钥签名；真实工业接入需要设备控制器侧**可独立核验的不可变事件 ID 和原始执行记录**。如果设备本身不提供幂等机制，则不能宣称系统在宕机窗口避免二次物理动作。
- 工具交付签名凭证是内部实验传输层扩展，**不是原版官方 Schema 新增消息类型**；官方 Schema 与 39 项语义测试没有修改。
- 仍需解决真实时间跨度内的 PREPARE/FINALIZE、C/E/X 认证分离、单一跨 Profile W、0-RTT / STATUS / Result、所有官方场景覆盖。

**官方完整符合性状态：仍为 0 PASS / 0 完整 FAIL / 39 BLOCKED_FULL_CONFORMANCE。** 新测试只构成 IND 核心的实验性支持，不得把部分测试数量折算为认证结果。
