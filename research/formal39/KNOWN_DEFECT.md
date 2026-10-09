# 官方机器合同检查发现的实际缺陷与修复

## 实验：原版三套 JSON Schema 与真实签名场景

- 协议：ZJJ-CORE-2.6-R2；官方清单 Git blob: `b0bc9dbeedac135f6520b5e93729f63686d97bb4`
- PAY Schema Git blob: `86ba1bae0e4c455899af661bed44edfc5494aa5e`
- IND Schema Git blob: `f937286b1be32b2a8356b991a93770abff430578`
- MED Schema Git blob: `5e43b803ed32a3359e4ad2b7e48a3c96f7fd9482`

### 修复前真实失败

工业、医疗签名协议输出的 `BASIS.value.deps`、`COMMIT.value.checked_deps`、Review/Authorization/IssueRequest/Permit 等消息 `body.deps` 包含实验私有 `EVIDENCE` namespace。

但官方 IND/MED Dep.namespace 的枚举只有 `POLICY`, `TASK`, `UNIT` / `ENCOUNTER`, `BEHAVIOR`, `KEY`, `ROLE`，没有 `EVIDENCE`。原版 Schema 检查直接报 `UPSTREAM_SCHEMA_REJECT:...namespace`。修复前五个场景共出现28份结构拒绝：IND 16、MED 12。这是实现与规范不符合，不是攻击或模型精度问题。

### 修复方案

修改 `research/phase8/scene_authority.py::_deps`：只序列化规范允许的 Dep namespace。内部的 EVIDENCE 行仍存储签名来源记录，不被删掉；其 `RecordRef` 与当前场景 `UNIT/ENCOUNTER` 行的 `evidence_ref` 严格相等。证据导入、替换及撤回均原子推进场景 revision/ref。签署与接受时 `_bound` 会再次核当前来源签名、权限和场景证据行；领取时核对冻结场景的 `scene_after`，因而删除私有 wire namespace 不表示取消证据新鲜性检查。

### 修复后可复现结果

- `python -m unittest research.phase8.test_scene_authority -q`：54项通过。
- `python -m unittest research.formal39.test_machine_gates -q`：4项通过（含跨场景篡改与证据陈旧拒绝）。
- 原版 Schema 检查：工业三场景97份对象通过、医疗两场景64份对象通过、两者均为零结构拒绝。
- PAY 五条持久化签名研究轨迹又检查了82份原版 PAY Schema 对象。

**边界**：机器结构符合只覆盖这些生成对象，不等于官方39项语义完整符合；完整管理控制面、历史发布审计、场景间跨服务工具账与运输协议仍未形成全部独立证明。
