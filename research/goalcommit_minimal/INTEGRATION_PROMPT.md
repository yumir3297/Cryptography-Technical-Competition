# 给 Codex 的最小接线任务（先审查和 shadow，不要直接合并）

仓库：`yumir3297/Cryptography-Technical-Competition`。

目标：基于最新实际分支与主线，给 C 的受信发布添加可选 `GoalFloor`（见 README），其判定仅是有限“必要事项最小资源剩余”约束；与旧 `CommonGuard`、W 原子接受、X Acceptance 和 EXEC-0 结合。**不要重新实现 GoalRelation v3 的 winning region/rank/Merkle 全证明。**

执行顺序：

1. 列出现有 C 的 `TrustedState.publish` namespace、`CompetitionSchema` 比赛视图、`CommonW.accept` 的调用顺序，先确认共同资源是否真的在同一个事务内。检查当前 feature 分支与 main 差异，禁止盲目 merge 覆盖。
2. 提取 `goal_commit.py` 的纯 `evaluate_goal` 逻辑，整理为不含新 SQLite 初始化/签名器的 `competition/core/goal_floor.py`；签发/验签调用当前 C 受信路径而非重新发明身份系统。
3. C 新字段采用严格 Schema；签名绑定 group、epoch、required obligations、精确资源代价、Profile owner、Task/Policy refs。任何不满足 W 自己 `plan.amount` 的代价声明必须拒绝。
4. 先实现 **shadow mode**，不改变旧放行结果：输出 old_guard/new_goal_guard 判定差异及依据；至少对比 1）工业单任务成功 2）容量不足 3）PAY UNKNOWN 4）非原三场景有限模拟 5）共同目标共享资源并发。确认新旧拒绝语义与 rollback 都有明确测试。
5. 激活时只新增一个必要断言 `LegacyGuard AND GoalFloor`。对旧 Task 无 GoalFloor 字段的行为完全保持不变；拒绝无 W 接受副作用。冻结 C GoalRef、当前状态摘要、判定摘要进入既有 COMMIT，通过原 X 的 `commit_record_ref` 认证，不改变 ACK 与 EXEC 的顺序。
6. 工具效果、原 attempt、UNKNOWN 保留/恢复、FinalFactID 不得修改。做至少一个“先提交后丢回执，仅恢复原 Core”的完整故障试验。
7. 真实回归测试、Schema 向量、历史 39 项及 Docker demos 单独记录。不要把隔离 31 项测试宣称为正式比赛 PASS。

验收要点：相同的 W 快照下判定确定、旧状态重放被拒绝、签名或摘要篡改拒绝、不同 Profile 不能借用 GoalFloor、未知的必要事项不能视为完成、普通无目标任务行为与基线一致、哈希对象可用独立公钥复验、回滚无副作用。共享资源如仍按 `profile,key` 隔离，**不可宣称已完成跨 Profile 原子性**。