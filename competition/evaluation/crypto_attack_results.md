# 密码学篡改、替换与重放结果

生成脚本：`python -m competition.evaluation.experiments.crypto_attacks`。原始：`results/crypto-attacks.json`。

合法包：`PASS`（13 项检查）。以下每个篡改都从同一合法包深拷贝后只改一个关系，独立验证器必须返回 `FAIL`。表中“主拒绝”是第一个非 PASS 检查；“后续 SKIP”表示验证器在前提失败后停止，不再对不可信对象做下游断言（这是刻意 fail-closed，不是漏检）。

| # | 篡改 | 结果 | 主拒绝 | 说明 |
|---|---|---|---|---|
| 1 | Action payload route 替换 | FAIL | `commit_record_ref:COMMIT_REF` | COMMIT 内容变化导致 ref 不再匹配；后续 SKIP |
| 2 | ActionHash 替换 | FAIL | `authorization_chain:ACTION_HASH` | ctx.action_hash 与 Action 不一致 |
| 3 | Goal capacity 篡改 | FAIL | `control_certificates:CONTROL_RECORD` | C 记录内容与 C 签名 claim 不一致 |
| 4 | TaskRef 替换 | FAIL | `authorization_chain:BASIS_REF` | Basis 内容变化导致 ref 不匹配 |
| 5 | Resource capacity 篡改 | FAIL | `resource_certificate:RESOURCE_CAPACITY` | W 资源行与 C 资源证书不一致 |
| 6 | Scope/Profile 替换 | FAIL | `control_certificates:CONTROL_SCOPE` | 控制记录与包 scope 不一致 |
| 7 | PermitRef 替换 | FAIL | `commit_record_ref:COMMIT_REF` | COMMIT 引用变化 |
| 8 | Acceptance commit ref 替换 | FAIL | `x_acceptance:FROZEN_RECEIPT_CONFLICT` | 签名 acceptance 不再等于冻结 core |
| 9 | Acceptance 签名篡改 | FAIL | `x_acceptance:SIGNATURE_ENCODING` | 严格 Ed25519 编码/验签失败 |
| 10 | C 控制记录签名篡改 | FAIL | `control_certificates:BAD_SIGNATURE` | 根签名失败 |
| 11 | attempt_id 替换 | FAIL | `attempt:ATTEMPT_ID` | W 包 attempt 与 outbox 不一致 |
| 12 | 工具终局 outcome/effect 篡改 | FAIL | `tool_final:BAD_SIGNATURE` | 工具签名覆盖终局字段 |
| 13 | FinalFactID 替换 | FAIL | `settlement:SETTLEMENT_FACT` | 结算行与工具终局事实不一致 |
| 14 | A 操作的 Acceptance 拼到 B 包 | FAIL | `x_acceptance:FROZEN_RECEIPT_CONFLICT` | 跨操作拼接被冻结 core 拒绝 |
| 15 | B 的 COMMIT 拼到 A 包 | FAIL | `commit_record_ref:COMMIT_ACTION` | COMMIT 与 A action 不一致；attempt/acceptance 也拒绝 |

## 结论

- 所有 15 个定向篡改都被拒绝；没有出现“签名都合法但对象关系非法”被接受的情况。
- 合法包通过，说明拒绝不是验证器“一律拒绝”。
- 这些不是穷举模糊测试；未覆盖的字段组合在 `conformance_39.md` 中仍为 `NOT_RUN`。

## 复现

```powershell
python -m competition.evaluation.experiments.crypto_attacks
```

脚本只使用公开证据包、公开信任锚和验证器；不打开 W 数据库，不导入 CommonW。
