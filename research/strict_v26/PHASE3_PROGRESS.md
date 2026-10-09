# ZJJ 第三阶段：PAY-1 严格子集、权威依赖重建和计算符合性（2026-10-09）

基线：`ZJJ-CORE-2.6-R2`；阅读了上游 `system_dev/v26/01_core_contract.md`、`02_pay1_profile.md` 和 `pay1.schema.json` 的必要字段，基于仓库 HEAD `0ad0ddc3a1f97a2e6da340337cf9a53426aaa45c`。新增代码在 `research/strict_v26/`，不会替换旧协议文档或篡改官方语义用例状态。

## 1. 本轮实际补上的能力

1. `history-int-v2` 纯整数独立重算：完整快照先验校验，CASE 唯一与规范排序，ratio = floor(10000*amount/max)，distance≤1000，双时间过滤、最多5例、按距离与 ASCII case_id 排序，n<3→INSUFFICIENT，5*d≥4*n→FLAG，其余CLEAR。客户端伪报的 Assessment.result / feature / cutoff 均拒绝。
2. 固定 PAY-1 Record 骨架与数据合同：`POLICY`、`PAY_TASK`、`PAY_HISTORY`、`PAY_EVIDENCE`、`ASSESSMENT` 字段完整性、数值边界、作用域、任务/订单/策略绑定；严格验证来自公开测试签名钥的 Ed25519 `2.5 Evidence` 白名单桥接消息签名/Ref与三个已知硬事实。
3. v2.5 Evidence 的 `refs`、`deps` 基础格式与七类 legacy namespace 的 key 形状验证；**历史资格证明链与原始存储字节认证仍是可信输入，未实现旧版全依赖授权**。
4. `RequiredDeps` 独立子集：从可信状态行及当前 `POLICY/TASK/ORDER/EXPERIENCE/BEHAVIOR`、H/E/U/G/X/必要V 的 `KEY/ROLE` Grant、角色范围和固定策略签署 kid 派生，严格规范排序与完全等集。即使 G 重新签名一个省略依赖的 Permit，独立核对仍拒绝。
5. 状态 Revision 严格递增、过期与当前撤销角色拒绝；KEY 永久撤销后的同 kid 重新激活被测试辅助存储拒绝。
6. 350组固定随机种子数值/选例交叉测试，另有确定性边界与故障模拟测试；三种 PAY 风险输出与派生依赖数有结构化轨迹 `pay_profile_traces.json`。

## 2. 这轮的执行结果

```
python -m research.strict_v26.run_phase3
```

综合**143 / 143** Python unittest 通过，无错误/失败；其中严格 PAY 子模块为 **66 项**，其余为此前研究模型及签名执行器回归测试。结构化证据：

- `phase3_validation_report.json`：总数、环境、源码 SHA-256、限制及上游 Schema 探针状态；
- `phase3_test_log.txt`：143项完整测试名称与结果；
- `pay_profile_traces.json`：CLEAR / FLAG / INSUFFICIENT 筛选与拒绝篡改输出示例；
- `coverage_phase3.json`：上游39用例的 PARTIAL / NOT_RUN 映射。

**官方 39 项完整协议符合性验收仍 0 项 FULL PASS。** 这批离线算法/资格子集使30项有局部相关研究证据，9项尚未覆盖；“部分相关”不能按正式过关统计。

## 3. 上游 JSON Schema：明确的 SKIPPED

当前补丁包为了避免覆盖现有仓库文件，没有包含上游三套 `contracts/*.schema.json`。运行入口在上游仓库根目录可自动识别官方 Schema 并校验 PAY `POLICY/TASK/HISTORY/EVIDENCE/ASSESSMENT` 示例；**本地离线执行结果是五项 `SKIPPED_NO_UPSTREAM_SCHEMA`，不声称已跑过。**

我通过 GitHub 直接读取了上游 `pay1.schema.json` 的 `$defs`，独立核对 `Action/ActionPayload/Case` 与 PAY 五类 Record 的**字段集合**，与本轮手写字段集合一致。但字段集合一致不保证类型、正则、跨字段语义、V25完整依赖或跨语言一致。`upstream_schema.py` 是运行真正官方 Schema 的适配器，缺失时会明确报 `SCHEMA_NOT_INSTALLED` 而不是偷偷使用本地替代品。

## 4. 关键未覆盖边界

- 并未把严格 PAY 校验整体接入第二阶段的 `ReferenceW.commit`：其 `FIXTURE_EVIDENCE`、简化 COMMIT 和模拟资源账仍是不符合正式合同的研究对象。这里是独立子系统，不是完成整个 PAY-1 端到端。
- `witness_authenticated` 与控制状态注册由受信测试夹具提供；没有实现 C 的签名登记 PoP、权限发布见证、历史来源证明连续性或持久外部账。
- `KEY/ROLE` 激活语义只检查了 PAY 固定子集；完整必要依赖还包括传递图、所有签名者的特定用途及范围见证、DENY 发布集合的单 W 原子顺序。
- 原 v2.5 Evidence 的历史发布资格/来源字节、legacy Dep 全闭包以及原签名与现今 CURRENT KEY 的完整桥接仍需实现。
- 未接入正式全字段 `COMMIT`, `Acceptance/Result`、真实数据库的隔离/崩溃恢复、多 Profile、完整双实现互操作；三个 Profile 的原工作台仍只是演示模拟。
- 未对生产级软件或真实付款/工业/医疗系统执行任何工具调用，所有密钥都是公开可预测测试钥。

## 5. 下一阶段实施门槛

1. **在真正上游仓库运行 `upstream_schema.py` 的五个 Schema 探针**，按失败字段修正 fixtures，而不是修改官方 Schema 来迎合原型。PAY 全局 `source` 历史桥接需实现完整可信验证。
2. 将 `PAY_POLICY/PAY_TASK/PAY_HISTORY/PAY_EVIDENCE/ASSESSMENT/BASIS` 精确对象存于 W，并把独立风险/依赖重建接入正常 Issue/Commit；生成和验签符合 R2 的完整 COMMIT Witness 及 Acceptance。
3. 建立原39项中 PAY-01~05 与 CORE-03/05/07/20 的 **单条完整协议轨迹**，输出可重放输入、可信 W 前后状态、每条守卫结果及原始字节；只在完整 case 包含的每个子条件均通过时标 FULL PASS。
4. 之后优先建立可重启、持久、并发可检查的 W 仿真及 R2 工具原账；再扩展 IND / MED 和双实现。

**这轮是扎实的研究补全，但仍不是可提交的“协议全套验收通过”结论。**
