# 20261123 公开证据包

本目录由 `python -m competition.evaluation.generate_evidence` 生成，构建提交见 `manifest.json.git_sha`。

- `anchor-three-profiles.json`：三 Profile 的 C 根公钥、W delivery 公钥和角色公钥。评委必须通过独立渠道固定其 SHA-256。
- `*-package.json`：单个操作的公开证据包（无私有密钥、无可写数据库）。
- `*-audit.json`：`competition/evaluation/verify.py` 的离线审计结果。
- `manifest.json`：每个文件的 SHA-256。

验证：

```powershell
python -m competition.evaluation.verify `
  competition/evaluation/evidence/20261123/IND-DEMO-1-package.json `
  competition/evaluation/evidence/20261123/anchor-three-profiles.json
```

证据包中的公钥副本不能替代外部固定 anchor。
