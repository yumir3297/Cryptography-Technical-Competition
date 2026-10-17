# 本轮实际结果

- 核心回归：137/137 通过（279.499 秒）。
- 最终组合复测：47/47 通过（六字段专项 25，原 E1–E4 22），0 failures、0 errors。
- 本轮没有修改核心、原适配器、Schema、签名域或旧证据；与上轮已发布版本逐字节核对 380 个原文件均一致。
- 机器结果：evidence/run-02/results.json.gz；原始字节无损压缩，解压后即运行器输出。原始未压缩数据亦保存在本地交付包。

## 逐字段结果

| 字段 | 提案夹带 | 已签 Action 替换 |
|---|---|---|
| operation_id | PASS：PROPOSAL_FIELDS | PASS：BINDING |
| principal | PASS：PROPOSAL_FIELDS | PASS：BINDING |
| holder | PASS：PROPOSAL_FIELDS | PASS：WRONG_HOLDER |
| holder_kid | PASS：PROPOSAL_FIELDS | PASS：WRONG_HOLDER |
| executor | PASS：PROPOSAL_FIELDS | PASS：BINDING |
| destination | PASS：PROPOSAL_FIELDS | PASS：CLAIM_FALSE |

非法签署：H/U/V/G/X 的伪造调用全部 BAD_SIGNATURE；缺凭据为 SIGN_CALLER_REQUIRED。H 无权冒充 U/V/G/X。
完整新 Action 通过 CommonGuard 与真实签名校验；重复接受的 COMMIT/ref 完全一致；重复执行后仅一个效果。

## 失败与必要修改

首轮 run-01 实际运行 47 项，2 errors；diagnostic-01 单独复现相同错误。两者属于实验脚本断言/输入选择问题：
1. 错误目标映射在 C.publish 的原工业 Task Schema 就被拒绝，早于 Resolver；改为精确断言该拒绝码，不放宽原 Schema。
2. authorization=None 在 canonical 编码时被 WIRE_TYPE 拒绝，不能用于证明 Guard 拒绝。改为可编码的空授权对象，并在独立用例中首次 freeze，再提交给实际 W 拒绝。也移除了初版测试清空自己临时冻结记录的故障注入。
只修改本轮测试代码；没有需要实施的协议或旧运行代码修复。不得把本轮有限测试通过当作完整安全证明。

## DelegationProof

未实现；额外委托字段拒绝仅是入口约束。未来发行者权威、权限交集、撤销/版本、审计、签名与 Action 绑定须单独设计和验证。详细边界见 REPORT.md。

## 命令与逐项详情

见 COMMANDS.md、evidence/core-regression.log、evidence/run-01/tests.log、evidence/diagnostic-01.log 和 evidence/run-02/tests.log。
