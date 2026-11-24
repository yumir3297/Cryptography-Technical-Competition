# 研究目标与职责边界（2026-11-24）

## 目标

面向高后果智能体决策，ZJJ-CORE 对 Agent 提出的外部动作提供密码学可验证的授权、原子接受、唯一执行资格、工具终局和结算证据链。GoalFloor 只维护经 C 认证的目标必要资源下界，防止后续局部合法动作挤占已确定的必要资源。

## 职责划分

| 主体 | 责任 | 不负责 |
|---|---|---|
| Agent | 目标提出、概率性推理、规划、候选动作生成 | 不能自定受信成本、依赖、角色、Goal，也不能自行删除适用约束 |
| C | 认证并发布 Policy/Task/Key/Role/Resource/Goal/Incident 记录 | 不证明目标业务上合理，不证明 Agent 规划正确 |
| W | 在原子事务中检查授权、资源、GoalFloor、意图、执行资格和结算 | 不搜索最优路径，不做 winning region/rank，不保证目标最终可达 |
| X | 对冻结的 Acceptance core 签名 | 不判断业务目标是否合理 |
| 工具/效果端 | 固定执行事实并签名终局记录 | 不证明物理世界恰好执行一次 |
| 时间源 | 提供受信事件时间区间 | 不提供外部可信时间戳/原子钟 |

## GoalFloor 数学模型

对同一 `(profile, resource_key)` 且适用活跃 GoalFloor 的候选动作：

```text
Spent + Reserved + CandidateCost + RemainingGoalFloor <= Capacity
```

- `Spent/Reserved` 来自 W 资源账；
- `CandidateCost` 来自 W 的 `TransactionPlans.plan`；
- `RemainingGoalFloor` 来自所有共享资源的活跃 C GoalFloor 的 OPEN 必要成本，排除候选匹配的事项；
- `Capacity` 来自 C 资源证书。

这是接受时的**必要资源保障**，不是目标可达的充分条件；多 Goal 求和是保守语义，不支持析取目标或跨 Profile 原子性。

## 模式

- `off`：默认，保持原 CommonW 语义。
- `shadow`：计算并记录，不改变放行。
- `enforce`：`LegacyGuard AND GoalFloorGuard`；比赛演示固定使用该模式。

Agent 没有 goal 选择字段；W 用冻结 Action 的 selector 匹配 C 规则。停用、epoch、依赖和 obligation 集合的治理规则见 `invariant-spec.md` 与 `protocol-boundary.md`。
