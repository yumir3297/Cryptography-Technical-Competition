# ZJJ-CORE-2.6-R2 规范闭合提案（非已生效修订）

日期：2026-10-09。范围：仅拟解决 R1 记录的 Q01/Q02 及恢复边界澄清。**本提案未经协议负责人采纳之前，不修改现有 2.6-R2 规范版本、签名消息类型、Schema 或验证状态。** 采纳时须评估兼容性，更新相应精确合同、语义用例与测试向量，并给予新的修订标识。

## C01 / Q01：已发布 DENY 集合的完整性和线性化

1. W 必须为 `(scope,profile,basis_ref,review_purpose)` 维护受控发布的 Review 判定历史及单调的集合版本/范围版本。该记录归属 W 顺序，包括零条记录的空集范围见证。只有当前合规 V 经认证发布的签名 Review 可以进入权威集合；客户端声明、缓存或内联 objects 不具有发布效力。
2. `RecordApproval` 的成功发布、`Issue` 和 `Commit` 的相应读取必须属于一个可解释的 W 全序。对本 Basis 必需的每个 `review_purpose`，提交接受之前在事务内核验所要求的 APPROVE 及截至该事务序列点全部已发布的 DENY；任一已发布 DENY 阻断该 Basis 的新签发和新接受。无客户端选择子集替代权威范围查询。
3. 在准备/许可签发时，可携带绑定范围版本的依赖见证；在 `Commit` 事务内重查时必须保护「该 Basis 相应用途发布集合未新增 DENY」的谓词（序列化范围读、版本 CAS 或等价约束）。只对既存 Review 行加行锁而忽略幻读，不满足此要求。
4. 并发先后语义：若 DENY 的 W 发布顺序号 **早于** ACCEPT 线性化顺序号，则 ACCEPT 必须失败；若 DENY 晚于已接受事务，不追溯撤销既有 ACCEPT，也不代表工具效果会被逆转。两种顺序均须有自动化执行轨迹。
5. 已发布 DENY 及其索引/证据应在必要的审计期限内不可被客户端删除、隐藏或覆盖为 APPROVE；本 Basis 不允许另一个 V 签的 APPROVE 冲淡任何已发布 DENY。重新准备必须生成新 Basis 并依当前输入重新审查，不能给原 Basis 清空历史。

**拟新增/细化语义用例**：
- `C01-DENY-BEFORE-ACCEPT`：V1 DENY 发布后即使 V2 APPROVE 已发布或晚到，原 Basis 不得接受。
- `C02-CONCURRENT-PUBLISH-COMMIT`：同 Basis 的 DENY 与 Commit 并发，检查两种 W 顺序，不存在否决先发布而接受仍成功的历史。
- `C03-EMPTY-TO-NONEMPTY`：发布前 Review 集合为空，加入 DENY 必须改变范围版本并使旧的通过见证无效。

## C02 / Q02：PAY-1 的主体分离

PAY-1 部署身份约束建议统一为：

```
U.subject != G.subject
U.subject != X.subject
V.subject != U.subject   (each required V)
V.subject != G.subject   (each required V)
V.subject != X.subject   (each required V)
```

此外，审批权的不同主体是 **身份登记层约束**，不是简单比较不同 `kid`。C 发布/修改 ROLE/KEY/POLICY 时应拒绝破坏主体分离的生效配置；X/W 在 Issue/Commit 对当前权威身份与角色映射机械重查。接受前若配置变化导致主体重叠，则 `F/NO_ROLE` 或明确的分离原因码（如拟新增则需同步修改原因码封闭枚举）拒绝；不能自动用旧授权越过新的角色映射。

现实独立性仍需要 C 及私钥管理的可信前提，字符串不同不能证明两把密钥没有落到同一控制方。以上增强的是可检查的配置约束，非「抗 U 与 G 串谋」承诺。

**用例**：U 与 G 同 subject 不同 kid；V 与 G 同 subject 不同 kid；Role 修改导致后验重叠；C 受控发布被拒绝；原授权签名曾合法但当前资格失效。

## C03：Acceptance 回执冻结、过期与密钥丢失

- Commit 原子接受后，Acceptance 的 `core/kid/iat/exp/ref` 已冻结；不可改变任一字段来「恢复」同一接受。
- 若签名尚未生成而原签名密钥被永久撤销/丢失，原签名回执可能无法恢复。即使密钥未丢失，超过冻结的 `exp` 窗口亦不能任意补签旧 core。此为已声明的可用性边界，不允许绕过为第二次接受，也不允许假造 REJECT。
- `STATUS` 使用当前有权主体查询，历史 Acceptance 的原始 aud 和字节保持不变；新主体的读取权限须单独检查，不修改已存在签名。

## C04：工具账连续性信任边界

- R2 `ReattestFinal` 的恢复安全依赖 C 正确确认 `ledger_id` 代表相同的不可变工具事实集、单调序号和唯一 effect_id。
- 本提案不把「两次使用相同 ledger_id 字符串」当作连续性证明；账损坏/回滚/缺失必须保持 `EFFECT_UNKNOWN` / 占用，不重新派发或从不存在的记录合成 `FAILED_CONFIRMED`。
- 后续方案可采用链式根承诺 + 可信持久单调检查点 + 抽样/完整重放见证。但在没有恶意工具/恶意 C 威胁模型及相应独立核验实现前，不声明密码学保护了账连续性。

## 冻结前检查

采纳本提案必须同步变更：
- `01_core_contract.md` §4–5、`02_pay1_profile.md` §5–7、R2 恢复/状态相关文字；
- 39 项 `semantic_cases.json` 中受影响用例及新增用例（扩充后不应仍声称 39）；
- 独立测试与负例向量（不能用同生成器自我验证代替独立规范检查）；
- 版本变更矩阵和审查记录，避免无声修改 wire 合同。
