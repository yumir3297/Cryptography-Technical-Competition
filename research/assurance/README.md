# ZJJ-CORE-2.6-R2 安全协议研究增量包

**状态：可运行的研究增量；不替代 2.6-R2 生产实现，不代表已经完成 39 项协议语义测试。** 创建日期：2026-10-09。

此目录建议整体放入仓库根目录 `research/assurance/`；未覆盖 `main` 上现有的 `system_dev/v26`、`verification`、`docs`，避免修改已冻结签名合同和历史报告。协议正文的修改应在评审通过后另开修订版本与向量生成流程。

## 文件与步骤

1. `01_normative_closure_PROPOSED.md`：针对 Q01 DENY 发布范围、Q02 独立授权者与 G/X 身份分离，以及回执、账连续性边界的规范闭合建议，**不是现有协议正式规则**。
2. `02_formal_model_and_claims.md`：明确定义模型状态、威胁前提、安全不变量、状态转换、证明与适用边界。
3. `abstract_checker.py` / `abstract_report.json`：标准库有限状态 BFS，穷举基线与 8 类错误守卫变体，并附反例轨迹。默认深度18、两个共享同一意图键的候选。
4. `test_abstract_checker.py`：13 项抽象层回归/消融测试。
5. `deny_range_model.py` / `test_deny_range_model.py`：五项拟议 DENY 发布集合幻读 / 线性化模型测试；**与真实数据库串行化实现无关**。
6. `conformance_inventory.py`：接入现存 `system_dev/v26/semantic_cases.json`，记录 39 项仍 `NOT_RUN`，不把上面的抽象测试当成正式通过项。
7. `03_literature_and_experiment_design.md`：相关工作与待证伪贡献假设、公平实验矩阵和性能指标。
8. `benchmark_primitives.py` / `primitive_benchmark_result.json`：可重复运行的 SHA-256 与 Ed25519 本机基础开销微基准；不是协议实际端到端延迟。
9. `run_all.py`：一键重跑，输出 `local_validation_report.json` 和源代码 SHA-256。

## 一键复现

在包含本目录的工程根目录运行：

```sh
python research/assurance/run_all.py
```

单独运行模型（保留反例轨迹）：

```sh
python research/assurance/abstract_checker.py --depth 18 --mutants --output research/assurance/abstract_report.json
python -m unittest discover -s research/assurance -p 'test_*.py' -v
python research/assurance/benchmark_primitives.py --iterations 600 --output research/assurance/primitive_benchmark_result.json
python research/assurance/conformance_inventory.py
```

其中有限状态模型和测试仅需 Python 标准库；微基准需要 `cryptography`，建议在现有项目运行环境中安装。不要直接把这个包的 `report` 的全 PASS 填入原 39 项用例。

## 下一道真实门槛

要把规范研究提升为密码学竞赛中可信的协议验证作品，后续必须实现最小、独立的 **协议参考状态机执行器**。它要能够从签名/Record/当前权威状态构造完整轨迹、读真实受控状态并给出可核对的 Result/Acceptance、支持 fault injection；之后逐项把原 39 项 `NOT_RUN` 改为有运行日志与证据哈希的 PASS/FAIL。这里提供的是可复现的第一层抽象验证和安全分析，不伪装为已经做到那一步。

此外应补一个与现有 Python 生成器**独立实现**的完整协议验证器，覆盖编码、严格验签、RequiredDeps、提交原子性、恢复与场景业务规则，而不是仅复算同一来源自动生成的成功向量。

## 明确的信任与局限

- 受信 C/W、工具最终事实与密钥保管在抽象模型中是模型输入；不抗 C/W 失陷。
- 无现有仓库真实 Schema、本地 v2.6 运行时、工具账数据库或三 Profile 演示软件时，不可能将实验扩充为完整协议符合性 PASS。
- R2 已有 16 项真实 Ed25519 局部恢复模型测试及 371 项结构/密码检查属于**原仓库自己的历史报告**，本包没有重新执行那些原项目验证器。
- 此目录故意不实现网络攻击/利用脚本，仅用于离线协议状态和数学安全实验。


## 第二阶段追加参考执行器

此研究包现包含 `../reference_executor/` 子目录，请参见[离线签名执行器 README](../reference_executor/README.md)。新增真实签名和59项测试，但**仍未取得 39 项原语义验收的任何一项完整符合性 PASS**，因此本文件早期“下一道门槛”关于完整参考执行器的任务并未关闭，只是有了可复用的局部执行内核。
