# Phase 18 · 工业 AI 安全决策最小闭环：角色密钥的 Linux OS 隔离

本阶段聚焦 **IND-DEMO-1**，不扩展 PAY/MED，不修改原始 2.6 Schema、39 条官方语义用例和早期研究夹具。

## 问题是什么？

Phase17 已经让 E、C、H/G/U/X/Tool 分别发出密码学签名，W 只用公钥验证，但签名私钥属于同一个 Linux 账户，因此只证明了 API 调用路径分开，并没有证明操作系统实际阻止 W 打开其他角色的私钥。

Phase18 在这个基础上引入可验证的 **OS discretionary access control（DAC）边界**。注意，这不是 HSM/KMS 密钥托管，不能把它称为真正独立的多方信任治理。

## 运行示意

```text
临时 Provisioner 生成 9 把不同的 Ed25519 密钥
    ↓
C/H/G/U/X/V/E/Tool 私钥分别 chown 给不同的 Linux 系统用户
    ↓
root 拥有不可由 W 替换的 signer 目录和只读 signer 程序
    ↓
W/协调程序仅掌握公开公钥
    ↓    每次需要签名时，调用具有该签名角色 UID 的受限 broker
  Broker 检查：自己的私钥属主/0600 → 签名域 → 角色 → profile → kid
    ↓
   只返回 Ed25519 签名和非秘密运行收据，不返回私钥
    ↓
Phase17 工业闭环继续：
E 源证据 → W 复核 → 各角色许可 → X Acceptance
→ W 原子接受/签名派发 → 工具模拟执行
→ 工具提交后故障 → 重试返回原事实 → W 一次结算/只读审计
```

**特别说明：** W 使用的 `WTOOL` 专用交付签名密钥属于 W 自身，不与 E/C/X 的权威密钥混同。其余 8 个角色分别在独立 Linux 用户下使用自己的密钥。

## 主要源代码

- `research/phase18/key_broker.py`：无内部模块依赖的最小 Ed25519 签名代理，只接受 canonical JSON 所定义的受限协议签名域，并约束角色、签名消息类型和 signer kid。
- `research/phase18/process_flow.py`：每次将代理安装到 root-owned 的只读临时目录；将 8 个角色密钥分配给不同 Linux 用户，W 验证不能读取其他私钥；将签名结果透明接回 Phase17 运行流程。
- `research/phase18/test_isolated_signers.py`：7 个专项用例，覆盖自己可读、其他角色不可读、W 无权替换密钥、错误签名域/角色被拒绝、业务闭环及模拟账本唯一性。
- `research/phase18/build_report.py`：校验原版 4 份合同/语义 SHA-256、不造假地沿用 39 项官方状态；复制白名单中的公开证据和数据库，明确排除 `.key` 文件。
- `.github/workflows/phase18-ind.yml`：在 GitHub-hosted Ubuntu 临时虚拟机验证。Linux `sudo` 是试验的前提，不能直接在普通 Windows 主机运行。

## 官方 CI 的已确认实验结果（2026-10-10）

| 判据 | 结果 |
| --- | --- |
| 临时角色专有 Linux 用户 | 8 |
| 具有可核验签名的代理调用记录 | 14 |
| 隔离和安全回归测试 | 7/7 |
| 完整 IND 实验流水线 | 25/25 阶段 |
| W 接受 / 派发 / 结算 | 各 1 |
| 工具模拟执行的唯一持久化记录 | 1 |
| 伪造 E/X/W 签名 | 拒绝 |
| 其他角色/W 打开本角色私钥 | 权限拒绝 |
| 原始 39 项官方完整符合性 | **0 PASS，39 BLOCKED** |
| 发布 ZIP 是否包含私钥文件 | **否** |

公开证据：`research_evidence/phase18/phase18_report.json`、`research_evidence/phase18/public_process/`、`research_evidence/phase18/phase18_39case_matrix.csv`。

可复现的运行方式是进入 GitHub Actions，启动 `Phase18 Industrial Signer OS Isolation`；成功后下载 job artifact。这个工作流创建临时 Linux 角色，**只适合隔离的试验环境**，不建议在现有生产设备账户上直接运行。

## 必须诚实披露的剩余边界

1. **初始钥匙生成仍是集中式：** Phase17 bootstrap 曾经在同一进程内同时持有所有钥匙，随后转移属主。它证明转移后的 DAC，不证明密钥从创建起的独立掌控。
2. **CI 管理员仍有 sudo：** 能管理或调用 broker。当前 broker 拒绝超出自身角色/协议域的消息，但尚未进行独立业务决策、人工批准和防滥签治理。
3. **不是跨网络独立服务：** 通过本机 `sudo -u` 子进程 IPC 发送签名请求。没有已验证的 mTLS、HSM、远程证明、密钥轮换和跨域治理。
4. **时间仍采用 Phase17 实验固定时刻：** PREPARE/FINALIZE 在同一签名时间，不代表真实网络延迟下的提交语义已经正确。
5. **工业设备效果仍由 SQLite 模拟：** 证明模拟账本原事实唯一，不证明机械动作恰好执行一次。
6. **全部官方项仍无完整 PASS：** 这是真实但有限的实验进展，不能替换 39 条原版官方义务。

## 下一个最小工作

不增加新场景。优先完善 **非零延迟的 PREPARE/Sign/FINALIZE**：保留现有不可变签名承诺，明确区分“签名承诺时间”和“数据库正式提交时间”，在控制撤销、证据过期、策略修订和并发资源冲突时逐项 fail-closed。之后再研究真实工业工具的认证执行回执。
