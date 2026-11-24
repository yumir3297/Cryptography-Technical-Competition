# FINAL VERDICT — ZJJ-CORE GoalFloor（2026-11-24）

冻结实验代码 `7f5dd03`，实验分支头 `d83546b`。后续文档/合并不改变原运行身份；默认 off 保持旧入口兼容，只有 enforce 提供强制下界保障。原始 JSON、证据包已提交，运行日志仍需独立归档。

## 结论

**CONDITIONAL_READY**。

核心创新（C 认证的 GoalFloor 必要资源下界 + W 同事务原子接受 + COMMIT/X/attempt/tool/settlement 证据链）已获得真实 CommonW 长序列差分、40 条真实并发历史、15+ 项密码学关系负例、3 个崩溃边界、PAY/MED/IND/事件响应跨场景和 4,363 状态有界模型检查的支持。

Linux/WSL 全量：**526 tests，1 failure / 3 errors**；4 项均为环境（负载下 clock 超 2s、复制树无 `.git`、HTTP proxy 拦截 127.0.0.1），隔离复跑均通过。仍不能据此宣称单一进程 526/526 全绿。

仍存在明确的非核心缺口：正式 39 项为 **2 PASS / 22 PARTIAL / 15 NOT_RUN**；真实并发历史 40 条、长序列 20 条，未达到 1,000/100 目标；工具换钥/账丢失 AUD-02B/C 未跑；性能样本仍属探索性。因此不能标记 READY，也不能宣称 39/39 PASS。

## 核心证据

| 实验 | 结果 |
|---|---|
| E1 长序列 | 20 条真实配对、112 动作、20 个 off 接受/Proposed 拒绝反例、Oracle mismatch 0；10,000 条四类模型序列 |
| E2 并发 | 40 条真实 W 历史全部线性化；10,000 条模型、240,000 转移、0 违反 |
| E3 绑定 | 15/15 篡改/重放拒绝；合法包 PASS；新增容量/资源/Profile/epoch 关系测试 |
| E4 恢复 | 3/3 崩溃边界；UNKNOWN 保留；停用有 PENDING 时 `GOAL_INACTIVE_PENDING`；enforce 唯一索引 |
| E5 跨场景 | IND/PAY/MED/事件响应；PAY/MED 各有正常 GoalFloor 审计 PASS 与挤占拒绝 |
| E6 性能 | 纯 GoalFloor 微秒级；真实 accept 由子进程签名主导；批量样本探索性 |
| E7 模型 | 4,363 状态、67,746 转移、0 违反 |

## 明确不声称

- 不证明目标最终可达；
- 不提供跨 Profile 原子性；
- 不证明 W 账本现实真实性、证据当期性、真实设备效果；
- 不宣称正式 39 项全部通过；
- 不把模拟支付/医疗/工业/隔离当作生产效果。

## 一键复验

在分支 `integration/goalcommit-shadow-20261123` 的 checkout 中：

```powershell
python -m competition.evaluation.verify `
  competition/evaluation/evidence/20261123/IND-DEMO-1-package.json `
  competition/evaluation/evidence/20261123/anchor-three-profiles.json
```

预期 `PASS`、`passed: 13`、`failed: 0`。

## 剩余关键工作

1. 闭合 39 项关键子变体；2. 扩大真实并发/长序列样本；3. AUD-02B/C 工具换钥/账丢失；4. Linux 全量逐项分类；5. 稳定 p99/QPS；6. 正式签名 Result/AUDITBundle 与远端治理（如需）。
