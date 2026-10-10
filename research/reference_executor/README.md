# ZJJ-CORE-2.6-R2 离线签名参考执行器（第二阶段）

## 可信声明

**这是研究原型 / reference slice，不是完整协议实现或通过正式符合性验证的产品。** 它比第一阶段单纯布尔/状态枚举模型前进了一层：真的产生、解析、验证 Ed25519 签名 Envelope，在一个进程内执行授权、许可、Challenge、CommitProof、Acceptance、工具终局等局部流程，并生成成功/失败轨迹证据。

为了不借给定 Schema 生成器做自我验证，`wire.py` 独立实现受限 JSON 字节编码、对象域分离摘要、严格 Ed25519 点/阶检查和签名验证。验签/结构测试覆盖恶意更改的消息与规范非接受点。它并未实现全量 `system_dev/v26/contracts/*.schema.json`、`PAY-1/history-int-v2` 或完整 `COMMIT` 审计见证，不能声称与原仓库传输合同互操作。

## 运行

位于仓库根目录（将本增量包解压于同一根路径）运行：

```sh
python -m research.reference_executor.run_reference
# 或
python -m unittest research.reference_executor.test_reference -v
```

依赖：Python >= 3.10、`cryptography`。无数据库、Web 服务和网络访问要求。

脚本生成：`test_run.txt`（59项测试各自状态）、`coverage_matrix.json`（原39项编号的PARTIAL/NOT_RUN映射）、`demo_traces.json`（三个Profile的refs与R2恢复轨迹）、`signed_wire_samples.json`（每一步实际签名的消息字节结构与公开测试公钥）及 `validation_report.json`（执行环境、源文件散列、限制）。这些产物的时间戳是当前实际执行时间。

## 实现边界

| 组件 | 实际完成 | 仍未完成 |
|---|---|---|
| Envelope / Ed25519 | 三Profile共通信封、签名输入、域隔离摘要、原始字节规范、点/标量严格检查 | 官方全部Schema；RFC全部异常角落实证跨语言互操作 |
| 核心消息 | Review、Authorization、IssueRequest、Permit、ChallengeRequest、Challenge、CommitProof、Acceptance、StatusQuery 的签名构造与验证 | Result响应全路径、40余具体场景字段/期限交织、正确 full COMMIT witness |
| 授权 | U/V/G/H/X分离的签名链、依据Revision检查、DENY集合、Permit依赖比较 | 全源认证 KEY_GRANT/ROLE_GRANT/C，W数据库真实范围锁和可见性，完全独立RequiredDeps算法 |
| 状态 | 同意图唯一接受、模拟容量8、任务领取至多一次、未知不重复派发 | 真实事务日志/ACID、失败后的进程重启恢复、事务签署故障及资源复杂度 |
| 工具终局 | 真实Ed25519签名TOOL_FINAL、FinalFactID、同事实新认证、反向事实HALTED | 原子效果账、连续性证明、所有历史同Ref重传的归档证明路径 |
| Profiles | PAY/CLEAR+ANOMALY+LOW_EVIDENCE 的fixture、工业固定标签映射、医疗A/B模板和读取完整性fixture | PAY history-int-v2、来源实际签名/300s验证、IND二阶段单位持久流、MED权限/资格及完整场景状态 |

`engine.py` 的 Record `kind='FIXTURE_EVIDENCE'`、Assessment.method=`REFERENCE-SLICE` 和 COMMIT 包含 `reference_slice_warning`，都是**故意可识别的非正式占位值**。切勿将这种对象拿去生产服务申请授权，也不要修改 Schema 来接纳测试捷径。

## 下一阶段具体任务

1. 在原仓库环境加载官方 JSON Schema，消除所有实验占位，精确构造 `POLICY/TASK/EVIDENCE/ASSESSMENT/BASIS/COMMIT` 的所有强制字段；从权威受控发布凭证独立导出 RequiredDeps。
2. 实现 PAY `history-int-v2`，完整 IND cycle2、MED READER/AUDITOR 和 C 登记证明；实现真实 `W` 持久事务与可重启故障注入。
3. 用一次完整封闭编排器跑 `semantic_cases.json` 每一条用例；测试应附输入、权威W快照、每条守卫、结果、签名/状态散列和独立Expected oracle。现在 39 项仍 **0 个 FULL PASS**。
4. 独立第二验证器（推荐 Go/Rust），比对受限编码/拒绝集、数据Schema、引用闭包与全场景正负轨迹，而不仅是签名向量。

本轮会按照严格口径继续开发，不以堆叠自造测试用例数量作为“已满足核心协议语义”的证明。

**注意：所有签名材料使用公开、可预测的固定测试密钥；不得复制到实际部署环境。**
