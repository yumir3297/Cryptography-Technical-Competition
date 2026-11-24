# GoalFloor 最小正式集成（2026-11-23）

## 1. 范围

本文件记录 `integration/goalcommit-shadow-20261123` 对原 ZJJ-CORE-2.6-R2 的唯一协议扩展：C 认证的可选 `GOAL_FLOOR` 记录，以及 W 接受事务中的必要资源下界检查。它不替换 C/Resolver/W/X/工具/结算核心，不引入 winning region、rank function 或 Agent 规划器。

## 2. 新增对象

C 通过既有 `TrustedState.publish` 路径发布（域 `COMP-APP-C-PUBLISH-v1`）：

```json
{
  "version": "2.6",
  "profile": "IND-DEMO-1",
  "kind": "GOAL_FLOOR",
  "scope": {"domain": "lab", "tenant": "tenant-1", "scenario": "industrial"},
  "value": {
    "model": "goal-floor-v1",
    "group": "goal-1",
    "epoch": "1",
    "resource_key": ["lab", "tenant-1", "industrial", "route-capacity", "demo-line-a", "ind-inspection-bay", "unit"],
    "unit": "UNIT",
    "capacity": "2",
    "deps": [{"namespace": "POLICY", "key": ["..."], "revision": "1", "ref": "..."}],
    "actions": [{"name": "inspect-a", "profile": "IND-DEMO-1",
                 "action_digest": "...", "obligation": "unit-a", "cost": "1"}]
  }
}
```

- `action_digest` 由 `competition/core/goal_floor.py::action_selector` 计算，覆盖 scope/principal/holder/holder_kid/executor/tool/tool_version/destination/payload，排除 `operation_id`。Agent 请求中没有 goal 字段；W 用冻结 Action 匹配 C 规则。
- `deps` 支持 `POLICY/TASK/INCIDENT`，逐项比较 revision 与 ref；任一变化使旧 GoalFloor 失效（`GOAL_DEPS_STALE`）。
- 同一 group 的新 epoch 必须保持 `resource_key/capacity/unit` 和非空 obligation 集合不变（`GOAL_MIGRATION_REQUIRED`），避免更新把未决 obligation 孤立。
- `capacity` 必须等于 W 资源证书容量；`cost` 必须等于 W `plan.amount`；否则 `GOAL_CAPACITY_MISMATCH` / `GOAL_COST_MISMATCH`。

## 3. W 接受事务

`CommonW.accept` 在 `BEGIN IMMEDIATE` 事务内：

1. 读取同 Profile、同资源的所有活跃 GoalFloor；
2. 校验 C 记录、C 签名、revision/ref、依赖新鲜性；
3. 读取 W 资源账 `reserved/spent` 和 `w_goal` 状态；
4. 用 W 自己的 `plan.amount` 计算：

```text
total = spent + reserved + candidate_cost + remaining_floor
```

5. `goal_mode='enforce'` 时要求 `total <= capacity` 且无 PENDING/BLOCKED 必要事项；否则拒绝，事务回滚，无业务副作用；
6. `goal_mode='shadow'` 时只记录 `COMMIT.value.goal`，不改变旧放行；
7. `goal_mode='off'` 时完全不读取 GoalFloor，旧任务行为不变。

`COMMIT.value.goal` 包含 `mode/decision/reason/goal_refs/deps/matched/capacity/spent/reserved/candidate_cost/remaining_floor/total/headroom/state_ref/check_ref`。COMMIT 由 X Acceptance 的 `commit_record_ref` 间接签名；GoalFloor 见证不能接受后替换。

## 4. 状态与 UNKNOWN

- 接受时把匹配的必要事项写入 `w_goal`，状态 `PENDING`；成功结算 `DONE`，确认失败/取消 `BLOCKED`。
- `PENDING` 包括 STARTED/UNKNOWN；GoalFloor 拒绝新的必要动作 `GOAL_PENDING_UNKNOWN`。这与原 W 的“UNKNOWN 保留 reservation、查询原 attempt、不自动重派”一致。
- 取消不自动重置 Goal；需要 C 发布新 epoch。
- 多 Goal 共享同一资源时，`remaining_floor` 对所有活跃 Goal 的 OPEN 必要成本求和；这是保守必要条件，不处理“Goal 之间二选一”的析取。

## 5. 模式与默认

- `goal_mode='off'` 默认，保证旧任务/旧测试不受影响。
- `goal_mode='shadow'` 只观察，不改变放行；用于对照。
- `goal_mode='enforce'` 才形成 `LegacyGuard AND GoalFloorGuard`。

## 6. 证据

- `competition/tests/test_goal_floor.py`（10 项）
- `competition/tests/test_goal_floor_pure.py`（8 项）
- `competition/tests/test_evidence_verifier.py`（15 项）
- `competition/tests/test_cross_scenario_evidence.py`（3 项）
- `competition/tests/test_incident_workflow.py`（1 项）
- `competition/tests/test_crash_boundaries.py`（3 项）
- `competition/evaluation/`：五组实验、39 项状态、性能、评委复验。

## 7. 不声称

- 不证明目标最终可达；GoalFloor 只是必要资源下界。
- 不提供跨 Profile 原子性；资源账按 `(profile,key)` 隔离。
- 不把 `status/audit` 当作正式签名 Result/AUDITBundle。
- 不把模拟支付/医疗/工业/隔离效果当作真实生产效果。
- 不把原型 31 项或本轮新增测试混算为正式 39 项 PASS；当前正式状态见 `competition/evaluation/conformance_39.md`。
