# 密码学技术竞赛：协议交接材料

> 📌 **竞赛开发优先入口（与本地 Codex 对齐）**：**[最终交付目标、剩余修复与逐项验收清单](00_COMPETITION_FINAL_DELIVERY_SPEC.md)**。当前在 `competition/zjj-core-final-20261010` 分支开发；此链接对应竞赛交付规格，不代表已通过正式 39 项完整验收。


当前协议实现依据为 [ZJJ-CORE-2.6-R2](system_dev/v26/README.md)。核心协议保持10条签名消息；R2补齐了工具终局事实再认证与换钥恢复规则。

## 阅读顺序

1. [协议交接入口](system_dev/v26/README.md)
2. [核心精确合同](system_dev/v26/01_core_contract.md)
3. [PAY-1合同](system_dev/v26/02_pay1_profile.md)
4. [工业与医疗合同](system_dev/v26/03_industrial_medical_profiles.md)
5. [工具终局再认证合同](system_dev/v26/04_tool_final_recovery.md)
6. [核心协议正文](docs/证决界_动作授权与接受安全核心协议_v2.6.md)
7. [R1审查与R2修复记录](docs/证决界_v2.6_R1_协议质疑审查_2026-10-07.md)

`system_dev/v26/contracts/`、`vectors/`和`tools/`提供结构合同、公开向量及复现工具。局部恢复模型在`verification/protocol_v26_final_recovery/`。该模型不等于产品实现或完整安全证明；真实工具账、控制账连续性和系统验收仍需开发验证。

运行结构与向量核验：

```powershell
python system_dev/v26/tools/build_contracts.py
python system_dev/v26/tools/verify_contracts.py
python verification/protocol_v26_final_recovery/run_all.py
```
