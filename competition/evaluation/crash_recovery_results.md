# 崩溃一致性与恢复结果

测试：`python -m unittest -v competition.tests.test_crash_boundaries`（3/3 PASS）。

每个用例在子进程中到达持久化边界后 `os._exit`，父进程用公开恢复夹具重开真实 W/tool ledgers；不是 mock。

| # | 边界 | 崩溃后状态 | 重开后的断言 | 结果 |
|---|---|---|---|---|
| 1 | `accept(crash_after_commit=True)` 提交后、X 签名前 | `w_operation` 存在、`receipt=NULL`、reservation 1、`accepts=1`、`attempts=0` | `complete_receipt` 只对冻结 core 签名；不重新接受、不新增 reservation；`acceptance_state=COMMITTED` | PASS |
| 2 | `execute_once(crash_after_marker=True)`：EXEC-0 标记已提交、工具未调用 | `exec_invocation=1`、`attempts=1`、`exec_marker=1`、工具效果 0 | 再次 `execute_once` 返回 `EXEC_ALREADY_CONSUMED`；`query_attempt` 返回 UNKNOWN；`settle` 保留 reservation；`settlements=0`；总 `exec_invocations=1` | PASS |
| 3 | `settle(crash_after_settlement=True)`：结算已提交、客户端未收到成功 | `w_settlement` 1 行、operation SETTLED、reservation SPENT | 重复 `settle` 返回 `existing=True`；`settlements=1`；不重复释放/花费 | PASS |

## 现有故障注入的补充

- `test_w_recovery::test_three_profiles_lost_ack_query_same_fact_without_new_exec`：三 Profile 工具已执行但应答丢失；重试不新增发送，查询同一 attempt 得到同一 FinalFactID，结算一次。
- `test_w_recovery::test_unknown_query_preserves_resource_flight_and_creates_no_effect`：三 Profile UNKNOWN 保留 reservation/flight，不产生效果。
- `test_w_recovery::test_actual_w_exit_after_commit_recovers_exact_frozen_acceptance`：PAY 接受提交后进程退出，恢复同一 COMMIT/Core。
- `test_common_w::test_delayed_final_acceptance_guard_cannot_publish_a_stale_time_sample`：接受最后时间窗重检失败整体回滚。

## 结论

- 3 个新增边界 + 既有 lost-ack/unknown/commit-crash 均未产生第二次执行资格或第二次结算。
- 所有重开检查都重新打开持久账，不依赖内存状态。
- 不声称“工具调用最多一次”等于物理世界恰好一次；工具已执行但应答丢失仍是 UNKNOWN，必须查询原 attempt。
- 不声称防 W/工具整库回滚；当前只有高水位/head 矛盾检测。
