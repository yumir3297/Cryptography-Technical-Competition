# 比赛运行支持模块

仅保留比赛运行或测试实际依赖的基础模块。完整原研究文件存于本地归档。类名和密码学域保持原行为；目录名与导入路径按职责整理。

| 当前模块 | 原来源（提交 4202127） |
|---|---|
| wire.py | `research/reference_executor/wire.py` |
| schema.py | `research/strict_v26/upstream_schema.py` |
| pay_dependencies.py | `research/strict_v26/pay_dependencies.py` |
| pay_records.py | `research/strict_v26/pay_history.py` |
| enrollment.py | `research/conformance39/enrollment_lab.py` |
| durable_pay.py | `research/phase5/durable_w.py` |
| tool_final.py | `research/phase6/trusted_final.py` |
| dispatch_guard.py | `research/phase7/guarded_dispatch.py` |
| scene_authority.py | `research/phase8/scene_authority.py` |
| scene_fixtures.py | `research/phase8/fixtures.py` |
| scene_recovery.py | `research/phase11/scene_r2.py` |
| pay_recovery.py | `research/phase11/pay_r2.py` |
| legacy_clock.py | `research/phase11/trusted_clock.py` |
| authority_guards.py | `research/phase12/authority.py` |
| scene_verifier.py | `research/phase14/verifier.py` |
| broker_policy.py | `research/phase18/key_broker.py` |

来源摘要、迁移范围和导入变更文件见 [provenance.json](provenance.json)。这些支持类服务于固定比赛模拟，不代表完整原研究流程或全部 R2 响应已经实现。
