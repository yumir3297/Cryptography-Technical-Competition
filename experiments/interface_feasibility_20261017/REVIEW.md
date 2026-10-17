# 独立代码与证据复核

复核范围：本实验 adapter/lab/test_probe/README 与原可信状态、凭据及业务派生实现；只读审查，不替代运行结果。

发现并动态复现 P2：缓存命中时，H 的 KEY/HOLDER/READER grant 有效，但当前 POLICY.readers 已删除 H，仍可返回含 E 派生 Assessment 的缓存构造。READER 动作范围缩小也存在相同路径。

两项新增测试先复现失败（cached-acl-red.log，2 failures），再修复：返回旧构造前，对缓存 Action 调用原 store.read_permission，从而校验当前 Policy ACL、READER 凭据、有效期与动作范围。

复核者再次只读确认该修改覆盖原缺口，未发现其他重要问题。最终运行结果以 evidence/probe-final-22 为准。本审查不证明生产进程隔离或真实设备接入安全。
