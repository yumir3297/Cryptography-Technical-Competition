# Phase 4 — PAY-1 签名闭环与完整 COMMIT Witness（研究版）

目标协议：`ZJJ-CORE-2.6-R2`（上游检视提交 `0ad0ddc3a1f97a2e6da340337cf9a53426aaa45c`）。本目录通过原有 `research/reference_executor` 的真实 Ed25519 消息、`research/strict_v26` 的风险独立重算和权威依赖重建，形成一个可运行、可核验的 PAY-1 **内存实验闭环**，不作为产品系统。

## 运行

```bash
# 在补全包根目录，或解压并合并后的原仓库根目录
python -m research.phase4.run_phase4

# 指向包含未修改官方 Schema 的原仓库；不存在或 blob SHA 不匹配直接报错
python -m research.phase4.run_phase4 --upstream-root .
```

依赖 Python 3.10+，`cryptography`、`jsonschema`。没有安装依赖时先在虚拟环境执行 `pip install cryptography jsonschema`。检查器默认检测当前根目录 `system_dev/v26/contracts/pay1.schema.json` 是否存在。为防止以修改过的 Schema 冒充官方验证，要求其 git blob SHA-1 精确等于 `86ba1bae0e4c455899af661bed44edfc5494aa5e`；原仓库如有后续更新，请先核对新规范与新 SHA，不要直接关闭检查。

## 新模块

- `flow.py`：三阶段拼接；PAY-1 的 `POLICY/PAY_TASK/PAY_HISTORY/PAY_EVIDENCE` 当前受信记录绑定；`ASSESSMENT/BASIS` 精确字段；Review/Authorization/Permit/Challenge/CommitProof/Acceptance 的真实签名；由冻结 Action、资源、BEHAVIOR 前后状态、资格证据生成 19 字段 `COMMIT`；签名 `ISSUED/ACCEPTED Result`；首次终局和相同事实换钥再认证。
- `test_flow.py`：CLEAR/FLAG/INSUFFICIENT 的正常签名轨迹、变更授权复核用途、冒名回执、过期、有效签名缺依赖、删除权威记录、权威源三事实 false、COMMIT 被篡改、8线程重传及效果结算等。
- `run_phase4.py`：合并第一至第四阶段 180 项自动化测试；产出日志、明文字段/签名样例及状态前后摘要；对上游 Schema 和正式39项严格区分结果。
- `validation_report.json`：机器可读测试记录；`signed_pay_traces.json`/`signed_pay_artifacts.json`：三条可复核正向轨迹；`coverage_phase4.json`：39项原用例的研究证据映射。

## 本阶段的新增发现及修复

1. 旧参考执行器可能只验证 Review 数量而遗漏**Review 用途**。现将实际 Review.purpose 严格等于重新计算的 required_reviews。以 `LOW_EVIDENCE` 要求误传 `ANOMALY` 已在测试中拒绝。
2. 旧参考执行器将一份已经成功的相同 `CommitProof` 重传一律当作 `REPLAY`。此行为与正式 v2.6 的“同一证明重传返回原持久结果”矛盾。现改为**原字节相同返回同一 Acceptance**；不同字节复用已消费 nonce → `REPLAY`。8并发测试中只发生一次接受。
3. Phase 2 的旧 `COMMIT` 只有少数字段，并有 `reference_slice_warning` 占位字段。本次已为 **PAY-1** 生成合同要求的全部19个值字段，且 Acceptance 的 `commit_record_ref` 直接绑定真实 COMMIT RecordRef。阶段2旧代码仍保留用于回归，不应把它和本阶段视为同等严格。
4. PAY-1 中非 CLEAR 复核者必须有策略阅读权限。固定输入已显式包含 V 的 POLICY.readers 和原 Evidence.aud（重新签署固定测试证据），确保演示不绕过读权限声明。
5. 原存储中的 POLICY/TASK/ORDER/EXPERIENCE 与实际独立重算输入必须来自同一**当前激活权威记录**；现在有独立的对象身份、Ref 与内容等值检查。

## 严格限制与诚实证据口径

- **正式39项全协议语义验收：0 PASS。** 目前离线包并无原仓库的正式验收执行器，不能把本地测试更名为正式通过。
- **官方 JSON Schema：本次离线实验 `SKIPPED`。** 原仓库未随前几轮离线压缩包一起提供完整 `pay1.schema.json`；本包不拿手工字段合同冒充它。若将包合并到原仓库并用相同固定版本运行，则进入真实 JSON Schema Draft 2020-12 验证。未实际运行过的检查永远不能写为已通过。
- 控制平面 C 的正式密钥登记、受控发布及历史 v2.5 Evidence 的完整凭据/依赖溯源仍由可信 fixture 承担。Schema 通过也不能证明这些信任语义。
- `ReferenceW` 只是一把 Python 进程内 `RLock`，不是持久数据库、跨进程可线性化事务、崩溃恢复或原工具账的不可篡改实现。
- 工具调用/效果计数仍是模拟，不是现实支付或 exactly-once 证明；R2 再认证的工具账连续性仍是可信前提。
- IND / MED 维持 Phase 2 演示水平，本阶段更严格的 PAY-1 验证器不能直接替代其他 Profile。

**推荐下轮**：先把本包放入真实仓库跑固定 Git blob 校验和全部上游 Schema 探针；再实现 W 的 SQLite/PostgreSQL 原子 nonce/intent/resource/COMMIT 写入、崩溃注入和 ACCEPTED 历史回执恢复。随后才能开始逐条对 `semantic_cases.json` 做完整 `PASS/FAIL` 验收。
