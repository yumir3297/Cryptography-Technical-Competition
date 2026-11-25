# 核心缺陷记录：同一工具账本的交错结算被判为 stale

**状态：** 已复现，未修复，保留原始失败证据。  
**发现来源：** 外部基准实验 D（原子接受与密码学证据耦合）。  
**影响范围：** 多个同一工具账本上的在途 attempt 以非执行顺序结算。  
**不宣称：** 越权、重复效果、签名伪造或资源超卖。

## 1. 复现

原始结果：`external_benchmark/results/interleaved-settlement-defect.json`  
复现脚本：`external_benchmark/benchmarks/differential_effectiveness/repro_interleaved_settlement.py`

```text
accept A
accept B
claim A
claim B
execute A
execute B
settle A   -> LEDGER_STALE_UNKNOWN
settle B   -> SETTLED
```

实际终态（来自 JSON）：

```json
{
  "reserved": 1,
  "spent": 1,
  "capacity": 4,
  "operations": [
    {"oid": "ZUCd...", "state": "STARTED", "effect_state": "SUCCEEDED"},
    {"oid": "ZZQb...", "state": "SETTLED", "effect_state": "SUCCEEDED"}
  ],
  "settlements": 1
}
```

A 的 final fact 是真实工具密钥签名的，绑定 A 的 `operation_id`、`attempt_id`、`action_hash`、`commit_ref` 和当时有效的 checkpoint；它不是伪造对象。拒绝原因却是 `LEDGER_STALE_UNKNOWN`。

## 2. 代码位置

`competition/core/common_w.py:497`：

```python
if int(cl['high_water']) < tool['high_water']:
    raise ProtocolError('LEDGER_STALE_UNKNOWN')
```

工具账本在每次执行时推进 `tool_meta.high_water`（`competition/tools/common_tool.py:218-231`）。当 B 的 final 已推进 `tool.high_water`，A 的较早 final 的 `cl['high_water']` 合法地小于当前值，于是被当作“陈旧账本”。

## 3. 为什么这是缺陷

W 的接受事务允许同一 Profile 的多个操作进入 `STARTED`（不同业务任务可以同时持有 flight；`w_flight` 以 `profile,oid` 为键）。外部工具端可以按 A、B 的顺序执行，并分别产生两个真实的 final。W 没有规定“必须先结算 A 再执行 B”，但 `_verify_final` 的检查把“当前 head 已前进”误读为“A 的 final 不再可信”。

结果是：

- 合法的 A 无法结算，资源 `reserved` 长期占用；
- A 的操作保持 `STARTED`，形成需要人工处理的悬挂状态；
- 没有重复效果（这是安全侧的好消息），但可用性和最终一致性不满足协议对“后续证据绑定”的承诺；
- 该失败不是适配器错误，也不是测试构造错误；它发生在真实 CommonW、真实工具子进程和真实签名路径上。

## 4. 建议修复（未实施）

**方案 A（最小、串行化）：** W 对同一 `tool_ledger` 只允许一个未结算 attempt；或在 `claim`/`execute` 时冻结结算顺序，要求按顺序 `settle`。这会把并发能力限制为每账本单在途，但语义简单、可证明。

**方案 B（保留并发、证明历史）：** 在 final fact 中携带可验证的 `previous_ledger_head`/checkpoint 链，使 W 能证明 A 的 checkpoint 是当前 head 的祖先，而不是要求 `high_water` 不小于当前值。验收条件应包括：

```text
A.checkpoint is ancestor of current ledger head
AND A.attempt_id/action_hash/commit_ref match
AND no settlement already exists for A
```

**方案 C（显式有序回收）：** 保留当前 final 格式，但把 `LEDGER_STALE_UNKNOWN` 改为可重试的 `SETTLE_OUT_OF_ORDER`，并由 W 记录最早未结算 attempt；这要求上层有可靠的排序/重试器，不能单独解决资源占用。

**推荐顺序：** 先做方案 A 作为可验证的最小修复；若要保留多 attempt 并发，再设计方案 B 的祖先证明。无论哪种，都需要新增真实子进程测试：A/B 交错执行、A 先/后结算、崩溃恢复、重复结算。

## 5. 现有测试为什么没抓到

现有 `test_crash_boundaries` 和 `test_w_recovery` 每个场景通常只有一个 attempt 在途；`test_w_acceptance_races` 覆盖 accept/claim/cancel 竞争，但不覆盖“同一工具账本两个 final 都已生成、再逆序 settle”。这是测试覆盖缺口，不是既有测试失败。

## 6. 结论

- 该缺陷削弱了 H2 在“授权—接受—执行—结算证据闭环”上的强断言。
- 它不推翻“唯一 attempt / 无重复效果 / 证据绑定”的已有正向测试；它暴露的是并发结算顺序假设。
- 在修复和回归前，不应把 ZJJ 描述为在所有并发路径上都能完成“接受事实与后续证据一致”的闭环。
