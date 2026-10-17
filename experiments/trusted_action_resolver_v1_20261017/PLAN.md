# Trusted Action Resolver V1.0 六字段验证范围

本轮是现有隔离 TrustedAdapter 的契约验证，不创建新的生产 Resolver，不改核心或上轮实验。

- 上轮已发布实验基线：4b301f9cbdc61440a9f5ee7e79b7e0af70628f8c。
- 稳定核心：cc4e36b4e302fcdc53cc809a012c77d8464182af。
- 新增 test_resolver.py：逐字段测试不可信提案夹带、签署后替换、权威源绑定及权限收窄；另测各角色非法签署、完整链和 COMMIT/一次执行兼容。
- 新增 run_validation.py：25 项专项与原 22 项 E1–E4 合并运行，独立新证据目录；记录源文件 SHA256、逐项结果、拒绝码及公开 W/工具事实。
- 重新运行原 competition/tests，复核与上轮全部文件字节不变。
- DelegationProof 仅记录接入前提及尚未设计的约束；拒绝额外 delegation 字段不等于已实现证明验证。
- 所有 seed、签署和故障注入仅用于受信测试端，不能成为 Agent 工具。

问题分类按证据给出：原协议安全语义是否冲突；原实现是否缺少应用层契约/编排；实验脚本是否错误；运行环境是否触发时钟或依赖错误。不得把四类混写。
