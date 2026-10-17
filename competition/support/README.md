# 比赛运行支持模块

仅保留比赛运行或测试实际依赖的基础模块。完整原研究文件存于本地归档。类名和密码学域保持原行为；目录名与导入路径按职责整理。

| 当前模块 | 原来源（提交 4202127） |
|---|---|
| wire.py | `research/reference_executor/wire.py` |
| schema.py | `research/strict_v26/upstream_schema.py` |
| pay_dependencies.py | `research/strict_v26/pay_dependencies.py` |
| pay_records.py | `research/strict_v26/pay_history.py` |
| enrollment.py | `research/conformance39/enrollment_lab.py` |
| broker_policy.py | `research/phase18/key_broker.py` |
| scene_contract.py | `research/phase8/scene_authority.py`（场景常量与记录工具） |
| scene_base.py | `research/phase8/scene_authority.py`（只读场景推导方法） |
| final_fact.py | `research/phase6/trusted_final.py`（纯终局事实函数） |
| artifact.py | 入口共享产物工具（比赛整理新增，无研究来源） |
| paths.py | 仓库根路径工具（无研究来源） |

早期垂直切片（`durable_pay`、`tool_final`、`dispatch_guard`、`pay_recovery`、`authority_guards`、`scene_authority`、`scene_fixtures`、`scene_recovery`、`scene_verifier`、`legacy_clock`）及其工业初始化与切片入口已移除；当前比赛核心与测试只依赖上表模块。原始研究文件仍保存在本地归档。

来源摘要、迁移范围和导入变更文件见 [provenance.json](provenance.json)。这些支持类服务于固定比赛模拟，不代表完整原研究流程或全部 R2 响应已经实现。
