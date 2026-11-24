# 评委独立复验指南

交付分支：`integration/goalcommit-shadow-20261123`，交付提交 `89275d7d0c6910999e53f5538c93bfdc59ecd1eb`；代码/证据生成提交 `fcbc6b3b3ad63c9de84387c98bccc004f726a77b`；基线 `7604d6b5b902f38d950234dec53d9375429f1e7f`。

## 1. 固定信任根

评委应通过比赛材料/现场公布等独立渠道获得并固定：

```text
competition/evaluation/evidence/20261123/anchor-three-profiles.json
SHA-256 982b189c7b841dbd1c81323c6b166d59bbeb6d9235a0c297c7e43fbc9c64c23f
```

以及：

```text
anchor-goal.json
SHA-256 dfc8f59a4db3009d01077d67260b15ce8eaf4d67c7ab01f57cda071a809f788b

incident-20261123/anchor-incident.json
SHA-256 1398a057fb2cfbcf7b172b352eccd9af439c0fad3fa0b93eadc97deaa7f6b291
```

`anchor` 含 C 根公钥、W delivery 公钥、六个角色的 name/kid/public_key/roles/purposes。**不要**信任证据包内附带的公钥副本；只信外部固定的 anchor。

## 2. 一条命令验证一个包

```powershell
python -m competition.evaluation.verify `
  competition/evaluation/evidence/20261123/IND-DEMO-1-package.json `
  competition/evaluation/evidence/20261123/anchor-three-profiles.json
```

预期：

```json
{"status":"PASS", "passed":13, "failed":0, ...}
```

退出码 `0` 表示 PASS，`1` 表示 FAIL。验证器只读 JSON，不打开 W/tool 数据库，不导入 CommonW。

三 Profile 与 Goal 包：

```powershell
python -m competition.evaluation.verify `
  competition/evaluation/evidence/20261123/PAY-1-package.json `
  competition/evaluation/evidence/20261123/anchor-three-profiles.json

python -m competition.evaluation.verify `
  competition/evaluation/evidence/20261123/MED-DEMO-1-package.json `
  competition/evaluation/evidence/20261123/anchor-three-profiles.json

python -m competition.evaluation.verify `
  competition/evaluation/evidence/20261123/ind-goal-package.json `
  competition/evaluation/evidence/20261123/anchor-goal.json
```

安全事件响应工作流：

```powershell
python -m competition.evaluation.verify `
  competition/evaluation/evidence/incident-20261123/incident-package.json `
  competition/evaluation/evidence/incident-20261123/anchor-incident.json
```

## 3. 验证器检查什么

1. `anchor` 与包内 root/delivery 公钥一致；actor kid = hash(public key)。
2. 所有 C 控制记录：`COMP-APP-C-PUBLISH-v1` 签名、profile/scope、revision、record ref；KEY 的 PoP；ROLE 的 epoch。
3. 工具信任证书 `ZJJ-CONTROL-TOOL-v1`；资源证书 `COMP-W-RESOURCE-v1`；资源账求和与容量。
4. 授权链：Review/Authorization/IssueRequest/Permit/ChallengeRequest/Challenge/CommitProof 的签名、scope、aud、refs、payload 等式、时间窗。
5. COMMIT：`rec_ref`、Action/ctx、permit/proof/auth/review refs、X 公钥、dispatch_before。
6. X Acceptance：冻结 core 一致、`commit_record_ref`、X 签名、refs。
7. 唯一 attempt：W delivery 签名、attempt/action_hash/commit/acceptance/tool_trust/origin 绑定。
8. GoalFloor：重算 `state_ref`、`check_ref`、`remaining_floor/total/headroom`、matched 规则、依赖 refs。
9. 工具终局：工具签名、operation/action/attempt/ledger/tool/destination、FinalFactID、检查点 request_hash/high_water/head。
10. 结算：`fact_id`/ledger/effect_id/outcome 与工具终局一致。

验证器会输出 `limitations`，明确 W 账本真实性、当期性、真实设备效果和证据缺失不在离线证明范围。

## 4. 篡改演示

复制一个包，改动 `commit.value.acceptance_ref` 或 `goal.capacity`，再运行验证器，应得到：

```json
{"status":"FAIL", "failed":1, ...}
```

完整的 15 项负例：`python -m competition.evaluation.experiments.crypto_attacks`。

## 5. 重新生成证据

```powershell
python -m competition.evaluation.generate_evidence `
  --output competition/evaluation/evidence/20261123
```

这会新建一次运行并覆盖同名证据文件；`manifest.json` 记录 git SHA、Python、平台、每个文件的 SHA-256。重新生成后的 SHA 会变化，评委应使用本次提交附带的 manifest，而不是用旧哈希校验新文件。

## 6. 重新运行主要实验

```powershell
python -m unittest -v competition.tests.test_goal_floor
python -m unittest -v competition.tests.test_goal_floor_pure
python -m unittest -v competition.tests.test_crash_boundaries
python -m unittest -v competition.tests.test_evidence_verifier
python -m unittest -v competition.tests.test_cross_scenario_evidence
python -m unittest -v competition.tests.test_incident_workflow
python -m competition.evaluation.experiments.concurrency --repetitions 10 --model-count 10000
python -m competition.evaluation.experiments.ablation
python -m competition.evaluation.experiments.crypto_attacks
python -m competition.evaluation.experiments.performance
```

## 7. 预期限制

- Windows 上完整 `unittest discover` 会因 Linux DAC/Unix socket 测试失败；核心协议子集与新增专项不受影响。
- 证据包只证明模拟器效果；真实支付/医疗/工业/隔离设备不在范围。
- GoalFloor 只证明必要资源下界，不证明目标可达。
