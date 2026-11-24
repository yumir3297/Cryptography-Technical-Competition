# 安全事件响应工作流证据包

复用 IND-DEMO-1 wire；新增 C 认证 `INCIDENT` 记录、独立 containment 工具账和优先级 GoalFloor。不是第四个官方 R2 Profile，也不代表真实隔离设备。

- `anchor-incident.json`：该独立运行的 C/W/角色公钥；评委需独立固定其 SHA-256。
- `incident-package.json`：第二次关键 containment（epoch 2 后）的公开证据。
- `incident-audit.json`：离线审计结果。
- `manifest.json`：低优先级拒绝、旧 Goal 失效、文件 SHA-256 和构建 SHA。

验证：

```powershell
python -m competition.evaluation.verify `
  competition/evaluation/evidence/incident-20261123/incident-package.json `
  competition/evaluation/evidence/incident-20261123/anchor-incident.json
```
