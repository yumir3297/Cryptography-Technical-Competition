# ZJJ-CORE-2.6-R2：39项正式验收与Phase11–12独立局部证据

**核心说明：本报告执行了全部39项的原始清单校验、局部独立单元测试以及选定的端到端专项探针；尚未完成的整条用例不得记为PASS。**

- 官方清单：Git blob `b0bc9dbeedac135f6520b5e93729f63686d97bb4`，固定版本核验通过
- PAY 官方 Schema：`EXACT_ORIGINAL_SCHEMA_LOADED`
- 工业官方 Schema：`EXACT_ORIGINAL_SCHEMA_LOADED`
- 医疗官方 Schema：`EXACT_ORIGINAL_SCHEMA_LOADED`
- 39项局部关联测试：110/110
- 新增独立端到端探针：5/5 个通过
- 有新增端到端验证切面的正式用例：10/39
- Phase11四项重点专项签名切面：4/4 项，带原始输入/签名/C证书/SQLite事务审计（仅局部）
- Phase11新增检查：17 项，完整Profile切面 12 组
- Phase12新增局部证据：2/2 官方用例，6 组三Profile运行记录
- **正式完整通过：0/39**

## 为什么仍未颁发完整PASS

虽然Phase11已有本地PoP/签名C控制/跨IND-MED ToolFinal/局部依赖闭包和统一领取取消语义，但远端真实C/E可信治理、全局统一部署的W、物理工具账和完整传输/STATUS尚未闭合。每条用例的具体缺口、实际测试ID和测试日志见JSON/CSV。

## 高价值已执行的端到端验证

| 专项 | 实际结果 |
|---|---|
| guarded_revocation | PASS_SCOPED_INTEGRATION |
| pay_archive_tamper | PASS_SCOPED_INTEGRATION |
| pay_hard_false_no_accept | PASS_SCOPED_INTEGRATION |
| pay_signed_durable_paths | PASS_SCOPED_INTEGRATION |
| scene_signed_positive | PASS_SCOPED_INTEGRATION |

## 复现

将ZIP解压到仓库根目录：依次执行 `python -m research.phase11.run_phase11`、`python -m research.phase12.run_phase12` 和 `python -m research.formal39.run_formal39`。
若新增官方原始 Schema 文件，程序会重新读取并校验固定 Git blob；完整PASS仍需专门的独立签名及信任证据证明，不由文件存在自动赋予。

## 验收口径

`BLOCKED_FULL_CONFORMANCE`不是FAIL：已经运行过局部及部分端到端检查，但缺少完整可信证据。
`FAIL_OBSERVED_SUBTEST`表示确实发现可重现的测试违例，需要修复；它也不等同于已穷尽正式全量验收。
将来只有提供完整检查、签名、权威状态、全部预期/副作用证明后才可单独转为 `PASS`。
